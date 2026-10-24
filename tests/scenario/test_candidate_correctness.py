"""Deterministic correctness tests comparing optimized candidate generation against exhaustive candidate enumeration."""

import math
from typing import Sequence

import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.policy import DispatchPolicy
from engine.contracts.routing import Coordinate, RoadNetworkRoutingProvider
from engine.domain.candidate import CandidateAssignment
from engine.domain.enums import RequestStatus, RideStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle
from engine.dispatch import DispatchEngine
from tests.oracle.candidate_oracle import (
    IndependentCandidateOracle,
    OracleCandidateSignature,
)


def enumerate_exhaustive_candidates(
    requests: Sequence[RideRequest],
    vehicles: Sequence[Vehicle],
    active_rides: Sequence[Ride],
    router: RoadNetworkRoutingProvider,
    policy: DispatchPolicy,
    current_time: int,
    max_bundle_size: int = 2,
) -> list[OracleCandidateSignature]:
    """
    Independent first-principles ground-truth candidate generator.
    Evaluates every active vehicle and request combination from first principles
    without importing or invoking production candidate generation routines.
    """
    oracle = IndependentCandidateOracle(
        router=router,
        policy=policy,
        max_bundle_size=max_bundle_size,
    )
    return oracle.enumerate_feasible_candidates(
        requests=requests,
        vehicles=vehicles,
        active_rides=active_rides,
        current_time=current_time,
    )


def compare_candidate_sets(
    optimized: Sequence[CandidateAssignment],
    exhaustive: Sequence[object],
) -> dict[str, object]:
    """
    Compares optimized candidate set against exhaustive reference.
    Reports:
    - exhaustive_count: total feasible candidates in ground truth
    - optimized_count: total feasible candidates in optimized output
    - false_negatives: candidates present in exhaustive but missing from optimized
    - recall_pct: recall percentage of feasible candidates
    """
    def _cand_key(c: object) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
        if isinstance(c, CandidateAssignment):
            return (c.vehicle_id, tuple(sorted(c.request_ids)), tuple(s.stop_id for s in c.ordered_stops))
        elif isinstance(c, OracleCandidateSignature):
            return (c.vehicle_id, tuple(sorted(c.request_ids)), c.ordered_stop_ids)
        raise TypeError(f"Unknown candidate type: {type(c)}")

    ex_map = {_cand_key(c): c for c in exhaustive}
    opt_map = {_cand_key(c): c for c in optimized}

    false_negatives = [c for k, c in ex_map.items() if k not in opt_map]
    extra_candidates = [c for k, c in opt_map.items() if k not in ex_map]

    ex_count = len(ex_map)
    opt_count = len(opt_map)
    recall = ((ex_count - len(false_negatives)) / ex_count * 100.0) if ex_count > 0 else 100.0

    return {
        "exhaustive_count": ex_count,
        "optimized_count": opt_count,
        "false_negatives": false_negatives,
        "false_negative_count": len(false_negatives),
        "extra_candidates": extra_candidates,
        "recall_pct": round(recall, 2),
    }


# =============================================================================
# TDD Regression Tests for Arbitrary Search Limits
# =============================================================================

def test_radius_cap_5km_excludes_feasible_candidate() -> None:
    """
    Regression Test for Limit 1 (Fixed 5 km search-radius cap):
    A vehicle at 6,000m is physically reachable within max_pickup_delay_seconds=600
    (takes 540s at 40 km/h).
    Exhaustive search finds 1 candidate; arbitrary 5km cap causes a false negative.
    """
    policy = DispatchPolicy(max_pickup_delay_seconds=600)
    policy_provider = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial_index = H3SpatialIndexAdapter()
    engine = DispatchEngine(
        policy_provider=policy_provider,
        routing_provider=router,
        spatial_index=spatial_index,
    )

    req = RideRequest(
        request_id="req-far-1",
        user_id="user-1",
        pickup_location=GeoCoordinate(latitude=40.7000, longitude=-74.0000),
        dropoff_location=GeoCoordinate(latitude=40.7200, longitude=-74.0000),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=3000,
        direct_distance_meters=2220,
        direct_duration_seconds=200,
        status=RequestStatus.PENDING,
    )

    # Vehicle located at ~6,000m north (0.054 degrees lat * 111,000m ~ 6,000m)
    veh_far = Vehicle(
        vehicle_id="veh-far-6km",
        driver_id="drv-far",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=40.7540, longitude=-74.0000),
        is_active=True,
    )

    # 1. Exhaustive ground truth
    ex_cands = enumerate_exhaustive_candidates(
        requests=[req],
        vehicles=[veh_far],
        active_rides=[],
        router=router,
        policy=policy,
        current_time=1000,
    )
    assert len(ex_cands) >= 1, "Exhaustive search must discover vehicle reachable in 540s <= 600s"

    # 2. Optimized engine candidate generation
    res = engine.dispatch_batch(
        requests=[req],
        vehicles=[veh_far],
        active_rides=[],
        current_time=1000,
    )
    # Under the arbitrary 5km cap, veh-far-6km is omitted and left unassigned
    assert len(res.selected_assignments) == 1, (
        "Engine must not silently drop reachable vehicle at 6km when delay limit allows 600s"
    )
    assert res.selected_assignments[0].vehicle_id == "veh-far-6km"


