"""Integration tests for PostgresRideStorage with live PostgreSQL/PostGIS (T050).

These tests verify schema creation, full CRUD persistence across adapter instances,
atomic seat holds, optimistic concurrency control (OCC), exact-boundary expiration,
and multi-threaded contention under row-level locking (SELECT ... FOR UPDATE).

Skipped automatically if no live PostgreSQL server is accessible via TEST_DATABASE_URL or DATABASE_URL.
"""

import concurrent.futures
import os
from typing import Generator

import psycopg
import pytest

from engine.adapters.postgres_storage import PostgresRideStorage
from engine.contracts.storage import IdempotencyRecord, SeatHold
from engine.domain.enums import JoinStatus, RequestStatus, RideStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, JoinRequest, Ride, RideRequest, RouteStop, Vehicle

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


def test_schema_migration_idempotent(postgres_storage: PostgresRideStorage) -> None:
    """Verifies that create_schema can be executed multiple times without failure."""
    postgres_storage.create_schema()
    postgres_storage.create_schema()


def test_vehicle_and_ride_crud_persistence(postgres_storage: PostgresRideStorage) -> None:
    """
    Verifies that Vehicles, Rides, and RouteStops persist across separate storage instances
    and reflect updates accurately.
    """
    assert TEST_DB_URL is not None
    v = Vehicle(
        vehicle_id="veh-int-1",
        driver_id="drv-int-1",
        total_seat_capacity=4,
        luggage_capacity_units=2,
        current_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        is_active=True,
    )
    postgres_storage.save_vehicle(v)

    stop1 = RouteStop(
        stop_id="stop-1",
        ride_id="ride-int-1",
        request_id="req-1",
        stop_type=StopType.PICKUP,
        location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        passenger_delta=1,
        scheduled_arrival_time=1000,
        promised_window_start=950,
        promised_window_end=1100,
        actual_arrival_time=None,
        dwell_duration_seconds=30,
        dwell_start_time=None,
        status=StopStatus.SCHEDULED,
    )
    stop2 = RouteStop(
        stop_id="stop-2",
        ride_id="ride-int-1",
        request_id="req-1",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=40.7589, longitude=-73.9851),
        passenger_delta=-1,
        scheduled_arrival_time=1600,
        promised_window_start=1500,
        promised_window_end=1800,
        actual_arrival_time=None,
        dwell_duration_seconds=30,
        dwell_start_time=None,
        status=StopStatus.SCHEDULED,
    )

    ride = Ride(
        ride_id="ride-int-1",
        vehicle_id="veh-int-1",
        driver_id="drv-int-1",
        lifecycle_status=RideStatus.SCHEDULED,
        stops=(stop1, stop2),
        scheduled_departure_time=1000,
        actual_departure_time=None,
        active_passenger_count=0,
        total_vmt_meters=12000,
        version=1,
    )
    postgres_storage.save_ride(ride)

    # Instantiate a second independent storage instance
    storage2 = PostgresRideStorage(dsn=TEST_DB_URL)
    loaded_vehicle = storage2.get_vehicle("veh-int-1")
    assert loaded_vehicle is not None
    assert loaded_vehicle == v

    loaded_ride = storage2.get_ride("ride-int-1")
    assert loaded_ride is not None
    assert loaded_ride.ride_id == "ride-int-1"
    assert loaded_ride.lifecycle_status == RideStatus.SCHEDULED
    assert len(loaded_ride.stops) == 2
    assert loaded_ride.stops[0].stop_id == "stop-1"
    assert loaded_ride.stops[1].stop_id == "stop-2"

    # Update ride lifecycle status and version
    updated_ride = Ride(
        ride_id="ride-int-1",
        vehicle_id="veh-int-1",
        driver_id="drv-int-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop1, stop2),
        scheduled_departure_time=1000,
        actual_departure_time=1005,
        active_passenger_count=1,
        total_vmt_meters=12500,
        version=2,
    )
    storage2.save_ride(updated_ride)

    reloaded_ride = postgres_storage.get_ride("ride-int-1")
    assert reloaded_ride is not None
    assert reloaded_ride.lifecycle_status == RideStatus.ACTIVE
    assert reloaded_ride.active_passenger_count == 1
    assert reloaded_ride.version == 2
    storage2.close()


