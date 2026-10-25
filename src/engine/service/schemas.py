"""Pydantic schemas and DTO contracts for the pool engine API service."""

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

from engine.domain.candidate import CandidateAssignment
from engine.domain.enums import RequestStatus, RideStatus, SearchStatus
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle


class CreateRideRequestInput(BaseModel):
    """Payload for submitting a new ride request."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: Optional[str] = None
    user_id: str
    pickup_location: GeoCoordinate
    dropoff_location: GeoCoordinate
    seat_count: int = Field(default=1, ge=1, le=50)
    earliest_pickup_time: int = Field(ge=0)
    latest_dropoff_time: int = Field(ge=0)
    direct_distance_meters: Optional[int] = Field(default=None, ge=0)
    direct_duration_seconds: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_time_window(self) -> "CreateRideRequestInput":
        if self.latest_dropoff_time <= self.earliest_pickup_time:
            raise ValueError(
                f"latest_dropoff_time ({self.latest_dropoff_time}) must be strictly greater "
                f"than earliest_pickup_time ({self.earliest_pickup_time})"
            )
        if self.direct_duration_seconds is not None:
            min_dropoff = self.earliest_pickup_time + self.direct_duration_seconds
            if self.latest_dropoff_time < min_dropoff:
                raise ValueError(
                    f"latest_dropoff_time ({self.latest_dropoff_time}) cannot accommodate direct "
                    f"travel duration of {self.direct_duration_seconds}s from earliest_pickup_time "
                    f"({self.earliest_pickup_time}). Earliest possible dropoff is {min_dropoff}."
                )
        return self


class CancelRideRequestInput(BaseModel):
    """Payload for cancelling a ride request."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: Optional[str] = None


class RegisterVehicleInput(BaseModel):
    """Payload for registering an available vehicle."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    vehicle_id: str
    driver_id: str
    total_seat_capacity: int = Field(ge=1, le=50)
    current_location: GeoCoordinate
    is_active: bool = True
    luggage_capacity_units: int = Field(default=0, ge=0)


class UpdateLocationInput(BaseModel):
    """Payload for updating a vehicle's geographical position."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    latitude: float = Field(ge=-90.0, le=90.0, description="Latitude in degrees [-90.0, 90.0]")
    longitude: float = Field(ge=-180.0, le=180.0, description="Longitude in degrees [-180.0, 180.0]")


class UpdateVehicleStatusInput(BaseModel):
    """Payload for updating a vehicle's active status."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    is_active: bool


class DispatchRunInput(BaseModel):
    """Payload for requesting an optimized dispatch batch solve and commit cycle."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    current_time: int = Field(ge=0)
    cycle_id: Optional[str] = None
    idempotency_token: Optional[str] = None
    deadline_seconds: Optional[float] = Field(default=None, gt=0.0)
    request_limit: Optional[int] = Field(default=None, ge=1)
    vehicle_limit: Optional[int] = Field(default=None, ge=1)


class StaleAssignmentDiagnosticResponse(BaseModel):
    """Diagnostic details for an assignment that was rejected during commit."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    vehicle_id: str
    request_ids: tuple[str, ...]
    rejection_reason: str
    retry_count: int


class DispatchCycleResponse(BaseModel):
    """Response returned upon completion of a dispatch cycle."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    cycle_id: str
    batch_id: str
    timestamp: int
    search_status: SearchStatus
    is_approximated: bool
    total_vmt_savings_meters: int
    cycle_duration_ms: float
    routing_errors_count: int
    committed_assignments: tuple[CandidateAssignment, ...]
    rejected_assignments: tuple[StaleAssignmentDiagnosticResponse, ...]
    unassigned_request_ids: tuple[str, ...]