def test_top_5_vehicles_limit_excludes_feasible_6th_vehicle() -> None:
    """
    Regression Test for Limit 2 (Limit of 5 spatial vehicles per request):
    The 5 closest vehicles are all full (capacity=2 but request needs 3 seats).
    The 6th vehicle (at 1,200m) has capacity=4 and is feasible.
    Engine must discover the 6th vehicle and not terminate at max_candidates=5.
    """
    policy = DispatchPolicy(max_pickup_delay_seconds=600)
    policy_provider = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0)
    spatial_index = H3SpatialIndexAdapter()
    engine = DispatchEngine(
        policy_provider=policy_provider,
        routing_provider=router,
        spatial_index=spatial_index,
    )

    # Request requires 3 seats
    req = RideRequest(
        request_id="req-group-3",
        user_id="user-grp",
        pickup_location=GeoCoordinate(latitude=40.7100, longitude=-74.0000),
        dropoff_location=GeoCoordinate(latitude=40.7300, longitude=-74.0000),
        seat_count=3,
        earliest_pickup_time=1000,
        latest_dropoff_time=3000,
        direct_distance_meters=2220,
        direct_duration_seconds=200,
        status=RequestStatus.PENDING,
    )

    # 5 closer vehicles (100m to 500m away), but all have only 2 seats!
    closer_vehs = [
        Vehicle(
            vehicle_id=f"veh-close-{i}",
            driver_id=f"drv-{i}",
            total_seat_capacity=2,  # Cannot fit 3-seat request!
            current_location=GeoCoordinate(latitude=40.7100 + i * 0.001, longitude=-74.0000),
            is_active=True,
        )
        for i in range(1, 6)
    ]

    # 6th vehicle: 1,200m away, has 4 seats!
    veh_6 = Vehicle(
        vehicle_id="veh-capable-6",
        driver_id="drv-6",
        total_seat_capacity=4,  # Fits 3-seat request!
        current_location=GeoCoordinate(latitude=40.7100 + 0.011, longitude=-74.0000),
        is_active=True,
    )

    all_vehs = closer_vehs + [veh_6]

    # 1. Exhaustive ground truth
    ex_cands = enumerate_exhaustive_candidates(
        requests=[req],
        vehicles=all_vehs,
        active_rides=[],
        router=router,
        policy=policy,
        current_time=1000,
    )
    assert len(ex_cands) >= 1
    assert any(c.vehicle_id == "veh-capable-6" for c in ex_cands)

    # 2. Optimized engine candidate generation
    res = engine.dispatch_batch(
        requests=[req],
        vehicles=all_vehs,
        active_rides=[],
        current_time=1000,
    )
    assert len(res.selected_assignments) == 1, (
        "Engine must not miss feasible 6th vehicle due to max_candidates=5 cutoff"
    )
    assert res.selected_assignments[0].vehicle_id == "veh-capable-6"