def test_ride_request_and_join_request_persistence(postgres_storage: PostgresRideStorage) -> None:
    """Verifies persistence and update lifecycle of RideRequest and JoinRequest."""
    req = RideRequest(
        request_id="req-int-1",
        user_id="user-1",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7589, longitude=-73.9851),
        seat_count=2,
        earliest_pickup_time=1000,
        latest_dropoff_time=2000,
        direct_distance_meters=8500,
        direct_duration_seconds=900,
        status=RequestStatus.PENDING,
        matched_ride_id=None,
    )
    postgres_storage.save_request(req)

    loaded_req = postgres_storage.get_request("req-int-1")
    assert loaded_req is not None
    assert loaded_req == req

    v = Vehicle(
        vehicle_id="veh-int-1",
        driver_id="drv-int-1",
        total_seat_capacity=4,
        luggage_capacity_units=2,
        current_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        is_active=True,
    )
    postgres_storage.save_vehicle(v)

    ride = Ride(
        ride_id="ride-int-1",
        vehicle_id="veh-int-1",
        driver_id="drv-int-1",
        lifecycle_status=RideStatus.SCHEDULED,
        stops=(),
        scheduled_departure_time=1000,
        actual_departure_time=None,
        active_passenger_count=0,
        total_vmt_meters=12000,
        version=1,
    )
    postgres_storage.save_ride(ride)

    join_req = JoinRequest(
        join_request_id="join-int-1",
        ride_id="ride-int-1",
        request_id="req-int-1",
        user_id="user-1",
        seat_count=2,
        submitted_at=1000,
        expires_at=1300,
        status=JoinStatus.PENDING,
        idempotency_token="idem-tok-1",
    )
    postgres_storage.save_join_request(join_req)

    loaded_join = postgres_storage.get_join_request("join-int-1")
    assert loaded_join is not None
    assert loaded_join == join_req

    # Update join request to APPROVED
    updated_join = JoinRequest(
        join_request_id="join-int-1",
        ride_id="ride-int-1",
        request_id="req-int-1",
        user_id="user-1",
        seat_count=2,
        submitted_at=1000,
        expires_at=1300,
        status=JoinStatus.APPROVED,
        idempotency_token="idem-tok-1",
    )
    postgres_storage.save_join_request(updated_join)
    reloaded_join = postgres_storage.get_join_request("join-int-1")
    assert reloaded_join is not None
    assert reloaded_join.status == JoinStatus.APPROVED


def test_spatial_bounding_box_query(postgres_storage: PostgresRideStorage) -> None:
    """Verifies that bounding-box spatial queries locate active and scheduled rides."""
    v = Vehicle(
        vehicle_id="veh-spatial-1",
        driver_id="drv-spatial-1",
        total_seat_capacity=4,
        luggage_capacity_units=2,
        current_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        is_active=True,
    )
    postgres_storage.save_vehicle(v)

    ride = Ride(
        ride_id="ride-spatial-1",
        vehicle_id="veh-spatial-1",
        driver_id="drv-spatial-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(),
        scheduled_departure_time=1000,
        active_passenger_count=0,
        version=1,
    )
    postgres_storage.save_ride(ride)

    # Query bounding box covering NYC (should return the ride)
    nyc_rides = postgres_storage.get_active_rides_in_bounding_box(
        min_lat=40.70,
        min_lon=-74.05,
        max_lat=40.75,
        max_lon=-73.95,
    )
    assert len(nyc_rides) == 1
    assert nyc_rides[0].ride_id == "ride-spatial-1"

    # Query bounding box covering London (should return empty)
    lon_rides = postgres_storage.get_active_rides_in_bounding_box(
        min_lat=51.40,
        min_lon=-0.20,
        max_lat=51.60,
        max_lon=0.10,
    )
    assert len(lon_rides) == 0


