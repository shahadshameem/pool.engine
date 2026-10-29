"""Live PostgreSQL integration tests for private-host corridor matching and ahead-of-vehicle en-route joining.

Verifies:
- Durable persistence of Host Ride corridor metadata (origin, destination, max_detour) in PostgreSQL.
- Two-party bilateral acceptance committing host and intermediate traveller stops atomically to PostgreSQL.
- Concurrent seat contention on a host ride with only 1 remaining seat.
- Ahead-of-vehicle spatial gating with updated vehicle location and completed stops in PostgreSQL.
- Unbroken backwards compatibility for existing fleet dispatch cycles.
"""

import concurrent.futures
import os
import time
from typing import Generator

import psycopg
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.mock_routing import MockRoutingProvider
from engine.adapters.postgres_storage import PostgresRideStorage
from engine.domain.enums import JoinStatus, RequestStatus, RideStatus, StopType
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle
from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator, OrchestrationConfig
from engine.service.app import create_app
from engine.service.client import AsgiTestClient
from engine.service.schemas import CreateHostRideInput, EnRouteJoinInput, UpdateVehicleLocationInput
from engine.service.service import PoolEngineService

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")

# Manhattan Landmarks
MIDTOWN = GeoCoordinate(latitude=40.7580, longitude=-73.9855)       # Host Origin
FLATIRON = GeoCoordinate(latitude=40.7410, longitude=-73.9897)      # Internal Waypoint 1
FOURTEENTH_ST = GeoCoordinate(latitude=40.7350, longitude=-73.9910) # En-Route Vehicle Location
CANAL_ST = GeoCoordinate(latitude=40.7180, longitude=-74.0010)      # Ahead Pickup
CITY_HALL = GeoCoordinate(latitude=40.7128, longitude=-74.0060)     # Ahead Dropoff
WALL_ST = GeoCoordinate(latitude=40.7070, longitude=-74.0090)       # Host Destination