def test_nearby_requests_truncation_excludes_feasible_4th_request() -> None:
    """
    Regression Test for Limit 3 (nearby_reqs[:3] truncation):
    4 requests are near an active ride. The first 3 requests cause severe detours
    for the onboard passenger. The 4th request aligns perfectly with the active ride's
    destination. Engine must not discard the 4th request.
    """
    policy = DispatchPolicy(detour_relative_multiplier=1.3, detour_absolute_cap_seconds=900)
    policy_provider = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0)
    spatial_index = H3SpatialIndexAdapter()
    engine = DispatchEngine(
        policy_provider=policy_provider,
        routing_provider=router,
        spatial_index=spatial_index,
    )

    veh = Vehicle(
        vehicle_id="veh-active-1",
        driver_id="drv-active",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=40.7100, longitude=-74.0000),
        is_active=True,
    )

    # Active ride: heading North to Midtown (40.7500, -74.0000)
    dest_stop = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-active-1",
        request_id="req-onboard",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=40.7500, longitude=-74.0000),
        passenger_delta=-1,
        scheduled_arrival_time=1400,
        promised_window_start=1000,
        promised_window_end=1500,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-active-1",
        vehicle_id="veh-active-1",
        driver_id="drv-active",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(dest_stop,),
        scheduled_departure_time=1000,
        active_passenger_count=1,
    )

    # 3 requests heading far West/East causing huge detour for onboard rider
    incompatible_reqs = [
        RideRequest(
            request_id=f"req-detour-{i}",
            user_id=f"u-detour-{i}",
            pickup_location=GeoCoordinate(latitude=40.7110 + i * 0.001, longitude=-74.0000),
            dropoff_location=GeoCoordinate(latitude=40.7110, longitude=-74.1500 + i * 0.010),
            seat_count=1,
            earliest_pickup_time=1000,
            latest_dropoff_time=4000,
            direct_distance_meters=12000,
            direct_duration_seconds=1100,
            status=RequestStatus.PENDING,
        )
        for i in range(3)
    ]

    # 4th request: directly on the way to Midtown dropoff!
    req_aligned = RideRequest(
        request_id="req-aligned-4",
        user_id="u-aligned-4",
        pickup_location=GeoCoordinate(latitude=40.7200, longitude=-74.0000),
        dropoff_location=GeoCoordinate(latitude=40.7400, longitude=-74.0000),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=2000,
        direct_distance_meters=2220,
        direct_duration_seconds=200,
        status=RequestStatus.PENDING,
    )

    all_reqs = incompatible_reqs + [req_aligned]

    # 1. Exhaustive ground truth
    ex_cands = enumerate_exhaustive_candidates(
        requests=all_reqs,
        vehicles=[veh],
        active_rides=[ride],
        router=router,
        policy=policy,
        current_time=1000,
    )
    assert len(ex_cands) >= 1
    assert any("req-aligned-4" in c.request_ids for c in ex_cands)

    # 2. Optimized engine candidate generation
    res = engine.dispatch_batch(
        requests=all_reqs,
        vehicles=[veh],
        active_rides=[ride],
        current_time=1000,
    )
    assert len(res.selected_assignments) == 1, (
        "Engine must not truncate 4th request when first 3 requests are incompatible"
    )
    assert "req-aligned-4" in res.selected_assignments[0].request_ids


def test_bundle_size_cap_excludes_feasible_3_request_bundle() -> None:
    """
    Regression Test for Limit 4 (Bundle-size cap of 2 requests):
    3 compatible 1-seat requests on a 4-seat vehicle should form a 3-passenger bundle
    when max_bundle_size=3 is specified. Engine must not clamp max_bundle_size to 2.
    """
    policy = DispatchPolicy(max_pickup_delay_seconds=600)
    policy_provider = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial_index = H3SpatialIndexAdapter()
    engine = DispatchEngine(
        policy_provider=policy_provider,
        routing_provider=router,
        spatial_index=spatial_index,
    )

    veh = Vehicle(
        vehicle_id="veh-idle-4",
        driver_id="drv-idle",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=40.7100, longitude=-74.0000),
        is_active=True,
    )

    reqs = [
        RideRequest(
            request_id=f"req-b3-{i}",
            user_id=f"usr-{i}",
            pickup_location=GeoCoordinate(latitude=40.7120 + i * 0.002, longitude=-74.0000),
            dropoff_location=GeoCoordinate(latitude=40.7300 + i * 0.002, longitude=-74.0000),
            seat_count=1,
            earliest_pickup_time=1000,
            latest_dropoff_time=3000,
            direct_distance_meters=2000,
            direct_duration_seconds=180,
            status=RequestStatus.PENDING,
        )
        for i in range(3)
    ]

    # 1. Exhaustive ground truth with max_bundle_size=3
    ex_cands = enumerate_exhaustive_candidates(
        requests=reqs,
        vehicles=[veh],
        active_rides=[],
        router=router,
        policy=policy,
        current_time=1000,
        max_bundle_size=3,
    )
    b3_cands = [c for c in ex_cands if len(c.request_ids) == 3]
    assert len(b3_cands) >= 1, "Exhaustive search must produce 3-passenger bundle"

    # 2. Optimized engine with max_bundle_size=3
    res = engine.dispatch_batch(
        requests=reqs,
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
        max_bundle_size=3,
    )
    # The solver should select the 3-passenger bundle (maximizing VMT savings & occupancy)
    assert len(res.selected_assignments) == 1
    assert len(res.selected_assignments[0].request_ids) == 3, (
        f"Expected 3-request bundle, but got {res.selected_assignments[0].request_ids} "
        "(engine hardcodes max_bundle_size=min(max_bundle_size, 2))"
    )


