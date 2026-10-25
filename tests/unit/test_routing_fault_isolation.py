"""Unit tests for routing fault isolation, error types, and leg validation (Phase 1, Item 1.3)."""

import math
import time
from typing import Any
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.policy import DispatchPolicy
from engine.contracts.routing import (
    Coordinate,
    InvalidRouteDataError,
    RoadNetworkRoutingProvider,
    RouteLookupError,
    RouteTimeoutError,
    RoutingProviderError,
    validate_route_leg,
)
from engine.dispatch import (
    CandidateGenerationConfig,
    DispatchEngine,
)
from engine.domain.enums import RequestStatus, RideStatus, SearchStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle
from engine.lifecycle.transitions import LifecycleTransitionError, cancel_en_route_request
from engine.routing.bundle_generator import generate_group_bundles
from engine.routing.insertion import generate_active_ride_insertions, generate_single_request_insertions


# ---------------------------------------------------------------------------
# Test Helpers & Custom Failing Routers
# ---------------------------------------------------------------------------

def _make_req(
    req_id: str,
    p_lat: float,
    p_lon: float,
    d_lat: float,
    d_lon: float,
    current_time: int = 1000,
    seat_count: int = 1,
) -> RideRequest:
    return RideRequest(
        request_id=req_id,
        user_id=f"u-{req_id}",
        pickup_location=GeoCoordinate(latitude=p_lat, longitude=p_lon),
        dropoff_location=GeoCoordinate(latitude=d_lat, longitude=d_lon),
        seat_count=seat_count,
        earliest_pickup_time=current_time,
        latest_dropoff_time=current_time + 1800,
        direct_distance_meters=2000,
        direct_duration_seconds=300,
        status=RequestStatus.PENDING,
    )


def _make_veh(
    veh_id: str,
    lat: float,
    lon: float,
    capacity: int = 4,
) -> Vehicle:
    return Vehicle(
        vehicle_id=veh_id,
        driver_id=f"d-{veh_id}",
        total_seat_capacity=capacity,
        current_location=GeoCoordinate(latitude=lat, longitude=lon),
        is_active=True,
    )


class FailingMockRouter(MockRoutingProvider):
    """Mock router that fails on specific coordinate lookups or error types."""

    def __init__(
        self,
        base_router: RoadNetworkRoutingProvider | None = None,
        failing_coords: set[tuple[float, float]] | None = None,
        fail_with: Exception | None = None,
        fail_all: bool = False,
        invalid_return_val: Any = None,
        average_speed_kmh: float = 40.0,
        circuity_factor: float = 1.25,
    ) -> None:
        super().__init__(average_speed_kmh=average_speed_kmh, circuity_factor=circuity_factor)
        self.base_router = base_router
        self.failing_coords = failing_coords or set()
        self.fail_with = fail_with
        self.fail_all = fail_all
        self.invalid_return_val = invalid_return_val

    def _should_fail(self, c: Coordinate) -> bool:
        if self.fail_all:
            return True
        key = (round(c.latitude, 4), round(c.longitude, 4))
        return key in self.failing_coords

    def get_direct_leg(self, origin: Coordinate, destination: Coordinate) -> tuple[int, int]:
        if self._should_fail(origin) or self._should_fail(destination):
            if self.invalid_return_val is not None:
                return self.invalid_return_val  # type: ignore[no-any-return]
            if self.fail_with is not None:
                raise self.fail_with
            raise RouteLookupError(f"Route lookup failed between {origin} and {destination}")
        if self.base_router is not None:
            return self.base_router.get_direct_leg(origin, destination)
        return super().get_direct_leg(origin, destination)


# ---------------------------------------------------------------------------
# 1. validate_route_leg Tests
# ---------------------------------------------------------------------------

