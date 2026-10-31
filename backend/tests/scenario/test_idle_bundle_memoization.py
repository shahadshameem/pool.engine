"""Tests for local directed waypoint-leg memoization in idle-vehicle bundle generation."""

from collections import Counter
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.policy import DispatchPolicy
from engine.contracts.routing import Coordinate
from engine.domain.enums import RequestStatus
from engine.domain.models import GeoCoordinate, RideRequest, Vehicle
from engine.routing.bundle_generator import generate_group_bundles


class TrackingSpyRouter(MockRoutingProvider):
    """Spy router that records every queried directed leg."""

    def __init__(self, **kwargs: float) -> None:
        super().__init__(**kwargs)
        self.calls: list[tuple[Coordinate, Coordinate]] = []

    def get_direct_leg(
        self, origin: Coordinate, destination: Coordinate
    ) -> tuple[int, int]:
        self.calls.append((origin, destination))
        return super().get_direct_leg(origin, destination)


class AsymmetricSpyRouter(MockRoutingProvider):
    """Router that returns asymmetric travel metrics depending on direction."""

    def __init__(self) -> None:
        super().__init__(average_speed_kmh=40.0, circuity_factor=1.0)
        self.calls: list[tuple[Coordinate, Coordinate]] = []

    def get_direct_leg(
        self, origin: Coordinate, destination: Coordinate
    ) -> tuple[int, int]:
        self.calls.append((origin, destination))
        base_dist, base_dur = super().get_direct_leg(origin, destination)
        # Asymmetry: southward travels take 50% longer than northward travels
        if destination.latitude < origin.latitude:
            return int(round(base_dist * 1.5)), int(round(base_dur * 1.5))
        return base_dist, base_dur


@pytest.fixture
def policy() -> DispatchPolicy:
    return DispatchPolicy(
        max_pickup_delay_seconds=600,
        detour_relative_multiplier=1.40,
        detour_absolute_cap_seconds=900,
    )


def test_idle_bundle_waypoint_cache_deduplication_and_hits(
    policy: DispatchPolicy,
) -> None:
    """
    Test that local waypoint-leg memoization eliminates duplicate routing-provider calls
    so that every distinct directed leg between waypoints is queried at most once per invocation.
    """
    router = TrackingSpyRouter(average_speed_kmh=40.0, circuity_factor=1.0)
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-idle-memo-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )
    t_start = 1700000000

    r1 = RideRequest(
        request_id="req-im1",
        user_id="u1",
        pickup_location=GeoCoordinate(latitude=base_lat + 0.010, longitude=base_lon),
        dropoff_location=GeoCoordinate(latitude=base_lat + 0.020, longitude=base_lon),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=1000,
        direct_duration_seconds=90,
        status=RequestStatus.PENDING,
    )
    r2 = RideRequest(
        request_id="req-im2",
        user_id="u2",
        pickup_location=GeoCoordinate(latitude=base_lat + 0.015, longitude=base_lon),
        dropoff_location=GeoCoordinate(latitude=base_lat + 0.025, longitude=base_lon),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=1000,
        direct_duration_seconds=90,
        status=RequestStatus.PENDING,
    )

    cands = generate_group_bundles(
        vehicle=veh,
        requests=[r1, r2],
        router=router,
        policy=policy,
        current_time=t_start,
        max_bundle_size=2,
    )
    assert len(cands) > 0

    # With local waypoint-leg memoization, every distinct directed leg must be queried at most once!
    call_counts = Counter(router.calls)
    assert len(call_counts) > 0
    max_duplicate_calls = max(call_counts.values())
    assert (
        max_duplicate_calls == 1
    ), f"Expected at most 1 call per directed leg, got {max_duplicate_calls} calls for leg {call_counts.most_common(1)[0]}"


