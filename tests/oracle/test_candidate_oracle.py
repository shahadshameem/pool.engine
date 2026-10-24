"""
Tests for independent, first-principles candidate enumeration test oracle.

Verifies:
1. Oracle sensitivity: Catching intentional omissions and invalid routes in a flawed generator.
2. Idle vehicles with single and multi-passenger bundles (bundle size 2 and 3).
3. Active rides with onboard passengers and scheduled stops.
4. Overlapping capacity constraints.
5. Symmetric equal-score route orderings.
6. Geographic boundary cases (antimeridian).
7. Spatial-index failure recovery.
8. Hypothesis property-based testing against the first-principles oracle.
"""

from typing import Sequence
from hypothesis import given, settings, strategies as st
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.policy import DispatchPolicy
from engine.contracts.routing import Coordinate, RoadNetworkRoutingProvider
from engine.dispatch import CandidateGenerationConfig, DispatchEngine
from engine.domain.candidate import CandidateAssignment, ScoreBreakdown
from engine.domain.enums import RequestStatus, RideStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle
from tests.oracle.candidate_oracle import (
    IndependentCandidateOracle,
    OracleCandidateSignature,
)


def _make_req(
    req_id: str,
    p_lat: float,
    p_lon: float,
    d_lat: float,
    d_lon: float,
    seats: int = 1,
    earliest_p: int = 1000,
    latest_d: int = 3000,
    direct_dist: int = 2000,
    direct_dur: int = 180,
) -> RideRequest:
    return RideRequest(
        request_id=req_id,
        user_id=f"user-{req_id}",
        pickup_location=GeoCoordinate(latitude=p_lat, longitude=p_lon),
        dropoff_location=GeoCoordinate(latitude=d_lat, longitude=d_lon),
        seat_count=seats,
        earliest_pickup_time=earliest_p,
        latest_dropoff_time=latest_d,
        direct_distance_meters=direct_dist,
        direct_duration_seconds=direct_dur,
        status=RequestStatus.PENDING,
    )


def _make_req_exact(
    router: RoadNetworkRoutingProvider,
    req_id: str,
    p_lat: float,
    p_lon: float,
    d_lat: float,
    d_lon: float,
    seats: int = 1,
    earliest_p: int = 1000,
    latest_d: int = 5000,
) -> RideRequest:
    p_coord = Coordinate(latitude=p_lat, longitude=p_lon)
    d_coord = Coordinate(latitude=d_lat, longitude=d_lon)
    dist, dur = router.get_direct_leg(p_coord, d_coord)
    return RideRequest(
        request_id=req_id,
        user_id=f"user-{req_id}",
        pickup_location=GeoCoordinate(latitude=p_lat, longitude=p_lon),
        dropoff_location=GeoCoordinate(latitude=d_lat, longitude=d_lon),
        seat_count=seats,
        earliest_pickup_time=earliest_p,
        latest_dropoff_time=latest_d,
        direct_distance_meters=dist,
        direct_duration_seconds=dur,
        status=RequestStatus.PENDING,
    )


def _make_veh(
    veh_id: str,
    lat: float,
    lon: float,
    capacity: int = 4,
    is_active: bool = True,
) -> Vehicle:
    return Vehicle(
        vehicle_id=veh_id,
        driver_id=f"drv-{veh_id}",
        total_seat_capacity=capacity,
        current_location=GeoCoordinate(latitude=lat, longitude=lon),
        is_active=is_active,
    )


# ==============================================================================
# Requirement 7: Oracle Sensitivity Verification Against Flawed Test Generator
# ==============================================================================

def test_oracle_detects_deliberate_omissions_and_violations_in_mock_generator() -> None:
    """
    Requirement 7: Demonstrates that the independent test oracle detects:
    - Omission of reachable vehicles (false negatives)
    - Omission of valid stop permutations (false negatives)
    - Omission of valid multi-passenger bundles (false negatives)
    - Admission of capacity-violating routes (false positives)
    without modifying production code.
    """
    policy = DispatchPolicy(max_pickup_delay_seconds=600)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    oracle = IndependentCandidateOracle(router=router, policy=policy, max_bundle_size=2)

    req1 = _make_req("r1", 40.7100, -74.0000, 40.7200, -74.0000, seats=1)
    req2 = _make_req("r2", 40.7110, -74.0000, 40.7210, -74.0000, seats=1)
    veh1 = _make_veh("v1", 40.7090, -74.0000, capacity=4)
    veh2 = _make_veh("v2", 40.7080, -74.0000, capacity=4)

    # Truth from oracle:
    oracle_cands = oracle.enumerate_feasible_candidates(
        requests=[req1, req2],
        vehicles=[veh1, veh2],
        active_rides=[],
        current_time=1000,
    )
    assert len(oracle_cands) > 0

    # 1. Flaw A: Test-only generator that omits vehicle 2 completely
    flawed_a = [
        c for c in oracle_cands if c.vehicle_id != "v2"
    ]
    # Re-wrap in mock production CandidateAssignment objects
    mock_prod_a = [
        CandidateAssignment(
            candidate_id=f"c-a-{idx}",
            vehicle_id=c.vehicle_id,
            existing_ride_id=None,
            request_ids=c.request_ids,
            ordered_stops=tuple(
                RouteStop(
                    stop_id=sid,
                    ride_id="ride-flaw",
                    request_id=sid.split("-")[-1],
                    stop_type=StopType.PICKUP if "-p-" in sid else StopType.DROPOFF,
                    location=GeoCoordinate(latitude=40.7100, longitude=-74.0000),
                    passenger_delta=+1 if "-p-" in sid else -1,
                    scheduled_arrival_time=1000,
                    promised_window_start=1000,
                    promised_window_end=2000,
                    status=StopStatus.SCHEDULED,
                )
                for sid in c.ordered_stop_ids
            ),
            peak_seat_load=c.peak_occupancy,
            vmt_meters=c.total_vmt_meters,
            objective_value=0.2,
            normalized_score=0.8,
            score_breakdown=ScoreBreakdown(),
        )
        for idx, c in enumerate(flawed_a)
    ]
    res_a = oracle.compare(production_candidates=mock_prod_a, oracle_candidates=oracle_cands)
    assert len(res_a.false_negatives) > 0, "Oracle must catch omitted vehicle v2"
    assert any(fn.vehicle_id == "v2" for fn in res_a.false_negatives)
    assert res_a.recall_pct < 100.0

    # 2. Flaw B: Test-only generator that omits bundle of size 2
    flawed_b = [
        c for c in oracle_cands if len(c.request_ids) == 1
    ]
    mock_prod_b = [
        CandidateAssignment(
            candidate_id=f"c-b-{idx}",
            vehicle_id=c.vehicle_id,
            existing_ride_id=None,
            request_ids=c.request_ids,
            ordered_stops=tuple(
                RouteStop(
                    stop_id=sid,
                    ride_id="ride-flaw",
                    request_id=sid.split("-")[-1],
                    stop_type=StopType.PICKUP if "-p-" in sid else StopType.DROPOFF,
                    location=GeoCoordinate(latitude=40.7100, longitude=-74.0000),
                    passenger_delta=+1 if "-p-" in sid else -1,
                    scheduled_arrival_time=1000,
                    promised_window_start=1000,
                    promised_window_end=2000,
                    status=StopStatus.SCHEDULED,
                )
                for sid in c.ordered_stop_ids
            ),
            peak_seat_load=c.peak_occupancy,
            vmt_meters=c.total_vmt_meters,
            objective_value=0.2,
            normalized_score=0.8,
            score_breakdown=ScoreBreakdown(),
        )
        for idx, c in enumerate(flawed_b)
    ]
    res_b = oracle.compare(production_candidates=mock_prod_b, oracle_candidates=oracle_cands)
    assert len(res_b.false_negatives) > 0
    assert any(len(fn.request_ids) == 2 for fn in res_b.false_negatives), (
        "Oracle must catch omitted 2-request bundle"
    )

    # 3. Flaw C: Test-only generator that introduces an illegal route (capacity breach)
    illegal_candidate = CandidateAssignment(
        candidate_id="c-illegal",
        vehicle_id="v1",
        existing_ride_id=None,
        request_ids=("r1", "r2"),
        ordered_stops=tuple(
            RouteStop(
                stop_id=sid,
                ride_id="ride-flaw",
                request_id="r-overflow",
                stop_type=StopType.PICKUP,
                location=GeoCoordinate(latitude=40.7100, longitude=-74.0000),
                passenger_delta=+10,  # Capacity violation!
                scheduled_arrival_time=1000,
                promised_window_start=1000,
                promised_window_end=2000,
                status=StopStatus.SCHEDULED,
            )
            for sid in ("stop-overflow-1", "stop-overflow-2")
        ),
        peak_seat_load=10,
        vmt_meters=1000,
        objective_value=0.1,
        normalized_score=0.5,
        score_breakdown=ScoreBreakdown(),
    )
    res_c = oracle.compare(
        production_candidates=[illegal_candidate],
        oracle_candidates=oracle_cands,
    )
    assert len(res_c.false_positives) == 1, "Oracle must catch invalid capacity-breaching route"
    assert res_c.false_positives[0][0] == "v1"