def test_validate_route_leg_validates_physical_invariants() -> None:
    c1 = Coordinate(40.7128, -74.0060)
    c2 = Coordinate(40.7589, -73.9851)

    # Valid leg for distinct coords
    dist, dur = validate_route_leg(c1, c2, (1500, 180))
    assert dist == 1500
    assert dur == 180
    assert isinstance(dist, int)
    assert isinstance(dur, int)

    # Floats cast to rounded int
    dist, dur = validate_route_leg(c1, c2, (1500.8, 180.2))
    assert dist == 1501
    assert dur == 180

    # Identical coords allow (0, 0)
    dist, dur = validate_route_leg(c1, c1, (0, 0))
    assert dist == 0
    assert dur == 0

    # Non-tuple / wrong length
    with pytest.raises(InvalidRouteDataError, match="invalid leg structure"):
        validate_route_leg(c1, c2, "invalid-structure")
    with pytest.raises(InvalidRouteDataError, match="invalid leg structure"):
        validate_route_leg(c1, c2, (1000,))
    with pytest.raises(InvalidRouteDataError, match="invalid leg structure"):
        validate_route_leg(c1, c2, (1000, 200, 50))

    # Non-numeric / boolean values
    with pytest.raises(InvalidRouteDataError, match="non-numeric"):
        validate_route_leg(c1, c2, ("1000", 200))
    with pytest.raises(InvalidRouteDataError, match="non-numeric"):
        validate_route_leg(c1, c2, (True, 200))
    with pytest.raises(InvalidRouteDataError, match="non-numeric"):
        validate_route_leg(c1, c2, (1000, False))

    # NaN / Inf
    with pytest.raises(InvalidRouteDataError, match="NaN or infinite"):
        validate_route_leg(c1, c2, (float("nan"), 200))
    with pytest.raises(InvalidRouteDataError, match="NaN or infinite"):
        validate_route_leg(c1, c2, (1000, float("inf")))

    # Negative distance or duration
    with pytest.raises(InvalidRouteDataError, match="negative leg values"):
        validate_route_leg(c1, c2, (-10, 200))
    with pytest.raises(InvalidRouteDataError, match="negative leg values"):
        validate_route_leg(c1, c2, (1000, -5))

    # Distinct coordinates returning zero distance or duration
    with pytest.raises(InvalidRouteDataError, match="returned zero distance or duration"):
        validate_route_leg(c1, c2, (0, 200))
    with pytest.raises(InvalidRouteDataError, match="returned zero distance or duration"):
        validate_route_leg(c1, c2, (1000, 0))
    with pytest.raises(InvalidRouteDataError, match="returned zero distance or duration"):
        validate_route_leg(c1, c2, (0, 0))


# ---------------------------------------------------------------------------
# 2. Idle Bundle Generation Fault Isolation
# ---------------------------------------------------------------------------

def test_idle_bundle_generation_isolates_failing_request() -> None:
    policy = DefaultPolicyProvider().get_policy()
    v = _make_veh("v1", 40.7100, -74.0050)
    r1 = _make_req("r1", 40.7110, -74.0040, 40.7300, -73.9900)
    r2 = _make_req("r2", 40.7120, -74.0030, 40.7320, -73.9920)
    r3 = _make_req("r3", 40.7130, -74.0020, 40.7340, -73.9940)

    # Make r2 pickup fail
    failing_router = FailingMockRouter(
        failing_coords={(40.7120, -74.0030)},
        fail_with=RouteLookupError("Simulated OSRM 500 downstream error"),
    )

    shared_errors: list[RoutingProviderError] = []
    candidates = generate_group_bundles(
        requests=[r1, r2, r3],
        vehicle=v,
        router=failing_router,
        policy=policy,
        current_time=1000,
        shared_routing_errors=shared_errors,
        propagate_routing_errors=False,
    )

    # We must have generated valid candidates for r1 and r3, but never r2
    assert len(candidates) > 0
    for cand in candidates:
        assert "r2" not in cand.request_ids
        assert len(cand.request_ids) > 0

    # Confirm error was recorded
    assert len(shared_errors) > 0
    assert any("Simulated OSRM" in str(e) for e in shared_errors)


# ---------------------------------------------------------------------------
# 3. Active Ride Insertion Fault Isolation
# ---------------------------------------------------------------------------