@pytest.fixture(scope="module")
def postgres_storage() -> Generator[PostgresRideStorage, None, None]:
    """Provides an initialized PostgresRideStorage connected to a live test database."""
    if not TEST_DB_URL:
        pytest.skip(
            "Live PostgreSQL database environment is unavailable (set TEST_DATABASE_URL to execute)"
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


def _build_test_env(
    storage: PostgresRideStorage,
) -> tuple[AsgiTestClient, PoolEngineService, DispatchOrchestrator]:
    router = MockRoutingProvider(average_speed_kmh=40.0)
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
    return client, service, orchestrator


def test_postgres_host_ride_lifecycle_and_persistence(
    postgres_storage: PostgresRideStorage,
) -> None:
    """Verifies full host ride lifecycle persisted end-to-end in PostgreSQL."""
    client, service, _ = _build_test_env(postgres_storage)
    now = int(time.time())

    # 1. Register host ride
    resp_host = client.post(
        "/v1/host-rides",
        json={
            "driver_id": "usr-host-pg",
            "origin": {"latitude": MIDTOWN.latitude, "longitude": MIDTOWN.longitude},
            "destination": {"latitude": WALL_ST.latitude, "longitude": WALL_ST.longitude},
            "scheduled_departure_time": now + 600,
            "available_seats": 3,
            "max_detour_seconds": 900,
        },
    )
    assert resp_host.status_code == 201
    host_data = resp_host.json()
    ride_id = host_data["ride_id"]

    # Verify loaded from DB directly
    ride_db = postgres_storage.get_ride(ride_id)
    assert ride_db is not None
    assert ride_db.is_host_ride is True
    assert ride_db.origin_location is not None
    assert ride_db.origin_location.latitude == pytest.approx(MIDTOWN.latitude, abs=1e-4)
    assert ride_db.destination_location is not None
    assert ride_db.destination_location.latitude == pytest.approx(WALL_ST.latitude, abs=1e-4)
    assert ride_db.max_detour_seconds == 900

    # 2. Register compatible traveller request
    resp_req = client.post(
        "/v1/requests",
        json={
            "request_id": "req-traveller-pg",
            "user_id": "usr-traveller-pg",
            "pickup_location": {"latitude": FLATIRON.latitude, "longitude": FLATIRON.longitude},
            "dropoff_location": {"latitude": CITY_HALL.latitude, "longitude": CITY_HALL.longitude},
            "seat_count": 1,
            "earliest_pickup_time": now + 600,
            "latest_dropoff_time": now + 3600,
            "direct_distance_meters": 3500,
            "direct_duration_seconds": 350,
        },
    )
    assert resp_req.status_code == 201

    # 3. Match host ride
    resp_match = client.post(f"/v1/host-rides/{ride_id}/match", json={"request_id": "req-traveller-pg"})
    assert resp_match.status_code == 200
    proposals = resp_match.json()["proposals"]
    assert len(proposals) == 1
    proposal_id = proposals[0]["proposal_id"]

    # 4. Bilateral acceptance
    resp_a1 = client.post(f"/v1/proposals/{proposal_id}/accept", json={"user_id": "usr-host-pg"})
    assert resp_a1.status_code == 200
    assert resp_a1.json()["is_confirmed"] is False

    resp_a2 = client.post(f"/v1/proposals/{proposal_id}/accept", json={"user_id": "usr-traveller-pg"})
    assert resp_a2.status_code == 200
    assert resp_a2.json()["is_confirmed"] is True

    # 5. Verify confirmed ride in PostgreSQL has updated stops with mandatory endpoints intact
    confirmed_ride = postgres_storage.get_ride(ride_id)
    assert confirmed_ride is not None
    assert len(confirmed_ride.stops) == 4
    # Boundary endpoints intact
    assert confirmed_ride.stops[0].location.latitude == pytest.approx(MIDTOWN.latitude, abs=1e-4)
    assert confirmed_ride.stops[-1].location.latitude == pytest.approx(WALL_ST.latitude, abs=1e-4)
    # Intermediate stops contain traveller
    assert confirmed_ride.stops[1].request_id == "req-traveller-pg"
    assert confirmed_ride.stops[2].request_id == "req-traveller-pg"


def test_postgres_concurrent_seat_contention_on_host_ride(
    postgres_storage: PostgresRideStorage,
) -> None:
    """Verifies that when multiple threads contend for the 1 remaining seat on a host ride,
    exactly one acquires the temporary seat hold and the other is safely rejected."""
    client, service, _ = _build_test_env(postgres_storage)
    now = int(time.time())

    # Host ride with capacity for only 1 traveller (available_seats = 1)
    resp_host = client.post(
        "/v1/host-rides",
        json={
            "driver_id": "usr-host-conc",
            "origin": {"latitude": MIDTOWN.latitude, "longitude": MIDTOWN.longitude},
            "destination": {"latitude": WALL_ST.latitude, "longitude": WALL_ST.longitude},
            "scheduled_departure_time": now + 600,
            "available_seats": 1,
            "max_detour_seconds": 600,
        },
    )
    ride_id = resp_host.json()["ride_id"]

    # Create 2 competing traveller requests
    for req_id, user_id in [("req-c1", "usr-c1"), ("req-c2", "usr-c2")]:
        client.post(
            "/v1/requests",
            json={
                "request_id": req_id,
                "user_id": user_id,
                "pickup_location": {"latitude": FLATIRON.latitude, "longitude": FLATIRON.longitude},
                "dropoff_location": {"latitude": CITY_HALL.latitude, "longitude": CITY_HALL.longitude},
                "seat_count": 1,
                "earliest_pickup_time": now + 600,
                "latest_dropoff_time": now + 3600,
                "direct_distance_meters": 3500,
                "direct_duration_seconds": 350,
            },
        )

    # Spawn 2 concurrent proposal creation attempts targeting the single seat
    def attempt_create_proposal(req_id: str) -> int:
        thread_storage = PostgresRideStorage(dsn=TEST_DB_URL)
        try:
            t_client, _, _ = _build_test_env(thread_storage)
            resp = t_client.post("/v1/proposals", json={"ride_id": ride_id, "request_id": req_id})
            return resp.status_code
        finally:
            thread_storage.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(attempt_create_proposal, "req-c1")
        f2 = executor.submit(attempt_create_proposal, "req-c2")
        status_codes = [f1.result(), f2.result()]

    # Exactly 1 success (201) and 1 conflict (409)
    assert sorted(status_codes) == [201, 409]

    # Verify PostgreSQL active seat holds count is strictly 1
    holds = postgres_storage.get_active_seat_holds(ride_id, current_time=now)
    assert len(holds) == 1
    assert holds[0].seat_count == 1


def test_postgres_en_route_join_ahead_vs_behind_gating(
    postgres_storage: PostgresRideStorage,
) -> None:
    """Verifies that an in-transit vehicle updated in PostgreSQL permits ahead pickups
    and rejects behind pickups under the Ahead-of-Vehicle Spatial Gate."""
    client, service, _ = _build_test_env(postgres_storage)
    now = int(time.time())

    resp_host = client.post(
        "/v1/host-rides",
        json={
            "driver_id": "usr-host-enroute",
            "origin": {"latitude": MIDTOWN.latitude, "longitude": MIDTOWN.longitude},
            "destination": {"latitude": WALL_ST.latitude, "longitude": WALL_ST.longitude},
            "scheduled_departure_time": now + 100,
            "available_seats": 3,
            "max_detour_seconds": 1200,
        },
    )
    ride_id = resp_host.json()["ride_id"]
    veh_id = resp_host.json()["vehicle_id"]

    # Initial traveller confirms ride
    client.post(
        "/v1/requests",
        json={
            "request_id": "req-p1-pg",
            "user_id": "usr-p1-pg",
            "pickup_location": {"latitude": FLATIRON.latitude, "longitude": FLATIRON.longitude},
            "dropoff_location": {"latitude": WALL_ST.latitude, "longitude": WALL_ST.longitude},
            "seat_count": 1,
            "earliest_pickup_time": now + 100,
            "latest_dropoff_time": now + 3600,
            "direct_distance_meters": 4500,
            "direct_duration_seconds": 450,
        },
    )
    p1 = client.post(f"/v1/host-rides/{ride_id}/match", json={"request_id": "req-p1-pg"}).json()["proposals"][0]
    client.post(f"/v1/proposals/{p1['proposal_id']}/accept", json={"user_id": "usr-host-enroute"})
    client.post(f"/v1/proposals/{p1['proposal_id']}/accept", json={"user_id": "usr-p1-pg"})

    # Host vehicle departs and advances to 14th Street
    # Origin and Flatiron pickup stops are completed
    resp_loc = client.post(
        f"/v1/vehicles/{veh_id}/location",
        json={
            "latitude": FOURTEENTH_ST.latitude,
            "longitude": FOURTEENTH_ST.longitude,
            "ride_id": ride_id,
            "completed_stop_ids": [f"stop-origin-{ride_id}", "stop-p-req-p1-pg"],
            "current_time": now + 500,
        },
    )
    assert resp_loc.status_code == 200

    # Traveller Behind: Pickup at Flatiron (behind 14th St)
    client.post(
        "/v1/requests",
        json={
            "request_id": "req-behind-pg",
            "user_id": "usr-behind-pg",
            "pickup_location": {"latitude": FLATIRON.latitude, "longitude": FLATIRON.longitude},
            "dropoff_location": {"latitude": CITY_HALL.latitude, "longitude": CITY_HALL.longitude},
            "seat_count": 1,
            "earliest_pickup_time": now + 500,
            "latest_dropoff_time": now + 3600,
            "direct_distance_meters": 3000,
            "direct_duration_seconds": 300,
        },
    )
    resp_behind = client.post(
        f"/v1/rides/{ride_id}/en-route-join",
        json={"request_id": "req-behind-pg", "current_time": now + 500},
    )
    assert resp_behind.status_code == 409
    behind_data = resp_behind.json()
    assert behind_data["eligible"] is False
    assert behind_data["rejection_reason"] == "PICKUP_BEHIND_VEHICLE"

    # Traveller Ahead: Pickup at Canal St (ahead of 14th St)
    client.post(
        "/v1/requests",
        json={
            "request_id": "req-ahead-pg",
            "user_id": "usr-ahead-pg",
            "pickup_location": {"latitude": CANAL_ST.latitude, "longitude": CANAL_ST.longitude},
            "dropoff_location": {"latitude": CITY_HALL.latitude, "longitude": CITY_HALL.longitude},
            "seat_count": 1,
            "earliest_pickup_time": now + 500,
            "latest_dropoff_time": now + 3600,
            "direct_distance_meters": 1500,
            "direct_duration_seconds": 180,
        },
    )
    resp_ahead = client.post(
        f"/v1/rides/{ride_id}/en-route-join",
        json={"request_id": "req-ahead-pg", "current_time": now + 500},
    )
    assert resp_ahead.status_code == 200
    ahead_data = resp_ahead.json()
    assert ahead_data["eligible"] is True
    assert ahead_data["proposal"] is not None
    assert not ahead_data["proposal"]["is_confirmed"]


def test_existing_fleet_dispatch_unaffected(
    postgres_storage: PostgresRideStorage,
) -> None:
    """Verifies that classic fleet dispatch (POST /v1/dispatch) continues to operate identically."""
    client, service, _ = _build_test_env(postgres_storage)
    now = int(time.time())

    # Register commercial fleet vehicle
    resp_v = client.post(
        "/v1/vehicles",
        json={
            "vehicle_id": "veh-fleet-1",
            "driver_id": "drv-fleet-1",
            "total_seat_capacity": 4,
            "current_location": {"latitude": MIDTOWN.latitude, "longitude": MIDTOWN.longitude},
            "is_active": True,
        },
    )
    assert resp_v.status_code == 201

    # Register request
    client.post(
        "/v1/requests",
        json={
            "request_id": "req-fleet-1",
            "user_id": "usr-fleet-1",
            "pickup_location": {"latitude": FLATIRON.latitude, "longitude": FLATIRON.longitude},
            "dropoff_location": {"latitude": CITY_HALL.latitude, "longitude": CITY_HALL.longitude},
            "seat_count": 1,
            "earliest_pickup_time": now,
            "latest_dropoff_time": now + 3600,
            "direct_distance_meters": 3500,
            "direct_duration_seconds": 350,
        },
    )

    # Run dispatch cycle
    resp = client.post("/v1/dispatch", json={"current_time": now, "cycle_id": "cycle-pg-1"})
    assert resp.status_code == 200
    dispatch_data = resp.json()
    assert len(dispatch_data["committed_assignments"]) == 1
