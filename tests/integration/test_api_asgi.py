"""Integration tests verifying standard ASGI 3 application behavior via AsgiTestClient."""

import asyncio
import pytest
from unittest.mock import MagicMock

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.routing import RouteLookupError
from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator, OrchestrationConfig
from engine.service.app import create_app
from engine.service.client import AsgiTestClient
from engine.service.service import PoolEngineService


@pytest.fixture
def asgi_client() -> tuple[AsgiTestClient, InMemoryRideStorage, MockRoutingProvider, PoolEngineService]:
    storage = InMemoryRideStorage()
    router = MockRoutingProvider()
    spatial = H3SpatialIndexAdapter()
    policy = DefaultPolicyProvider()
    orchestrator = DispatchOrchestrator(
        storage=storage,
        policy_provider=policy,
        routing_provider=router,
        spatial_index=spatial,
        config=OrchestrationConfig(deadline_seconds=0.500),
    )
    service = PoolEngineService(
        storage=storage,
        orchestrator=orchestrator,
        router=router,
    )
    app = create_app(service)
    client = AsgiTestClient(app)
    return client, storage, router, service


def test_health_check(asgi_client: tuple[AsgiTestClient, InMemoryRideStorage, MockRoutingProvider, PoolEngineService]) -> None:
    client, _, _, _ = asgi_client
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "pool-engine"


def test_route_not_found(asgi_client: tuple[AsgiTestClient, InMemoryRideStorage, MockRoutingProvider, PoolEngineService]) -> None:
    client, _, _, _ = asgi_client
    resp = client.get("/v1/nonexistent-endpoint")
    assert resp.status_code == 404
    err = resp.json()
    assert err["error"]["code"] == "ROUTE_NOT_FOUND"


def test_method_not_allowed(asgi_client: tuple[AsgiTestClient, InMemoryRideStorage, MockRoutingProvider, PoolEngineService]) -> None:
    client, _, _, _ = asgi_client
    resp = client.delete("/v1/health")
    assert resp.status_code == 405
    err = resp.json()
    assert err["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_vehicle_lifecycle_endpoints(
    asgi_client: tuple[AsgiTestClient, InMemoryRideStorage, MockRoutingProvider, PoolEngineService],
) -> None:
    client, _, _, _ = asgi_client

    # 1. Register vehicle
    payload = {
        "vehicle_id": "veh-100",
        "driver_id": "drv-100",
        "total_seat_capacity": 4,
        "current_location": {"latitude": 40.75, "longitude": -73.98},
        "is_active": True,
        "luggage_capacity_units": 2,
    }
    resp = client.post("/v1/vehicles", json=payload)
    assert resp.status_code == 201
    veh_data = resp.json()
    assert veh_data["vehicle_id"] == "veh-100"
    assert veh_data["total_seat_capacity"] == 4

    # 2. Retrieve vehicle
    get_resp = client.get("/v1/vehicles/veh-100")
    assert get_resp.status_code == 200
    assert get_resp.json()["driver_id"] == "drv-100"

    # 3. Nonexistent vehicle
    get_missing = client.get("/v1/vehicles/veh-does-not-exist")
    assert get_missing.status_code == 404
    assert get_missing.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    # 4. Update vehicle location
    loc_payload = {"latitude": 40.76, "longitude": -73.97}
    patch_resp = client.patch("/v1/vehicles/veh-100/location", json=loc_payload)
    assert patch_resp.status_code == 200
    assert patch_resp.json()["current_location"]["latitude"] == 40.76

    # 5. Update vehicle status
    status_payload = {"is_active": False}
    status_resp = client.patch("/v1/vehicles/veh-100/status", json=status_payload)
    assert status_resp.status_code == 200
    assert status_resp.json()["is_active"] is False


def test_request_lifecycle_and_validation(
    asgi_client: tuple[AsgiTestClient, InMemoryRideStorage, MockRoutingProvider, PoolEngineService],
) -> None:
    client, _, _, _ = asgi_client

    # 1. Invalid coordinates (lat > 90)
    bad_coords = {
        "user_id": "usr-1",
        "pickup_location": {"latitude": 95.0, "longitude": -73.98},
        "dropoff_location": {"latitude": 40.78, "longitude": -73.96},
        "earliest_pickup_time": 1000,
        "latest_dropoff_time": 2000,
    }
    resp_bad = client.post("/v1/requests", json=bad_coords)
    assert resp_bad.status_code == 400
    assert resp_bad.json()["error"]["code"] == "VALIDATION_ERROR"

    # 2. Infeasible time window
    bad_window = {
        "user_id": "usr-1",
        "pickup_location": {"latitude": 40.75, "longitude": -73.98},
        "dropoff_location": {"latitude": 40.78, "longitude": -73.96},
        "earliest_pickup_time": 2000,
        "latest_dropoff_time": 1000,
    }
    resp_window = client.post("/v1/requests", json=bad_window)
    assert resp_window.status_code == 400

    # 3. Create valid request
    valid_req = {
        "request_id": "req-asgi-1",
        "user_id": "usr-1",
        "pickup_location": {"latitude": 40.75, "longitude": -73.98},
        "dropoff_location": {"latitude": 40.78, "longitude": -73.96},
        "seat_count": 1,
        "earliest_pickup_time": 1000,
        "latest_dropoff_time": 3000,
    }
    resp_create = client.post("/v1/requests", json=valid_req)
    assert resp_create.status_code == 201
    created = resp_create.json()
    assert created["request_id"] == "req-asgi-1"
    assert created["status"] == "PENDING"
    assert created["direct_distance_meters"] > 0
    assert created["direct_duration_seconds"] > 0

    # 4. Get request
    resp_get = client.get("/v1/requests/req-asgi-1")
    assert resp_get.status_code == 200
    assert resp_get.json()["user_id"] == "usr-1"

    # 5. Cancel request
    resp_cancel = client.post("/v1/requests/req-asgi-1/cancel", json={"reason": "changed_mind"})
    assert resp_cancel.status_code == 200
    assert resp_cancel.json()["status"] == "CANCELLED"


