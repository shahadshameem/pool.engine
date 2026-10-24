"""Canonical domain entities and models."""

from pydantic import BaseModel, ConfigDict, Field

from engine.domain.enums import (
    DispatchMode,
    DriverStatus,
    JoinStatus,
    RequestStatus,
    RideStatus,
    SearchStatus,
    StopStatus,
    StopType,
)
from engine.domain.candidate import CandidateAssignment


class GeoCoordinate(BaseModel):
    """Geographical location on the WGS84 ellipsoid."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    latitude: float = Field(ge=-90.0, le=90.0, description="Latitude in degrees [-90.0, 90.0]")
    longitude: float = Field(ge=-180.0, le=180.0, description="Longitude in degrees [-180.0, 180.0]")


class User(BaseModel):
    """Passenger or group organizer requesting transportation."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str
    name: str
    accessibility_requirements: list[str] = Field(default_factory=list)
    created_at: int


class Driver(BaseModel):
    """Registered vehicle operator executing pooled routes."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    driver_id: str
    name: str
    active_status: DriverStatus
    current_location: GeoCoordinate
    shift_start_time: int
    shift_end_time: int
    total_idle_seconds: int = Field(default=0, ge=0)


class Vehicle(BaseModel):
    """Physical motor vehicle executing pooled rides."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    vehicle_id: str
    driver_id: str
    total_seat_capacity: int = Field(ge=1, le=50)
    luggage_capacity_units: int = Field(default=0, ge=0)
    current_location: GeoCoordinate
    is_active: bool = True


class RouteStop(BaseModel):
    """Scheduled stop along a vehicle route itinerary."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    stop_id: str
    ride_id: str
    request_id: str
    stop_type: StopType
    location: GeoCoordinate
    passenger_delta: int
    scheduled_arrival_time: int
    promised_window_start: int
    promised_window_end: int
    actual_arrival_time: int | None = None
    dwell_duration_seconds: int = Field(default=0, ge=0)
    dwell_start_time: int | None = None
    status: StopStatus = StopStatus.SCHEDULED


class Ride(BaseModel):
    """Vehicle trip instance managing an ordered itinerary of stops."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    ride_id: str
    vehicle_id: str
    driver_id: str
    lifecycle_status: RideStatus
    stops: tuple[RouteStop, ...]
    scheduled_departure_time: int
    actual_departure_time: int | None = None
    active_passenger_count: int = Field(default=0, ge=0)
    total_vmt_meters: int = Field(default=0, ge=0)
    version: int = Field(default=1, ge=1)


class RideRequest(BaseModel):
    """Passenger ride request demand entry."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str
    user_id: str
    pickup_location: GeoCoordinate
    dropoff_location: GeoCoordinate
    seat_count: int = Field(ge=1)
    earliest_pickup_time: int
    latest_dropoff_time: int
    direct_distance_meters: int = Field(default=0, ge=0)
    direct_duration_seconds: int = Field(ge=0)
    status: RequestStatus = RequestStatus.PENDING
    matched_ride_id: str | None = None


class JoinRequest(BaseModel):
    """Request to join an active or scheduled ride."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    join_request_id: str
    ride_id: str
    request_id: str
    user_id: str
    seat_count: int = Field(ge=1)
    submitted_at: int
    expires_at: int
    status: JoinStatus = JoinStatus.PENDING
    idempotency_token: str


class MatchResult(BaseModel):
    """Deterministic output of a batch optimization solve cycle."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    match_id: str
    batch_id: str
    solver_timestamp: int
    selected_assignments: tuple[CandidateAssignment, ...]
    unassigned_request_ids: tuple[str, ...]
    total_vmt_savings_meters: int = 0
    solve_duration_ms: float = 0.0
    dispatch_mode: DispatchMode = DispatchMode.BOUNDED
    search_status: SearchStatus = SearchStatus.COMPLETE
    is_approximated: bool = False


# Rebuild candidate assignment now that RouteStop is defined
CandidateAssignment.model_rebuild()