def test_atomic_seat_hold_and_reservation_flow(postgres_storage: PostgresRideStorage) -> None:
    """
    Verifies full reservation flow:
    - Hold acquisition
    - Active holds query
    - Idempotency token registration & replay
    - Capacity enforcement
    - Promotion to reservation
    """
    v = Vehicle(
        vehicle_id="veh-res-1",
        driver_id="drv-res-1",
        total_seat_capacity=4,
        luggage_capacity_units=2,
        current_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        is_active=True,
    )
    postgres_storage.save_vehicle(v)

    ride = Ride(
        ride_id="ride-res-1",
        vehicle_id="veh-res-1",
        driver_id="drv-res-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(),
        scheduled_departure_time=1000,
        active_passenger_count=0,
        version=1,
    )
    postgres_storage.save_ride(ride)

    # 1. Acquire hold for 2 seats
    ok = postgres_storage.acquire_seat_hold_atomic(
        ride_id="ride-res-1",
        request_id="req-res-1",
        join_request_id="join-res-1",
        seat_count=2,
        submitted_at=1000,
        expires_at=1300,
        expected_version=1,
        idempotency_token="tok-hold-1",
    )
    assert ok is True

    # 2. Check active seat holds
    holds = postgres_storage.get_active_seat_holds("ride-res-1", current_time=1000)
    assert len(holds) == 1
    assert holds[0].join_request_id == "join-res-1"
    assert holds[0].seat_count == 2

    # 3. Check idempotency record
    rec = postgres_storage.get_idempotency_record("tok-hold-1")
    assert rec is not None
    assert rec.token == "tok-hold-1"
    assert rec.record_type == "hold"

    # 4. Idempotent replay of identical hold acquisition
    replay_ok = postgres_storage.acquire_seat_hold_atomic(
        ride_id="ride-res-1",
        request_id="req-res-1",
        join_request_id="join-res-1",
        seat_count=2,
        submitted_at=1000,
        expires_at=1300,
        expected_version=1,
        idempotency_token="tok-hold-1",
    )
    assert replay_ok is True

    # 5. Conflicting hold acquisition with same token must fail
    conflict_ok = postgres_storage.acquire_seat_hold_atomic(
        ride_id="ride-res-1",
        request_id="req-conflict",
        join_request_id="join-conflict",
        seat_count=1,
        submitted_at=1000,
        expires_at=1300,
        expected_version=2,
        idempotency_token="tok-hold-1",
    )
    assert conflict_ok is False

    # 6. Acquire second hold for remaining 2 seats (version was bumped to 2)
    ride_v2 = postgres_storage.get_ride("ride-res-1")
    assert ride_v2 is not None
    assert ride_v2.version == 2
    ok2 = postgres_storage.acquire_seat_hold_atomic(
        ride_id="ride-res-1",
        request_id="req-res-2",
        join_request_id="join-res-2",
        seat_count=2,
        submitted_at=1050,
        expires_at=1350,
        expected_version=ride_v2.version,
        idempotency_token="tok-hold-2",
    )
    assert ok2 is True

    # 7. Attempt third hold (capacity 4 is fully exhausted)
    ride_v3 = postgres_storage.get_ride("ride-res-1")
    assert ride_v3 is not None
    assert ride_v3.version == 3
    ok3 = postgres_storage.acquire_seat_hold_atomic(
        ride_id="ride-res-1",
        request_id="req-res-3",
        join_request_id="join-res-3",
        seat_count=1,
        submitted_at=1100,
        expires_at=1400,
        expected_version=ride_v3.version,
        idempotency_token="tok-hold-3",
    )
    assert ok3 is False

    # 8. Promote first hold to reservation
    res_ok = postgres_storage.reserve_seats_atomic(
        ride_id="ride-res-1",
        request_id="req-res-1",
        join_request_id="join-res-1",
        seat_count=2,
        expected_version=ride_v3.version,
        idempotency_token="tok-res-1",
        current_time=1150,
    )
    assert res_ok is True

    # Hold must now be cleared
    holds_after = postgres_storage.get_active_seat_holds("ride-res-1", current_time=1150)
    assert len(holds_after) == 1
    assert holds_after[0].join_request_id == "join-res-2"

    # Idempotent replay of reservation
    res_replay = postgres_storage.reserve_seats_atomic(
        ride_id="ride-res-1",
        request_id="req-res-1",
        join_request_id="join-res-1",
        seat_count=2,
        expected_version=ride_v3.version,
        idempotency_token="tok-res-1",
        current_time=1160,
    )
    assert res_replay is True