# ==============================================================================
# Requirement 5: Comprehensive Production Verification Against Oracle
# ==============================================================================

def test_oracle_idle_vehicle_single_and_multi_request_bundles() -> None:
    """Idle vehicle with 2 requests: Oracle and Production exact mode must match 100%."""
    policy = DispatchPolicy(max_pickup_delay_seconds=600)
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial = H3SpatialIndexAdapter()

    req1 = _make_req("req-01", 40.7100, -74.0000, 40.7300, -74.0000, seats=1)
    req2 = _make_req("req-02", 40.7120, -74.0000, 40.7320, -74.0000, seats=1)
    veh = _make_veh("veh-idle-1", 40.7080, -74.0000, capacity=4)

    # 1. Oracle ground truth
    oracle = IndependentCandidateOracle(router=router, policy=policy, max_bundle_size=2)
    oracle_cands = oracle.enumerate_feasible_candidates(
        requests=[req1, req2],
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
    )
    assert len(oracle_cands) >= 3  # req1 alone, req2 alone, and bundle(req1, req2)

    # 2. Production EXACT candidate generation
    cfg_exact = CandidateGenerationConfig.exact(max_bundle_size=2)
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)
    prod_cands = engine.generate_candidates(
        requests=[req1, req2],
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
        config=cfg_exact,
    )

    cmp_res = oracle.compare(production_candidates=prod_cands, oracle_candidates=oracle_cands)
    assert cmp_res.is_perfect_match, (
        f"Mismatch between Oracle and Production! False Negatives: {cmp_res.false_negatives}, "
        f"False Positives: {cmp_res.false_positives}"
    )
    assert cmp_res.recall_pct == 100.0
    assert cmp_res.precision_pct == 100.0


def test_oracle_bundle_size_3() -> None:
    """3 compatible requests on idle 4-seat vehicle with max_bundle_size=3."""
    policy = DispatchPolicy(max_pickup_delay_seconds=600)
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial = H3SpatialIndexAdapter()

    reqs = [
        _make_req(f"r-b3-{i}", 40.7100 + i * 0.002, -74.0000, 40.7300 + i * 0.002, -74.0000, seats=1)
        for i in range(3)
    ]
    veh = _make_veh("veh-cap4", 40.7080, -74.0000, capacity=4)

    oracle = IndependentCandidateOracle(router=router, policy=policy, max_bundle_size=3)
    oracle_cands = oracle.enumerate_feasible_candidates(
        requests=reqs,
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
    )
    # Check that 3-request bundle orderings exist in oracle
    assert any(len(c.request_ids) == 3 for c in oracle_cands)

    cfg_exact = CandidateGenerationConfig.exact(max_bundle_size=3)
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)
    prod_cands = engine.generate_candidates(
        requests=reqs,
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
        config=cfg_exact,
    )

    cmp_res = oracle.compare(production_candidates=prod_cands, oracle_candidates=oracle_cands)
    assert cmp_res.is_perfect_match
    assert cmp_res.recall_pct == 100.0


def test_oracle_active_ride_with_onboard_passenger() -> None:
    """Active ride with 1 onboard passenger and 1 future dropoff."""
    policy = DispatchPolicy(max_pickup_delay_seconds=600)
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial = H3SpatialIndexAdapter()

    veh = _make_veh("veh-act-1", 40.7100, -74.0000, capacity=3)
    dropoff_stop = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-act-1",
        request_id="req-onboard",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=40.7500, longitude=-74.0000),
        passenger_delta=-1,
        scheduled_arrival_time=1500,
        promised_window_start=1000,
        promised_window_end=2000,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-act-1",
        vehicle_id="veh-act-1",
        driver_id="drv-act",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(dropoff_stop,),
        scheduled_departure_time=1000,
        active_passenger_count=1,
    )

    # req_fit needs 1 seat (1 onboard + 1 = 2 <= 3 capacity) -> Feasible
    req_fit = _make_req("req-fit", 40.7200, -74.0000, 40.7400, -74.0000, seats=1)
    # req_overflow needs 3 seats (1 onboard + 3 = 4 > 3 capacity) -> Infeasible
    req_overflow = _make_req("req-overflow", 40.7200, -74.0000, 40.7400, -74.0000, seats=3)

    oracle = IndependentCandidateOracle(router=router, policy=policy)
    oracle_cands = oracle.enumerate_feasible_candidates(
        requests=[req_fit, req_overflow],
        vehicles=[veh],
        active_rides=[ride],
        current_time=1000,
    )
    # req_overflow must NOT produce any candidate
    assert not any("req-overflow" in c.request_ids for c in oracle_cands)
    assert any("req-fit" in c.request_ids for c in oracle_cands)

    cfg_exact = CandidateGenerationConfig.exact()
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)
    prod_cands = engine.generate_candidates(
        requests=[req_fit, req_overflow],
        vehicles=[veh],
        active_rides=[ride],
        current_time=1000,
        config=cfg_exact,
    )

    cmp_res = oracle.compare(production_candidates=prod_cands, oracle_candidates=oracle_cands)
    assert cmp_res.is_perfect_match
    assert cmp_res.recall_pct == 100.0


def test_oracle_active_ride_multi_request_bundles() -> None:
    """
    Active ride with 1 onboard passenger and 2 compatible incoming requests.
    Verifies that the oracle independently enumerates both single-request insertions
    and multi-request group bundle insertions (bundle_size=2) into the active ride,
    matching production candidates with 100% recall and precision.
    """
    policy = DispatchPolicy(
        max_pickup_delay_seconds=600,
        detour_relative_multiplier=1.40,
        detour_absolute_cap_seconds=900,
    )
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial = H3SpatialIndexAdapter()

    veh = _make_veh("veh-multi-act", 40.7100, -74.0000, capacity=4)
    dropoff_stop = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-multi-act",
        request_id="req-onboard",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=40.7500, longitude=-74.0000),
        passenger_delta=-1,
        scheduled_arrival_time=1500,
        promised_window_start=1000,
        promised_window_end=2200,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-multi-act",
        vehicle_id="veh-multi-act",
        driver_id="drv-multi",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(dropoff_stop,),
        scheduled_departure_time=1000,
        active_passenger_count=1,
    )

    req1 = _make_req("req-1", 40.7200, -74.0000, 40.7350, -74.0000, seats=1, earliest_p=1000)
    req2 = _make_req("req-2", 40.7250, -74.0000, 40.7400, -74.0000, seats=1, earliest_p=1020)

    oracle = IndependentCandidateOracle(router=router, policy=policy, max_bundle_size=2)
    oracle_cands = oracle.enumerate_feasible_candidates(
        requests=[req1, req2],
        vehicles=[veh],
        active_rides=[ride],
        current_time=1000,
    )

    # Must contain both single-request insertions and multi-request bundles
    oracle_single = [c for c in oracle_cands if len(c.request_ids) == 1]
    oracle_bundle = [c for c in oracle_cands if len(c.request_ids) == 2]
    assert len(oracle_single) >= 2, "Oracle must enumerate single-request insertions"
    assert len(oracle_bundle) >= 1, "Oracle must enumerate multi-request bundle insertions"

    cfg_exact = CandidateGenerationConfig.exact(max_bundle_size=2)
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)
    prod_cands = engine.generate_candidates(
        requests=[req1, req2],
        vehicles=[veh],
        active_rides=[ride],
        current_time=1000,
        config=cfg_exact,
    )

    cmp_res = oracle.compare(production_candidates=prod_cands, oracle_candidates=oracle_cands)
    assert cmp_res.is_perfect_match, (
        f"Multi-request active ride candidate mismatch!\n"
        f"  Oracle count: {cmp_res.oracle_count}, Production count: {cmp_res.production_count}\n"
        f"  False Negatives: {cmp_res.false_negatives}\n"
        f"  False Positives: {cmp_res.false_positives}"
    )
    assert cmp_res.recall_pct == 100.0
    assert cmp_res.precision_pct == 100.0