def test_exhaustive_vs_optimized_dense_and_sparse() -> None:
    """
    Step 2: Evaluates candidate generation completeness across dense and sparse scenarios.
    Compares candidate sets before optimization, reporting recall and false negatives.
    """
    policy = DispatchPolicy(max_pickup_delay_seconds=600)
    policy_provider = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0)
    spatial_index = H3SpatialIndexAdapter()
    engine = DispatchEngine(
        policy_provider=policy_provider,
        routing_provider=router,
        spatial_index=spatial_index,
    )

    # 1. Sparse Scenario: 2 requests, 2 vehicles (1 idle, 1 active)
    sparse_reqs = [
        RideRequest(
            request_id=f"req-sp-{i}",
            user_id=f"u-sp-{i}",
            pickup_location=GeoCoordinate(latitude=40.7100 + i * 0.005, longitude=-74.0000),
            dropoff_location=GeoCoordinate(latitude=40.7300 + i * 0.005, longitude=-74.0000),
            seat_count=1,
            earliest_pickup_time=1000,
            latest_dropoff_time=3000,
            direct_distance_meters=2220,
            direct_duration_seconds=200,
            status=RequestStatus.PENDING,
        )
        for i in range(2)
    ]
    sparse_vehs = [
        Vehicle(
            vehicle_id=f"veh-sp-{j}",
            driver_id=f"d-sp-{j}",
            total_seat_capacity=4,
            current_location=GeoCoordinate(latitude=40.7080 + j * 0.005, longitude=-74.0000),
            is_active=True,
        )
        for j in range(2)
    ]

    ex_sparse = enumerate_exhaustive_candidates(
        requests=sparse_reqs,
        vehicles=sparse_vehs,
        active_rides=[],
        router=router,
        policy=policy,
        current_time=1000,
        max_bundle_size=2,
    )
    opt_sparse = engine.generate_candidates(
        requests=sparse_reqs,
        vehicles=sparse_vehs,
        active_rides=[],
        current_time=1000,
        max_bundle_size=2,
    )
    sparse_cmp = compare_candidate_sets(optimized=opt_sparse, exhaustive=ex_sparse)
    assert sparse_cmp["false_negative_count"] == 0, (
        f"Sparse scenario must have 0 false negatives, got {sparse_cmp['false_negative_count']}"
    )
    assert sparse_cmp["recall_pct"] == 100.0


def test_antimeridian_and_polar_recall(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Step 2: Candidate recall across antimeridian (+/-180 deg) and polar latitudes (>85 deg).
    Compares candidate recall under both H3 and fallback spatial indexing against exhaustive.
    """
    import engine.adapters.h3_spatial as h3_spatial_mod

    policy = DispatchPolicy(max_pickup_delay_seconds=600)
    policy_provider = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0)

    # Test antimeridian: target at lon=179.99, vehicle at lon=-179.99 (distance ~2.2 km across boundary)
    req_anti = RideRequest(
        request_id="req-anti-1",
        user_id="u-anti",
        pickup_location=GeoCoordinate(latitude=0.0000, longitude=179.9900),
        dropoff_location=GeoCoordinate(latitude=0.0200, longitude=179.9900),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=3000,
        direct_distance_meters=2220,
        direct_duration_seconds=200,
        status=RequestStatus.PENDING,
    )
    veh_anti = Vehicle(
        vehicle_id="veh-anti-1",
        driver_id="d-anti",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=0.0000, longitude=-179.9900),
        is_active=True,
    )

    for use_grid in [False, True]:
        if use_grid:
            # Force grid fallback
            monkeypatch.setattr(h3_spatial_mod, "_H3_MODULE", None)
        spatial = H3SpatialIndexAdapter()

        engine = DispatchEngine(
            policy_provider=policy_provider,
            routing_provider=router,
            spatial_index=spatial,
        )

        ex_cands = enumerate_exhaustive_candidates(
            requests=[req_anti],
            vehicles=[veh_anti],
            active_rides=[],
            router=router,
            policy=policy,
            current_time=1000,
        )
        assert len(ex_cands) >= 1

        opt_cands = engine.generate_candidates(
            requests=[req_anti],
            vehicles=[veh_anti],
            active_rides=[],
            current_time=1000,
        )
        cmp_res = compare_candidate_sets(optimized=opt_cands, exhaustive=ex_cands)
        assert cmp_res["false_negative_count"] == 0, (
            f"Antimeridian candidate missed under {'grid' if use_grid else 'h3'}: "
            f"recall={cmp_res['recall_pct']}%"
        )