def test_seat_hold_exact_boundary_expiry_and_sweep(postgres_storage: PostgresRideStorage) -> None:
    """
    Verifies that seat holds follow strict exact-boundary semantics:
    - current_time <= expires_at: hold is active
    - current_time > expires_at: hold is expired
    - sweep_expired_holds cleans up expired holds idempotently
    """
    v = Vehicle(
        vehicle_id="veh-exp-1",
        driver_id="drv-exp-1",
        total_seat_capacity=4,
        luggage_capacity_units=2,
        current_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        is_active=True,
    )
    postgres_storage.save_vehicle(v)

    ride = Ride(
        ride_id="ride-exp-1",
        vehicle_id="veh-exp-1",
        driver_id="drv-exp-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(),
        scheduled_departure_time=1000,
        active_passenger_count=0,
        version=1,
    )
    postgres_storage.save_ride(ride)

    # Hold expiring at exact timestamp 1300
    ok = postgres_storage.acquire_seat_hold_atomic(
        ride_id="ride-exp-1",
        request_id="req-exp-1",
        join_request_id="join-exp-1",
        seat_count=2,
        submitted_at=1000,
        expires_at=1300,
        expected_version=1,
        idempotency_token="tok-exp-1",
    )
    assert ok is True

    # At t = 1300, hold is still active
    holds_1300 = postgres_storage.get_active_seat_holds("ride-exp-1", current_time=1300)
    assert len(holds_1300) == 1

    # At t = 1300, sweep sweeps nothing
    swept_1300 = postgres_storage.sweep_expired_holds(current_time=1300)
    assert len(swept_1300) == 0

    # At t = 1301, hold is expired and not returned
    holds_1301 = postgres_storage.get_active_seat_holds("ride-exp-1", current_time=1301)
    assert len(holds_1301) == 0

    # At t = 1301, sweep cleans the hold
    swept_1301 = postgres_storage.sweep_expired_holds(current_time=1301)
    assert swept_1301 == ["join-exp-1"]

    # Second sweep is idempotent
    swept_again = postgres_storage.sweep_expired_holds(current_time=1301)
    assert len(swept_again) == 0


def test_optimistic_concurrency_version_mismatch(postgres_storage: PostgresRideStorage) -> None:
    """Verifies that stale version numbers are rejected atomically without state corruption."""
    v = Vehicle(
        vehicle_id="veh-occ-1",
        driver_id="drv-occ-1",
        total_seat_capacity=4,
        luggage_capacity_units=2,
        current_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        is_active=True,
    )
    postgres_storage.save_vehicle(v)

    ride = Ride(
        ride_id="ride-occ-1",
        vehicle_id="veh-occ-1",
        driver_id="drv-occ-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(),
        scheduled_departure_time=1000,
        active_passenger_count=0,
        version=1,
    )
    postgres_storage.save_ride(ride)

    # Attempt acquire with stale expected_version = 99
    ok = postgres_storage.acquire_seat_hold_atomic(
        ride_id="ride-occ-1",
        request_id="req-occ-1",
        join_request_id="join-occ-1",
        seat_count=2,
        submitted_at=1000,
        expires_at=1300,
        expected_version=99,
        idempotency_token="tok-occ-stale",
    )
    assert ok is False

    # Ensure ride version remains 1 and no holds were created
    ride_curr = postgres_storage.get_ride("ride-occ-1")
    assert ride_curr is not None
    assert ride_curr.version == 1
    assert len(postgres_storage.get_active_seat_holds("ride-occ-1")) == 0