def test_active_ride_insertion_isolates_failing_request() -> None:
    policy = DefaultPolicyProvider().get_policy()
    v = _make_veh("v1", 40.7100, -74.0050)
    loc_exist = GeoCoordinate(latitude=40.7500, longitude=-73.9850)
    stop_d = RouteStop(
        stop_id="d0",
        ride_id="ride1",
        request_id="r0",
        stop_type=StopType.DROPOFF,
        location=loc_exist,
        passenger_delta=-1,
        scheduled_arrival_time=1600,
        promised_window_start=1000,
        promised_window_end=2500,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride1",
        vehicle_id="v1",
        driver_id="d-v1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_d,),
        scheduled_departure_time=1000,
        active_passenger_count=1,
        total_vmt_meters=5000,
        version=1,
    )

    r1 = _make_req("r1", 40.7150, -74.0000, 40.7450, -73.9900)
    r2 = _make_req("r2", 40.7200, -73.9950, 40.7480, -73.9880)

    # Make r2 dropoff fail
    failing_router = FailingMockRouter(
        failing_coords={(40.7480, -73.9880)},
        fail_with=RouteTimeoutError("Routing engine connection timed out"),
    )

    shared_errors: list[RoutingProviderError] = []
    candidates = generate_active_ride_insertions(
        active_ride=ride,
        requests=[r1, r2],
        vehicle=v,
        router=failing_router,
        policy=policy,
        current_time=1000,
        shared_routing_errors=shared_errors,
        propagate_routing_errors=False,
    )

    assert len(candidates) > 0
    for cand in candidates:
        assert "r2" not in cand.request_ids
        assert "r1" in cand.request_ids

    assert len(shared_errors) > 0
    assert any("timed out" in str(e) for e in shared_errors)


# ---------------------------------------------------------------------------
# 4. Active Ride Unroutable Existing Route Returns Empty
# ---------------------------------------------------------------------------

def test_active_ride_unroutable_existing_route_returns_empty() -> None:
    policy = DefaultPolicyProvider().get_policy()
    v = _make_veh("v1", 40.7100, -74.0050)
    loc_exist = GeoCoordinate(latitude=40.7500, longitude=-73.9850)
    stop_d = RouteStop(
        stop_id="d0",
        ride_id="ride1",
        request_id="r0",
        stop_type=StopType.DROPOFF,
        location=loc_exist,
        passenger_delta=-1,
        scheduled_arrival_time=1600,
        promised_window_start=1000,
        promised_window_end=2500,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride1",
        vehicle_id="v1",
        driver_id="d-v1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_d,),
        scheduled_departure_time=1000,
        active_passenger_count=1,
        total_vmt_meters=5000,
        version=1,
    )
    r1 = _make_req("r1", 40.7150, -74.0000, 40.7450, -73.9900)

    # Fail routing to existing stop
    failing_router = FailingMockRouter(
        failing_coords={(40.7500, -73.9850)},
        fail_with=RouteLookupError("Bridge road closure / unreachable"),
    )

    shared_errors: list[RoutingProviderError] = []
    candidates = generate_active_ride_insertions(
        active_ride=ride,
        requests=[r1],
        vehicle=v,
        router=failing_router,
        policy=policy,
        current_time=1000,
        shared_routing_errors=shared_errors,
        propagate_routing_errors=False,
    )

    # Existing route could not be established -> no safe baseline VMT -> returns []
    assert candidates == []
    assert len(shared_errors) > 0


# ---------------------------------------------------------------------------
# 5. Dispatch Batch Survives Partial Routing Failures
# ---------------------------------------------------------------------------