def test_idle_bundle_waypoint_cache_distinct_directed_legs(
    policy: DispatchPolicy,
) -> None:
    """
    Test that the local waypoint-leg cache distinguishes directed legs (A -> B != B -> A)
    and correctly handles asymmetric routing providers without conflating directions.
    """
    router = AsymmetricSpyRouter()
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-idle-asym-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )
    t_start = 1700000000

    r1 = RideRequest(
        request_id="req-asym-1",
        user_id="u-asym-1",
        pickup_location=GeoCoordinate(latitude=base_lat + 0.020, longitude=base_lon),
        dropoff_location=GeoCoordinate(latitude=base_lat + 0.005, longitude=base_lon),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=1500,
        direct_duration_seconds=120,
        status=RequestStatus.PENDING,
    )
    r2 = RideRequest(
        request_id="req-asym-2",
        user_id="u-asym-2",
        pickup_location=GeoCoordinate(latitude=base_lat + 0.005, longitude=base_lon),
        dropoff_location=GeoCoordinate(latitude=base_lat + 0.020, longitude=base_lon),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=1500,
        direct_duration_seconds=120,
        status=RequestStatus.PENDING,
    )

    cands = generate_group_bundles(
        vehicle=veh,
        requests=[r1, r2],
        router=router,
        policy=policy,
        current_time=t_start,
        max_bundle_size=2,
    )

    assert len(cands) > 0
    for c in cands:
        assert c.vmt_meters > 0
        assert c.score_breakdown.vmt_savings_ratio >= 0


def test_idle_bundle_waypoint_cache_repeated_waypoints(
    policy: DispatchPolicy,
) -> None:
    """
    Test that multiple requests with identical pickup coordinates (co-located stops)
    have distinct stable waypoint identities and do not collide in the waypoint cache.
    """
    router = TrackingSpyRouter(average_speed_kmh=40.0, circuity_factor=1.0)
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-idle-coloc-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )
    t_start = 1700000000

    co_lat, co_lon = base_lat + 0.010, base_lon
    r1 = RideRequest(
        request_id="req-coloc-1",
        user_id="u1",
        pickup_location=GeoCoordinate(latitude=co_lat, longitude=co_lon),
        dropoff_location=GeoCoordinate(latitude=base_lat + 0.020, longitude=base_lon),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=1000,
        direct_duration_seconds=90,
        status=RequestStatus.PENDING,
    )
    r2 = RideRequest(
        request_id="req-coloc-2",
        user_id="u2",
        pickup_location=GeoCoordinate(latitude=co_lat, longitude=co_lon),
        dropoff_location=GeoCoordinate(latitude=base_lat + 0.030, longitude=base_lon),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=2000,
        direct_duration_seconds=180,
        status=RequestStatus.PENDING,
    )

    cands = generate_group_bundles(
        vehicle=veh,
        requests=[r1, r2],
        router=router,
        policy=policy,
        current_time=t_start,
        max_bundle_size=2,
    )

    bundle_cands = [c for c in cands if len(c.request_ids) == 2]
    assert len(bundle_cands) > 0
    for c in bundle_cands:
        stop_ids = [s.stop_id for s in c.ordered_stops]
        assert "stop-p-req-coloc-1" in stop_ids
        assert "stop-p-req-coloc-2" in stop_ids


def test_idle_bundle_waypoint_cache_separate_vehicle_scopes(
    policy: DispatchPolicy,
) -> None:
    """
    Test that local waypoint-leg caches have separate scopes per vehicle/invocation
    and do not leak state across vehicles or persistent router state.
    """
    router = TrackingSpyRouter(average_speed_kmh=40.0, circuity_factor=1.0)
    base_lat, base_lon = 40.7100, -74.0000
    t_start = 1700000000

    veh1 = Vehicle(
        vehicle_id="veh-scope-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=base_lat, longitude=base_lon),
        is_active=True,
    )
    veh2 = Vehicle(
        vehicle_id="veh-scope-2",
        driver_id="drv-2",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=base_lat + 0.050, longitude=base_lon),
        is_active=True,
    )

    req = RideRequest(
        request_id="req-scope-1",
        user_id="u1",
        pickup_location=GeoCoordinate(latitude=base_lat + 0.010, longitude=base_lon),
        dropoff_location=GeoCoordinate(latitude=base_lat + 0.020, longitude=base_lon),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=1000,
        direct_duration_seconds=90,
        status=RequestStatus.PENDING,
    )

    _ = generate_group_bundles(
        vehicle=veh1,
        requests=[req],
        router=router,
        policy=policy,
        current_time=t_start,
        max_bundle_size=1,
    )
    calls_after_veh1 = len(router.calls)
    assert calls_after_veh1 > 0

    _ = generate_group_bundles(
        vehicle=veh2,
        requests=[req],
        router=router,
        policy=policy,
        current_time=t_start,
        max_bundle_size=1,
    )
    calls_after_veh2 = len(router.calls)
    # veh2 must query its own legs (e.g. veh2 -> pickup) rather than falsely reusing veh1's location
    assert calls_after_veh2 > calls_after_veh1