def test_concurrent_seat_hold_contention(postgres_storage: PostgresRideStorage) -> None:
    """
    Verifies row-level locking (SELECT ... FOR UPDATE) under concurrent thread contention.
    Multiple independent database sessions race to acquire the last seats in a vehicle.
    Exactly one must succeed, and total capacity must never be exceeded.
    """
    assert TEST_DB_URL is not None
    v = Vehicle(
        vehicle_id="veh-race-1",
        driver_id="drv-race-1",
        total_seat_capacity=2,
        luggage_capacity_units=2,
        current_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        is_active=True,
    )
    postgres_storage.save_vehicle(v)

    ride = Ride(
        ride_id="ride-race-1",
        vehicle_id="veh-race-1",
        driver_id="drv-race-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(),
        scheduled_departure_time=1000,
        active_passenger_count=0,
        version=1,
    )
    postgres_storage.save_ride(ride)

    def _attempt_hold(worker_idx: int) -> bool:
        # Each worker thread opens an independent connection to test real DB locking
        worker_storage = PostgresRideStorage(dsn=TEST_DB_URL)
        try:
            return worker_storage.acquire_seat_hold_atomic(
                ride_id="ride-race-1",
                request_id=f"req-race-{worker_idx}",
                join_request_id=f"join-race-{worker_idx}",
                seat_count=2,
                submitted_at=1000,
                expires_at=1300,
                expected_version=1,
                idempotency_token=f"tok-race-{worker_idx}",
            )
        finally:
            worker_storage.close()

    # Launch 4 competing threads for the 2 available seats
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_attempt_hold, i) for i in range(4)]
        results = [f.result() for f in futures]

    successes = sum(1 for r in results if r is True)
    failures = sum(1 for r in results if r is False)

    assert successes == 1, f"Expected exactly 1 thread to acquire hold, got {successes}"
    assert failures == 3, f"Expected 3 threads to be rejected, got {failures}"

    holds = postgres_storage.get_active_seat_holds("ride-race-1", current_time=1000)
    assert len(holds) == 1
    assert holds[0].seat_count == 2


def test_transaction_rollback_on_error(postgres_storage: PostgresRideStorage) -> None:
    """Verifies that failures inside transaction blocks roll back completely."""
    v = Vehicle(
        vehicle_id="veh-rb-1",
        driver_id="drv-rb-1",
        total_seat_capacity=4,
        luggage_capacity_units=2,
        current_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        is_active=True,
    )
    postgres_storage.save_vehicle(v)

    ride = Ride(
        ride_id="ride-rb-1",
        vehicle_id="veh-rb-1",
        driver_id="drv-rb-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(),
        scheduled_departure_time=1000,
        active_passenger_count=0,
        version=1,
    )
    postgres_storage.save_ride(ride)

    # Trigger a database CheckViolation inside a transaction
    conn = postgres_storage._get_connection()
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            with conn.cursor() as cur:
                # Mutate ride version
                cur.execute("UPDATE rides SET version = 99 WHERE ride_id = %s", ("ride-rb-1",))
                # Insert seat hold with invalid seat_count 0 violating check constraint (seat_count >= 1)
                cur.execute(
                    """
                    INSERT INTO seat_holds (
                        join_request_id, ride_id, request_id, seat_count,
                        submitted_at, expires_at, idempotency_token
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    ("join-rb-1", "ride-rb-1", "req-rb-1", 0, 1000, 1300, "tok-rb-1"),
                )

    # Verify that the entire transaction was rolled back
    reloaded_ride = postgres_storage.get_ride("ride-rb-1")
    assert reloaded_ride is not None
    assert reloaded_ride.version == 1, "Ride version must not have been modified due to rollback"
    holds = postgres_storage.get_active_seat_holds("ride-rb-1")
    assert len(holds) == 0, "No seat holds should exist after rollback"


def test_connection_recovery_after_disconnect(postgres_storage: PostgresRideStorage) -> None:
    """Verifies that if the underlying connection is closed or broken, the adapter cleanly reconnects."""
    v = Vehicle(
        vehicle_id="veh-recov-1",
        driver_id="drv-recov-1",
        total_seat_capacity=4,
        luggage_capacity_units=2,
        current_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        is_active=True,
    )
    postgres_storage.save_vehicle(v)
    assert postgres_storage.get_vehicle("veh-recov-1") is not None

    # Simulate connection loss by explicitly closing the internal connection
    conn = postgres_storage._get_connection()
    conn.close()
    assert conn.closed

    # Next operation should automatically establish a fresh connection
    fetched = postgres_storage.get_vehicle("veh-recov-1")
    assert fetched is not None
    assert fetched.vehicle_id == "veh-recov-1"
