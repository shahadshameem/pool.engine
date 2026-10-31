"""Strict TDD tests for explicit exact and bounded dispatch modes (T056)."""

import time
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.policy import DispatchPolicy
from engine.contracts.routing import Coordinate
from engine.domain.enums import (
    DispatchMode,
    RequestStatus,
    RideStatus,
    SearchStatus,
    StopStatus,
    StopType,
)
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle
from engine.dispatch import CandidateGenerationConfig, DispatchEngine
from tests.benchmark.conftest import generate_benchmark_scenario
from tests.scenario.test_candidate_correctness import (
    compare_candidate_sets,
    enumerate_exhaustive_candidates,
)


def _make_request(
    request_id: str,
    pickup_lat: float,
    pickup_lon: float,
    dropoff_lat: float,
    dropoff_lon: float,
    seat_count: int = 1,
    earliest_pickup: int = 1000,
    latest_dropoff: int = 3000,
) -> RideRequest:
    return RideRequest(
        request_id=request_id,
        user_id=f"user-{request_id}",
        pickup_location=GeoCoordinate(latitude=pickup_lat, longitude=pickup_lon),
        dropoff_location=GeoCoordinate(latitude=dropoff_lat, longitude=dropoff_lon),
        seat_count=seat_count,
        earliest_pickup_time=earliest_pickup,
        latest_dropoff_time=latest_dropoff,
        direct_distance_meters=2220,
        direct_duration_seconds=200,
        status=RequestStatus.PENDING,
    )


def _make_vehicle(
    vehicle_id: str,
    lat: float,
    lon: float,
    capacity: int = 4,
) -> Vehicle:
    return Vehicle(
        vehicle_id=vehicle_id,
        driver_id=f"drv-{vehicle_id}",
        total_seat_capacity=capacity,
        current_location=GeoCoordinate(latitude=lat, longitude=lon),
        is_active=True,
    )


def test_batch_sizes_20_and_21_identical_semantics() -> None:
    """
    Requirement 1 & 5: Batch sizes 20 and 21 must have identical configuration semantics.
    Removing the undocumented `len(pending_requests) > 20` threshold ensures that
    the candidate generation limits and configuration behavior do not abruptly change at N=21.
    """
    reqs, vehs, rides = generate_benchmark_scenario(seed=42)
    policy_prov = DefaultPolicyProvider()
    router = MockRoutingProvider()
    spatial = H3SpatialIndexAdapter()

    # Exact mode configuration
    cfg_exact = CandidateGenerationConfig.exact()
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)

    # 20 requests vs 21 requests in exact mode
    sub20_reqs = reqs[:20]
    sub21_reqs = reqs[:21]
    sub_vehs = vehs[:5]
    sub_rides = rides[:2]

    cands20 = engine.generate_candidates(sub20_reqs, sub_vehs, sub_rides, 1700000000, config=cfg_exact)
    cands21 = engine.generate_candidates(sub21_reqs, sub_vehs, sub_rides, 1700000000, config=cfg_exact)

    # In exact mode, both must be EXACT and COMPLETE with 0 approximation
    assert getattr(cands20, "dispatch_mode") == DispatchMode.EXACT
    assert getattr(cands21, "dispatch_mode") == DispatchMode.EXACT
    assert getattr(cands20, "search_status") == SearchStatus.COMPLETE
    assert getattr(cands21, "search_status") == SearchStatus.COMPLETE
    assert getattr(cands20, "is_approximated") is False
    assert getattr(cands21, "is_approximated") is False

    # Candidates formed for the first 20 requests in cands21 must match cands20
    cands20_keys = {
        (c.vehicle_id, c.request_ids, tuple(s.stop_id for s in c.ordered_stops))
        for c in cands20
    }
    cands21_sub20_keys = {
        (c.vehicle_id, c.request_ids, tuple(s.stop_id for s in c.ordered_stops))
        for c in cands21
        if all(rid != "req-bench-0020" for rid in c.request_ids)
    }
    assert cands20_keys == cands21_sub20_keys, (
        "Batch size 21 truncated or altered candidate generation for the first 20 requests; "
        "undocumented threshold at N=20 must be completely eliminated."
    )


