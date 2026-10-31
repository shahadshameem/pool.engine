"""Live PostgreSQL integration tests for atomic assigned-request cancellation.

Verifies:
- Atomic updates of ride itinerary, version increment, and request status in a single transaction.
- Locking with SELECT ... FOR UPDATE.
- Rejection of stale ride versions (OCC).
- Rejection when passenger has already boarded.
- Transaction rollback safety guaranteeing no partial writes or state corruption.
- Concurrent cancellation safety across multiple threads.
- Idempotent replay safety with idempotency tokens.
"""

import concurrent.futures
import os
from typing import Generator

import psycopg
import pytest

from engine.adapters.postgres_storage import PostgresRideStorage
from engine.contracts.storage import CancellationCommitResult
from engine.domain.enums import RequestStatus, RideStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest.fixture(scope="module")
def postgres_storage() -> Generator[PostgresRideStorage, None, None]:
    if not TEST_DB_URL:
        pytest.skip(
            "Live PostgreSQL database environment is unavailable (set TEST_DATABASE_URL to execute)"
        )

    try:
        conn = psycopg.connect(TEST_DB_URL, connect_timeout=3)
        conn.close()
    except Exception as exc:
        pytest.skip(f"Live PostgreSQL database unreachable at {TEST_DB_URL}: {exc}")

    storage = PostgresRideStorage(dsn=TEST_DB_URL)
    storage.create_schema()
    yield storage
    storage.close()


@pytest.fixture(autouse=True)
def clean_database(postgres_storage: PostgresRideStorage) -> Generator[None, None, None]:
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


def _setup_ride_with_two_passengers(
    storage: PostgresRideStorage,
) -> tuple[Vehicle, Ride, RideRequest, RideRequest]:
    loc1 = GeoCoordinate(latitude=40.750, longitude=-73.985)
    loc2 = GeoCoordinate(latitude=40.780, longitude=-73.965)

    veh = Vehicle(
        vehicle_id="veh-c-1",
        driver_id="drv-c-1",
        total_seat_capacity=4,
        current_location=loc1,
        is_active=True,
    )
    storage.save_vehicle(veh)

    req1 = RideRequest(
        request_id="req-p1",
        user_id="usr-1",
        pickup_location=loc1,
        dropoff_location=loc2,
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=3000,
        direct_distance_meters=3000,
        direct_duration_seconds=500,
        status=RequestStatus.MATCHED,
        matched_ride_id="ride-c-1",
    )
    req2 = RideRequest(
        request_id="req-p2",
        user_id="usr-2",
        pickup_location=loc1,
        dropoff_location=loc2,
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=3000,
        direct_distance_meters=3000,
        direct_duration_seconds=500,
        status=RequestStatus.MATCHED,
        matched_ride_id="ride-c-1",
    )

    pickup1 = RouteStop(
        stop_id="s-p1",
        ride_id="ride-c-1",
        request_id="req-p1",
        stop_type=StopType.PICKUP,
        location=loc1,
        passenger_delta=1,
        scheduled_arrival_time=1100,
        promised_window_start=1050,
        promised_window_end=1150,
        status=StopStatus.SCHEDULED,
    )
    pickup2 = RouteStop(
        stop_id="s-p2",
        ride_id="ride-c-1",
        request_id="req-p2",
        stop_type=StopType.PICKUP,
        location=loc1,
        passenger_delta=1,
        scheduled_arrival_time=1200,
        promised_window_start=1150,
        promised_window_end=1250,
        status=StopStatus.SCHEDULED,
    )
    dropoff1 = RouteStop(
        stop_id="s-d1",
        ride_id="ride-c-1",
        request_id="req-p1",
        stop_type=StopType.DROPOFF,
        location=loc2,
        passenger_delta=-1,
        scheduled_arrival_time=1500,
        promised_window_start=1450,
        promised_window_end=1550,
        status=StopStatus.SCHEDULED,
    )
    dropoff2 = RouteStop(
        stop_id="s-d2",
        ride_id="ride-c-1",
        request_id="req-p2",
        stop_type=StopType.DROPOFF,
        location=loc2,
        passenger_delta=-1,
        scheduled_arrival_time=1600,
        promised_window_start=1550,
        promised_window_end=1650,
        status=StopStatus.SCHEDULED,
    )

    ride = Ride(
        ride_id="ride-c-1",
        vehicle_id="veh-c-1",
        driver_id="drv-c-1",
        lifecycle_status=RideStatus.SCHEDULED,
        stops=(pickup1, pickup2, dropoff1, dropoff2),
        scheduled_departure_time=1000,
        active_passenger_count=0,
        total_vmt_meters=6000,
        version=1,
    )

    storage.save_ride(ride)
    storage.save_request(req1)
    storage.save_request(req2)

    return veh, ride, req1, req2


