"""Integration tests for PostgresRideStorage bounded ConnectionPool against live test PostgreSQL."""

import concurrent.futures
import os
import threading
import time
from typing import Any, Generator
import psycopg
import pytest

from engine.adapters.postgres_storage import PostgresRideStorage
from engine.contracts.storage import StorageProviderError
from engine.domain.enums import JoinStatus, RequestStatus, RideStatus
from engine.domain.models import GeoCoordinate, JoinRequest, Ride, RideRequest, RouteStop, Vehicle

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:5433/pool_engine_test"),
)


@pytest.fixture
def pool_storage() -> Generator[PostgresRideStorage, None, None]:
    """Provides a fresh pooled PostgresRideStorage connected to pool_engine_test."""
    try:
        test_conn = psycopg.connect(TEST_DB_URL, connect_timeout=3)
        test_conn.close()
    except Exception as exc:
        pytest.skip(f"Live PostgreSQL test database unavailable at {TEST_DB_URL}: {exc}")

    storage = PostgresRideStorage(dsn=TEST_DB_URL, min_size=2, max_size=5, timeout=3.0)
    storage.create_schema()

    # Clean test tables
    with storage.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                TRUNCATE vehicles, rides, route_stops, ride_requests, join_requests, seat_holds, idempotency_records
                CASCADE;
                """
            )

    yield storage
    storage.close()


def test_pool_startup_acquisition_and_release() -> None:
    """Verifies that the pool starts lazily, hands out connections, and reclaims them upon exit."""
    fresh_storage = PostgresRideStorage(dsn=TEST_DB_URL, min_size=2, max_size=5, timeout=3.0)
    stats_before = fresh_storage.get_pool_stats()
    assert stats_before is None, "Pool should start uninitialized before first query"

    with fresh_storage.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 42")
            assert cur.fetchone()[0] == 42

    stats_after = fresh_storage.get_pool_stats()
    assert stats_after is not None
    assert stats_after["pool_size"] >= 2, "Pool should maintain min_size warm connections"
    assert stats_after["pool_available"] >= 1, "Connection should be reclaimed and available"
    fresh_storage.close()


def test_pool_release_on_exception(pool_storage: PostgresRideStorage) -> None:
    """Verifies that connections are safely returned to the pool even when an unhandled exception occurs."""
    try:
        with pool_storage.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            raise RuntimeError("Simulated failure inside application block")
    except RuntimeError:
        pass

    # Next checkout must succeed immediately
    with pool_storage.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 99")
            assert cur.fetchone()[0] == 99


def test_pool_rollback_after_database_error(pool_storage: PostgresRideStorage) -> None:
    """Verifies that an error inside conn.transaction() rolls back and does not contaminate the connection."""
    # Attempt an invalid transaction
    try:
        with pool_storage.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO vehicles (vehicle_id) VALUES ('missing-required-fields')")
    except Exception:
        pass

    # Verify that subsequent transactions on pooled connections succeed normally
    with pool_storage.connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM vehicles")
                assert cur.fetchone()[0] == 0


def test_pool_exhaustion_and_acquisition_timeout() -> None:
    """Verifies that acquiring more connections than max_size within timeout raises StorageProviderError."""
    # Dedicated tight pool: max_size=2, timeout=0.25s
    tight_storage = PostgresRideStorage(dsn=TEST_DB_URL, min_size=1, max_size=2, timeout=0.25)
    tight_storage.create_schema()

    ev1 = threading.Event()
    ev2 = threading.Event()
    finish_ev = threading.Event()

    def hold_connection(ev: threading.Event) -> None:
        with tight_storage.connection():
            ev.set()
            finish_ev.wait(timeout=2.0)

    t1 = threading.Thread(target=hold_connection, args=(ev1,))
    t2 = threading.Thread(target=hold_connection, args=(ev2,))
    t1.start()
    t2.start()

    assert ev1.wait(timeout=2.0), "Worker 1 should acquire connection"
    assert ev2.wait(timeout=2.0), "Worker 2 should acquire connection"

    # Both connections in max_size=2 are held. Attempting a 3rd checkout must time out!
    with pytest.raises(StorageProviderError, match="Database connection pool exhausted"):
        with tight_storage.connection():
            pass

    finish_ev.set()
    t1.join()
    t2.join()
    tight_storage.close()


def test_multiple_concurrent_threads_separate_backend_pids(pool_storage: PostgresRideStorage) -> None:
    """Verifies that concurrent threads execute on distinct PostgreSQL backend processes."""
    pids: list[int] = []
    lock = threading.Lock()
    barrier = threading.Barrier(4)

    def query_pid() -> None:
        with pool_storage.connection() as conn:
            barrier.wait(timeout=3.0)  # Synchronize threads so all 4 hold connections at the same instant
            with conn.cursor() as cur:
                cur.execute("SELECT pg_backend_pid()")
                pid = cur.fetchone()[0]
                with lock:
                    pids.append(pid)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(query_pid) for _ in range(4)]
        for f in futures:
            f.result()

    assert len(pids) == 4
    # All 4 backend PIDs must be distinct, proving 4 separate concurrent PostgreSQL connections were active
    assert len(set(pids)) == 4, f"Expected 4 distinct backend PIDs, got {pids}"


def test_concurrent_seat_holds_under_pooled_connections(pool_storage: PostgresRideStorage) -> None:
    """5 concurrent threads contending for 1 remaining seat on the same shared PostgresRideStorage instance.
    SELECT ... FOR UPDATE must ensure exactly 1 succeeds and 4 receive False, with zero deadlock or nesting errors.
    """
    now = int(time.time())
    vehicle = Vehicle(
        vehicle_id="veh-tight-pool-1",
        driver_id="usr-host-tight",
        total_seat_capacity=1,  # Only 1 seat available
        current_location=GeoCoordinate(latitude=40.7580, longitude=-73.9855),
        is_active=True,
    )
    pool_storage.save_vehicle(vehicle)

    ride = Ride(
        ride_id="ride-tight-pool-1",
        vehicle_id=vehicle.vehicle_id,
        driver_id=vehicle.driver_id,
        lifecycle_status=RideStatus.ACTIVE,
        stops=(),
        scheduled_departure_time=now,
        active_passenger_count=0,
        version=1,
    )
    pool_storage.save_ride(ride)

    results: list[bool] = []
    lock = threading.Lock()

    def attempt_hold(req_idx: int) -> None:
        req_id = f"req-pool-contend-{req_idx}"
        join_id = f"join-pool-contend-{req_idx}"
        success = pool_storage.acquire_seat_hold_atomic(
            ride_id=ride.ride_id,
            request_id=req_id,
            join_request_id=join_id,
            seat_count=1,
            submitted_at=now,
            expires_at=now + 300,
            expected_version=1,
            idempotency_token=f"tok-pool-contend-{req_idx}",
        )
        with lock:
            results.append(success)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(attempt_hold, i) for i in range(5)]
        for f in futures:
            f.result()

    # Exactly 1 success, 4 failures
    assert results.count(True) == 1, f"Expected exactly 1 seat hold granted, got: {results}"
    assert results.count(False) == 4, f"Expected 4 rejections, got: {results}"

    # Verify exactly 1 seat hold exists in the database
    with pool_storage.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM seat_holds WHERE ride_id = %s", (ride.ride_id,))
            assert cur.fetchone()[0] == 1


def test_concurrent_proposal_acceptance_shared_pool_storage(pool_storage: PostgresRideStorage) -> None:
    """Host and traveller call record_proposal_acceptance concurrently sharing the SAME PostgresRideStorage instance.
    Previously failed with OutOfOrderTransactionNesting; under ConnectionPool, both transactions commit cleanly.
    """
    now = int(time.time())
    veh_id = "veh-pool-accept-1"
    ride_id = "ride-pool-accept-1"
    req_id = "req-pool-accept-1"
    join_id = "join-pool-accept-race-1"

    # 1. Create parent vehicle
    veh = Vehicle(
        vehicle_id=veh_id,
        driver_id="usr-pool-host",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=40.7580, longitude=-73.9855),
        is_active=True,
    )
    pool_storage.save_vehicle(veh)

    # 2. Create parent ride
    ride = Ride(
        ride_id=ride_id,
        vehicle_id=veh_id,
        driver_id="usr-pool-host",
        lifecycle_status=RideStatus.SCHEDULED,
        stops=(),
        scheduled_departure_time=now + 3600,
        active_passenger_count=0,
        version=1,
    )
    pool_storage.save_ride(ride)

    # 3. Create parent request
    req = RideRequest(
        request_id=req_id,
        user_id="usr-pool-traveller",
        pickup_location=GeoCoordinate(latitude=40.7410, longitude=-73.9897),
        dropoff_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        seat_count=1,
        earliest_pickup_time=now + 3500,
        latest_dropoff_time=now + 5000,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    pool_storage.save_request(req)

    # 4. Create pending proposal
    join_req = JoinRequest(
        join_request_id=join_id,
        ride_id=ride_id,
        request_id=req_id,
        user_id="usr-pool-traveller",
        seat_count=1,
        submitted_at=now,
        expires_at=now + 300,
        status=JoinStatus.PENDING,
        idempotency_token="tok-pool-accept-race",
        host_accepted=False,
        traveller_accepted=False,
    )
    pool_storage.save_join_request(join_req)

    def accept_host() -> Any:
        return pool_storage.record_proposal_acceptance(join_id, is_host=True, is_traveller=False)

    def accept_traveller() -> Any:
        return pool_storage.record_proposal_acceptance(join_id, is_host=False, is_traveller=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_host = executor.submit(accept_host)
        f_traveller = executor.submit(accept_traveller)
        res_host = f_host.result()
        res_traveller = f_traveller.result()

    assert res_host is not None
    assert res_traveller is not None

    # Verify updated state in database has BOTH accepted
    updated = pool_storage.get_join_request(join_id)
    assert updated is not None
    assert updated.host_accepted is True
    assert updated.traveller_accepted is True