def test_routing_failure_in_request_creation(
    asgi_client: tuple[AsgiTestClient, InMemoryRideStorage, MockRoutingProvider, PoolEngineService],
) -> None:
    client, storage, _, service = asgi_client
    failing_router = MagicMock()
    failing_router.get_direct_leg.side_effect = RouteLookupError("Unreachable road coordinate")
    failing_service = PoolEngineService(
        storage=storage,
        orchestrator=service.orchestrator,
        router=failing_router,
    )
    app = create_app(failing_service)
    failing_client = AsgiTestClient(app)

    valid_req = {
        "user_id": "usr-1",
        "pickup_location": {"latitude": 40.75, "longitude": -73.98},
        "dropoff_location": {"latitude": 40.78, "longitude": -73.96},
        "seat_count": 1,
        "earliest_pickup_time": 1000,
        "latest_dropoff_time": 3000,
    }
    resp = failing_client.post("/v1/requests", json=valid_req)
    assert resp.status_code == 502
    err = resp.json()["error"]
    assert err["code"] == "ROUTING_BACKEND_ERROR"
    assert "Unreachable road coordinate" in err["message"]


def test_end_to_end_dispatch_and_ride_inspection(
    asgi_client: tuple[AsgiTestClient, InMemoryRideStorage, MockRoutingProvider, PoolEngineService],
) -> None:
    client, _, _, _ = asgi_client

    # 1. Register vehicle
    veh_payload = {
        "vehicle_id": "veh-dispatch-1",
        "driver_id": "drv-dispatch-1",
        "total_seat_capacity": 4,
        "current_location": {"latitude": 40.74, "longitude": -73.99},
        "is_active": True,
    }
    client.post("/v1/vehicles", json=veh_payload)

    # 2. Create pending ride request
    req_payload = {
        "request_id": "req-dispatch-1",
        "user_id": "usr-1",
        "pickup_location": {"latitude": 40.75, "longitude": -73.98},
        "dropoff_location": {"latitude": 40.78, "longitude": -73.96},
        "seat_count": 1,
        "earliest_pickup_time": 1000,
        "latest_dropoff_time": 3000,
        "direct_distance_meters": 3500,
        "direct_duration_seconds": 600,
    }
    client.post("/v1/requests", json=req_payload)

    # 3. Execute dispatch run
    dispatch_payload = {
        "current_time": 1000,
        "cycle_id": "cycle-test-1",
        "idempotency_token": "token-test-1",
        "deadline_seconds": 0.500,
    }
    headers = {"Idempotency-Key": "token-test-1"}
    resp_dispatch = client.post("/v1/dispatch", json=dispatch_payload, headers=headers)
    assert resp_dispatch.status_code == 200
    res_data = resp_dispatch.json()
    assert res_data["cycle_id"] == "cycle-test-1"
    assert res_data["search_status"] in ("COMPLETE", "APPROXIMATED")
    assert len(res_data["committed_assignments"]) == 1

    committed = res_data["committed_assignments"][0]
    assert committed["vehicle_id"] == "veh-dispatch-1"
    assert "req-dispatch-1" in committed["request_ids"]

    # 4. Check request status updated to MATCHED
    req_check = client.get("/v1/requests/req-dispatch-1")
    assert req_check.status_code == 200
    req_data = req_check.json()
    assert req_data["status"] == "MATCHED"
    assert req_data["matched_ride_id"] is not None

    # 5. Check ride details via GET /v1/rides/{ride_id}
    ride_id = req_data["matched_ride_id"]
    ride_resp = client.get(f"/v1/rides/{ride_id}")
    assert ride_resp.status_code == 200
    ride_data = ride_resp.json()
    assert ride_data["ride_id"] == ride_id
    assert ride_data["vehicle_id"] == "veh-dispatch-1"
    assert len(ride_data["stops"]) == 2  # 1 pickup, 1 dropoff
    assert ride_data["version"] >= 1

    # 6. Idempotent replay of same dispatch returns cached response
    resp_replay = client.post("/v1/dispatch", json=dispatch_payload, headers=headers)
    assert resp_replay.status_code == 200
    assert resp_replay.json()["cycle_id"] == "cycle-test-1"

    # 7. Cancel matched request en-route
    cancel_resp = client.post("/v1/requests/req-dispatch-1/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "CANCELLED"

    # Verify stops removed from ride
    updated_ride = client.get(f"/v1/rides/{ride_id}").json()
    assert len(updated_ride["stops"]) == 0


def test_asgi_lifespan_events(
    asgi_client: tuple[AsgiTestClient, InMemoryRideStorage, MockRoutingProvider, PoolEngineService],
) -> None:
    _, _, _, service = asgi_client
    app = create_app(service)

    async def run_lifespan() -> None:
        scope = {"type": "lifespan"}
        events_received: list[str] = []

        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        queue.put_nowait({"type": "lifespan.startup"})

        async def receive() -> dict[str, str]:
            return await queue.get()

        async def send(message: dict[str, str]) -> None:
            events_received.append(message.get("type", ""))
            if message.get("type") == "lifespan.startup.complete":
                queue.put_nowait({"type": "lifespan.shutdown"})

        await app(scope, receive, send)
        assert "lifespan.startup.complete" in events_received
        assert "lifespan.shutdown.complete" in events_received

    asyncio.run(run_lifespan())
