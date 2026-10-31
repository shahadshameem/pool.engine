"""Unit tests for API DTO schemas, validators, and error models."""

import pytest
from pydantic import ValidationError

from engine.domain.models import GeoCoordinate
from engine.service.errors import ErrorBody, ErrorDetail, ErrorEnvelope, ValidationError as ApiValidationError
from engine.service.schemas import (
    CancelRideRequestInput,
    CreateRideRequestInput,
    DispatchRunInput,
    RegisterVehicleInput,
    UpdateLocationInput,
    UpdateVehicleStatusInput,
)


def test_create_ride_request_valid() -> None:
    req = CreateRideRequestInput(
        user_id="usr-1",
        pickup_location=GeoCoordinate(latitude=40.7580, longitude=-73.9855),
        dropoff_location=GeoCoordinate(latitude=40.7829, longitude=-73.9654),
        seat_count=2,
        earliest_pickup_time=1000,
        latest_dropoff_time=2000,
        direct_distance_meters=3000,
        direct_duration_seconds=500,
    )
    assert req.user_id == "usr-1"
    assert req.seat_count == 2
    assert req.direct_duration_seconds == 500


def test_create_ride_request_coordinate_bounds() -> None:
    with pytest.raises(ValidationError) as exc:
        CreateRideRequestInput(
            user_id="usr-1",
            pickup_location=GeoCoordinate(latitude=95.0, longitude=-73.9855),
            dropoff_location=GeoCoordinate(latitude=40.7829, longitude=-73.9654),
            earliest_pickup_time=1000,
            latest_dropoff_time=2000,
        )
    assert "latitude" in str(exc.value)

    with pytest.raises(ValidationError) as exc:
        CreateRideRequestInput(
            user_id="usr-1",
            pickup_location=GeoCoordinate(latitude=40.7580, longitude=-190.0),
            dropoff_location=GeoCoordinate(latitude=40.7829, longitude=-73.9654),
            earliest_pickup_time=1000,
            latest_dropoff_time=2000,
        )
    assert "longitude" in str(exc.value)


def test_create_ride_request_seat_bounds() -> None:
    with pytest.raises(ValidationError) as exc:
        CreateRideRequestInput(
            user_id="usr-1",
            pickup_location=GeoCoordinate(latitude=40.7580, longitude=-73.9855),
            dropoff_location=GeoCoordinate(latitude=40.7829, longitude=-73.9654),
            seat_count=0,
            earliest_pickup_time=1000,
            latest_dropoff_time=2000,
        )
    assert "seat_count" in str(exc.value)


def test_create_ride_request_invalid_time_window() -> None:
    # Dropoff before pickup
    with pytest.raises(ValidationError) as exc:
        CreateRideRequestInput(
            user_id="usr-1",
            pickup_location=GeoCoordinate(latitude=40.7580, longitude=-73.9855),
            dropoff_location=GeoCoordinate(latitude=40.7829, longitude=-73.9654),
            earliest_pickup_time=2000,
            latest_dropoff_time=1000,
        )
    assert "latest_dropoff_time" in str(exc.value)

    # Infeasible direct duration
    with pytest.raises(ValidationError) as exc:
        CreateRideRequestInput(
            user_id="usr-1",
            pickup_location=GeoCoordinate(latitude=40.7580, longitude=-73.9855),
            dropoff_location=GeoCoordinate(latitude=40.7829, longitude=-73.9654),
            earliest_pickup_time=1000,
            latest_dropoff_time=1200,
            direct_duration_seconds=500,
        )
    assert "cannot accommodate direct" in str(exc.value)


def test_register_vehicle_validation() -> None:
    # Valid
    veh = RegisterVehicleInput(
        vehicle_id="veh-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=40.75, longitude=-73.98),
    )
    assert veh.total_seat_capacity == 4
    assert veh.is_active is True

    # Invalid capacity <= 0
    with pytest.raises(ValidationError):
        RegisterVehicleInput(
            vehicle_id="veh-1",
            driver_id="drv-1",
            total_seat_capacity=0,
            current_location=GeoCoordinate(latitude=40.75, longitude=-73.98),
        )

    # Invalid capacity > 50
    with pytest.raises(ValidationError):
        RegisterVehicleInput(
            vehicle_id="veh-1",
            driver_id="drv-1",
            total_seat_capacity=51,
            current_location=GeoCoordinate(latitude=40.75, longitude=-73.98),
        )


def test_update_location_validation() -> None:
    valid = UpdateLocationInput(latitude=40.7, longitude=-73.9)
    assert valid.latitude == 40.7

    with pytest.raises(ValidationError):
        UpdateLocationInput(latitude=91.0, longitude=0.0)


def test_dispatch_run_input_validation() -> None:
    valid = DispatchRunInput(current_time=1700000000, deadline_seconds=0.500)
    assert valid.current_time == 1700000000
    assert valid.deadline_seconds == 0.500

    with pytest.raises(ValidationError):
        DispatchRunInput(current_time=-1)

    with pytest.raises(ValidationError):
        DispatchRunInput(current_time=100, deadline_seconds=-0.5)


def test_error_envelope_structure() -> None:
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code="TEST_ERROR",
            message="Something went wrong",
            details=[ErrorDetail(field="seat_count", issue="Must be >= 1")],
        )
    )
    dumped = envelope.model_dump()
    assert dumped["error"]["code"] == "TEST_ERROR"
    assert dumped["error"]["details"][0]["field"] == "seat_count"
