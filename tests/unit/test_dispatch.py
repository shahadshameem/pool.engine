"""Unit tests for top-level unified dispatch engine facade (T051)."""

import time
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.policy import DispatchPolicy
from engine.dispatch import DispatchEngine
from engine.domain.enums import RequestStatus, RideStatus
from engine.domain.models import GeoCoordinate, Ride, RideRequest, Vehicle


def _make_sample_request(
    req_id: str,
    pickup_lat: float,
    pickup_lon: float,
    dropoff_lat: float,
    dropoff_lon: float,
    seat_count: int = 1,
    current_time: int = 1000,
) -> RideRequest:
    return RideRequest(
        request_id=req_id,
        user_id=f"user-{req_id}",
        pickup_location=GeoCoordinate(latitude=pickup_lat, longitude=pickup_lon),
        dropoff_location=GeoCoordinate(latitude=dropoff_lat, longitude=dropoff_lon),
        seat_count=seat_count,
        earliest_pickup_time=current_time,
        latest_dropoff_time=current_time + 1800,
        direct_distance_meters=2000,
        direct_duration_seconds=300,
        status=RequestStatus.PENDING,
    )


def _make_sample_vehicle(
    veh_id: str,
    lat: float,
    lon: float,
    capacity: int = 4,
) -> Vehicle:
    return Vehicle(
        vehicle_id=veh_id,
        driver_id=f"drv-{veh_id}",
        total_seat_capacity=capacity,
        current_location=GeoCoordinate(latitude=lat, longitude=lon),
        is_active=True,
    )


def test_dispatch_engine_empty_inputs() -> None:
    """Verifies that dispatching with empty requests returns a clean empty MatchResult."""
    policy_provider = DefaultPolicyProvider()
    routing_provider = MockRoutingProvider()
    spatial_index = H3SpatialIndexAdapter()
    engine = DispatchEngine(
        policy_provider=policy_provider,
        routing_provider=routing_provider,
        spatial_index=spatial_index,
    )

    result = engine.dispatch_batch(
        requests=[],
        vehicles=[],
        active_rides=[],
        current_time=1000,
        batch_id="batch-empty",
    )
    assert result.batch_id == "batch-empty"
    assert len(result.selected_assignments) == 0
    assert len(result.unassigned_request_ids) == 0
    assert result.solve_duration_ms >= 0.0


def test_dispatch_engine_single_request_match() -> None:
    """Verifies that an incoming request is matched to a nearby idle vehicle."""
    policy_provider = DefaultPolicyProvider()
    routing_provider = MockRoutingProvider()
    spatial_index = H3SpatialIndexAdapter()
    engine = DispatchEngine(
        policy_provider=policy_provider,
        routing_provider=routing_provider,
        spatial_index=spatial_index,
    )

    req = _make_sample_request("req-1", 40.7128, -74.0060, 40.7300, -73.9950)
    veh = _make_sample_vehicle("veh-1", 40.7125, -74.0055, capacity=4)

    result = engine.dispatch_batch(
        requests=[req],
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
        batch_id="batch-single",
    )

    assert len(result.selected_assignments) == 1
    assert result.selected_assignments[0].vehicle_id == "veh-1"
    assert "req-1" in result.selected_assignments[0].request_ids
    assert len(result.unassigned_request_ids) == 0
    assert result.solve_duration_ms > 0.0


def test_dispatch_engine_timeout_safe_fallback() -> None:
    """
    Verifies that reaching deadline triggers immediate interrupt,
    leaves all requests cleanly unassigned, and returns 0 assignments.
    """
    policy_provider = DefaultPolicyProvider()
    routing_provider = MockRoutingProvider()
    spatial_index = H3SpatialIndexAdapter()
    engine = DispatchEngine(
        policy_provider=policy_provider,
        routing_provider=routing_provider,
        spatial_index=spatial_index,
    )

    req = _make_sample_request("req-timeout", 40.7128, -74.0060, 40.7300, -73.9950)
    veh = _make_sample_vehicle("veh-timeout", 40.7125, -74.0055, capacity=4)

    # Monotonic deadline already elapsed
    past_deadline = time.monotonic() - 0.010
    result = engine.dispatch_batch(
        requests=[req],
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
        batch_id="batch-timeout",
        deadline=past_deadline,
    )

    assert len(result.selected_assignments) == 0
    assert "req-timeout" in result.unassigned_request_ids


def test_dispatch_engine_reproducible_determinism() -> None:
    """Verifies that consecutive dispatch cycles on identical inputs produce identical MatchResult."""
    policy_provider = DefaultPolicyProvider()
    routing_provider = MockRoutingProvider()
    spatial_index = H3SpatialIndexAdapter()
    engine = DispatchEngine(
        policy_provider=policy_provider,
        routing_provider=routing_provider,
        spatial_index=spatial_index,
    )

    reqs = [
        _make_sample_request(f"req-{i}", 40.7128 + i * 0.005, -74.0060, 40.7500, -73.9800)
        for i in range(5)
    ]
    vehs = [
        _make_sample_vehicle(f"veh-{j}", 40.7130 + j * 0.005, -74.0050, capacity=4)
        for j in range(3)
    ]

    res1 = engine.dispatch_batch(
        requests=reqs,
        vehicles=vehs,
        active_rides=[],
        current_time=1000,
        batch_id="batch-det",
    )
    res2 = engine.dispatch_batch(
        requests=reqs,
        vehicles=vehs,
        active_rides=[],
        current_time=1000,
        batch_id="batch-det",
    )

    # Identical assignments
    assert len(res1.selected_assignments) == len(res2.selected_assignments)
    for a1, a2 in zip(res1.selected_assignments, res2.selected_assignments):
        assert a1.vehicle_id == a2.vehicle_id
        assert a1.request_ids == a2.request_ids
        assert a1.objective_value == a2.objective_value
    assert res1.unassigned_request_ids == res2.unassigned_request_ids