def test_postgres_atomic_cancellation_success(postgres_storage: PostgresRideStorage) -> None:
    veh, ride, req1, req2 = _setup_ride_with_two_passengers(postgres_storage)

    # Remaining stops for req2 only
    remaining_stops = tuple(s for s in ride.stops if s.request_id != "req-p1")

    res = postgres_storage.cancel_assigned_request_atomic(
        ride_id="ride-c-1",
        request_id="req-p1",
        expected_ride_version=1,
        updated_stops=remaining_stops,
        new_total_vmt_meters=3500,
        idempotency_token="token-pg-c1",
    )
    assert res.success
    assert res.ride is not None
    assert res.ride.version == 2
    assert len(res.ride.stops) == 2
    assert all(s.request_id == "req-p2" for s in res.ride.stops)
    assert res.request is not None
    assert res.request.status == RequestStatus.CANCELLED

    # Check persistence in PostgreSQL across new queries
    persisted_ride = postgres_storage.get_ride("ride-c-1")
    assert persisted_ride is not None
    assert persisted_ride.version == 2
    assert len(persisted_ride.stops) == 2

    persisted_req1 = postgres_storage.get_request("req-p1")
    assert persisted_req1 is not None
    assert persisted_req1.status == RequestStatus.CANCELLED

    persisted_req2 = postgres_storage.get_request("req-p2")
    assert persisted_req2 is not None
    assert persisted_req2.status == RequestStatus.MATCHED


def test_postgres_cancellation_stale_version_rejected(
    postgres_storage: PostgresRideStorage,
) -> None:
    veh, ride, req1, req2 = _setup_ride_with_two_passengers(postgres_storage)

    remaining_stops = tuple(s for s in ride.stops if s.request_id != "req-p1")

    # Pass stale version 99
    res = postgres_storage.cancel_assigned_request_atomic(
        ride_id="ride-c-1",
        request_id="req-p1",
        expected_ride_version=99,
        updated_stops=remaining_stops,
        new_total_vmt_meters=3500,
    )
    assert not res.success
    assert res.rejection_reason == "VERSION_CONFLICT"

    # Confirm storage is untouched
    persisted_ride = postgres_storage.get_ride("ride-c-1")
    assert persisted_ride is not None
    assert persisted_ride.version == 1
    assert len(persisted_ride.stops) == 4

    persisted_req1 = postgres_storage.get_request("req-p1")
    assert persisted_req1 is not None
    assert persisted_req1.status == RequestStatus.MATCHED


def test_postgres_cancellation_boarded_passenger_rejected(
    postgres_storage: PostgresRideStorage,
) -> None:
    veh, ride, req1, req2 = _setup_ride_with_two_passengers(postgres_storage)

    # Mark req1 pickup stop as COMPLETED in database
    conn = postgres_storage._get_connection()
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE route_stops SET status = 'COMPLETED' WHERE ride_id = %s AND request_id = %s AND stop_type = 'PICKUP'",
                ("ride-c-1", "req-p1"),
            )

    remaining_stops = tuple(s for s in ride.stops if s.request_id != "req-p1")

    res = postgres_storage.cancel_assigned_request_atomic(
        ride_id="ride-c-1",
        request_id="req-p1",
        expected_ride_version=1,
        updated_stops=remaining_stops,
        new_total_vmt_meters=3500,
    )
    assert not res.success
    assert res.rejection_reason == "PASSENGER_ALREADY_BOARDED"

    # Verify request was NOT marked cancelled
    persisted_req = postgres_storage.get_request("req-p1")
    assert persisted_req is not None
    assert persisted_req.status == RequestStatus.MATCHED


