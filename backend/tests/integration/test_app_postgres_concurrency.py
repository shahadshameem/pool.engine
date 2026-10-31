"""Live PostgreSQL integration tests for FastAPI / ASGI concurrency and connection pool (Phase 2).

Verifies against isolated live database `pool_engine_test` on port 5433:
1. Concurrent API requests utilize separate pool connections without driver-level serialization.
2. Concurrent bilateral proposal acceptance through the HTTP API completes atomically with row locks.
3. Live pool exhaustion produces controlled HTTP 503 STORAGE_POOL_EXHAUSTED response.
4. Concurrent vehicle location updates from simulated high-frequency GPS pings execute safely.
"""

import concurrent.futures
import os
import threading
import time
from typing import Any, Generator

import psycopg
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.mock_routing import MockRoutingProvider
from engine.adapters.postgres_storage import PostgresRideStorage
from engine.domain.enums import JoinStatus, RideStatus
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle
from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator
from engine.service.app import create_app
from engine.service.client import AsgiTestClient
from engine.service.config import ServiceConfig
from engine.service.service import PoolEngineService
from engine.service.telemetry import StructuredLoggerTelemetry

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest.fixture(scope="module")
def live_postgres_storage() -> Generator[PostgresRideStorage, None, None]:
    if not TEST_DB_URL:
        pytest.skip(
            "Live PostgreSQL environment is unavailable (set TEST_DATABASE_URL or DATABASE_URL)"
        )
    try:
        conn = psycopg.connect(TEST_DB_URL, connect_timeout=3)
        conn.close()
    except Exception as exc:
        pytest.skip(f"Live PostgreSQL unreachable at {TEST_DB_URL}: {exc}")

    storage = PostgresRideStorage(dsn=TEST_DB_URL, min_size=2, max_size=10, timeout=5.0)
    storage.create_schema()
    yield storage
    storage.close()


@pytest.fixture(autouse=True)
def clean_database(live_postgres_storage: PostgresRideStorage) -> Generator[None, None, None]:
    with live_postgres_storage.connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "TRUNCATE vehicles, rides, route_stops, ride_requests, join_requests, seat_holds, idempotency_records CASCADE"
                )
    yield


def _build_service_with_storage(storage: PostgresRideStorage) -> PoolEngineService:
    router = MockRoutingProvider()
    spatial = H3SpatialIndexAdapter()
    policy = DefaultPolicyProvider()
    orchestrator = DispatchOrchestrator(
        storage=storage,
        policy_provider=policy,
        routing_provider=router,
        spatial_index=spatial,
    )
    return PoolEngineService(
        storage=storage,
        orchestrator=orchestrator,
        router=router,
        telemetry=StructuredLoggerTelemetry(),
    )


def test_concurrent_vehicle_location_updates(live_postgres_storage: PostgresRideStorage) -> None:
    """Verifies concurrent GPS location updates execute simultaneously across pooled connections."""
    service = _build_service_with_storage(live_postgres_storage)
    app = create_app(service=service)

    # Pre-register 4 vehicles
    for i in range(4):
        veh = Vehicle(
            vehicle_id=f"veh-gps-{i}",
            driver_id=f"driver-{i}",
            current_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
            total_seat_capacity=4,
            is_active=True,
        )
        live_postgres_storage.save_vehicle(veh)

    def send_gps_ping(veh_idx: int) -> int:
        client = AsgiTestClient(app)
        resp = client.patch(
            f"/v1/vehicles/veh-gps-{veh_idx}/location",
            json={
                "latitude": 40.7128 + (veh_idx * 0.001),
                "longitude": -74.0060 + (veh_idx * 0.001),
            },
        )
        return resp.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(send_gps_ping, i) for i in range(4)]
        results = [f.result() for f in futures]

    assert results == [200, 200, 200, 200]

    for i in range(4):
        v = live_postgres_storage.get_vehicle(f"veh-gps-{i}")
        assert v is not None
        assert abs(v.current_location.latitude - (40.7128 + i * 0.001)) < 1e-5