def test_exact_mode_discovers_6km_vehicle_with_closer_vehicle_present() -> None:
    """
    Requirement 3 & 5: A feasible vehicle 6 km away must be discovered in exact mode
    even when another capable vehicle is within 5 km.
    The old fallback stopped expanding at 5km when any vehicle was found.
    """
    policy = DispatchPolicy(max_pickup_delay_seconds=600)  # 600s allows 6,666m at 40 km/h (11.11 m/s)
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial = H3SpatialIndexAdapter()

    # Target request at (40.7000, -74.0000)
    req = _make_request("req-target", 40.7000, -74.0000, 40.7200, -74.0000)

    # Vehicle 1: 1,000m North (inside 5km initial radius)
    # 0.009 deg lat * 111,000m ~ 1,000m
    veh_close = _make_vehicle("veh-close-1km", 40.7090, -74.0000, capacity=4)

    # Vehicle 2: 6,000m North (outside 5km, but reachable in 540s <= 600s)
    # 0.054 deg lat * 111,000m ~ 6,000m
    veh_far = _make_vehicle("veh-far-6km", 40.7540, -74.0000, capacity=4)

    # 1. Exact mode: MUST discover BOTH vehicles
    cfg_exact = CandidateGenerationConfig.exact()
    engine_exact = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)

    cands_exact = engine_exact.generate_candidates(
        requests=[req],
        vehicles=[veh_close, veh_far],
        active_rides=[],
        current_time=1000,
        config=cfg_exact,
    )

    discovered_veh_ids_exact = {c.vehicle_id for c in cands_exact}
    assert "veh-close-1km" in discovered_veh_ids_exact
    assert "veh-far-6km" in discovered_veh_ids_exact, (
        "Exact mode must examine full physical reachability radius (20km) and discover veh-far-6km "
        "even when veh-close-1km is present within 5km."
    )
    assert getattr(cands_exact, "dispatch_mode") == DispatchMode.EXACT
    assert getattr(cands_exact, "is_approximated") is False
    assert getattr(cands_exact, "search_status") == SearchStatus.COMPLETE

    # 2. Bounded mode with max_search_radius_meters = 5000.0:
    # Explicitly reports approximation and omits veh-far-6km
    cfg_bounded = CandidateGenerationConfig.bounded(
        max_search_radius_meters=5000.0,
        max_vehicles_per_request=10,
        max_requests_per_vehicle=5,
        exhaustive_fallback=False,
    )
    engine_bounded = DispatchEngine(policy_prov, router, spatial, config=cfg_bounded)

    cands_bounded = engine_bounded.generate_candidates(
        requests=[req],
        vehicles=[veh_close, veh_far],
        active_rides=[],
        current_time=1000,
        config=cfg_bounded,
    )

    discovered_veh_ids_bounded = {c.vehicle_id for c in cands_bounded}
    assert "veh-close-1km" in discovered_veh_ids_bounded
    assert "veh-far-6km" not in discovered_veh_ids_bounded
    assert getattr(cands_bounded, "dispatch_mode") == DispatchMode.BOUNDED
    assert getattr(cands_bounded, "is_approximated") is True
    assert getattr(cands_bounded, "search_status") == SearchStatus.APPROXIMATED


def test_exact_candidate_sets_match_exhaustive_reference() -> None:
    """
    Requirement 2 & 5: Exact candidate sets must match exhaustive reference results
    with 100% recall on small deterministic fixtures.
    """
    policy = DispatchPolicy(max_pickup_delay_seconds=600)
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0)
    spatial = H3SpatialIndexAdapter()

    reqs, vehs, rides = generate_benchmark_scenario(seed=42)
    # Include requests and vehicles where distances exceed 5km
    test_reqs = reqs[:10]
    test_vehs = vehs[:8]
    test_rides = rides[:4]

    # Ground truth reference
    ex_cands = enumerate_exhaustive_candidates(
        requests=test_reqs,
        vehicles=test_vehs,
        active_rides=test_rides,
        router=router,
        policy=policy,
        current_time=1700000000,
        max_bundle_size=2,
    )
    assert len(ex_cands) > 0

    cfg_exact = CandidateGenerationConfig.exact(max_bundle_size=2)
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)

    opt_cands = engine.generate_candidates(
        requests=test_reqs,
        vehicles=test_vehs,
        active_rides=test_rides,
        current_time=1700000000,
        config=cfg_exact,
    )

    cmp_res = compare_candidate_sets(opt_cands, ex_cands)
    assert cmp_res["false_negative_count"] == 0, (
        f"Exact mode had {cmp_res['false_negative_count']} false negatives vs exhaustive reference! "
        f"Recall was {cmp_res['recall_pct']}%."
    )
    assert cmp_res["recall_pct"] == 100.0
    assert getattr(opt_cands, "is_approximated") is False
    assert getattr(opt_cands, "search_status") == SearchStatus.COMPLETE


