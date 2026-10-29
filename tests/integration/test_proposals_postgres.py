"""Live PostgreSQL integration tests for marketplace proposal lifecycle and bilateral acceptance.

Verifies:
- Durable persistence of JoinRequest and SeatHold state in PostgreSQL.
- Two-party acceptance (host + traveller) committing atomically via PostgreSQL transactions.
- Concurrent seat contention during proposal creation (SELECT ... FOR UPDATE).
- Concurrent acceptance thread-safety.
- Concurrent cancellation racing with proposal confirmation.
- Immediate release of seat holds on proposal decline.
- Unauthenticated/stranger coordinate masking and user ID redaction.
"""

import concurrent.futures
import os
import time
from typing import Any, Generator

import psycopg
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.mock_routing import MockRoutingProvider
from engine.adapters.postgres_storage import PostgresRideStorage
from engine.domain.enums import JoinStatus, RequestStatus, RideStatus
from engine.domain.models import GeoCoordinate, Ride, RideRequest, Vehicle
from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator, OrchestrationConfig
from engine.service.app import create_app
from engine.service.client import AsgiTestClient
from engine.service.schemas import CreateProposalInput
from engine.service.service import PoolEngineService

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


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


def _build_test_client(
    storage: PostgresRideStorage,
) -> tuple[AsgiTestClient, PoolEngineService]:
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
    return client, service


def _setup_pg_fixtures(
    storage: PostgresRideStorage,
    capacity: int = 4,
    base_time: int | None = None,
) -> tuple[Vehicle, Ride, RideRequest]:
    now = base_time if base_time is not None else int(time.time())

    vehicle = Vehicle(
        vehicle_id="veh-pg-host",
        driver_id="usr-pg-host",
        total_seat_capacity=capacity,
        current_location=GeoCoordinate(latitude=40.7580, longitude=-73.9855),
        is_active=True,
    )
    storage.save_vehicle(vehicle)

    ride = Ride(
        ride_id="ride-pg-host",
        vehicle_id=vehicle.vehicle_id,
        driver_id=vehicle.driver_id,
        lifecycle_status=RideStatus.ACTIVE,
        stops=(),
        scheduled_departure_time=now,
        active_passenger_count=0,
        version=1,
    )
    storage.save_ride(ride)

    req = RideRequest(
        request_id="req-pg-traveller",
        user_id="usr-pg-traveller",
        pickup_location=GeoCoordinate(latitude=40.7410, longitude=-73.9897),
        dropoff_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        seat_count=1,
        earliest_pickup_time=now - 60,
        latest_dropoff_time=now + 7200,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    storage.save_request(req)
    return vehicle, ride, req


def test_postgres_proposal_full_bilateral_lifecycle(
    postgres_storage: PostgresRideStorage,
) -> None:
    """Verifies complete proposal lifecycle persisted to PostgreSQL and confirmed atomically."""
    client, service = _build_test_client(postgres_storage)
    _, ride, req = _setup_pg_fixtures(postgres_storage)

    # 1. Create Proposal via API
    resp_create = client.post(
        "/v1/proposals",
        json={"ride_id": ride.ride_id, "request_id": req.request_id, "seat_count": 1},
    )
    assert resp_create.status_code == 201
    prop_data = resp_create.json()
    proposal_id = prop_data["proposal_id"]
    assert prop_data["status"] == "PENDING"
    assert not prop_data["host_accepted"]
    assert not prop_data["traveller_accepted"]
    assert not prop_data["is_confirmed"]

    # Verify PostgreSQL seat_holds and join_requests records
    conn = postgres_storage._get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT host_accepted, traveller_accepted FROM join_requests WHERE join_request_id = %s",
            (proposal_id,),
        )
        jr_row = cur.fetchone()
        assert jr_row is not None
        assert jr_row[0] is False  # host_accepted
        assert jr_row[1] is False  # traveller_accepted

        cur.execute("SELECT * FROM seat_holds WHERE join_request_id = %s", (proposal_id,))
        hold_row = cur.fetchone()
        assert hold_row is not None
        assert hold_row[3] == 1  # seat_count

    # 2. Host accepts first -> Proposal remains PENDING
    resp_host = client.post(
        f"/v1/proposals/{proposal_id}/accept",
        json={"user_id": "usr-pg-host"},
    )
    assert resp_host.status_code == 200
    host_accept_data = resp_host.json()
    assert host_accept_data["host_accepted"] is True
    assert host_accept_data["traveller_accepted"] is False
    assert host_accept_data["is_confirmed"] is False

    # Verify ride in DB still has 0 stops
    assert len(postgres_storage.get_ride(ride.ride_id).stops) == 0  # type: ignore[union-attr]

    # 3. Traveller accepts second -> Mutual acceptance triggers atomic confirmation!
    resp_traveller = client.post(
        f"/v1/proposals/{proposal_id}/accept",
        json={"user_id": "usr-pg-traveller"},
    )
    assert resp_traveller.status_code == 200
    traveller_accept_data = resp_traveller.json()
    assert traveller_accept_data["host_accepted"] is True
    assert traveller_accept_data["traveller_accepted"] is True
    assert traveller_accept_data["is_confirmed"] is True
    assert traveller_accept_data["status"] == "CONFIRMED"

    # Verify in PostgreSQL:
    # a. Route stops persisted (2 stops)
    confirmed_ride = postgres_storage.get_ride(ride.ride_id)
    assert confirmed_ride is not None
    assert len(confirmed_ride.stops) == 2
    assert confirmed_ride.version > 1

    # b. Seat hold deleted
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM seat_holds WHERE join_request_id = %s", (proposal_id,))
        count_row = cur.fetchone()
        assert count_row is not None
        assert count_row[0] == 0

    # c. Request marked MATCHED
    persisted_req = postgres_storage.get_request(req.request_id)
    assert persisted_req is not None
    assert persisted_req.status == RequestStatus.MATCHED

    # 4. Inspect as stranger -> Masked
    resp_stranger = client.get(
        f"/v1/proposals/{proposal_id}",
        headers={"X-User-Id": "usr-stranger"},
    )
    assert resp_stranger.status_code == 200
    stranger_view = resp_stranger.json()
    assert stranger_view["is_masked"] is True
    assert stranger_view["host_id"] is None
    assert stranger_view["traveller_id"] is None