def test_oracle_overlapping_capacity_constraints() -> None:
    """
    Overlapping capacity: Two 2-seat requests on a 3-seat vehicle.
    Any route ordering where both passengers are onboard simultaneously requires 2 + 2 = 4 seats (> 3)
    and must be pruned by the capacity invariant.
    Only sequential orderings where one passenger is dropped off before the other boards can be feasible.
    Oracle and production must both reject all overlapping routes and match 100%.
    """
    policy = DispatchPolicy(max_pickup_delay_seconds=600)
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial = H3SpatialIndexAdapter()

    # Two requests needing 2 seats each
    r1 = _make_req("r1-2seat", 40.7100, -74.0000, 40.7300, -74.0000, seats=2)
    r2 = _make_req("r2-2seat", 40.7120, -74.0000, 40.7320, -74.0000, seats=2)
    # Vehicle has only 3 seats
    veh = _make_veh("veh-3seat", 40.7080, -74.0000, capacity=3)

    oracle = IndependentCandidateOracle(router=router, policy=policy, max_bundle_size=2)
    oracle_cands = oracle.enumerate_feasible_candidates(
        requests=[r1, r2],
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
    )
    # Both individual single-request bundles are feasible (2 <= 3)
    assert any(c.request_ids == ("r1-2seat",) for c in oracle_cands)
    assert any(c.request_ids == ("r2-2seat",) for c in oracle_cands)

    # For 2-request bundles: ALL overlapping orderings (where both passengers are onboard, peak=4)
    # MUST be rejected. Only sequential non-overlapping orderings (peak=2 <= 3) may survive.
    bundle2_cands = [c for c in oracle_cands if len(c.request_ids) == 2]
    for c in bundle2_cands:
        assert c.peak_occupancy <= 3, "Overlapping capacity violation admitted in oracle!"
        # In ordered_stop_ids, dropoff of first request must precede pickup of second request
        first_p = c.ordered_stop_ids[0]
        first_d = c.ordered_stop_ids[1]
        assert "-p-" in first_p and "-d-" in first_d, (
            "Overlapping route ordering was not pruned: first passenger was not dropped off before second boarded!"
        )

    cfg_exact = CandidateGenerationConfig.exact(max_bundle_size=2)
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)
    prod_cands = engine.generate_candidates(
        requests=[r1, r2],
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
        config=cfg_exact,
    )

    cmp_res = oracle.compare(production_candidates=prod_cands, oracle_candidates=oracle_cands)
    assert cmp_res.is_perfect_match
    assert cmp_res.recall_pct == 100.0


def test_oracle_symmetric_equal_score_routes() -> None:
    """Symmetric route itineraries yielding equal distances: Oracle and production enumerate both."""
    policy = DispatchPolicy(max_pickup_delay_seconds=600)
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial = H3SpatialIndexAdapter()

    # Perfectly symmetric coordinates on a grid relative to vehicle
    r1 = _make_req("r-sym-1", 40.7100, -74.0000, 40.7200, -74.0000, seats=1)
    r2 = _make_req("r-sym-2", 40.7100, -74.0100, 40.7200, -74.0100, seats=1)
    veh = _make_veh("veh-sym", 40.7000, -74.0050, capacity=4)

    oracle = IndependentCandidateOracle(router=router, policy=policy, max_bundle_size=2)
    oracle_cands = oracle.enumerate_feasible_candidates(
        requests=[r1, r2],
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
    )

    cfg_exact = CandidateGenerationConfig.exact(max_bundle_size=2)
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)
    prod_cands = engine.generate_candidates(
        requests=[r1, r2],
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
        config=cfg_exact,
    )

    cmp_res = oracle.compare(production_candidates=prod_cands, oracle_candidates=oracle_cands)
    assert cmp_res.is_perfect_match
    assert cmp_res.recall_pct == 100.0


def test_oracle_geographic_boundary_antimeridian() -> None:
    """Antimeridian boundary: Request at +179.99, vehicle at -179.99."""
    policy = DispatchPolicy(max_pickup_delay_seconds=600)
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial = H3SpatialIndexAdapter()

    req = _make_req("r-anti", 0.0000, 179.9900, 0.0200, 179.9900, seats=1)
    veh = _make_veh("v-anti", 0.0000, -179.9900, capacity=4)

    oracle = IndependentCandidateOracle(router=router, policy=policy, max_bundle_size=1)
    oracle_cands = oracle.enumerate_feasible_candidates(
        requests=[req],
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
    )
    assert len(oracle_cands) == 1

    cfg_exact = CandidateGenerationConfig.exact(max_bundle_size=1)
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)
    prod_cands = engine.generate_candidates(
        requests=[req],
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
        config=cfg_exact,
    )

    cmp_res = oracle.compare(production_candidates=prod_cands, oracle_candidates=oracle_cands)
    assert cmp_res.is_perfect_match
    assert cmp_res.recall_pct == 100.0