def test_exact_mode_reports_incomplete_when_deadline_expires() -> None:
    """
    Requirement 4 & 5: When exact candidate generation cannot complete before the deadline,
    it must return an explicit incomplete-search status and not label the result complete or exact.
    """
    policy_prov = DefaultPolicyProvider()
    router = MockRoutingProvider()
    spatial = H3SpatialIndexAdapter()

    reqs, vehs, rides = generate_benchmark_scenario(seed=42)

    cfg_exact = CandidateGenerationConfig.exact()
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)

    # Tight/already expired deadline
    expired_deadline = time.monotonic() - 0.010

    result = engine.dispatch_batch(
        requests=reqs[:50],
        vehicles=vehs[:20],
        active_rides=rides[:10],
        current_time=1700000000,
        deadline=expired_deadline,
        config=cfg_exact,
    )

    assert result.dispatch_mode == DispatchMode.EXACT
    assert result.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
    assert result.is_approximated is True, "Incomplete exact search must report is_approximated=True"


def test_bounded_mode_reports_approximation() -> None:
    """
    Requirement 2 & 5: Bounded mode must explicitly report approximation when a configured
    limit (search radius, candidate vehicles, or request count) truncates search.
    """
    policy_prov = DefaultPolicyProvider()
    router = MockRoutingProvider()
    spatial = H3SpatialIndexAdapter()

    req = _make_request("req-b-1", 40.7100, -74.0000, 40.7300, -74.0000)
    vehs = [
        _make_vehicle(f"veh-b-{i}", 40.7100 + i * 0.005, -74.0000, capacity=4)
        for i in range(10)
    ]

    # Explicitly bound vehicles per request to 3
    cfg_bounded = CandidateGenerationConfig.bounded(
        max_vehicles_per_request=3,
        max_requests_per_vehicle=2,
        max_search_radius_meters=3000.0,
    )
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_bounded)

    res = engine.dispatch_batch(
        requests=[req],
        vehicles=vehs,
        active_rides=[],
        current_time=1000,
        config=cfg_bounded,
    )

    assert res.dispatch_mode == DispatchMode.BOUNDED
    assert res.search_status == SearchStatus.APPROXIMATED
    assert res.is_approximated is True


def test_hard_constraints_enforced_in_both_modes() -> None:
    """
    Requirement 2 & 5: Every hard physical invariant (seat capacity, pickup-before-dropoff,
    detour bounds, and pickup delay) must remain strictly enforced in both exact and bounded modes.
    """
    policy = DispatchPolicy(
        max_pickup_delay_seconds=300,
        detour_relative_multiplier=1.2,
        detour_absolute_cap_seconds=600,
    )
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0)
    spatial = H3SpatialIndexAdapter()

    # Request requiring 4 seats
    req_4seat = _make_request("req-4seat", 40.7100, -74.0000, 40.7300, -74.0000, seat_count=4)
    # Vehicle with only 3 seats -> physically impossible capacity violation
    veh_3seat = _make_vehicle("veh-3seat", 40.7105, -74.0000, capacity=3)

    for mode in [DispatchMode.EXACT, DispatchMode.BOUNDED]:
        cfg = (
            CandidateGenerationConfig.exact()
            if mode == DispatchMode.EXACT
            else CandidateGenerationConfig.bounded()
        )
        engine = DispatchEngine(policy_prov, router, spatial, config=cfg)

        cands = engine.generate_candidates(
            requests=[req_4seat],
            vehicles=[veh_3seat],
            active_rides=[],
            current_time=1000,
            config=cfg,
        )
        assert len(cands) == 0, f"Capacity violation admitted in {mode} mode!"

        res = engine.dispatch_batch(
            requests=[req_4seat],
            vehicles=[veh_3seat],
            active_rides=[],
            current_time=1000,
            config=cfg,
        )
        assert len(res.selected_assignments) == 0, f"Illegal assignment made in {mode} mode!"
        assert "req-4seat" in res.unassigned_request_ids
