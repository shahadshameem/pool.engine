"""Canonical domain status enums."""

from enum import Enum


class RideStatus(str, Enum):
    """Lifecycle status of a vehicle ride itinerary."""
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DRIVER_NO_SHOW = "DRIVER_NO_SHOW"


class StopStatus(str, Enum):
    """Lifecycle status of an individual route stop."""
    SCHEDULED = "SCHEDULED"
    ARRIVED = "ARRIVED"
    IN_GRACE_PERIOD = "IN_GRACE_PERIOD"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    SKIPPED = "SKIPPED"


class JoinStatus(str, Enum):
    """Status of a prospective passenger's join request."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class DriverStatus(str, Enum):
    """Operational status of a driver."""
    OFFLINE = "OFFLINE"
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    ON_TRIP = "ON_TRIP"
    ON_BREAK = "ON_BREAK"


class StopType(str, Enum):
    """Type of route stop."""
    PICKUP = "PICKUP"
    DROPOFF = "DROPOFF"
    WAYPOINT = "WAYPOINT"


class RequestStatus(str, Enum):
    """Lifecycle status of a ride request demand entry."""
    PENDING = "PENDING"
    MATCHED = "MATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class DispatchMode(str, Enum):
    """Operating mode for candidate generation and dispatch solving."""
    EXACT = "EXACT"
    BOUNDED = "BOUNDED"


class SearchStatus(str, Enum):
    """Completeness status of candidate discovery and solving."""
    COMPLETE = "COMPLETE"
    INCOMPLETE_DEADLINE_EXPIRED = "INCOMPLETE_DEADLINE_EXPIRED"
    APPROXIMATED = "APPROXIMATED"
