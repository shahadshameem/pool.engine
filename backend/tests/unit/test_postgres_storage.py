"""Unit tests for PostgresRideStorage mapping, schema validation, and error semantics (T049)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from engine.adapters.postgres_storage import PostgresRideStorage
from engine.contracts.storage import StorageProviderError
from engine.domain.enums import JoinStatus, RequestStatus, RideStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, RouteStop


def test_schema_sql_defines_all_required_tables() -> None:
    """Verifies that schema.sql contains DDL for all canonical tables and indexes."""
    schema_path = Path("src/engine/adapters/schema.sql")
    assert schema_path.exists(), "schema.sql must exist"
    sql = schema_path.read_text(encoding="utf-8")

    expected_tables = [
        "vehicles",
        "rides",
        "route_stops",
        "ride_requests",
        "join_requests",
        "seat_holds",
        "idempotency_records",
    ]
    for table in expected_tables:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql, f"Missing table definition: {table}"

    # Verify key constraints and indexes
    assert "total_seat_capacity INTEGER NOT NULL CHECK" in sql
    assert "version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1)" in sql
    assert "idx_seat_holds_expiry" in sql
    assert "idx_route_stops_coords" in sql


def test_postgres_storage_missing_connection_raises_error() -> None:
    """Verifies that PostgresRideStorage raises StorageProviderError if no DSN or connection is provided."""
    storage = PostgresRideStorage(dsn=None, connection=None)
    with pytest.raises(StorageProviderError, match="requires a DSN or active psycopg Connection"):
        storage._get_connection()


def test_row_to_vehicle_mapping() -> None:
    """Verifies row dictionary translation to Vehicle domain model."""
    row = {
        "vehicle_id": "veh-101",
        "driver_id": "drv-202",
        "total_seat_capacity": 6,
        "luggage_capacity_units": 2,
        "current_latitude": 40.7128,
        "current_longitude": -74.0060,
        "is_active": True,
    }
    v = PostgresRideStorage._row_to_vehicle(row)
    assert v.vehicle_id == "veh-101"
    assert v.driver_id == "drv-202"
    assert v.total_seat_capacity == 6
    assert v.luggage_capacity_units == 2
    assert v.current_location == GeoCoordinate(latitude=40.7128, longitude=-74.0060)
    assert v.is_active is True


def test_row_to_route_stop_mapping() -> None:
    """Verifies row dictionary translation to RouteStop domain model."""
    row = {
        "stop_id": "stop-p-1",
        "ride_id": "ride-1",
        "request_id": "req-1",
        "stop_type": "PICKUP",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "passenger_delta": 2,
        "scheduled_arrival_time": 1000,
        "promised_window_start": 950,
        "promised_window_end": 1200,
        "actual_arrival_time": 995,
        "dwell_duration_seconds": 20,
        "dwell_start_time": 995,
        "status": "COMPLETED",
    }
    s = PostgresRideStorage._row_to_route_stop(row)
    assert s.stop_id == "stop-p-1"
    assert s.stop_type == StopType.PICKUP
    assert s.passenger_delta == 2
    assert s.status == StopStatus.COMPLETED


def test_row_to_ride_mapping() -> None:
    """Verifies row dictionary translation to Ride domain model with ordered stops."""
    ride_row = {
        "ride_id": "ride-1",
        "vehicle_id": "veh-1",
        "driver_id": "drv-1",
        "lifecycle_status": "ACTIVE",
        "scheduled_departure_time": 1000,
        "actual_departure_time": 1005,
        "active_passenger_count": 2,
        "total_vmt_meters": 15000,
        "version": 3,
    }
    stop_rows = [
        {
            "stop_id": "stop-p-1",
            "ride_id": "ride-1",
            "request_id": "req-1",
            "stop_type": "PICKUP",
            "latitude": 40.7128,
            "longitude": -74.0060,
            "passenger_delta": 2,
            "scheduled_arrival_time": 1000,
            "promised_window_start": 950,
            "promised_window_end": 1200,
            "actual_arrival_time": 1005,
            "dwell_duration_seconds": 0,
            "dwell_start_time": None,
            "status": "COMPLETED",
        },
        {
            "stop_id": "stop-d-1",
            "ride_id": "ride-1",
            "request_id": "req-1",
            "stop_type": "DROPOFF",
            "latitude": 40.7589,
            "longitude": -73.9851,
            "passenger_delta": -2,
            "scheduled_arrival_time": 1500,
            "promised_window_start": 950,
            "promised_window_end": 1800,
            "actual_arrival_time": None,
            "dwell_duration_seconds": 0,
            "dwell_start_time": None,
            "status": "SCHEDULED",
        },
    ]
    r = PostgresRideStorage._row_to_ride(ride_row, stop_rows)
    assert r.ride_id == "ride-1"
    assert r.lifecycle_status == RideStatus.ACTIVE
    assert len(r.stops) == 2
    assert r.stops[0].stop_id == "stop-p-1"
    assert r.stops[1].stop_id == "stop-d-1"
    assert r.version == 3


def test_row_to_request_mapping() -> None:
    """Verifies row dictionary translation to RideRequest domain model."""
    row = {
        "request_id": "req-42",
        "user_id": "user-99",
        "pickup_latitude": 40.7128,
        "pickup_longitude": -74.0060,
        "dropoff_latitude": 40.7589,
        "dropoff_longitude": -73.9851,
        "seat_count": 3,
        "earliest_pickup_time": 1000,
        "latest_dropoff_time": 2500,
        "direct_distance_meters": 6200,
        "direct_duration_seconds": 720,
        "status": "MATCHED",
        "matched_ride_id": "ride-1",
    }
    req = PostgresRideStorage._row_to_request(row)
    assert req.request_id == "req-42"
    assert req.seat_count == 3
    assert req.status == RequestStatus.MATCHED
    assert req.matched_ride_id == "ride-1"


def test_row_to_seat_hold_and_idempotency_mapping() -> None:
    """Verifies SeatHold and IdempotencyRecord mappings."""
    hold_row = {
        "ride_id": "ride-1",
        "request_id": "req-1",
        "join_request_id": "join-1",
        "seat_count": 2,
        "submitted_at": 1000,
        "expires_at": 1300,
        "idempotency_token": "tok-1",
    }
    hold = PostgresRideStorage._row_to_seat_hold(hold_row)
    assert hold.ride_id == "ride-1"
    assert hold.seat_count == 2
    assert hold.expires_at == 1300

    idem_row = {
        "idempotency_token": "tok-1",
        "record_type": "hold",
        "join_request_id": "join-1",
        "request_id": "req-1",
        "ride_id": "ride-1",
        "version": 2,
        "created_at": 1000,
    }
    rec = PostgresRideStorage._row_to_idempotency_record(idem_row)
    assert rec.token == "tok-1"
    assert rec.record_type == "hold"
    assert rec.version == 2