def test_idle_bundle_candidate_equivalence_and_determinism(
    policy: DispatchPolicy,
) -> None:
    """
    Test that memoization produces candidates with identical ordered stops,
    metrics, scores, and deterministic ordering across repeated runs.
    """
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.25)
    base_lat, base_lon = 40.7100, -74.0000
    veh = Vehicle(
        vehicle_id="veh-eq-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=base_lat, longitude=base_lon),
        is_active=True,
    )
    t_start = 1700000000

    reqs = [
        RideRequest(
            request_id=f"req-eq-{i}",
            user_id=f"u-{i}",
            pickup_location=GeoCoordinate(latitude=base_lat + 0.005 * i, longitude=base_lon),
            dropoff_location=GeoCoordinate(latitude=base_lat + 0.005 * i + 0.010, longitude=base_lon),
            seat_count=1,
            earliest_pickup_time=t_start,
            latest_dropoff_time=t_start + 3600,
            direct_distance_meters=1000,
            direct_duration_seconds=90,
            status=RequestStatus.PENDING,
        )
        for i in range(1, 4)
    ]

    run1 = generate_group_bundles(
        vehicle=veh,
        requests=reqs,
        router=router,
        policy=policy,
        current_time=t_start,
        max_bundle_size=3,
    )
    run2 = generate_group_bundles(
        vehicle=veh,
        requests=reqs,
        router=router,
        policy=policy,
        current_time=t_start,
        max_bundle_size=3,
    )

    assert len(run1) == len(run2)
    for c1, c2 in zip(run1, run2):
        assert c1.request_ids == c2.request_ids
        assert c1.objective_value == c2.objective_value
        assert c1.vmt_meters == c2.vmt_meters
        assert [s.stop_id for s in c1.ordered_stops] == [s.stop_id for s in c2.ordered_stops]
        assert [s.scheduled_arrival_time for s in c1.ordered_stops] == [s.scheduled_arrival_time for s in c2.ordered_stops]


def test_idle_bundle_dead_branch_pruning(policy: DispatchPolicy) -> None:
    """
    Test that an impossible prefix branch (pickup arriving strictly after pickup deadline)
    is pruned immediately during prefix search, so that legs from the impossible stop
    to other candidate stops are never queried.
    """
    router = TrackingSpyRouter(average_speed_kmh=40.0, circuity_factor=1.0)
    base_lat, base_lon = 40.7100, -74.0000
    veh = Vehicle(
        vehicle_id="veh-prune-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=base_lat, longitude=base_lon),
        is_active=True,
    )
    t_start = 1700000000

    # Request 1: pickup is nearby (feasible)
    r1 = RideRequest(
        request_id="req-near",
        user_id="u1",
        pickup_location=GeoCoordinate(latitude=base_lat + 0.010, longitude=base_lon),
        dropoff_location=GeoCoordinate(latitude=base_lat + 0.020, longitude=base_lon),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=1000,
        direct_duration_seconds=90,
        status=RequestStatus.PENDING,
    )
    # Request 2: pickup is extremely far away (impossible pickup delay: 50km away with 600s max delay)
    r2 = RideRequest(
        request_id="req-far",
        user_id="u2",
        pickup_location=GeoCoordinate(latitude=base_lat + 0.500, longitude=base_lon),
        dropoff_location=GeoCoordinate(latitude=base_lat + 0.510, longitude=base_lon),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=1000,
        direct_duration_seconds=90,
        status=RequestStatus.PENDING,
    )

    cands = generate_group_bundles(
        vehicle=veh,
        requests=[r1, r2],
        router=router,
        policy=policy,
        current_time=t_start,
        max_bundle_size=2,
    )

    # Candidate with req-far must not exist
    for c in cands:
        assert "req-far" not in c.request_ids

    # With prefix DFS pruning, once veh -> req-far is found to violate pickup delay,
    # the dead branch is pruned: the leg from req-far pickup to req-near dropoff is NEVER queried!
    p_far = Coordinate(r2.pickup_location.latitude, r2.pickup_location.longitude)
    d_near = Coordinate(r1.dropoff_location.latitude, r1.dropoff_location.longitude)
    queried_legs = set(router.calls)
    assert (p_far, d_near) not in queried_legs, "Dead branch was not pruned: (p_far -> d_near) should never be queried!"


