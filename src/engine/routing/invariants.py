"""Stage 1 hard invariant gate functions and baseline calculations."""

from typing import Sequence

from engine.contracts.policy import DispatchPolicy
from engine.domain.enums import StopType
from engine.domain.models import RideRequest, RouteStop


def check_precedence(stops: Sequence[RouteStop]) -> bool:
    """
    Verifies that pickup precedes dropoff for every request present in stops.
    If a request has both PICKUP and DROPOFF in stops, index(PICKUP) < index(DROPOFF).
    A DROPOFF must never precede its corresponding PICKUP.
    """
    pickup_indices: dict[str, int] = {}
    dropoff_indices: dict[str, int] = {}

    for idx, stop in enumerate(stops):
        if stop.stop_type == StopType.PICKUP:
            pickup_indices[stop.request_id] = idx
        elif stop.stop_type == StopType.DROPOFF:
            dropoff_indices[stop.request_id] = idx
            # If pickup exists in sequence and dropoff appears before it
            if stop.request_id in pickup_indices and pickup_indices[stop.request_id] >= idx:
                return False

    # Check for any request where dropoff index is <= pickup index
    for req_id, p_idx in pickup_indices.items():
        if req_id in dropoff_indices:
            d_idx = dropoff_indices[req_id]
            if p_idx >= d_idx:
                return False

    return True


def check_capacity_profile(
    stops: Sequence[RouteStop],
    capacity: int,
    initial_passengers: int = 0
) -> bool:
    """
    Verifies that cumulative vehicle occupancy never exceeds vehicle capacity
    and never drops below zero on any route leg.
    """
    current_occupancy = initial_passengers
    if current_occupancy < 0 or current_occupancy > capacity:
        return False

    for stop in stops:
        current_occupancy += stop.passenger_delta
        if current_occupancy > capacity or current_occupancy < 0:
            return False

    return True


def check_detour_bound(
    actual_duration: int,
    direct_duration: int,
    policy: DispatchPolicy
) -> bool:
    """
    Verifies that passenger additional in-vehicle travel time (detour)
    satisfies: Delta T <= min((alpha - 1.0) * T_direct, C).
    """
    additional_duration = max(0, actual_duration - direct_duration)
    relative_allowed = (policy.detour_relative_multiplier - 1.0) * direct_duration
    absolute_allowed = float(policy.detour_absolute_cap_seconds)
    max_allowed_detour = min(relative_allowed, absolute_allowed)

    return additional_duration <= (max_allowed_detour + 1e-6)


def check_pickup_delay(
    actual_pickup_time: int,
    requested_pickup_time: int,
    max_delay: int
) -> bool:
    """
    Verifies that actual pickup time does not exceed requested earliest pickup time
    by more than max_delay seconds. Early arrival (actual < requested) is allowed.
    """
    delay = max(0, actual_pickup_time - requested_pickup_time)
    return delay <= max_delay


def calculate_unshared_vmt_baseline(requests: Sequence[RideRequest]) -> int:
    """Calculates sum of direct unshared road distances for all requests."""
    return sum(req.direct_distance_meters for req in requests)


def calculate_vmt_savings(baseline_vmt: int, shared_vmt: int) -> int:
    """Calculates road distance saved by sharing vehicles (non-negative)."""
    return max(0, baseline_vmt - shared_vmt)