def test_postgres_cancellation_transaction_rollback_preserves_consistency(
    postgres_storage: PostgresRideStorage,
) -> None:
    """Verifies that an error raised midway through execution triggers full transaction rollback."""
    veh, ride, req1, req2 = _setup_ride_with_two_passengers(postgres_storage)

    # Check baseline
    assert postgres_storage.get_ride("ride-c-1").version == 1  # type: ignore[union-attr]
    assert len(postgres_storage.get_ride("ride-c-1").stops) == 4  # type: ignore[union-attr]
    assert postgres_storage.get_request("req-p1").status == RequestStatus.MATCHED  # type: ignore[union-attr]

    # Create two stops with identical stop_id to trigger a PRIMARY KEY violation on the 2nd insert
    loc = GeoCoordinate(latitude=40.75, longitude=-73.98)
    duplicate_stop1 = RouteStop(
        stop_id="collision-stop-id",
        ride_id="ride-c-1",
        request_id="req-p2",
        stop_type=StopType.PICKUP,
        location=loc,
        passenger_delta=1,
        scheduled_arrival_time=1200,
        promised_window_start=1150,
        promised_window_end=1250,
        status=StopStatus.SCHEDULED,
    )
    duplicate_stop2 = RouteStop(
        stop_id="collision-stop-id",  # Same stop_id!
        ride_id="ride-c-1",
        request_id="req-p2",
        stop_type=StopType.DROPOFF,
        location=loc,
        passenger_delta=-1,
        scheduled_arrival_time=1600,
        promised_window_start=1550,
        promised_window_end=1650,
        status=StopStatus.SCHEDULED,
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        postgres_storage.cancel_assigned_request_atomic(
            ride_id="ride-c-1",
            request_id="req-p1",
            expected_ride_version=1,
            updated_stops=(duplicate_stop1, duplicate_stop2),
            new_total_vmt_meters=2000,
        )

    # Verify atomic rollback: neither ride version nor request status was modified
    persisted_ride = postgres_storage.get_ride("ride-c-1")
    assert persisted_ride is not None
    assert persisted_ride.version == 1
    assert len(persisted_ride.stops) == 4

    persisted_req1 = postgres_storage.get_request("req-p1")
    assert persisted_req1 is not None
    assert persisted_req1.status == RequestStatus.MATCHED

    persisted_req2 = postgres_storage.get_request("req-p2")
    assert persisted_req2 is not None
    assert persisted_req2.status == RequestStatus.MATCHED


def test_postgres_cancellation_concurrent_race_prevention(
    postgres_storage: PostgresRideStorage,
) -> None:
    """Verifies that concurrent cancellations for the same ride under OCC result in exactly one
    successful commit and one version conflict without corrupted or partial states.
    """
    veh, ride, req1, req2 = _setup_ride_with_two_passengers(postgres_storage)

    stops_without_p1 = tuple(s for s in ride.stops if s.request_id != "req-p1")
    stops_without_p2 = tuple(s for s in ride.stops if s.request_id != "req-p2")

    results: list[CancellationCommitResult] = []

    def cancel_p1() -> CancellationCommitResult:
        thread_storage = PostgresRideStorage(dsn=TEST_DB_URL)
        try:
            return thread_storage.cancel_assigned_request_atomic(
                ride_id="ride-c-1",
                request_id="req-p1",
                expected_ride_version=1,
                updated_stops=stops_without_p1,
                new_total_vmt_meters=3500,
            )
        finally:
            thread_storage.close()

    def cancel_p2() -> CancellationCommitResult:
        thread_storage = PostgresRideStorage(dsn=TEST_DB_URL)
        try:
            return thread_storage.cancel_assigned_request_atomic(
                ride_id="ride-c-1",
                request_id="req-p2",
                expected_ride_version=1,
                updated_stops=stops_without_p2,
                new_total_vmt_meters=3500,
            )
        finally:
            thread_storage.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(cancel_p1)
        f2 = executor.submit(cancel_p2)
        results = [f1.result(), f2.result()]

    successes = [r for r in results if r.success]
    failures = [r for r in results if not r.success]

    # Exactly one succeeded and one failed with VERSION_CONFLICT
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].rejection_reason == "VERSION_CONFLICT"

    # Ride version is exactly 2
    final_ride = postgres_storage.get_ride("ride-c-1")
    assert final_ride is not None
    assert final_ride.version == 2


def test_postgres_cancellation_idempotent_replay(
    postgres_storage: PostgresRideStorage,
) -> None:
    veh, ride, req1, req2 = _setup_ride_with_two_passengers(postgres_storage)
    remaining_stops = tuple(s for s in ride.stops if s.request_id != "req-p1")

    res1 = postgres_storage.cancel_assigned_request_atomic(
        ride_id="ride-c-1",
        request_id="req-p1",
        expected_ride_version=1,
        updated_stops=remaining_stops,
        new_total_vmt_meters=3500,
        idempotency_token="tok-idem-cancel",
    )
    assert res1.success

    # Exact replay
    res2 = postgres_storage.cancel_assigned_request_atomic(
        ride_id="ride-c-1",
        request_id="req-p1",
        expected_ride_version=2,
        updated_stops=remaining_stops,
        new_total_vmt_meters=3500,
        idempotency_token="tok-idem-cancel",
    )
    assert res2.success
    assert res2.request is not None
    assert res2.request.status == RequestStatus.CANCELLED
