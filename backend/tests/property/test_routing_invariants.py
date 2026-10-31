"""Property-based tests for Stage 1 routing invariants using Hypothesis."""

from hypothesis import given, strategies as st

from engine.contracts.policy import DispatchPolicy
from engine.domain.enums import StopStatus, StopType
from engine.domain.models import GeoCoordinate, RouteStop
from engine.routing.invariants import (
    check_capacity_profile,
    check_detour_bound,
    check_pickup_delay,
    check_precedence,
)


@st.composite
def route_stop_sequence_strategy(draw: st.DrawFn) -> list[RouteStop]:
    """Generates valid pickup-dropoff paired stops with randomized deltas."""
    num_requests = draw(st.integers(min_value=1, max_value=5))
    stops: list[RouteStop] = []

    for i in range(num_requests):
        req_id = f"req-{i}"
        seats = draw(st.integers(min_value=1, max_value=4))
        p_stop = RouteStop(
            stop_id=f"p-{i}",
            ride_id="ride-prop",
            request_id=req_id,
            stop_type=StopType.PICKUP,
            location=GeoCoordinate(latitude=40.0, longitude=-74.0),
            passenger_delta=seats,
            scheduled_arrival_time=1700000000 + i * 100,
            promised_window_start=1700000000,
            promised_window_end=1700010000,
            status=StopStatus.SCHEDULED,
        )
        d_stop = RouteStop(
            stop_id=f"d-{i}",
            ride_id="ride-prop",
            request_id=req_id,
            stop_type=StopType.DROPOFF,
            location=GeoCoordinate(latitude=40.1, longitude=-73.9),
            passenger_delta=-seats,
            scheduled_arrival_time=1700000000 + i * 100 + 50,
            promised_window_start=1700000000,
            promised_window_end=1700010000,
            status=StopStatus.SCHEDULED,
        )
        stops.extend([p_stop, d_stop])

    return stops


@given(stops=route_stop_sequence_strategy())
def test_property_precedence_for_constructed_pairs(stops: list[RouteStop]) -> None:
    # Naturally paired stops where pickups precede dropoffs must pass precedence check
    assert check_precedence(stops) is True


@given(
    direct_duration=st.integers(min_value=60, max_value=7200),
    alpha=st.floats(min_value=1.0, max_value=2.0),
    cap_seconds=st.integers(min_value=300, max_value=1800),
)
def test_property_detour_bound_monotonicity(direct_duration: int, alpha: float, cap_seconds: int) -> None:
    policy = DispatchPolicy(
        detour_relative_multiplier=alpha,
        detour_absolute_cap_seconds=cap_seconds,
    )
    # Direct duration alone (0 detour) must always be accepted
    assert check_detour_bound(
        actual_duration=direct_duration,
        direct_duration=direct_duration,
        policy=policy,
    ) is True

    # Far excessive duration must always be rejected
    excessive_duration = int(direct_duration + max(alpha * direct_duration, cap_seconds) + 1000)
    assert check_detour_bound(
        actual_duration=excessive_duration,
        direct_duration=direct_duration,
        policy=policy,
    ) is False


@given(
    capacity=st.integers(min_value=1, max_value=10),
    initial_passengers=st.integers(min_value=0, max_value=10),
)
def test_property_capacity_bound(capacity: int, initial_passengers: int) -> None:
    stop = RouteStop(
        stop_id="s1",
        ride_id="r1",
        request_id="rq1",
        stop_type=StopType.PICKUP,
        location=GeoCoordinate(latitude=40.0, longitude=-74.0),
        passenger_delta=1,
        scheduled_arrival_time=1700000000,
        promised_window_start=1700000000,
        promised_window_end=1700001000,
        status=StopStatus.SCHEDULED,
    )
    is_valid = check_capacity_profile([stop], capacity=capacity, initial_passengers=initial_passengers)
    if initial_passengers + 1 <= capacity:
        assert is_valid is True
    else:
        assert is_valid is False
