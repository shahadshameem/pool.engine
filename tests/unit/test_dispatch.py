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


def test_dispatch_prefetch_matrix_integration() -> None:
    """Verifies that dispatch triggers prefetch_matrix on capable router during candidate discovery."""
    from typing import Sequence
    from engine.contracts.routing import Coordinate, MatrixResult, RoadNetworkRoutingProvider, RouteGeometry

    class SpyRoutingProvider(RoadNetworkRoutingProvider):
        def __init__(self) -> None:
            self._cache: dict[tuple[float, float, float, float], tuple[int, int]] = {}
            self.prefetch_calls: list[tuple[Sequence[Coordinate], Sequence[Coordinate] | None]] = []

        def _cache_key(self, o: Coordinate, d: Coordinate) -> tuple[float, float, float, float]:
            return (round(o.latitude, 6), round(o.longitude, 6), round(d.latitude, 6), round(d.longitude, 6))

        def get_direct_leg(self, origin: Coordinate, destination: Coordinate) -> tuple[int, int]:
            key = self._cache_key(origin, destination)
            if key in self._cache:
                return self._cache[key]
            return (1500, 200)

        def get_distance_matrix(self, origins: Sequence[Coordinate], destinations: Sequence[Coordinate]) -> MatrixResult:
            return MatrixResult(
                distances_meters=[[1500 for _ in destinations] for _ in origins],
                durations_seconds=[[200 for _ in destinations] for _ in origins],
            )

        def get_route(self, waypoints: Sequence[Coordinate]) -> RouteGeometry:
            return RouteGeometry(points=list(waypoints), total_distance_meters=1500, total_duration_seconds=200)

        def prefetch_matrix(
            self,
            origins: Sequence[Coordinate],
            destinations: Sequence[Coordinate] | None = None,
            deadline: float | None = None,
            reserved_headroom: float = 0.050,
        ) -> int:
            self.prefetch_calls.append((origins, destinations))
            for o in origins:
                for d in (destinations if destinations is not None else origins):
                    self._cache[self._cache_key(o, d)] = (1500, 200)
            return len(origins)

    spy_router = SpyRoutingProvider()
    engine = DispatchEngine(
        policy_provider=DefaultPolicyProvider(),
        routing_provider=spy_router,
        spatial_index=H3SpatialIndexAdapter(),
    )

    req = _make_sample_request("req-seed-1", 40.7128, -74.0060, 40.7500, -73.9800)
    veh = _make_sample_vehicle("veh-seed-1", 40.7130, -74.0050, capacity=4)

    res = engine.dispatch_batch(
        requests=[req],
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
        batch_id="batch-seed",
    )

    assert len(res.selected_assignments) == 1
    # Verify prefetch was invoked
    assert len(spy_router.prefetch_calls) > 0
    # Verify router's internal cache was populated
    p_c = Coordinate(req.pickup_location.latitude, req.pickup_location.longitude)
    d_c = Coordinate(req.dropoff_location.latitude, req.dropoff_location.longitude)
    assert spy_router._cache_key(p_c, d_c) in spy_router._cache


def test_dispatch_batch_completeness_and_deadline_status() -> None:
    """Verifies that dispatch marks search_status correctly and tracks completeness."""
    import time
    from engine.domain.enums import SearchStatus

    engine = DispatchEngine(
        policy_provider=DefaultPolicyProvider(),
        routing_provider=MockRoutingProvider(),
        spatial_index=H3SpatialIndexAdapter(),
    )

    req = _make_sample_request("req-compl-1", 40.7128, -74.0060, 40.7200, -74.0050)
    veh = _make_sample_vehicle("veh-compl-1", 40.7130, -74.0055, capacity=4)

    # 1. Normal run completes with APPROXIMATED or COMPLETE
    res_normal = engine.dispatch_batch(
        requests=[req],
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
        batch_id="batch-normal",
        deadline=time.monotonic() + 10.0,
    )
    assert res_normal.search_status in (SearchStatus.COMPLETE, SearchStatus.APPROXIMATED)
    assert res_normal.is_approximated is True  # default bounded mode
    assert len(res_normal.selected_assignments) == 1

    # 2. Expired deadline run flags INCOMPLETE_DEADLINE_EXPIRED
    res_expired = engine.dispatch_batch(
        requests=[req],
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
        batch_id="batch-expired",
        deadline=time.monotonic() - 1.0,
    )
    assert res_expired.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
    assert res_expired.is_approximated is True


def test_dispatch_batch_prefetches_matrices_across_candidate_vehicles() -> None:
    """Verifies that dispatch_batch calls prefetch_matrices across candidate vehicle waypoint groups."""
    from typing import Sequence
    from engine.contracts.routing import Coordinate, MatrixResult, RoadNetworkRoutingProvider, RouteGeometry

    class SpyMultiGroupRouter(RoadNetworkRoutingProvider):
        def __init__(self) -> None:
            self.prefetch_matrices_calls: list[Sequence[Sequence[Coordinate]]] = []

        def get_direct_leg(self, origin: Coordinate, destination: Coordinate) -> tuple[int, int]:
            return (1500, 200)

        def get_distance_matrix(self, origins: Sequence[Coordinate], destinations: Sequence[Coordinate]) -> MatrixResult:
            return MatrixResult(
                distances_meters=[[1500 for _ in destinations] for _ in origins],
                durations_seconds=[[200 for _ in destinations] for _ in origins],
            )

        def get_route(self, waypoints: Sequence[Coordinate]) -> RouteGeometry:
            return RouteGeometry(points=list(waypoints), total_distance_meters=1500, total_duration_seconds=200)

        def prefetch_matrices(
            self,
            groups: Sequence[Sequence[Coordinate]],
            deadline: float | None = None,
            reserved_headroom: float = 0.050,
        ) -> int:
            self.prefetch_matrices_calls.append(groups)
            return len(groups)

    spy = SpyMultiGroupRouter()
    engine = DispatchEngine(
        policy_provider=DefaultPolicyProvider(),
        routing_provider=spy,
        spatial_index=H3SpatialIndexAdapter(),
    )

    req1 = _make_sample_request("req-multi-1", 40.7128, -74.0060, 40.7200, -74.0050)
    veh1 = _make_sample_vehicle("veh-multi-1", 40.7130, -74.0055, capacity=4)
    veh2 = _make_sample_vehicle("veh-multi-2", 40.7132, -74.0058, capacity=4)

    res = engine.dispatch_batch(
        requests=[req1],
        vehicles=[veh1, veh2],
        active_rides=[],
        current_time=1000,
        batch_id="batch-multi",
    )

    assert len(res.selected_assignments) == 1
    assert len(spy.prefetch_matrices_calls) == 1
    # Verify groups were passed for candidate vehicles
    groups = spy.prefetch_matrices_calls[0]
    assert len(groups) >= 1