def test_concurrent_api_proposal_bilateral_acceptance(live_postgres_storage: PostgresRideStorage) -> None:
    """Verifies concurrent bilateral proposal acceptance through the HTTP API succeeds atomically."""
    service = _build_service_with_storage(live_postgres_storage)
    app = create_app(service=service)

    now = int(time.time())
    veh = Vehicle(
        vehicle_id="v-api-prop-1",
        driver_id="driver-host-1",
        current_location=GeoCoordinate(latitude=40.7580, longitude=-73.9855),
        total_seat_capacity=4,
        is_active=True,
    )
    live_postgres_storage.save_vehicle(veh)

    ride = Ride(
        ride_id="ride-api-prop-1",
        vehicle_id="v-api-prop-1",
        driver_id="driver-host-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(),
        scheduled_departure_time=now,
        active_passenger_count=0,
        total_vmt_meters=1000,
        version=1,
    )
    live_postgres_storage.save_ride(ride)

    req = RideRequest(
        request_id="req-api-prop-1",
        user_id="traveller-user-1",
        pickup_location=GeoCoordinate(latitude=40.7410, longitude=-73.9897),
        dropoff_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        seat_count=1,
        earliest_pickup_time=now - 60,
        latest_dropoff_time=now + 7200,
        direct_duration_seconds=600,
        direct_distance_meters=5000,
    )
    live_postgres_storage.save_request(req)

    # Create proposal via API
    client = AsgiTestClient(app)
    prop_resp = client.post(
        "/v1/proposals",
        json={
            "ride_id": "ride-api-prop-1",
            "request_id": "req-api-prop-1",
            "seat_count": 1,
        },
    )
    assert prop_resp.status_code == 201
    prop_id = prop_resp.json()["proposal_id"]

    # Concurrently accept from Host and Traveller
    def accept_role(role: str, user_id: str) -> tuple[int, dict[str, Any]]:
        thread_client = AsgiTestClient(app)
        resp = thread_client.post(
            f"/v1/proposals/{prop_id}/accept",
            headers={"x-user-id": user_id, "x-role": role},
            json={"role": role, "user_id": user_id},
        )
        return resp.status_code, resp.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_host = executor.submit(accept_role, "host", "driver-host-1")
        f_traveller = executor.submit(accept_role, "traveller", "traveller-user-1")
        status_h, body_h = f_host.result()
        status_t, body_t = f_traveller.result()

    assert status_h == 200
    assert status_t == 200

    # Proposal must be fully approved/confirmed and seat reservation confirmed
    final_prop = client.get(f"/v1/proposals/{prop_id}").json()
    assert final_prop["status"] in ("APPROVED", "CONFIRMED")
    assert final_prop["is_confirmed"] is True
    assert final_prop["host_accepted"] is True
    assert final_prop["traveller_accepted"] is True


def test_live_pool_exhaustion_controlled_error_response() -> None:
    """Verifies that when connection pool is exhausted on live PostgreSQL, HTTP 503 is returned."""
    if not TEST_DB_URL:
        pytest.skip("Live PostgreSQL environment is unavailable")

    # Tight pool: exactly 1 connection, 0.15s timeout
    storage = PostgresRideStorage(dsn=TEST_DB_URL, min_size=1, max_size=1, timeout=0.15)
    service = _build_service_with_storage(storage)
    app = create_app(service=service)

    barrier = threading.Barrier(2)

    def hold_connection_in_worker() -> None:
        # Check out the sole connection and hold it for 0.4s
        with storage.connection() as conn:
            barrier.wait()
            time.sleep(0.4)

    def send_api_request() -> tuple[int, dict[str, Any]]:
        barrier.wait()
        client = AsgiTestClient(app)
        # Give worker a moment to hold the connection
        time.sleep(0.02)
        resp = client.get("/v1/requests/req-will-timeout")
        return resp.status_code, resp.json()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f_hold = executor.submit(hold_connection_in_worker)
            f_req = executor.submit(send_api_request)
            f_hold.result()
            status, body = f_req.result()

        assert status == 503
        assert body["error"]["code"] == "STORAGE_POOL_EXHAUSTED"
        assert "exhausted" in body["error"]["message"].lower()
    finally:
        storage.close()
