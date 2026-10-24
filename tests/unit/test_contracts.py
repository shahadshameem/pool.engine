"""Unit tests for provider contracts and default/mock adapters."""

import pytest
from pydantic import ValidationError

from engine.contracts.routing import Coordinate, MatrixResult, RouteGeometry, RoadNetworkRoutingProvider
from engine.contracts.policy import DispatchPolicy, DispatchPolicyProvider
from engine.contracts.spatial import SpatialCandidate, SpatialIndexProvider
from engine.contracts.storage import RideStorageProvider
from engine.adapters.mock_routing import MockRoutingProvider
from engine.adapters.default_policy import DefaultPolicyProvider


def test_dispatch_policy_defaults_and_validation() -> None:
    policy = DispatchPolicy()
    assert policy.detour_relative_multiplier == 1.30
    assert policy.detour_absolute_cap_seconds == 900
    assert policy.max_pickup_delay_seconds == 600
    assert policy.boarding_grace_period_seconds == 180
    assert policy.scheduled_departure_grace_seconds == 600
    assert policy.join_request_expiry_seconds == 300
    assert policy.scheduled_activation_lead_seconds == 1800
    assert policy.stop_arrival_dwell_seconds == 15
    assert policy.weight_vmt_reduction == 0.40
    assert policy.weight_passenger_detour == 0.30
    assert policy.weight_passenger_wait == 0.20
    assert policy.weight_driver_idle == 0.10

    # Validates cleanly
    policy.validate()


def test_dispatch_policy_invalid_weights() -> None:
    # Negative weight
    p_neg = DispatchPolicy(weight_vmt_reduction=-0.1, weight_passenger_detour=0.5, weight_passenger_wait=0.4, weight_driver_idle=0.2)
    with pytest.raises(ValueError, match="non-negative"):
        p_neg.validate()

    # Sum not 1.0
    p_bad_sum = DispatchPolicy(weight_vmt_reduction=0.5, weight_passenger_detour=0.5, weight_passenger_wait=0.5, weight_driver_idle=0.1)
    with pytest.raises(ValueError, match="must sum to 1.0"):
        p_bad_sum.validate()


def test_dispatch_policy_invalid_ranges() -> None:
    # Relative detour multiplier < 1.0
    with pytest.raises(ValueError, match="detour_relative_multiplier"):
        DispatchPolicy(detour_relative_multiplier=0.9).validate()

    # Relative detour multiplier > 3.0
    with pytest.raises(ValueError, match="detour_relative_multiplier"):
        DispatchPolicy(detour_relative_multiplier=3.1).validate()

    # Detour absolute cap out of [60, 7200]
    with pytest.raises(ValueError, match="detour_absolute_cap_seconds"):
        DispatchPolicy(detour_absolute_cap_seconds=30).validate()
    with pytest.raises(ValueError, match="detour_absolute_cap_seconds"):
        DispatchPolicy(detour_absolute_cap_seconds=8000).validate()

    # Max pickup delay out of [0, 3600]
    with pytest.raises(ValueError, match="max_pickup_delay_seconds"):
        DispatchPolicy(max_pickup_delay_seconds=-1).validate()
    with pytest.raises(ValueError, match="max_pickup_delay_seconds"):
        DispatchPolicy(max_pickup_delay_seconds=4000).validate()


def test_default_policy_provider() -> None:
    provider = DefaultPolicyProvider()
    policy = provider.get_policy()
    assert policy.detour_relative_multiplier == 1.30

    new_policy = DispatchPolicy(detour_relative_multiplier=1.50)
    provider.update_policy(new_policy)
    assert provider.get_policy().detour_relative_multiplier == 1.50

    # Reject invalid update
    invalid_policy = DispatchPolicy(weight_vmt_reduction=0.9, weight_passenger_detour=0.9)
    with pytest.raises(ValueError):
        provider.update_policy(invalid_policy)


def test_mock_routing_provider() -> None:
    router = MockRoutingProvider(average_speed_kmh=40.0)
    c1 = Coordinate(latitude=40.7128, longitude=-74.0060)
    c2 = Coordinate(latitude=40.7589, longitude=-73.9851)

    dist, dur = router.get_direct_leg(c1, c2)
    assert dist > 0
    assert dur > 0

    matrix = router.get_distance_matrix([c1], [c2])
    assert len(matrix.distances_meters) == 1
    assert len(matrix.durations_seconds) == 1
    assert matrix.distances_meters[0][0] == dist
    assert matrix.durations_seconds[0][0] == dur

    route = router.get_route([c1, c2])
    assert route.total_distance_meters == dist
    assert route.total_duration_seconds == dur
    assert len(route.points) == 2
