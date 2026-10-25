"""Live PostgreSQL integration tests for the pool engine API service (Phase 2, Item 2.2).

Verifies end-to-end API workflows backed by persistent PostgreSQL storage:
- Vehicle registration and retrieval
- Request creation and retrieval
- Dispatch cycle execution committing atomically to PostgreSQL tables
- Ride retrieval with stops and OCC version checks
"""

import os
from typing import Generator

import psycopg
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.mock_routing import MockRoutingProvider
from engine.adapters.postgres_storage import PostgresRideStorage
from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator, OrchestrationConfig
from engine.service.app import create_app
from engine.service.client import AsgiTestClient
from engine.service.service import PoolEngineService

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest.fixture(scope="module")
def postgres_storage() -> Generator[PostgresRideStorage, None, None]:
    """Provides an initialized PostgresRideStorage connected to a live test database."""
    if not TEST_DB_URL:
        pytest.skip(
            "Live PostgreSQL database environment is unavailable (set TEST_DATABASE_URL or DATABASE_URL to execute)"
        )

    try:
        conn = psycopg.connect(TEST_DB_URL, connect_timeout=3)
        conn.close()
    except Exception as exc:
        pytest.skip(f"Live PostgreSQL database is unreachable at {TEST_DB_URL}: {exc}")

    storage = PostgresRideStorage(dsn=TEST_DB_URL)
    storage.create_schema()
    yield storage
    storage.close()


@pytest.fixture(autouse=True)
def clean_database(postgres_storage: PostgresRideStorage) -> Generator[None, None, None]:
    """Truncates all tables before each test to guarantee isolated test execution."""
    conn = postgres_storage._get_connection()
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                TRUNCATE vehicles, rides, route_stops, ride_requests, join_requests, seat_holds, idempotency_records
                CASCADE;
                """
            )
    yield


@pytest.fixture
def asgi_postgres_client(
    postgres_storage: PostgresRideStorage,
) -> tuple[AsgiTestClient, PostgresRideStorage, PoolEngineService]:
    router = MockRoutingProvider()
    spatial = H3SpatialIndexAdapter()
    policy = DefaultPolicyProvider()
    orchestrator = DispatchOrchestrator(
        storage=postgres_storage,
        policy_provider=policy,
        routing_provider=router,
        spatial_index=spatial,
        config=OrchestrationConfig(deadline_seconds=0.500),
    )
    service = PoolEngineService(
        storage=postgres_storage,
        orchestrator=orchestrator,
        router=router,
    )
    app = create_app(service)
    client = AsgiTestClient(app)
    return client, postgres_storage, service


def test_postgres_api_full_dispatch_workflow(
    asgi_postgres_client: tuple[AsgiTestClient, PostgresRideStorage, PoolEngineService],
) -> None:
    client, storage, _ = asgi_postgres_client

    # 1. Register vehicle via API
    veh_payload = {
        "vehicle_id": "veh-pg-1",
        "driver_id": "drv-pg-1",
        "total_seat_capacity": 4,
        "current_location": {"latitude": 40.75, "longitude": -73.98},
        "is_active": True,
    }
    veh_resp = client.post("/v1/vehicles", json=veh_payload)
    assert veh_resp.status_code == 201

    # Verify vehicle was persisted to PostgreSQL
    veh_db = storage.get_vehicle("veh-pg-1")
    assert veh_db is not None
    assert veh_db.driver_id == "drv-pg-1"

    # 2. Submit two ride requests via API
    req1_payload = {
        "request_id": "req-pg-1",
        "user_id": "usr-1",
        "pickup_location": {"latitude": 40.751, "longitude": -73.979},
        "dropoff_location": {"latitude": 40.780, "longitude": -73.960},
        "seat_count": 1,
        "earliest_pickup_time": 1000,
        "latest_dropoff_time": 3000,
        "direct_distance_meters": 3400,
        "direct_duration_seconds": 600,
    }
    resp1 = client.post("/v1/requests", json=req1_payload)
    assert resp1.status_code == 201

    req2_payload = {
        "request_id": "req-pg-2",
        "user_id": "usr-2",
        "pickup_location": {"latitude": 40.752, "longitude": -73.978},
        "dropoff_location": {"latitude": 40.781, "longitude": -73.959},
        "seat_count": 1,
        "earliest_pickup_time": 1000,
        "latest_dropoff_time": 3000,
        "direct_distance_meters": 3400,
        "direct_duration_seconds": 600,
    }
    resp2 = client.post("/v1/requests", json=req2_payload)
    assert resp2.status_code == 201

    # Verify requests persisted in PENDING status
    pending = storage.get_pending_requests()
    assert len(pending) == 2

    # 3. Trigger dispatch run via API
    dispatch_payload = {
        "current_time": 1000,
        "cycle_id": "cycle-pg-1",
        "idempotency_token": "token-pg-1",
    }
    headers = {"Idempotency-Key": "token-pg-1"}
    dispatch_resp = client.post("/v1/dispatch", json=dispatch_payload, headers=headers)
    assert dispatch_resp.status_code == 200
    res_data = dispatch_resp.json()
    assert len(res_data["committed_assignments"]) == 1

    # 4. Verify request statuses in PostgreSQL are MATCHED
    req1_check = client.get("/v1/requests/req-pg-1").json()
    req2_check = client.get("/v1/requests/req-pg-2").json()
    assert req1_check["status"] == "MATCHED"
    assert req2_check["status"] == "MATCHED"
    assert req1_check["matched_ride_id"] == req2_check["matched_ride_id"]

    # 5. Verify Ride in PostgreSQL via GET /v1/rides/{ride_id}
    ride_id = req1_check["matched_ride_id"]
    ride_resp = client.get(f"/v1/rides/{ride_id}")
    assert ride_resp.status_code == 200
    ride_data = ride_resp.json()
    assert ride_data["ride_id"] == ride_id
    assert ride_data["vehicle_id"] == "veh-pg-1"
    assert len(ride_data["stops"]) == 4  # 2 pickups, 2 dropoffs
    assert ride_data["version"] >= 1