def test_oracle_spatial_index_traversal_failure_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Simulated H3 traversal failure: Oracle proves production's exhaustive fallback
    recovers 100% of candidate routes without false negatives.
    """
    import engine.adapters.h3_spatial as h3_module

    policy = DispatchPolicy(max_pickup_delay_seconds=600)
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial = H3SpatialIndexAdapter()

    # Veh 1 is close, Veh 2 is further out (~2 km)
    req = _make_req("r-fail", 40.7100, -74.0000, 40.7300, -74.0000, seats=1)
    v1 = _make_veh("v-close", 40.7110, -74.0000, capacity=4)
    v2 = _make_veh("v-outer", 40.7250, -74.0000, capacity=4)

    # Truth according to oracle
    oracle = IndependentCandidateOracle(router=router, policy=policy, max_bundle_size=1)
    oracle_cands = oracle.enumerate_feasible_candidates(
        requests=[req],
        vehicles=[v1, v2],
        active_rides=[],
        current_time=1000,
    )
    assert len(oracle_cands) == 2

    # Simulate H3 native module error on outer rings
    class FailingH3:
        def latlng_to_cell(self, lat: float, lng: float, res: int) -> str:
            return "882a100d2bffff"

        def grid_ring(self, cell: str, k: int) -> list[str]:
            if k == 0:
                return [cell]
            raise RuntimeError(f"H3 pentagon error at k={k}")

        def grid_disk(self, cell: str, k: int) -> list[str]:
            if k == 0:
                return [cell]
            raise RuntimeError(f"H3 grid disk failed at k={k}")

    monkeypatch.setattr(h3_module, "_H3_MODULE", FailingH3())

    cfg_exact = CandidateGenerationConfig.exact(max_bundle_size=1)
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)
    prod_cands = engine.generate_candidates(
        requests=[req],
        vehicles=[v1, v2],
        active_rides=[],
        current_time=1000,
        config=cfg_exact,
    )

    cmp_res = oracle.compare(production_candidates=prod_cands, oracle_candidates=oracle_cands)
    assert cmp_res.is_perfect_match, (
        f"Production failed to recover candidates via fallback: {cmp_res.false_negatives}"
    )
    assert cmp_res.recall_pct == 100.0


# ==============================================================================
# Requirement 5: Deterministic Regression Boundary Tests
# ==============================================================================

def test_oracle_boundary_pickup_delay_exact_and_breach() -> None:
    """
    Deterministic boundary test for pickup delay:
    1. Exact boundary: arrival at pickup == earliest_pickup + max_delay (admitted).
    2. Boundary breach: arrival at pickup == earliest_pickup + max_delay + 1s (pruned).
    3. Early arrival: arrival at pickup < earliest_pickup (admitted, driver waits).
    """
    policy = DispatchPolicy(max_pickup_delay_seconds=300)
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial = H3SpatialIndexAdapter()
    oracle = IndependentCandidateOracle(router=router, policy=policy, max_bundle_size=1)
    cfg_exact = CandidateGenerationConfig.exact(max_bundle_size=1)
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)

    v_coord = Coordinate(latitude=40.7000, longitude=-74.0000)
    p_coord = Coordinate(latitude=40.7100, longitude=-74.0000)
    _, leg_dur = router.get_direct_leg(v_coord, p_coord)
    t_start = 1000
    t_arrival = t_start + leg_dur

    veh = _make_veh("veh-boundary", 40.7000, -74.0000, capacity=4)

    # Case 1: Exact boundary (arrival - earliest_p == max_delay)
    earliest_p_exact = t_arrival - policy.max_pickup_delay_seconds
    req_exact = _make_req_exact(
        router, "req-exact", 40.7100, -74.0000, 40.7200, -74.0000, earliest_p=earliest_p_exact
    )
    cands_oracle_exact = oracle.enumerate_feasible_candidates([req_exact], [veh], [], t_start)
    cands_prod_exact = engine.generate_candidates([req_exact], [veh], [], t_start, config=cfg_exact)
    cmp_exact = oracle.compare(cands_prod_exact, cands_oracle_exact)
    assert cmp_exact.is_perfect_match and cmp_exact.oracle_count == 1, (
        f"Exact boundary failed: false negatives {cmp_exact.false_negatives}"
    )

    # Case 2: Breach by 1 second (arrival - earliest_p == max_delay + 1)
    earliest_p_breach = earliest_p_exact - 1
    req_breach = _make_req_exact(
        router, "req-breach", 40.7100, -74.0000, 40.7200, -74.0000, earliest_p=earliest_p_breach
    )
    cands_oracle_breach = oracle.enumerate_feasible_candidates([req_breach], [veh], [], t_start)
    cands_prod_breach = engine.generate_candidates([req_breach], [veh], [], t_start, config=cfg_exact)
    cmp_breach = oracle.compare(cands_prod_breach, cands_oracle_breach)
    assert cmp_breach.is_perfect_match and cmp_breach.oracle_count == 0, (
        f"Breached candidate admitted: {cands_prod_breach}"
    )

    # Case 3: Early arrival (vehicle arrives before earliest_p; delay = 0)
    earliest_p_early = t_arrival + 200
    req_early = _make_req_exact(
        router, "req-early", 40.7100, -74.0000, 40.7200, -74.0000, earliest_p=earliest_p_early
    )
    cands_oracle_early = oracle.enumerate_feasible_candidates([req_early], [veh], [], t_start)
    cands_prod_early = engine.generate_candidates([req_early], [veh], [], t_start, config=cfg_exact)
    cmp_early = oracle.compare(cands_prod_early, cands_oracle_early)
    assert cmp_early.is_perfect_match and cmp_early.oracle_count == 1


def test_oracle_boundary_detour_relative_and_absolute() -> None:
    """
    Deterministic boundary test for passenger detour constraints:
    1. Relative multiplier boundary: detour == (alpha - 1.0) * direct_dur (admitted) vs > (pruned).
    2. Absolute cap boundary: detour == C (admitted) vs > C (pruned).
    """
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial = H3SpatialIndexAdapter()
    veh = _make_veh("veh-detour", 40.7000, -74.0000, capacity=4)

    r1 = _make_req_exact(router, "r1", 40.7020, -74.0000, 40.7200, -74.0000, earliest_p=1000)
    r2 = _make_req_exact(router, "r2", 40.7080, -74.0150, 40.7150, -74.0150, earliest_p=1000)

    # Measure detour of r1 in bundle [P1, P2, D2, D1]
    w = [
        Coordinate(veh.current_location.latitude, veh.current_location.longitude),
        Coordinate(r1.pickup_location.latitude, r1.pickup_location.longitude),
        Coordinate(r2.pickup_location.latitude, r2.pickup_location.longitude),
        Coordinate(r2.dropoff_location.latitude, r2.dropoff_location.longitude),
        Coordinate(r1.dropoff_location.latitude, r1.dropoff_location.longitude),
    ]
    clock = 1000
    times: dict[str, int] = {}
    for i in range(len(w) - 1):
        _, dur = router.get_direct_leg(w[i], w[i + 1])
        clock += dur
        times[f"stop_{i}"] = clock
    p1_time = times["stop_0"]
    d1_time = times["stop_3"]
    actual_in_veh = d1_time - p1_time
    detour_r1 = actual_in_veh - r1.direct_duration_seconds
    assert detour_r1 > 0, "Bundle must induce a positive detour for r1"

    # Part A: Relative multiplier boundary
    alpha_exact = 1.0 + (float(detour_r1) / float(r1.direct_duration_seconds))

    policy_admit = DispatchPolicy(
        max_pickup_delay_seconds=600,
        detour_relative_multiplier=alpha_exact + 0.005,
        detour_absolute_cap_seconds=2000,
    )
    oracle_admit = IndependentCandidateOracle(router, policy_admit, max_bundle_size=2)
    engine_admit = DispatchEngine(
        DefaultPolicyProvider(policy_admit),
        router,
        spatial,
        config=CandidateGenerationConfig.exact(2),
    )
    c_o_admit = oracle_admit.enumerate_feasible_candidates([r1, r2], [veh], [], 1000)
    c_p_admit = engine_admit.generate_candidates([r1, r2], [veh], [], 1000, config=CandidateGenerationConfig.exact(2))
    cmp_admit = oracle_admit.compare(c_p_admit, c_o_admit)
    assert cmp_admit.is_perfect_match
    assert any(c.ordered_stop_ids == ("stop-p-r1", "stop-p-r2", "stop-d-r2", "stop-d-r1") for c in c_o_admit)

    policy_prune = DispatchPolicy(
        max_pickup_delay_seconds=600,
        detour_relative_multiplier=alpha_exact - 0.05,
        detour_absolute_cap_seconds=2000,
    )
    oracle_prune = IndependentCandidateOracle(router, policy_prune, max_bundle_size=2)
    engine_prune = DispatchEngine(
        DefaultPolicyProvider(policy_prune),
        router,
        spatial,
        config=CandidateGenerationConfig.exact(2),
    )
    c_o_prune = oracle_prune.enumerate_feasible_candidates([r1, r2], [veh], [], 1000)
    c_p_prune = engine_prune.generate_candidates([r1, r2], [veh], [], 1000, config=CandidateGenerationConfig.exact(2))
    cmp_prune = oracle_prune.compare(c_p_prune, c_o_prune)
    assert cmp_prune.is_perfect_match
    assert not any(c.ordered_stop_ids == ("stop-p-r1", "stop-p-r2", "stop-d-r2", "stop-d-r1") for c in c_o_prune)

    # Part B: Absolute cap boundary
    policy_cap_admit = DispatchPolicy(
        max_pickup_delay_seconds=600,
        detour_relative_multiplier=3.0,
        detour_absolute_cap_seconds=detour_r1 + 5,
    )
    oracle_cap_admit = IndependentCandidateOracle(router, policy_cap_admit, max_bundle_size=2)
    engine_cap_admit = DispatchEngine(
        DefaultPolicyProvider(policy_cap_admit),
        router,
        spatial,
        config=CandidateGenerationConfig.exact(2),
    )
    c_o_cap_admit = oracle_cap_admit.enumerate_feasible_candidates([r1, r2], [veh], [], 1000)
    c_p_cap_admit = engine_cap_admit.generate_candidates([r1, r2], [veh], [], 1000, config=CandidateGenerationConfig.exact(2))
    cmp_cap_admit = oracle_cap_admit.compare(c_p_cap_admit, c_o_cap_admit)
    assert cmp_cap_admit.is_perfect_match
    assert any(c.ordered_stop_ids == ("stop-p-r1", "stop-p-r2", "stop-d-r2", "stop-d-r1") for c in c_o_cap_admit)

    policy_cap_prune = DispatchPolicy(
        max_pickup_delay_seconds=600,
        detour_relative_multiplier=3.0,
        detour_absolute_cap_seconds=detour_r1 - 5,
    )
    oracle_cap_prune = IndependentCandidateOracle(router, policy_cap_prune, max_bundle_size=2)
    engine_cap_prune = DispatchEngine(
        DefaultPolicyProvider(policy_cap_prune),
        router,
        spatial,
        config=CandidateGenerationConfig.exact(2),
    )
    c_o_cap_prune = oracle_cap_prune.enumerate_feasible_candidates([r1, r2], [veh], [], 1000)
    c_p_cap_prune = engine_cap_prune.generate_candidates([r1, r2], [veh], [], 1000, config=CandidateGenerationConfig.exact(2))
    cmp_cap_prune = oracle_cap_prune.compare(c_p_cap_prune, c_o_cap_prune)
    assert cmp_cap_prune.is_perfect_match
    assert not any(c.ordered_stop_ids == ("stop-p-r1", "stop-p-r2", "stop-d-r2", "stop-d-r1") for c in c_o_cap_prune)


def test_oracle_boundary_active_ride_dropoff_promise() -> None:
    """
    Deterministic boundary test for active ride dropoff promise windows:
    1. If new request inserted before existing dropoff delays arrival past
       promised_window_end, that insertion position is pruned.
    2. If promised_window_end is wide enough, insertion before existing dropoff is admitted.
    """
    policy = DispatchPolicy(max_pickup_delay_seconds=600)
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial = H3SpatialIndexAdapter()
    veh = _make_veh("veh-act-promise", 40.7000, -74.0000, capacity=4)

    v_coord = Coordinate(40.7000, -74.0000)
    d_coord = Coordinate(40.7200, -74.0000)
    _, direct_dur = router.get_direct_leg(v_coord, d_coord)
    direct_arrival = 1000 + direct_dur

    req = _make_req_exact(router, "req-inc", 40.7050, -74.0050, 40.7150, -74.0050, earliest_p=1000)

    # Tight promise window
    dropoff_tight = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-promise-tight",
        request_id="req-onboard",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=40.7200, longitude=-74.0000),
        passenger_delta=-1,
        scheduled_arrival_time=direct_arrival,
        promised_window_start=1000,
        promised_window_end=direct_arrival + 10,
        status=StopStatus.SCHEDULED,
    )
    ride_tight = Ride(
        ride_id="ride-promise-tight",
        vehicle_id="veh-act-promise",
        driver_id="drv-act",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(dropoff_tight,),
        scheduled_departure_time=1000,
        active_passenger_count=1,
    )

    oracle = IndependentCandidateOracle(router, policy)
    engine = DispatchEngine(policy_prov, router, spatial, config=CandidateGenerationConfig.exact())

    c_o_tight = oracle.enumerate_feasible_candidates([req], [veh], [ride_tight], 1000)
    c_p_tight = engine.generate_candidates([req], [veh], [ride_tight], 1000, config=CandidateGenerationConfig.exact())
    cmp_tight = oracle.compare(c_p_tight, c_o_tight)
    assert cmp_tight.is_perfect_match
    assert not any(
        c.ordered_stop_ids == ("stop-p-req-inc", "stop-d-req-inc", "stop-d-onboard")
        for c in c_o_tight
    )

    # Loose promise window
    dropoff_loose = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-promise-loose",
        request_id="req-onboard",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=40.7200, longitude=-74.0000),
        passenger_delta=-1,
        scheduled_arrival_time=direct_arrival,
        promised_window_start=1000,
        promised_window_end=direct_arrival + 2000,
        status=StopStatus.SCHEDULED,
    )
    ride_loose = Ride(
        ride_id="ride-promise-loose",
        vehicle_id="veh-act-promise",
        driver_id="drv-act",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(dropoff_loose,),
        scheduled_departure_time=1000,
        active_passenger_count=1,
    )
    c_o_loose = oracle.enumerate_feasible_candidates([req], [veh], [ride_loose], 1000)
    c_p_loose = engine.generate_candidates([req], [veh], [ride_loose], 1000, config=CandidateGenerationConfig.exact())
    cmp_loose = oracle.compare(c_p_loose, c_o_loose)
    assert cmp_loose.is_perfect_match
    assert any(
        c.ordered_stop_ids == ("stop-p-req-inc", "stop-d-req-inc", "stop-d-onboard")
        for c in c_o_loose
    )


def test_oracle_boundary_capacity_and_sequence_exhaustion() -> None:
    """
    Deterministic boundary test for vehicle capacity saturation and stop ordering:
    1. Saturated vehicle (2+2 on 4-seat): overlapping sequence peak load = 4 admitted.
    2. Over-capacity vehicle (2+2 on 3-seat): overlapping pruned (peak 4 > 3), sequential admitted (peak 2 <= 3).
    3. Exceeds capacity singly (4-seat request on 3-seat vehicle): 0 candidates generated.
    """
    policy = DispatchPolicy(max_pickup_delay_seconds=600)
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial = H3SpatialIndexAdapter()

    r1 = _make_req_exact(router, "r1", 40.7100, -74.0000, 40.7300, -74.0000, seats=2, earliest_p=1000)
    r2 = _make_req_exact(router, "r2", 40.7120, -74.0000, 40.7320, -74.0000, seats=2, earliest_p=1000)

    # 1. 4-seat vehicle: peak load 4 <= 4 admitted
    veh4 = _make_veh("veh-4", 40.7080, -74.0000, capacity=4)
    oracle4 = IndependentCandidateOracle(router, policy, max_bundle_size=2)
    engine4 = DispatchEngine(policy_prov, router, spatial, config=CandidateGenerationConfig.exact(2))
    c_o4 = oracle4.enumerate_feasible_candidates([r1, r2], [veh4], [], 1000)
    c_p4 = engine4.generate_candidates([r1, r2], [veh4], [], 1000, config=CandidateGenerationConfig.exact(2))
    cmp4 = oracle4.compare(c_p4, c_o4)
    assert cmp4.is_perfect_match
    assert any(
        c.ordered_stop_ids == ("stop-p-r1", "stop-p-r2", "stop-d-r1", "stop-d-r2")
        for c in c_o4
    )

    # 2. 3-seat vehicle: peak load 4 > 3 pruned; sequential peak load 2 <= 3 admitted
    veh3 = _make_veh("veh-3", 40.7080, -74.0000, capacity=3)
    oracle3 = IndependentCandidateOracle(router, policy, max_bundle_size=2)
    engine3 = DispatchEngine(policy_prov, router, spatial, config=CandidateGenerationConfig.exact(2))
    c_o3 = oracle3.enumerate_feasible_candidates([r1, r2], [veh3], [], 1000)
    c_p3 = engine3.generate_candidates([r1, r2], [veh3], [], 1000, config=CandidateGenerationConfig.exact(2))
    cmp3 = oracle3.compare(c_p3, c_o3)
    assert cmp3.is_perfect_match
    assert not any(
        c.ordered_stop_ids == ("stop-p-r1", "stop-p-r2", "stop-d-r1", "stop-d-r2")
        for c in c_o3
    )
    assert any(
        c.ordered_stop_ids == ("stop-p-r1", "stop-d-r1", "stop-p-r2", "stop-d-r2")
        for c in c_o3
    )

    # 3. Request 4 seats on 3-seat vehicle: zero candidates
    r_big = _make_req_exact(router, "r-big", 40.7100, -74.0000, 40.7300, -74.0000, seats=4, earliest_p=1000)
    c_o_big = oracle3.enumerate_feasible_candidates([r_big], [veh3], [], 1000)
    c_p_big = engine3.generate_candidates([r_big], [veh3], [], 1000, config=CandidateGenerationConfig.exact(2))
    cmp_big = oracle3.compare(c_p_big, c_o_big)
    assert cmp_big.is_perfect_match and cmp_big.oracle_count == 0


# ==============================================================================
# Requirement 6: Expanded Property-Based Verification with Hypothesis
# ==============================================================================

@settings(max_examples=30, deadline=None)
@given(
    d_lat1=st.floats(min_value=-0.012, max_value=0.012),
    d_lon1=st.floats(min_value=-0.012, max_value=0.012),
    d_lat2=st.floats(min_value=-0.012, max_value=0.012),
    d_lon2=st.floats(min_value=-0.012, max_value=0.012),
    earliest_p1=st.integers(min_value=800, max_value=1300),
    earliest_p2=st.integers(min_value=800, max_value=1300),
    max_pickup_delay=st.sampled_from([180, 300, 600, 900]),
    detour_multiplier=st.sampled_from([1.15, 1.25, 1.35, 1.60]),
    detour_cap=st.sampled_from([300, 600, 1200]),
    seat1=st.integers(min_value=1, max_value=2),
    seat2=st.integers(min_value=1, max_value=2),
    v_cap=st.integers(min_value=2, max_value=4),
)
def test_oracle_property_idle_bundles_timing_and_detour(
    d_lat1: float,
    d_lon1: float,
    d_lat2: float,
    d_lon2: float,
    earliest_p1: int,
    earliest_p2: int,
    max_pickup_delay: int,
    detour_multiplier: float,
    detour_cap: int,
    seat1: int,
    seat2: int,
    v_cap: int,
) -> None:
    """
    Property-based testing covering multi-request idle bundles with randomized
    request timing (pickup availability), detour policies (alpha, cap, max delay),
    geographic positions, and seat capacities.
    """
    policy = DispatchPolicy(
        max_pickup_delay_seconds=max_pickup_delay,
        detour_relative_multiplier=detour_multiplier,
        detour_absolute_cap_seconds=detour_cap,
    )
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial = H3SpatialIndexAdapter()

    base_lat, base_lon = 40.7100, -74.0000
    r1 = _make_req_exact(
        router,
        "req-p1",
        base_lat + d_lat1,
        base_lon + d_lon1,
        base_lat + d_lat1 + 0.010,
        base_lon + d_lon1,
        seats=seat1,
        earliest_p=earliest_p1,
    )
    r2 = _make_req_exact(
        router,
        "req-p2",
        base_lat + d_lat2,
        base_lon + d_lon2,
        base_lat + d_lat2 + 0.010,
        base_lon + d_lon2,
        seats=seat2,
        earliest_p=earliest_p2,
    )
    veh = _make_veh("veh-prop-idle", base_lat, base_lon, capacity=v_cap)

    oracle = IndependentCandidateOracle(router=router, policy=policy, max_bundle_size=2)
    oracle_cands = oracle.enumerate_feasible_candidates(
        requests=[r1, r2],
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
    )

    cfg_exact = CandidateGenerationConfig.exact(max_bundle_size=2)
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)
    prod_cands = engine.generate_candidates(
        requests=[r1, r2],
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
        config=cfg_exact,
    )

    cmp_res = oracle.compare(production_candidates=prod_cands, oracle_candidates=oracle_cands)
    assert cmp_res.is_perfect_match, (
        f"Idle bundles property mismatch!\n"
        f"  Oracle count: {cmp_res.oracle_count}, Production count: {cmp_res.production_count}\n"
        f"  False Negatives: {cmp_res.false_negatives}\n"
        f"  False Positives: {cmp_res.false_positives}\n"
        f"  Policy: max_delay={max_pickup_delay}, alpha={detour_multiplier}, cap={detour_cap}\n"
        f"  Req1: p={earliest_p1}, seats={seat1} | Req2: p={earliest_p2}, seats={seat2} | Cap={v_cap}"
    )


@settings(max_examples=30, deadline=None)
@given(
    onboard_seats=st.integers(min_value=0, max_value=2),
    req_seats=st.integers(min_value=1, max_value=2),
    v_cap=st.integers(min_value=3, max_value=4),
    req_lat_off=st.floats(min_value=-0.008, max_value=0.008),
    req_lon_off=st.floats(min_value=-0.008, max_value=0.008),
    req_earliest_p=st.integers(min_value=850, max_value=1250),
    promised_window_slack=st.sampled_from([25, 100, 300, 1000]),
    max_pickup_delay=st.sampled_from([240, 480, 720]),
    detour_multiplier=st.sampled_from([1.20, 1.40, 1.70]),
    detour_cap=st.sampled_from([300, 600, 900]),
)
def test_oracle_property_active_ride_insertions(
    onboard_seats: int,
    req_seats: int,
    v_cap: int,
    req_lat_off: float,
    req_lon_off: float,
    req_earliest_p: int,
    promised_window_slack: int,
    max_pickup_delay: int,
    detour_multiplier: float,
    detour_cap: int,
) -> None:
    """
    Property-based testing covering active-ride single-request insertions with
    varied onboard passenger loads, pending dropoffs, promised window slack,
    incoming request seats, pickup timing, and detour policies.
    """
    policy = DispatchPolicy(
        max_pickup_delay_seconds=max_pickup_delay,
        detour_relative_multiplier=detour_multiplier,
        detour_absolute_cap_seconds=detour_cap,
    )
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial = H3SpatialIndexAdapter()

    base_lat, base_lon = 40.7100, -74.0000
    veh = _make_veh("veh-prop-act", base_lat, base_lon, capacity=v_cap)

    t_start = 1000
    v_loc = Coordinate(base_lat, base_lon)

    if onboard_seats > 0:
        drop_loc = Coordinate(base_lat + 0.020, base_lon)
        _, drop_dur = router.get_direct_leg(v_loc, drop_loc)
        sched_arr = t_start + drop_dur
        drop_stop = RouteStop(
            stop_id="stop-d-onboard",
            ride_id="ride-prop-act",
            request_id="req-onboard",
            stop_type=StopType.DROPOFF,
            location=GeoCoordinate(latitude=drop_loc.latitude, longitude=drop_loc.longitude),
            passenger_delta=-onboard_seats,
            scheduled_arrival_time=sched_arr,
            promised_window_start=t_start,
            promised_window_end=sched_arr + promised_window_slack,
            status=StopStatus.SCHEDULED,
        )
        ride = Ride(
            ride_id="ride-prop-act",
            vehicle_id="veh-prop-act",
            driver_id="drv-prop",
            lifecycle_status=RideStatus.ACTIVE,
            stops=(drop_stop,),
            scheduled_departure_time=t_start,
            active_passenger_count=onboard_seats,
        )
    else:
        p_loc = Coordinate(base_lat + 0.010, base_lon)
        d_loc = Coordinate(base_lat + 0.025, base_lon)
        _, p_dur = router.get_direct_leg(v_loc, p_loc)
        _, d_dur = router.get_direct_leg(p_loc, d_loc)
        p_arr = t_start + p_dur
        d_arr = p_arr + d_dur
        p_stop = RouteStop(
            stop_id="stop-p-sched",
            ride_id="ride-prop-act",
            request_id="req-sched",
            stop_type=StopType.PICKUP,
            location=GeoCoordinate(latitude=p_loc.latitude, longitude=p_loc.longitude),
            passenger_delta=+1,
            scheduled_arrival_time=p_arr,
            promised_window_start=p_arr,
            promised_window_end=p_arr + max_pickup_delay,
            status=StopStatus.SCHEDULED,
        )
        d_stop = RouteStop(
            stop_id="stop-d-sched",
            ride_id="ride-prop-act",
            request_id="req-sched",
            stop_type=StopType.DROPOFF,
            location=GeoCoordinate(latitude=d_loc.latitude, longitude=d_loc.longitude),
            passenger_delta=-1,
            scheduled_arrival_time=d_arr,
            promised_window_start=p_arr,
            promised_window_end=d_arr + promised_window_slack,
            status=StopStatus.SCHEDULED,
        )
        ride = Ride(
            ride_id="ride-prop-act",
            vehicle_id="veh-prop-act",
            driver_id="drv-prop",
            lifecycle_status=RideStatus.ACTIVE,
            stops=(p_stop, d_stop),
            scheduled_departure_time=t_start,
            active_passenger_count=0,
        )

    # Incoming request
    req = _make_req_exact(
        router,
        "req-inc",
        base_lat + req_lat_off,
        base_lon + req_lon_off,
        base_lat + req_lat_off + 0.015,
        base_lon + req_lon_off,
        seats=req_seats,
        earliest_p=req_earliest_p,
    )

    oracle = IndependentCandidateOracle(router=router, policy=policy, max_bundle_size=1)
    oracle_cands = oracle.enumerate_feasible_candidates(
        requests=[req],
        vehicles=[veh],
        active_rides=[ride],
        current_time=t_start,
    )

    cfg_exact = CandidateGenerationConfig.exact()
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)
    prod_cands = engine.generate_candidates(
        requests=[req],
        vehicles=[veh],
        active_rides=[ride],
        current_time=t_start,
        config=cfg_exact,
    )

    cmp_res = oracle.compare(production_candidates=prod_cands, oracle_candidates=oracle_cands)
    assert cmp_res.is_perfect_match, (
        f"Active ride property mismatch!\n"
        f"  Oracle count: {cmp_res.oracle_count}, Production count: {cmp_res.production_count}\n"
        f"  False Negatives: {cmp_res.false_negatives}\n"
        f"  False Positives: {cmp_res.false_positives}\n"
        f"  Onboard: {onboard_seats}, ReqSeats: {req_seats}, Capacity: {v_cap}\n"
        f"  Slack: {promised_window_slack}, DelayCap: {max_pickup_delay}, Alpha: {detour_multiplier}\n"
        f"  Incoming Req earliest_p: {req_earliest_p}"
    )


@settings(max_examples=25, deadline=None)
@given(
    seat1=st.integers(min_value=1, max_value=3),
    seat2=st.integers(min_value=1, max_value=3),
    seat3=st.integers(min_value=1, max_value=3),
    v_cap=st.integers(min_value=2, max_value=4),
    max_bundle_size=st.sampled_from([2, 3]),
)
def test_oracle_property_capacity_and_sequence_permutations(
    seat1: int,
    seat2: int,
    seat3: int,
    v_cap: int,
    max_bundle_size: int,
) -> None:
    """
    Property-based testing covering multi-request capacity interactions and stop sequence
    orderings: verifies that sequential vs overlapping routes are admitted or pruned
    identically across 3 requests with varied seat requests and vehicle capacity.
    """
    policy = DispatchPolicy(max_pickup_delay_seconds=600)
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial = H3SpatialIndexAdapter()

    base_lat, base_lon = 40.7100, -74.0000
    r1 = _make_req_exact(router, "r1", base_lat + 0.002, base_lon, base_lat + 0.015, base_lon, seats=seat1, earliest_p=1000)
    r2 = _make_req_exact(router, "r2", base_lat + 0.005, base_lon, base_lat + 0.018, base_lon, seats=seat2, earliest_p=1020)
    r3 = _make_req_exact(router, "r3", base_lat + 0.008, base_lon, base_lat + 0.022, base_lon, seats=seat3, earliest_p=1040)
    veh = _make_veh("veh-prop-seq", base_lat, base_lon, capacity=v_cap)

    oracle = IndependentCandidateOracle(router=router, policy=policy, max_bundle_size=max_bundle_size)
    oracle_cands = oracle.enumerate_feasible_candidates(
        requests=[r1, r2, r3],
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
    )

    cfg_exact = CandidateGenerationConfig.exact(max_bundle_size=max_bundle_size)
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)
    prod_cands = engine.generate_candidates(
        requests=[r1, r2, r3],
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
        config=cfg_exact,
    )

    cmp_res = oracle.compare(production_candidates=prod_cands, oracle_candidates=oracle_cands)
    assert cmp_res.is_perfect_match, (
        f"Capacity and sequence property mismatch!\n"
        f"  Oracle count: {cmp_res.oracle_count}, Production count: {cmp_res.production_count}\n"
        f"  False Negatives: {cmp_res.false_negatives}\n"
        f"  False Positives: {cmp_res.false_positives}\n"
        f"  Seats: ({seat1}, {seat2}, {seat3}), Vehicle Capacity: {v_cap}, Max Bundle Size: {max_bundle_size}"
    )


@settings(max_examples=25, deadline=None)
@given(
    onboard_seats=st.integers(min_value=1, max_value=2),
    seat1=st.integers(min_value=1, max_value=2),
    seat2=st.integers(min_value=1, max_value=2),
    v_cap=st.sampled_from([3, 4]),
    offset_lat=st.sampled_from([0.005, 0.010, 0.015]),
)
def test_oracle_property_active_ride_multi_request_bundles(
    onboard_seats: int,
    seat1: int,
    seat2: int,
    v_cap: int,
    offset_lat: float,
) -> None:
    """
    Property-based testing covering multi-request insertions into active rides:
    evaluates combinations of onboard passenger seats, vehicle capacity, and incoming
    request seats, verifying 100% agreement between the oracle and production candidate generation.
    """
    policy = DispatchPolicy(
        max_pickup_delay_seconds=600,
        detour_relative_multiplier=1.40,
        detour_absolute_cap_seconds=900,
    )
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial = H3SpatialIndexAdapter()

    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = _make_veh("veh-prop-multi-act", base_lat, base_lon, capacity=v_cap)

    t_start = 1000
    d_onboard_loc = Coordinate(base_lat + 0.040, base_lon)
    _, dur_onboard = router.get_direct_leg(v_loc, d_onboard_loc)

    drop_stop = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-prop-multi-act",
        request_id="req-onboard",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onboard_loc.latitude, longitude=d_onboard_loc.longitude),
        passenger_delta=-onboard_seats,
        scheduled_arrival_time=t_start + dur_onboard,
        promised_window_start=t_start,
        promised_window_end=t_start + dur_onboard + 1200,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-prop-multi-act",
        vehicle_id="veh-prop-multi-act",
        driver_id="drv-prop",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(drop_stop,),
        scheduled_departure_time=t_start,
        active_passenger_count=onboard_seats,
    )

    r1 = _make_req_exact(
        router, "r1", base_lat + offset_lat, base_lon, base_lat + offset_lat + 0.015, base_lon,
        seats=seat1, earliest_p=1000
    )
    r2 = _make_req_exact(
        router, "r2", base_lat + offset_lat + 0.005, base_lon, base_lat + offset_lat + 0.020, base_lon,
        seats=seat2, earliest_p=1010
    )

    oracle = IndependentCandidateOracle(router=router, policy=policy, max_bundle_size=2)
    oracle_cands = oracle.enumerate_feasible_candidates(
        requests=[r1, r2],
        vehicles=[veh],
        active_rides=[ride],
        current_time=t_start,
    )

    cfg_exact = CandidateGenerationConfig.exact(max_bundle_size=2)
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)
    prod_cands = engine.generate_candidates(
        requests=[r1, r2],
        vehicles=[veh],
        active_rides=[ride],
        current_time=t_start,
        config=cfg_exact,
    )

    cmp_res = oracle.compare(production_candidates=prod_cands, oracle_candidates=oracle_cands)
    assert cmp_res.is_perfect_match, (
        f"Multi-request active ride property mismatch!\n"
        f"  Oracle count: {cmp_res.oracle_count}, Production count: {cmp_res.production_count}\n"
        f"  False Negatives: {cmp_res.false_negatives}\n"
        f"  False Positives: {cmp_res.false_positives}\n"
        f"  Onboard: {onboard_seats}, Seats: ({seat1}, {seat2}), Capacity: {v_cap}"
    )



# ==============================================================================
# Requirement B: Strengthened Property-Based Tests for Temporal Pruning & Oracle
# ==============================================================================

class AsymmetricPropertyRouter(MockRoutingProvider):
    """Deterministic routing provider returning asymmetric durations for directional testing."""

    def __init__(self, asym_factor: float = 1.3) -> None:
        super().__init__(average_speed_kmh=40.0, circuity_factor=1.0)
        self.asym_factor = asym_factor

    def get_direct_leg(self, origin: Coordinate, destination: Coordinate) -> tuple[int, int]:
        dist, dur = super().get_direct_leg(origin, destination)
        if destination.latitude < origin.latitude:
            return int(round(dist * self.asym_factor)), int(round(dur * self.asym_factor))
        return dist, dur


@settings(max_examples=12, deadline=None)
@given(
    onboard_seats=st.integers(min_value=1, max_value=2),
    v_cap=st.sampled_from([4, 6]),
    slack=st.sampled_from([100, 300, 1200]),
    max_delay=st.sampled_from([180, 300, 600]),
    detour_mult=st.sampled_from([1.20, 1.40, 1.60]),
)
def test_oracle_property_active_ride_bundle_size_3(
    onboard_seats: int,
    v_cap: int,
    slack: int,
    max_delay: int,
    detour_mult: float,
) -> None:
    """
    Property-based test covering bundle size 3 on active rides:
    verifies 100% agreement between the independent oracle and production candidate generation
    across varied onboard passenger counts, vehicle capacities, promised dropoff window slacks,
    pickup delays, and detour multipliers.
    """
    policy = DispatchPolicy(
        max_pickup_delay_seconds=max_delay,
        detour_relative_multiplier=detour_mult,
        detour_absolute_cap_seconds=900,
    )
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    spatial = H3SpatialIndexAdapter()

    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = _make_veh("veh-prop-b3", base_lat, base_lon, capacity=v_cap)

    t_start = 1000
    d_onboard_loc = Coordinate(base_lat + 0.045, base_lon)
    _, dur_onboard = router.get_direct_leg(v_loc, d_onboard_loc)

    drop_stop = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-prop-b3",
        request_id="req-onboard",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onboard_loc.latitude, longitude=d_onboard_loc.longitude),
        passenger_delta=-onboard_seats,
        scheduled_arrival_time=t_start + dur_onboard,
        promised_window_start=t_start,
        promised_window_end=t_start + dur_onboard + slack,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-prop-b3",
        vehicle_id="veh-prop-b3",
        driver_id="drv-prop",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(drop_stop,),
        scheduled_departure_time=t_start,
        active_passenger_count=onboard_seats,
    )

    r1 = _make_req_exact(
        router, "req-b3-1", base_lat + 0.010, base_lon, base_lat + 0.025, base_lon,
        seats=1, earliest_p=1000
    )
    r2 = _make_req_exact(
        router, "req-b3-2", base_lat + 0.015, base_lon, base_lat + 0.035, base_lon,
        seats=1, earliest_p=1005
    )
    r3 = _make_req_exact(
        router, "req-b3-3", base_lat + 0.020, base_lon, base_lat + 0.040, base_lon,
        seats=1, earliest_p=1010
    )

    oracle = IndependentCandidateOracle(router=router, policy=policy, max_bundle_size=3)
    oracle_cands = oracle.enumerate_feasible_candidates(
        requests=[r1, r2, r3],
        vehicles=[veh],
        active_rides=[ride],
        current_time=t_start,
    )

    cfg_exact = CandidateGenerationConfig.exact(max_bundle_size=3)
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)
    prod_cands = engine.generate_candidates(
        requests=[r1, r2, r3],
        vehicles=[veh],
        active_rides=[ride],
        current_time=t_start,
        config=cfg_exact,
    )

    cmp_res = oracle.compare(production_candidates=prod_cands, oracle_candidates=oracle_cands)
    assert cmp_res.is_perfect_match, (
        f"Active ride bundle size 3 property mismatch!\n"
        f"  Oracle count: {cmp_res.oracle_count}, Production count: {cmp_res.production_count}\n"
        f"  False Negatives: {cmp_res.false_negatives}\n"
        f"  False Positives: {cmp_res.false_positives}\n"
        f"  Onboard: {onboard_seats}, Capacity: {v_cap}, Slack: {slack}"
    )


@settings(max_examples=12, deadline=None)
@given(
    dwell_sec=st.sampled_from([0, 15, 30, 45]),
    asym_mult=st.sampled_from([1.0, 1.25, 1.5]),
    max_delay=st.sampled_from([150, 300, 600]),
    bundle_size=st.integers(min_value=1, max_value=2),
)
def test_oracle_property_asymmetric_and_dwell_temporal_pruning(
    dwell_sec: int,
    asym_mult: float,
    max_delay: int,
    bundle_size: int,
) -> None:
    """
    Property-based test covering asymmetric routing and dwell duration interaction:
    verifies that directional travel time differences and dwell accumulation do not
    cause false negatives or false positives between oracle and production.
    """
    policy = DispatchPolicy(
        max_pickup_delay_seconds=max_delay,
        detour_relative_multiplier=1.40,
        detour_absolute_cap_seconds=900,
    )
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    router = AsymmetricPropertyRouter(asym_factor=asym_mult)
    spatial = H3SpatialIndexAdapter()

    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = _make_veh("veh-prop-asym", base_lat, base_lon, capacity=4)

    t_start = 1000
    d_onboard_loc = Coordinate(base_lat + 0.030, base_lon)
    _, dur_onb = router.get_direct_leg(v_loc, d_onboard_loc)

    drop_stop = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-prop-asym",
        request_id="req-onboard",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onboard_loc.latitude, longitude=d_onboard_loc.longitude),
        passenger_delta=-1,
        scheduled_arrival_time=t_start + dur_onb,
        promised_window_start=t_start,
        promised_window_end=t_start + dur_onb + 1200,
        dwell_duration_seconds=dwell_sec,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-prop-asym",
        vehicle_id="veh-prop-asym",
        driver_id="drv-prop",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(drop_stop,),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )

    r1 = _make_req_exact(
        router, "req-asym-1", base_lat + 0.020, base_lon, base_lat - 0.005, base_lon,
        seats=1, earliest_p=1000
    )
    r2 = _make_req_exact(
        router, "req-asym-2", base_lat + 0.015, base_lon, base_lat - 0.010, base_lon,
        seats=1, earliest_p=1010
    )

    eval_reqs = [r1] if bundle_size == 1 else [r1, r2]

    oracle = IndependentCandidateOracle(router=router, policy=policy, max_bundle_size=bundle_size)
    oracle_cands = oracle.enumerate_feasible_candidates(
        requests=eval_reqs,
        vehicles=[veh],
        active_rides=[ride],
        current_time=t_start,
    )

    cfg_exact = CandidateGenerationConfig.exact(max_bundle_size=bundle_size)
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)
    prod_cands = engine.generate_candidates(
        requests=eval_reqs,
        vehicles=[veh],
        active_rides=[ride],
        current_time=t_start,
        config=cfg_exact,
    )

    cmp_res = oracle.compare(production_candidates=prod_cands, oracle_candidates=oracle_cands)
    assert cmp_res.is_perfect_match, (
        f"Asymmetric & dwell property mismatch!\n"
        f"  Oracle count: {cmp_res.oracle_count}, Production count: {cmp_res.production_count}\n"
        f"  False Negatives: {cmp_res.false_negatives}\n"
        f"  False Positives: {cmp_res.false_positives}\n"
        f"  Dwell: {dwell_sec}, Asym: {asym_mult}, MaxDelay: {max_delay}"
    )


@settings(max_examples=12, deadline=None)
@given(
    is_colocated=st.booleans(),
    tight_boundary=st.sampled_from([-1, 0, 10]),
    onboard_seats=st.integers(min_value=0, max_value=2),
)
def test_oracle_property_colocated_and_tight_windows(
    is_colocated: bool,
    tight_boundary: int,
    onboard_seats: int,
) -> None:
    """
    Property-based test covering co-located stop coordinates, exact deadline boundaries,
    and tightly constrained time windows for active rides.
    """
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = _make_veh("veh-prop-coloc", base_lat, base_lon, capacity=4)
    t_start = 1000

    p1_lat = base_lat + 0.015
    p2_lat = base_lat + 0.015 if is_colocated else base_lat + 0.020
    d1_lat = base_lat + 0.030
    d2_lat = base_lat + 0.035

    _, dur_p1 = router.get_direct_leg(v_loc, Coordinate(p1_lat, base_lon))

    # Test exact boundary (dur_p1), strictly infeasible (dur_p1 - 1), or loose (dur_p1 + 10)
    tested_delay = max(1, dur_p1 + tight_boundary)

    policy = DispatchPolicy(
        max_pickup_delay_seconds=tested_delay,
        detour_relative_multiplier=1.40,
        detour_absolute_cap_seconds=900,
    )
    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    spatial = H3SpatialIndexAdapter()

    rides = []
    if onboard_seats > 0:
        d_onb = Coordinate(base_lat + 0.050, base_lon)
        _, dur_onb = router.get_direct_leg(v_loc, d_onb)
        drop_stop = RouteStop(
            stop_id="stop-d-onboard",
            ride_id="ride-prop-coloc",
            request_id="req-onboard",
            stop_type=StopType.DROPOFF,
            location=GeoCoordinate(latitude=d_onb.latitude, longitude=d_onb.longitude),
            passenger_delta=-onboard_seats,
            scheduled_arrival_time=t_start + dur_onb,
            promised_window_start=t_start,
            promised_window_end=t_start + dur_onb + 1200,
            status=StopStatus.SCHEDULED,
        )
        ride = Ride(
            ride_id="ride-prop-coloc",
            vehicle_id="veh-prop-coloc",
            driver_id="drv-prop",
            lifecycle_status=RideStatus.ACTIVE,
            stops=(drop_stop,),
            scheduled_departure_time=t_start,
            active_passenger_count=onboard_seats,
        )
        rides.append(ride)

    r1 = _make_req_exact(router, "req-co-1", p1_lat, base_lon, d1_lat, base_lon, seats=1, earliest_p=1000)
    r2 = _make_req_exact(router, "req-co-2", p2_lat, base_lon, d2_lat, base_lon, seats=1, earliest_p=1000)

    oracle = IndependentCandidateOracle(router=router, policy=policy, max_bundle_size=2)
    oracle_cands = oracle.enumerate_feasible_candidates(
        requests=[r1, r2],
        vehicles=[veh],
        active_rides=rides,
        current_time=t_start,
    )

    cfg_exact = CandidateGenerationConfig.exact(max_bundle_size=2)
    engine = DispatchEngine(policy_prov, router, spatial, config=cfg_exact)
    prod_cands = engine.generate_candidates(
        requests=[r1, r2],
        vehicles=[veh],
        active_rides=rides,
        current_time=t_start,
        config=cfg_exact,
    )

    cmp_res = oracle.compare(production_candidates=prod_cands, oracle_candidates=oracle_cands)
    assert cmp_res.is_perfect_match, (
        f"Colocated & boundary property mismatch!\n"
        f"  Oracle count: {cmp_res.oracle_count}, Production count: {cmp_res.production_count}\n"
        f"  False Negatives: {cmp_res.false_negatives}\n"
        f"  False Positives: {cmp_res.false_positives}\n"
        f"  Colocated: {is_colocated}, Boundary offset: {tight_boundary}, Delay: {tested_delay}"
    )
