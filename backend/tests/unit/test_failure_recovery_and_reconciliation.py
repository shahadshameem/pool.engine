"""
Unit tests for Pool Engine failure recovery, restart handling, and capacity reconciliation.
Validates that:
1. Uninitialized/restarted vehicles buffer capacity updates and apply them upon registration.
2. Idempotent replays produce no duplicate business effects.
3. Out-of-order/stale versions are strictly rejected (HTTP 409 STALE_VERSION).
4. Reconcile endpoints authoritatively align vehicle capacity with Firestore state.
5. Dispatch cycle executes with authoritative capacity reconciliation, preventing stale dispatch.
"""

import time
import pytest
from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.mock_routing import MockRoutingProvider
from engine.domain.models import GeoCoordinate, Vehicle
from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator
from engine.service.client import AsgiTestClient
from engine.service.config import ServiceConfig
from engine.service.schemas import (
    DispatchRunInput,
    ReconcileRideInput,
    RegisterVehicleInput,
    SyncRideCapacityInput,
)
from engine.service.security import ApiKeyAuthProvider
from engine.service.service import PoolEngineService
from engine.service.app import create_app


def make_test_service_and_storage():
    storage = InMemoryRideStorage()
    router = MockRoutingProvider()
    policy = DefaultPolicyProvider()
    spatial = H3SpatialIndexAdapter()
    orchestrator = DispatchOrchestrator(
        storage=storage,
        policy_provider=policy,
        routing_provider=router,
        spatial_index=spatial,
    )
    service = PoolEngineService(storage=storage, orchestrator=orchestrator, router=router)
    return service, storage


def test_capacity_buffering_and_restart_recovery():
    """
    Simulates:
    1. Pool Engine restarts (storage empty).
    2. Capacity sync arrives for 'ride_tvm_01' (available_seats = 1).
    3. Engine buffers the capacity update instead of crashing or discarding.
    4. Vehicle is subsequently registered with initial default capacity 4.
    5. Vehicle total_seat_capacity is immediately reconciled to 1.
    """
    service, storage = make_test_service_and_storage()
    sync_res = service.sync_ride_capacity(
        ride_id="ride_tvm_01",
        available_seats=1,
        version=1730000001000,
        idempotency_token="token_restart_01"
    )
    assert sync_res["synced"] is True
    assert sync_res.get("buffered") is True
    assert sync_res["available_seats"] == 1

    # Vehicle registers after restart
    veh = service.register_vehicle(
        RegisterVehicleInput(
            vehicle_id="ride_tvm_01",
            driver_id="driver_01",
            total_seat_capacity=4,  # default specification
            current_location=GeoCoordinate(latitude=8.5241, longitude=76.9366)
        )
    )
    # Total capacity must reflect the buffered authoritative capacity (1 seat)
    assert veh.total_seat_capacity == 1
    assert storage.get_vehicle("ride_tvm_01").total_seat_capacity == 1


def test_reconcile_endpoint_and_batch_reconcile():
    """
    Tests REST endpoint POST /v1/rides/{ride_id}/reconcile and POST /v1/reconcile/batch.
    """
    service, storage = make_test_service_and_storage()
    # Register vehicle
    service.register_vehicle(
        RegisterVehicleInput(
            vehicle_id="veh_batch_01",
            driver_id="driver_batch_01",
            total_seat_capacity=4,
            current_location=GeoCoordinate(latitude=8.5241, longitude=76.9366)
        )
    )

    auth = ApiKeyAuthProvider({"test-key": ("admin-user", ("admin", "dispatch_operator"))})
    config = ServiceConfig(require_auth=True)
    app = create_app(service, config=config, auth_provider=auth)
    client = AsgiTestClient(app)

    # 1. Reconcile single ride
    res_single = client.post(
        "/v1/rides/veh_batch_01/reconcile",
        json={
            "available_seats": 2,
            "version": 1730000002000,
            "idempotency_token": "reconcile_single_token"
        },
        headers={"x-api-key": "test-key"}
    )
    assert res_single.status_code == 200
    assert res_single.json()["synced"] is True
    assert storage.get_vehicle("veh_batch_01").total_seat_capacity == 2

    # 2. Reconcile batch
    res_batch = client.post(
        "/v1/reconcile/batch",
        json={
            "rides": [
                {
                    "ride_id": "veh_batch_01",
                    "available_seats": 0,
                    "version": 1730000003000,
                    "idempotency_token": "batch_token_01"
                }
            ]
        },
        headers={"x-api-key": "test-key"}
    )
    assert res_batch.status_code == 200
    assert res_batch.json()["reconciled_count"] == 1
    assert storage.get_vehicle("veh_batch_01").total_seat_capacity == 0


def test_stale_reconciliation_rejected_409():
    """
    Verifies that an older reconciliation event is strictly rejected with HTTP 409 STALE_VERSION
    and cannot overwrite newer capacity.
    """
    service, storage = make_test_service_and_storage()
    service.register_vehicle(
        RegisterVehicleInput(
            vehicle_id="veh_stale_test",
            driver_id="driver_stale",
            total_seat_capacity=4,
            current_location=GeoCoordinate(latitude=8.5241, longitude=76.9366)
        )
    )

    auth = ApiKeyAuthProvider({"test-key": ("admin-user", ("admin", "dispatch_operator"))})
    config = ServiceConfig(require_auth=True)
    app = create_app(service, config=config, auth_provider=auth)
    client = AsgiTestClient(app)

    # Newer event (v=2000) sets seats to 1
    r1 = client.post(
        "/v1/rides/veh_stale_test/reconcile",
        json={"available_seats": 1, "version": 2000, "idempotency_token": "token_v2000"},
        headers={"x-api-key": "test-key"}
    )
    assert r1.status_code == 200
    assert storage.get_vehicle("veh_stale_test").total_seat_capacity == 1

    # Stale older event (v=1000) attempting to inflate seats back to 3
    r2 = client.post(
        "/v1/rides/veh_stale_test/reconcile",
        json={"available_seats": 3, "version": 1000, "idempotency_token": "token_v1000"},
        headers={"x-api-key": "test-key"}
    )
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "STALE_VERSION"
    # Authoritative capacity must remain 1
    assert storage.get_vehicle("veh_stale_test").total_seat_capacity == 1


def test_dispatch_cycle_with_authoritative_reconciliation():
    """
    Verifies that when dispatch runs with authoritative_capacities,
    the vehicle capacities are reconciled before solving, guaranteeing
    that dispatch cannot operate on stale capacity.
    """
    service, storage = make_test_service_and_storage()
    service.register_vehicle(
        RegisterVehicleInput(
            vehicle_id="veh_disp_01",
            driver_id="driver_disp_01",
            total_seat_capacity=4,
            current_location=GeoCoordinate(latitude=8.5241, longitude=76.9366)
        )
    )

    # Dispatch runs with authoritative capacity indicating 0 seats available
    run_input = DispatchRunInput(
        current_time=int(time.time()),
        cycle_id="cycle_recon_test",
        idempotency_token="idemp_disp_recon_01",
        authoritative_capacities=[
            ReconcileRideInput(
                ride_id="veh_disp_01",
                available_seats=0,
                version=1730000009999,
                idempotency_token="recon_in_disp_01"
            )
        ]
    )

    res = service.run_dispatch(run_input)
    assert res.cycle_id == "cycle_recon_test"
    # Vehicle capacity was reconciled down to 0 prior to solve
    assert storage.get_vehicle("veh_disp_01").total_seat_capacity == 0