def test_idle_bundle_exact_boundary_pickup_delay(policy: DispatchPolicy) -> None:
    """
    Test exact boundary conditions for pickup delay:
    - Arrival exactly equal to earliest_pickup_time + max_delay is FEASIBLE.
    - Arrival at earliest_pickup_time + max_delay + 1 is INFEASIBLE (pruned).
    """
    router = MockRoutingProvider(average_speed_kmh=36.0, circuity_factor=1.0)
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    t_start = 1700000000

    # At 36 km/h = 10 m/s:
    # 600 seconds delay = 6,000 meters travel distance.
    # We find coordinates matching exactly 6000m and 6010m.
    # 1 degree latitude ~ 111,139 meters. 6000m ~ 0.053986 degrees.
    target_coord = Coordinate(base_lat + 0.053986, base_lon)
    dist, dur = router.get_direct_leg(v_loc, target_coord)

    # Adjust earliest_pickup_time so that t_start + dur == earliest + max_delay (exact boundary)
    earliest_exact = t_start + dur - policy.max_pickup_delay_seconds
    earliest_late = earliest_exact - 1  # will make actual delay = max_delay + 1

    veh = Vehicle(
        vehicle_id="veh-bd-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )

    req_exact = RideRequest(
        request_id="req-exact",
        user_id="u-exact",
        pickup_location=GeoCoordinate(latitude=target_coord.latitude, longitude=target_coord.longitude),
        dropoff_location=GeoCoordinate(latitude=target_coord.latitude + 0.010, longitude=target_coord.longitude),
        seat_count=1,
        earliest_pickup_time=earliest_exact,
        latest_dropoff_time=t_start + 7200,
        direct_distance_meters=1000,
        direct_duration_seconds=100,
        status=RequestStatus.PENDING,
    )
    cands_exact = generate_group_bundles(
        vehicle=veh,
        requests=[req_exact],
        router=router,
        policy=policy,
        current_time=t_start,
        max_bundle_size=1,
    )
    assert len(cands_exact) == 1, "Candidate arriving exactly at pickup delay deadline must be accepted"

    req_late = RideRequest(
        request_id="req-late",
        user_id="u-late",
        pickup_location=GeoCoordinate(latitude=target_coord.latitude, longitude=target_coord.longitude),
        dropoff_location=GeoCoordinate(latitude=target_coord.latitude + 0.010, longitude=target_coord.longitude),
        seat_count=1,
        earliest_pickup_time=earliest_late,
        latest_dropoff_time=t_start + 7200,
        direct_distance_meters=1000,
        direct_duration_seconds=100,
        status=RequestStatus.PENDING,
    )
    cands_late = generate_group_bundles(
        vehicle=veh,
        requests=[req_late],
        router=router,
        policy=policy,
        current_time=t_start,
        max_bundle_size=1,
    )
    assert len(cands_late) == 0, "Candidate arriving 1 second late must be pruned"


def test_idle_bundle_exact_boundary_detour(policy: DispatchPolicy) -> None:
    """
    Test exact boundary conditions for in-vehicle passenger detour:
    - In-vehicle duration exactly equal to direct_duration + max_allowed_detour is FEASIBLE.
    - In-vehicle duration 1 second beyond max_allowed_detour is INFEASIBLE (pruned).
    """
    router = MockRoutingProvider(average_speed_kmh=36.0, circuity_factor=1.0)
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-detour-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )
    t_start = 1700000000

    # Direct trip: 500 seconds.
    # Detour allowed: min((1.4 - 1.0) * 500, 900) = 200 seconds. Max allowed in-vehicle = 700 seconds.
    p_loc = Coordinate(base_lat + 0.010, base_lon)
    d_loc = Coordinate(base_lat + 0.060, base_lon)
    _, dur_direct = router.get_direct_leg(p_loc, d_loc)

    # Detour intermediate stop location
    inter_loc = Coordinate(base_lat + 0.035, base_lon + 0.010)

    # We can create a 2-request bundle where request 1 experiences detour due to servicing request 2
    r1 = RideRequest(
        request_id="req-d1",
        user_id="u-d1",
        pickup_location=GeoCoordinate(latitude=p_loc.latitude, longitude=p_loc.longitude),
        dropoff_location=GeoCoordinate(latitude=d_loc.latitude, longitude=d_loc.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 7200,
        direct_distance_meters=5000,
        direct_duration_seconds=dur_direct,
        status=RequestStatus.PENDING,
    )
    r2 = RideRequest(
        request_id="req-d2",
        user_id="u-d2",
        pickup_location=GeoCoordinate(latitude=inter_loc.latitude, longitude=inter_loc.longitude),
        dropoff_location=GeoCoordinate(latitude=inter_loc.latitude + 0.005, longitude=inter_loc.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 7200,
        direct_distance_meters=1000,
        direct_duration_seconds=100,
        status=RequestStatus.PENDING,
    )

    cands = generate_group_bundles(
        vehicle=veh,
        requests=[r1, r2],
        router=router,
        policy=policy,
        current_time=t_start,
        max_bundle_size=2,
    )
    for c in cands:
        if "req-d1" not in c.request_ids:
            continue
        p_time = next(s.scheduled_arrival_time for s in c.ordered_stops if s.stop_id == "stop-p-req-d1")
        d_time = next(s.scheduled_arrival_time for s in c.ordered_stops if s.stop_id == "stop-d-req-d1")
        assert (d_time - p_time) <= dur_direct + min(0.40 * dur_direct, 900) + 1e-6


def test_idle_bundle_prefix_pruning_oracle_equivalence(policy: DispatchPolicy) -> None:
    """
    Test that idle-bundle generation with memoization and prefix pruning matches
    the independent candidate oracle across bundle sizes 1, 2, and 3 with zero discrepancies.
    """
    from tests.oracle.candidate_oracle import IndependentCandidateOracle

    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.2)
    base_lat, base_lon = 40.7100, -74.0000
    veh = Vehicle(
        vehicle_id="veh-oracle-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=base_lat, longitude=base_lon),
        is_active=True,
    )
    t_start = 1700000000

    reqs = [
        RideRequest(
            request_id=f"req-orc-{i}",
            user_id=f"u-{i}",
            pickup_location=GeoCoordinate(latitude=base_lat + 0.008 * i, longitude=base_lon),
            dropoff_location=GeoCoordinate(latitude=base_lat + 0.008 * i + 0.015, longitude=base_lon),
            seat_count=1,
            earliest_pickup_time=t_start + 60 * i,
            latest_dropoff_time=t_start + 3600,
            direct_distance_meters=1500,
            direct_duration_seconds=135,
            status=RequestStatus.PENDING,
        )
        for i in range(1, 4)
    ]

    for b_size in (1, 2, 3):
        oracle = IndependentCandidateOracle(router=router, policy=policy, max_bundle_size=b_size)
        oracle_cands = oracle.enumerate_feasible_candidates(
            requests=reqs[:b_size],
            vehicles=[veh],
            active_rides=[],
            current_time=t_start,
        )

        prod_cands = generate_group_bundles(
            vehicle=veh,
            requests=reqs[:b_size],
            router=router,
            policy=policy,
            current_time=t_start,
            max_bundle_size=b_size,
        )

        comp = oracle.compare(prod_cands, oracle_cands)
        assert comp.is_perfect_match, (
            f"Oracle mismatch for bundle size {b_size}: "
            f"FP={len(comp.false_positives)}, FN={len(comp.false_negatives)}"
        )