def test_dispatch_batch_survives_partial_routing_failures() -> None:
    policy_provider = DefaultPolicyProvider()
    spatial_index = H3SpatialIndexAdapter()
    v1 = _make_veh("v1", 40.7100, -74.0050)
    v2 = _make_veh("v2", 40.7300, -73.9900)

    r1 = _make_req("r1", 40.7110, -74.0040, 40.7250, -73.9950)
    r2 = _make_req("r2", 40.7310, -73.9890, 40.7450, -73.9800)

    # Fail r2 pickup
    failing_router = FailingMockRouter(
        failing_coords={(40.7310, -73.9890)},
        fail_with=RouteLookupError("OSRM 400 NoRoute"),
    )

    engine = DispatchEngine(
        policy_provider=policy_provider,
        routing_provider=failing_router,
        spatial_index=spatial_index,
        config=CandidateGenerationConfig.exact(),
    )

    # EXACT mode dispatch
    res = engine.dispatch_batch(
        requests=[r1, r2],
        vehicles=[v1, v2],
        active_rides=[],
        current_time=1000,
    )

    # r1 should be matched to v1, r2 remains unassigned
    assert len(res.selected_assignments) == 1
    assert "r1" in res.selected_assignments[0].request_ids
    assert "r2" in res.unassigned_request_ids
    assert res.routing_errors_count > 0
    # SearchStatus reflects incomplete routing error in exact mode
    assert res.search_status == SearchStatus.INCOMPLETE_ROUTING_ERROR
    assert res.is_approximated is True


# ---------------------------------------------------------------------------
# 6. Total Routing Outage Returns Safe Fallback
# ---------------------------------------------------------------------------

def test_dispatch_batch_total_routing_outage_returns_safe_fallback() -> None:
    policy_provider = DefaultPolicyProvider()
    spatial_index = H3SpatialIndexAdapter()
    v1 = _make_veh("v1", 40.7100, -74.0050)
    r1 = _make_req("r1", 40.7110, -74.0040, 40.7250, -73.9950)

    failing_router = FailingMockRouter(
        fail_all=True,
        fail_with=RouteLookupError("Network down: routing service unavailable"),
    )

    engine = DispatchEngine(
        policy_provider=policy_provider,
        routing_provider=failing_router,
        spatial_index=spatial_index,
        config=CandidateGenerationConfig.exact(),
    )

    res = engine.dispatch_batch(
        requests=[r1],
        vehicles=[v1],
        active_rides=[],
        current_time=1000,
    )

    assert len(res.selected_assignments) == 0
    assert "r1" in res.unassigned_request_ids
    assert res.routing_errors_count > 0
    assert res.search_status == SearchStatus.INCOMPLETE_ROUTING_ERROR


# ---------------------------------------------------------------------------
# 7. Propagate Routing Errors Flag
# ---------------------------------------------------------------------------

def test_propagate_routing_errors_flag() -> None:
    policy = DefaultPolicyProvider().get_policy()
    policy_provider = DefaultPolicyProvider()
    spatial_index = H3SpatialIndexAdapter()
    v = _make_veh("v1", 40.7100, -74.0050)
    r1 = _make_req("r1", 40.7110, -74.0040, 40.7250, -73.9950)

    failing_router = FailingMockRouter(
        fail_all=True,
        fail_with=RouteTimeoutError("Immediate timeout"),
    )

    # Bundle generator raises when propagate_routing_errors=True
    with pytest.raises(RoutingProviderError, match="Immediate timeout"):
        generate_group_bundles(
            requests=[r1],
            vehicle=v,
            router=failing_router,
            policy=policy,
            current_time=1000,
            propagate_routing_errors=True,
        )

    # Active ride insertion raises when propagate_routing_errors=True
    ride = Ride(
        ride_id="ride1",
        vehicle_id="v1",
        driver_id="d-v1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(),
        scheduled_departure_time=1000,
        active_passenger_count=0,
        total_vmt_meters=0,
        version=1,
    )
    with pytest.raises(RoutingProviderError, match="Immediate timeout"):
        generate_active_ride_insertions(
            active_ride=ride,
            requests=[r1],
            vehicle=v,
            router=failing_router,
            policy=policy,
            current_time=1000,
            propagate_routing_errors=True,
        )

    # dispatch_batch raises when propagate_routing_errors=True
    cfg = CandidateGenerationConfig(propagate_routing_errors=True)
    engine = DispatchEngine(
        policy_provider=policy_provider,
        routing_provider=failing_router,
        spatial_index=spatial_index,
        config=cfg,
    )
    with pytest.raises(RoutingProviderError, match="Immediate timeout"):
        engine.dispatch_batch(
            requests=[r1],
            vehicles=[v],
            active_rides=[],
            current_time=1000,
        )


# ---------------------------------------------------------------------------
# 8. Deadline Expiry Dominates Routing Errors
# ---------------------------------------------------------------------------