def test_postgres_concurrent_proposal_creation_contention(
    postgres_storage: PostgresRideStorage,
) -> None:
    """Two concurrent requests competing for 1 remaining seat.
    SELECT ... FOR UPDATE in acquire_seat_hold_atomic guarantees exactly 1 gets hold, 1 gets OVER_CAPACITY.
    """
    now = int(time.time())
    vehicle = Vehicle(
        vehicle_id="veh-tight-1",
        driver_id="usr-host-tight",
        total_seat_capacity=1,  # Only 1 seat!
        current_location=GeoCoordinate(latitude=40.7580, longitude=-73.9855),
        is_active=True,
    )
    postgres_storage.save_vehicle(vehicle)

    ride = Ride(
        ride_id="ride-tight-1",
        vehicle_id=vehicle.vehicle_id,
        driver_id=vehicle.driver_id,
        lifecycle_status=RideStatus.ACTIVE,
        stops=(),
        scheduled_departure_time=now,
        active_passenger_count=0,
        version=1,
    )
    postgres_storage.save_ride(ride)

    req1 = RideRequest(
        request_id="req-compete-1",
        user_id="usr-compete-1",
        pickup_location=GeoCoordinate(latitude=40.7410, longitude=-73.9897),
        dropoff_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        seat_count=1,
        earliest_pickup_time=now - 60,
        latest_dropoff_time=now + 7200,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    postgres_storage.save_request(req1)

    req2 = RideRequest(
        request_id="req-compete-2",
        user_id="usr-compete-2",
        pickup_location=GeoCoordinate(latitude=40.7420, longitude=-73.9880),
        dropoff_location=GeoCoordinate(latitude=40.7135, longitude=-74.0050),
        seat_count=1,
        earliest_pickup_time=now - 60,
        latest_dropoff_time=now + 7200,
        direct_distance_meters=5100,
        direct_duration_seconds=620,
        status=RequestStatus.PENDING,
    )
    postgres_storage.save_request(req2)

    def attempt_create(req_id: str) -> tuple[int, dict[str, Any]]:
        thread_storage = PostgresRideStorage(dsn=TEST_DB_URL)
        try:
            client, _ = _build_test_client(thread_storage)
            resp = client.post(
                "/v1/proposals",
                json={"ride_id": ride.ride_id, "request_id": req_id, "seat_count": 1},
            )
            return resp.status_code, resp.json()
        finally:
            thread_storage.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(attempt_create, req1.request_id)
        f2 = executor.submit(attempt_create, req2.request_id)
        results = [f1.result(), f2.result()]

    status_codes = [r[0] for r in results]
    assert 201 in status_codes
    assert 409 in status_codes

    # Exactly 1 active hold in database
    conn = postgres_storage._get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM seat_holds WHERE ride_id = %s", (ride.ride_id,))
        count_row = cur.fetchone()
        assert count_row is not None
        assert count_row[0] == 1


def test_postgres_concurrent_acceptance_race(
    postgres_storage: PostgresRideStorage,
) -> None:
    """Host and traveller call /accept concurrently.
    PostgreSQL transaction serialization ensures exactly one marks host, one marks traveller,
    and confirmation executes cleanly without duplicating stops.
    """
    client, service = _build_test_client(postgres_storage)
    _, ride, req = _setup_pg_fixtures(postgres_storage)

    resp_create = client.post(
        "/v1/proposals",
        json={"ride_id": ride.ride_id, "request_id": req.request_id, "seat_count": 1},
    )
    assert resp_create.status_code == 201
    proposal_id = resp_create.json()["proposal_id"]

    def accept_as(user_id: str) -> tuple[int, dict[str, Any]]:
        thread_storage = PostgresRideStorage(dsn=TEST_DB_URL)
        try:
            thread_client, _ = _build_test_client(thread_storage)
            resp = thread_client.post(
                f"/v1/proposals/{proposal_id}/accept",
                json={"user_id": user_id},
            )
            return resp.status_code, resp.json()
        finally:
            thread_storage.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_host = executor.submit(accept_as, "usr-pg-host")
        f_traveller = executor.submit(accept_as, "usr-pg-traveller")
        results = [f_host.result(), f_traveller.result()]

    # Both must succeed (200 OK)
    assert results[0][0] == 200
    assert results[1][0] == 200

    # Final state in DB: confirmed ride with exactly 2 stops
    final_ride = postgres_storage.get_ride(ride.ride_id)
    assert final_ride is not None
    assert len(final_ride.stops) == 2


def test_postgres_decline_releases_hold_immediately(
    postgres_storage: PostgresRideStorage,
) -> None:
    """Declining a proposal immediately removes seat hold from PostgreSQL."""
    client, _ = _build_test_client(postgres_storage)
    _, ride, req = _setup_pg_fixtures(postgres_storage)

    resp_create = client.post(
        "/v1/proposals",
        json={"ride_id": ride.ride_id, "request_id": req.request_id, "seat_count": 1},
    )
    proposal_id = resp_create.json()["proposal_id"]

    # Verify hold exists
    conn = postgres_storage._get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM seat_holds WHERE join_request_id = %s", (proposal_id,))
        count_row = cur.fetchone()
        assert count_row is not None
        assert count_row[0] == 1

    # Host declines
    resp_decline = client.post(
        f"/v1/proposals/{proposal_id}/decline",
        json={"user_id": "usr-pg-host"},
    )
    assert resp_decline.status_code == 200
    assert resp_decline.json()["status"] == "DECLINED"

    # Hold must be gone in DB
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM seat_holds WHERE join_request_id = %s", (proposal_id,))
        count_row_after = cur.fetchone()
        assert count_row_after is not None
        assert count_row_after[0] == 0

    # Subsequent accept call fails
    resp_accept = client.post(
        f"/v1/proposals/{proposal_id}/accept",
        json={"user_id": "usr-pg-traveller"},
    )
    assert resp_accept.status_code == 409
    assert resp_accept.json()["error"]["code"] == "PROPOSAL_DECLINED"


def test_postgres_cancellation_racing_with_confirmation_aborts_cleanly(
    postgres_storage: PostgresRideStorage,
) -> None:
    """If a traveller cancels before second acceptance, confirmation aborts and frees seats in PostgreSQL."""
    client, _ = _build_test_client(postgres_storage)
    _, ride, req = _setup_pg_fixtures(postgres_storage)

    resp_create = client.post(
        "/v1/proposals",
        json={"ride_id": ride.ride_id, "request_id": req.request_id, "seat_count": 1},
    )
    proposal_id = resp_create.json()["proposal_id"]

    # Host accepts first
    client.post(f"/v1/proposals/{proposal_id}/accept", json={"user_id": "usr-pg-host"})

    # Traveller cancels the underlying request
    client.post(f"/v1/requests/{req.request_id}/cancel")

    # Traveller now attempts to accept proposal
    resp_accept = client.post(
        f"/v1/proposals/{proposal_id}/accept",
        json={"user_id": "usr-pg-traveller"},
    )
    assert resp_accept.status_code == 409
    assert resp_accept.json()["error"]["code"] == "REQUEST_CANCELLED"

    # Ride was NOT confirmed in PostgreSQL
    fetched_ride = postgres_storage.get_ride(ride.ride_id)
    assert fetched_ride is not None
    assert len(fetched_ride.stops) == 0

    # Seat hold is released in PostgreSQL
    conn = postgres_storage._get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM seat_holds WHERE ride_id = %s", (ride.ride_id,))
        count_row_cancel = cur.fetchone()
        assert count_row_cancel is not None
        assert count_row_cancel[0] == 0