def test_deadline_expiry_dominates_routing_errors() -> None:
    policy_provider = DefaultPolicyProvider()
    spatial_index = H3SpatialIndexAdapter()
    v = _make_veh("v1", 40.7100, -74.0050)
    r1 = _make_req("r1", 40.7110, -74.0040, 40.7250, -73.9950)
    r2 = _make_req("r2", 40.7120, -74.0030, 40.7320, -73.9920)

    # Router that fails on r2 and also takes some time
    failing_router = FailingMockRouter(
        failing_coords={(40.7120, -74.0030)},
        fail_with=RouteLookupError("Partial failure"),
    )

    engine = DispatchEngine(
        policy_provider=policy_provider,
        routing_provider=failing_router,
        spatial_index=spatial_index,
        config=CandidateGenerationConfig.exact(),
    )

    # Supply an already expired deadline
    res = engine.dispatch_batch(
        requests=[r1, r2],
        vehicles=[v],
        active_rides=[],
        current_time=1000,
        deadline=time.monotonic() - 0.001,
    )

    # Status must be INCOMPLETE_DEADLINE_EXPIRED, taking precedence over routing errors
    assert res.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
    assert res.is_approximated is True


# ---------------------------------------------------------------------------
# 9. Cancel En Route Request Fault Isolation
# ---------------------------------------------------------------------------

def test_cancel_en_route_request_fault_isolation() -> None:
    storage = InMemoryRideStorage()
    loc1 = GeoCoordinate(latitude=40.7100, longitude=-74.0050)
    loc2 = GeoCoordinate(latitude=40.7300, longitude=-73.9900)
    loc3 = GeoCoordinate(latitude=40.7500, longitude=-73.9800)
    loc4 = GeoCoordinate(latitude=40.7600, longitude=-73.9700)

    stop1 = RouteStop(
        stop_id="s1",
        ride_id="ride1",
        request_id="r1",
        stop_type=StopType.PICKUP,
        location=loc2,
        passenger_delta=1,
        scheduled_arrival_time=1200,
        promised_window_start=1000,
        promised_window_end=1500,
        status=StopStatus.SCHEDULED,
    )
    stop2 = RouteStop(
        stop_id="s2",
        ride_id="ride1",
        request_id="r1",
        stop_type=StopType.DROPOFF,
        location=loc3,
        passenger_delta=-1,
        scheduled_arrival_time=1500,
        promised_window_start=1200,
        promised_window_end=1800,
        status=StopStatus.SCHEDULED,
    )
    stop3 = RouteStop(
        stop_id="s3",
        ride_id="ride1",
        request_id="r2",
        stop_type=StopType.DROPOFF,
        location=loc4,
        passenger_delta=-1,
        scheduled_arrival_time=1800,
        promised_window_start=1500,
        promised_window_end=2200,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride1",
        vehicle_id="v1",
        driver_id="d-v1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop1, stop2, stop3),
        scheduled_departure_time=1000,
        active_passenger_count=1,
        total_vmt_meters=8000,
        version=1,
    )
    storage.save_ride(ride)

    req1 = _make_req("r1", 40.7300, -73.9900, 40.7500, -73.9800)
    storage.save_request(req1)
    req2 = _make_req("r2", 40.7100, -74.0050, 40.7600, -73.9700)
    storage.save_request(req2)

    # Router fails on recalculation
    failing_router = FailingMockRouter(
        fail_all=True,
        fail_with=RouteLookupError("Routing service unreachable"),
    )

    with pytest.raises(LifecycleTransitionError, match="Failed to calculate route leg"):
        cancel_en_route_request(
            ride=ride,
            request_id="r1",
            router=failing_router,
            current_time=1100,
            vehicle_location=loc1,
            storage=storage,
        )

    # Verify storage was NOT corrupted
    stored_ride = storage.get_ride("ride1")
    assert stored_ride is not None
    assert stored_ride.version == 1  # Not updated
    assert stored_ride.total_vmt_meters == 8000
    stored_req = storage.get_request("r1")
    assert stored_req is not None
    assert stored_req.status == RequestStatus.PENDING  # Not cancelled
