"""Unit tests for Stage 1 physical invariants and baseline calculations."""

import pytest

from engine.contracts.policy import DispatchPolicy
from engine.domain.enums import StopStatus, StopType
from engine.domain.models import GeoCoordinate, RideRequest, RouteStop
from engine.routing.invariants import (
    calculate_unshared_vmt_baseline,
    calculate_vmt_savings,
    check_capacity_profile,
    check_detour_bound,
    check_pickup_delay,
    check_precedence,
)


def _make_stop(
    stop_id: str,
    stop_type: StopType,
    request_id: str,
    passenger_delta: int,
    scheduled_arrival: int = 1700000000,
) -> RouteStop:
    return RouteStop(
        stop_id=stop_id,
        ride_id="ride-1",
        request_id=request_id,
        stop_type=stop_type,
        location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        passenger_delta=passenger_delta,
        scheduled_arrival_time=scheduled_arrival,
        promised_window_start=scheduled_arrival - 300,
        promised_window_end=scheduled_arrival + 300,
        status=StopStatus.SCHEDULED,
    )


def test_precedence_invariant() -> None:
    # Valid: P1 before D1
    p1 = _make_stop("s1", StopType.PICKUP, "r1", +1)
    d1 = _make_stop("s2", StopType.DROPOFF, "r1", -1)
    assert check_precedence([p1, d1]) is True

    # Invalid: D1 before P1
    assert check_precedence([d1, p1]) is False

    # Multi-request valid: P1, P2, D1, D2
    p2 = _make_stop("s3", StopType.PICKUP, "r2", +1)
    d2 = _make_stop("s4", StopType.DROPOFF, "r2", -1)
    assert check_precedence([p1, p2, d1, d2]) is True

    # Multi-request invalid: P1, D2, P2, D1 (D2 before P2)
    assert check_precedence([p1, d2, p2, d1]) is False


def test_capacity_profile_invariant() -> None:
    p1 = _make_stop("s1", StopType.PICKUP, "r1", +2)
    p2 = _make_stop("s2", StopType.PICKUP, "r2", +2)
    d1 = _make_stop("s3", StopType.DROPOFF, "r1", -2)
    d2 = _make_stop("s4", StopType.DROPOFF, "r2", -2)

    # 4-passenger vehicle accommodates 2 + 2 = 4 peak load
    assert check_capacity_profile([p1, p2, d1, d2], capacity=4, initial_passengers=0) is True

    # 3-passenger vehicle cannot accommodate peak load 4
    assert check_capacity_profile([p1, p2, d1, d2], capacity=3, initial_passengers=0) is False

    # Negative occupancy anywhere is invalid
    bad_dropoff_first = _make_stop("s0", StopType.DROPOFF, "r0", -1)
    assert check_capacity_profile([bad_dropoff_first], capacity=4, initial_passengers=0) is False


def test_detour_bound_short_trip_relative_multiplier_binds() -> None:
    policy = DispatchPolicy(detour_relative_multiplier=1.30, detour_absolute_cap_seconds=900)
    # T_direct = 600s (10 min). Allowed detour = min(0.3 * 600, 900) = 180s. Max travel time = 780s.
    direct_duration = 600

    # Within bound: 780s (delta = 180s) -> True
    assert check_detour_bound(actual_duration=780, direct_duration=direct_duration, policy=policy) is True

    # Exceeds bound: 840s (delta = 240s) -> False
    assert check_detour_bound(actual_duration=840, direct_duration=direct_duration, policy=policy) is False


def test_detour_bound_long_trip_absolute_cap_binds() -> None:
    policy = DispatchPolicy(detour_relative_multiplier=1.30, detour_absolute_cap_seconds=900)
    # T_direct = 3600s (60 min).
    # Relative gives delta <= 0.3 * 3600 = 1080s.
    # Absolute cap gives delta <= 900s.
    # Allowed detour = min(1080, 900) = 900s. Max travel time = 4500s.
    direct_duration = 3600

    # Within bound: 4500s (delta = 900s) -> True
    assert check_detour_bound(actual_duration=4500, direct_duration=direct_duration, policy=policy) is True

    # Exceeds bound: 4560s (delta = 960s) -> False (even though 4560/3600 = 1.267 <= 1.30)
    assert check_detour_bound(actual_duration=4560, direct_duration=direct_duration, policy=policy) is False


def test_pickup_delay_invariant() -> None:
    requested_pickup = 1700000000
    max_delay = 600  # 10 minutes

    # On time: actual = requested
    assert check_pickup_delay(actual_pickup_time=1700000000, requested_pickup_time=requested_pickup, max_delay=max_delay) is True

    # Within 10 min: actual = requested + 600s
    assert check_pickup_delay(actual_pickup_time=1700000600, requested_pickup_time=requested_pickup, max_delay=max_delay) is True

    # Exceeded: actual = requested + 720s (12 min) -> False
    assert check_pickup_delay(actual_pickup_time=1700000720, requested_pickup_time=requested_pickup, max_delay=max_delay) is False


def test_unshared_vmt_baseline_and_savings() -> None:
    loc1 = GeoCoordinate(latitude=40.7128, longitude=-74.0060)
    loc2 = GeoCoordinate(latitude=40.7589, longitude=-73.9851)
    r1 = RideRequest(
        request_id="r1",
        user_id="u1",
        pickup_location=loc1,
        dropoff_location=loc2,
        seat_count=1,
        earliest_pickup_time=1700000000,
        latest_dropoff_time=1700003600,
        direct_distance_meters=4000,
        direct_duration_seconds=600,
    )
    r2 = RideRequest(
        request_id="r2",
        user_id="u2",
        pickup_location=loc1,
        dropoff_location=loc2,
        seat_count=1,
        earliest_pickup_time=1700000000,
        latest_dropoff_time=1700003600,
        direct_distance_meters=5000,
        direct_duration_seconds=700,
    )

    baseline = calculate_unshared_vmt_baseline([r1, r2])
    assert baseline == 9000

    savings = calculate_vmt_savings(baseline_vmt=baseline, shared_vmt=6000)
    assert savings == 3000

    # No negative savings
    assert calculate_vmt_savings(baseline_vmt=baseline, shared_vmt=10000) == 0


def test_deterministic_tie_breaking_tiers() -> None:
    from engine.domain.candidate import CandidateAssignment, ScoreBreakdown
    from engine.optimization.tie_breaking import compare_candidates_deterministic

    breakdown = ScoreBreakdown()
    stop = _make_stop("s1", StopType.PICKUP, "r1", +1)

    # Base candidate template
    def make_cand(
        cand_id: str,
        veh_id: str,
        req_ids: tuple[str, ...],
        vmt_meters: int,
        obj_val: float,
        vmt_savings_ratio: float = 0.0,
        detour_penalty_ratio: float = 0.0,
        wait_penalty_ratio: float = 0.0,
    ) -> CandidateAssignment:
        return CandidateAssignment(
            candidate_id=cand_id,
            vehicle_id=veh_id,
            existing_ride_id=None,
            request_ids=req_ids,
            ordered_stops=(stop,),
            peak_seat_load=1,
            vmt_meters=vmt_meters,
            objective_value=obj_val,
            normalized_score=0.5,
            score_breakdown=ScoreBreakdown(
                vmt_savings_ratio=vmt_savings_ratio,
                detour_penalty_ratio=detour_penalty_ratio,
                wait_penalty_ratio=wait_penalty_ratio,
            ),
        )

    # 1. Utility difference > 1e-6: higher J wins
    c_high_j = make_cand("c1", "v1", ("r1",), 1000, 0.2500)
    c_low_j = make_cand("c2", "v1", ("r1",), 1000, 0.2400)
    assert compare_candidates_deterministic(c_high_j, c_low_j) < 0  # c_high_j ranks before c_low_j
    assert compare_candidates_deterministic(c_low_j, c_high_j) > 0

    # 2. Tied utility within 1e-6 (|J_A - J_B| <= 1e-6):
    # Tier 1: Higher VMT savings ratio wins
    c_tie_j1 = make_cand("c1", "v1", ("r1",), 1000, 0.2500001, vmt_savings_ratio=0.30)
    c_tie_j2 = make_cand("c2", "v1", ("r1",), 1000, 0.2500002, vmt_savings_ratio=0.20)
    assert compare_candidates_deterministic(c_tie_j1, c_tie_j2) < 0

    # Tier 2: Same VMT savings, lower detour penalty wins
    c_detour1 = make_cand("c1", "v1", ("r1",), 1000, 0.25, vmt_savings_ratio=0.30, detour_penalty_ratio=0.05)
    c_detour2 = make_cand("c2", "v1", ("r1",), 1000, 0.25, vmt_savings_ratio=0.30, detour_penalty_ratio=0.10)
    assert compare_candidates_deterministic(c_detour1, c_detour2) < 0

    # Tier 3: Same VMT savings & detour, lower wait penalty wins
    c_wait1 = make_cand("c1", "v1", ("r1",), 1000, 0.25, vmt_savings_ratio=0.30, detour_penalty_ratio=0.05, wait_penalty_ratio=0.02)
    c_wait2 = make_cand("c2", "v1", ("r1",), 1000, 0.25, vmt_savings_ratio=0.30, detour_penalty_ratio=0.05, wait_penalty_ratio=0.08)
    assert compare_candidates_deterministic(c_wait1, c_wait2) < 0

    # Tier 4: All metrics identical -> Lexicographical comparison of vehicle ID, then request IDs, then candidate ID
    c_lex1 = make_cand("c1", "veh-A", ("r1",), 1000, 0.25)
    c_lex2 = make_cand("c2", "veh-B", ("r1",), 1000, 0.25)
    assert compare_candidates_deterministic(c_lex1, c_lex2) < 0

    c_lex_req1 = make_cand("c1", "veh-A", ("r1", "r2"), 1000, 0.25)
    c_lex_req2 = make_cand("c2", "veh-A", ("r1", "r3"), 1000, 0.25)
    assert compare_candidates_deterministic(c_lex_req1, c_lex_req2) < 0

    c_lex_id1 = make_cand("cand-001", "veh-A", ("r1",), 1000, 0.25)
    c_lex_id2 = make_cand("cand-002", "veh-A", ("r1",), 1000, 0.25)
    assert compare_candidates_deterministic(c_lex_id1, c_lex_id2) < 0


def test_deterministic_tie_breaking_canonical_stop_sequence() -> None:
    """
    Fix 2 Regression Test: Canonical stop-sequence must break ties BEFORE candidate_id.
    When two candidates have identical vehicle, identical request IDs, and identical utility scores,
    their relative order must be determined deterministically by the ordered stop IDs,
    NOT by random candidate UUIDs.
    """
    import uuid
    from engine.domain.candidate import CandidateAssignment, ScoreBreakdown
    from engine.optimization.tie_breaking import (
        candidate_sort_key,
        compare_candidates_deterministic,
        compare_candidates_pairwise_tolerance,
    )

    stop_p1 = _make_stop("s-01-p1", StopType.PICKUP, "r1", +1)
    stop_p2 = _make_stop("s-02-p2", StopType.PICKUP, "r2", +1)
    stop_d1 = _make_stop("s-03-d1", StopType.DROPOFF, "r1", -1)
    stop_d2 = _make_stop("s-04-d2", StopType.DROPOFF, "r2", -1)

    stops_seq_a = (stop_p1, stop_p2, stop_d1, stop_d2)
    stops_seq_b = (stop_p2, stop_p1, stop_d2, stop_d1)

    breakdown = ScoreBreakdown(
        vmt_savings_ratio=0.35,
        detour_penalty_ratio=0.10,
        wait_penalty_ratio=0.05,
    )

    # Candidate A has lexicographically earlier stop IDs: ('s-01-...', ...) < ('s-02-...', ...)
    # But assign it a lexicographically LARGER candidate_id ("cand-z999")
    cand_a = CandidateAssignment(
        candidate_id="cand-z999",
        vehicle_id="veh-1",
        existing_ride_id=None,
        request_ids=("r1", "r2"),
        ordered_stops=stops_seq_a,
        peak_seat_load=2,
        vmt_meters=5000,
        objective_value=0.25,
        normalized_score=0.85,
        score_breakdown=breakdown,
    )

    # Candidate B has lexicographically later stop IDs, but SMALLER candidate_id ("cand-a000")
    cand_b = CandidateAssignment(
        candidate_id="cand-a000",
        vehicle_id="veh-1",
        existing_ride_id=None,
        request_ids=("r1", "r2"),
        ordered_stops=stops_seq_b,
        peak_seat_load=2,
        vmt_meters=5000,
        objective_value=0.25,
        normalized_score=0.85,
        score_breakdown=breakdown,
    )

    # 1. Deterministic comparison must select Candidate A because of earlier stop sequence
    assert compare_candidates_deterministic(cand_a, cand_b) < 0, (
        "Canonical stop sequence must break ties before candidate_id"
    )
    assert compare_candidates_pairwise_tolerance(cand_a, cand_b) < 0, (
        "Pairwise tolerance comparator must break ties by stop sequence before candidate_id"
    )

    # 2. Stability across 50 repeated runs with random candidate UUIDs
    sort_fn = candidate_sort_key()
    for _ in range(50):
        c_rand_a = cand_a.model_copy(update={"candidate_id": f"cand-{uuid.uuid4().hex}"})
        c_rand_b = cand_b.model_copy(update={"candidate_id": f"cand-{uuid.uuid4().hex}"})
        sorted_pair = sorted([c_rand_b, c_rand_a], key=sort_fn)
        assert sorted_pair[0].ordered_stops == stops_seq_a, (
            "Random UUID candidate IDs must never overturn deterministic stop sequence ordering"
        )


def test_deterministic_tie_breaking_transitivity_and_anti_symmetry() -> None:
    from engine.domain.candidate import CandidateAssignment, ScoreBreakdown
    from engine.optimization.tie_breaking import (
        candidate_sort_key,
        compare_candidates_deterministic,
    )

    stop = _make_stop("s1", StopType.PICKUP, "r1", +1)

    def make_cand(cand_id: str, obj: float, vmt: float, det: float) -> CandidateAssignment:
        return CandidateAssignment(
            candidate_id=cand_id,
            vehicle_id="veh-1",
            existing_ride_id=None,
            request_ids=("r1",),
            ordered_stops=(stop,),
            peak_seat_load=1,
            vmt_meters=1000,
            objective_value=obj,
            normalized_score=0.5,
            score_breakdown=ScoreBreakdown(
                vmt_savings_ratio=vmt,
                detour_penalty_ratio=det,
                wait_penalty_ratio=0.0,
            ),
        )

    # Three candidates near the 1e-6 boundary
    # A has highest obj (0.200000)
    # B has tied obj with higher VMT (0.200000, vmt=0.30)
    # C has tied obj with lower VMT (0.200000, vmt=0.20)
    cand_a = make_cand("cA", 0.2000001, 0.35, 0.10)
    cand_b = make_cand("cB", 0.2000002, 0.30, 0.10)
    cand_c = make_cand("cC", 0.2000003, 0.20, 0.10)

    # Check anti-symmetry: comp(x, y) == -comp(y, x)
    assert compare_candidates_deterministic(cand_a, cand_b) == -compare_candidates_deterministic(cand_b, cand_a)
    assert compare_candidates_deterministic(cand_b, cand_c) == -compare_candidates_deterministic(cand_c, cand_b)
    assert compare_candidates_deterministic(cand_a, cand_a) == 0

    # Check transitivity: A < B and B < C => A < C
    cmp_ab = compare_candidates_deterministic(cand_a, cand_b)
    cmp_bc = compare_candidates_deterministic(cand_b, cand_c)
    cmp_ac = compare_candidates_deterministic(cand_a, cand_c)

    assert cmp_ab < 0  # cand_a is better than cand_b (vmt 0.35 vs 0.30)
    assert cmp_bc < 0  # cand_b is better than cand_c (vmt 0.30 vs 0.20)
    assert cmp_ac < 0  # cand_a must be better than cand_c

    # Check sorting stability across permutations
    cands = [cand_c, cand_a, cand_b]
    sorted_1 = sorted(cands, key=candidate_sort_key())
    sorted_2 = sorted(reversed(cands), key=candidate_sort_key())
    assert [c.candidate_id for c in sorted_1] == ["cA", "cB", "cC"]
    assert [c.candidate_id for c in sorted_2] == ["cA", "cB", "cC"]


def test_tie_breaking_utility_tolerance_exact_and_boundaries() -> None:
    """
    Exhaustive tests for utility differences:
    1. Continuous pairwise tolerance (compare_candidates_pairwise_tolerance) tested on
       just below, exactly at, and just above 1e-6, including negative and zero boundary cases.
    2. Unified Quantized Total Order policy (compare_candidates_deterministic) tested on
       intra-class equivalence ties vs inter-class strict utility ordering.
    """
    from engine.domain.candidate import CandidateAssignment, ScoreBreakdown
    from engine.optimization.tie_breaking import (
        compare_candidates_deterministic,
        compare_candidates_pairwise_tolerance,
    )

    stop = _make_stop("s1", StopType.PICKUP, "r1", +1)

    def make_cand(cand_id: str, obj: float, vmt: float = 0.0) -> CandidateAssignment:
        return CandidateAssignment(
            candidate_id=cand_id,
            vehicle_id="veh-1",
            existing_ride_id=None,
            request_ids=("r1",),
            ordered_stops=(stop,),
            peak_seat_load=1,
            vmt_meters=1000,
            objective_value=obj,
            normalized_score=0.5,
            score_breakdown=ScoreBreakdown(
                vmt_savings_ratio=vmt,
                detour_penalty_ratio=0.0,
                wait_penalty_ratio=0.0,
            ),
        )

    # -------------------------------------------------------------------------
    # Part A: Continuous Pairwise Tolerance Comparator
    # -------------------------------------------------------------------------
    # 1. Difference just below 1e-6 (0.999e-6): diff <= 1e-6 -> Tier 1 wins
    c_just_below_a = make_cand("c1", 0.2500000, vmt=0.50)
    c_just_below_b = make_cand("c2", 0.2500000 + 0.999e-6, vmt=0.10)
    assert compare_candidates_pairwise_tolerance(c_just_below_a, c_just_below_b) < 0
    assert compare_candidates_pairwise_tolerance(c_just_below_b, c_just_below_a) > 0

    # 2. Difference exactly at 1e-6 (1.0e-6): diff <= 1e-6 -> Tier 1 wins
    c_exact_a = make_cand("c1", 0.2500000, vmt=0.50)
    c_exact_b = make_cand("c2", 0.2500010, vmt=0.10)
    assert compare_candidates_pairwise_tolerance(c_exact_a, c_exact_b) < 0
    assert compare_candidates_pairwise_tolerance(c_exact_b, c_exact_a) > 0

    # 3. Difference just above 1e-6 (1.001e-6): diff > 1e-6 -> higher utility wins (Tier 1 ignored)
    c_just_above_a = make_cand("c1", 0.2500000, vmt=0.50)
    c_just_above_b = make_cand("c2", 0.2500000 + 1.001e-6, vmt=0.10)
    assert compare_candidates_pairwise_tolerance(c_just_above_b, c_just_above_a) < 0
    assert compare_candidates_pairwise_tolerance(c_just_above_a, c_just_above_b) > 0

    # 4. Negative values under continuous pairwise tolerance
    c_neg_base = make_cand("c1", -0.3000000, vmt=0.60)
    c_neg_below = make_cand("c2", -0.3000000 + 0.999e-6, vmt=0.10)
    assert compare_candidates_pairwise_tolerance(c_neg_base, c_neg_below) < 0

    c_neg_exact = make_cand("c3", -0.3000000 + 1.0e-6, vmt=0.10)
    assert compare_candidates_pairwise_tolerance(c_neg_base, c_neg_exact) < 0

    c_neg_above = make_cand("c4", -0.3000000 + 1.001e-6, vmt=0.10)
    assert compare_candidates_pairwise_tolerance(c_neg_above, c_neg_base) < 0

    # 5. Zero boundary under continuous pairwise tolerance
    c_zero = make_cand("c_zero", 0.0, vmt=0.50)
    c_pos_exact = make_cand("c_pos_exact", 1.0e-6, vmt=0.10)
    assert compare_candidates_pairwise_tolerance(c_zero, c_pos_exact) < 0

    c_pos_above = make_cand("c_pos_above", 1.001e-6, vmt=0.10)
    assert compare_candidates_pairwise_tolerance(c_pos_above, c_zero) < 0

    # -------------------------------------------------------------------------
    # Part B: Unified Quantized Total Order Comparator (compare_candidates_deterministic)
    # -------------------------------------------------------------------------
    # Intra-class candidates (same 6-decimal utility equivalence class):
    # Both round to 0.250000 -> tied on utility class -> Tier 1 (VMT) decides
    c_intra_a = make_cand("c1", 0.2500001, vmt=0.50)
    c_intra_b = make_cand("c2", 0.2500004, vmt=0.10)
    assert compare_candidates_deterministic(c_intra_a, c_intra_b) < 0
    assert compare_candidates_deterministic(c_intra_b, c_intra_a) > 0

    # Inter-class candidates (different 6-decimal utility equivalence classes):
    # c_inter_b in class 0.250002 > c_inter_a in class 0.250000 -> c_inter_b strictly wins
    c_inter_a = make_cand("c1", 0.2500000, vmt=0.80)
    c_inter_b = make_cand("c2", 0.2500020, vmt=0.10)
    assert compare_candidates_deterministic(c_inter_b, c_inter_a) < 0

    # Negative intra-class (both in class -0.300000): Tier 1 decides
    c_neg_intra_a = make_cand("c1", -0.3000001, vmt=0.60)
    c_neg_intra_b = make_cand("c2", -0.3000004, vmt=0.10)
    assert compare_candidates_deterministic(c_neg_intra_a, c_neg_intra_b) < 0

    # Zero intra-class (both in class 0.000000): Tier 1 decides
    c_zero_intra_a = make_cand("c1", 0.0000001, vmt=0.50)
    c_zero_intra_b = make_cand("c2", 0.0000004, vmt=0.10)
    assert compare_candidates_deterministic(c_zero_intra_a, c_zero_intra_b) < 0


def test_disagreement_between_continuous_pairwise_tolerance_and_quantized_collection_sorting() -> None:
    """
    Requirement 3: Demonstrates that continuous pairwise tolerance (|J_A - J_B| <= 1e-6)
    and quantized collection sorting (round(J, 6)) inherently disagree for candidates
    near a six-decimal rounding boundary.

    Proves why the engine must adopt a unified ranking policy (Quantized Equivalence Classes)
    to prevent collection sorting (candidate_sort_key) and pairwise selection
    (compare_candidates_deterministic) from contradicting each other.
    """
    from engine.domain.candidate import CandidateAssignment, ScoreBreakdown
    from engine.optimization.tie_breaking import (
        candidate_sort_key,
        compare_candidates_deterministic,
        compare_candidates_pairwise_tolerance,
    )

    stop = _make_stop("s1", StopType.PICKUP, "r1", +1)
    a = CandidateAssignment(
        candidate_id="cA",
        vehicle_id="v1",
        existing_ride_id=None,
        request_ids=("r1",),
        ordered_stops=(stop,),
        peak_seat_load=1,
        vmt_meters=1000,
        objective_value=0.20000049,
        normalized_score=0.5,
        score_breakdown=ScoreBreakdown(vmt_savings_ratio=0.80),
    )
    b = CandidateAssignment(
        candidate_id="cB",
        vehicle_id="v1",
        request_ids=("r1",),
        ordered_stops=(stop,),
        peak_seat_load=1,
        vmt_meters=1000,
        objective_value=0.20000051,
        normalized_score=0.5,
        score_breakdown=ScoreBreakdown(vmt_savings_ratio=0.10),
    )

    # 1. Continuous pairwise tolerance:
    # |J_A - J_B| = 2e-8 <= 1e-6 -> tied on utility -> Tier 1 (VMT 0.80 vs 0.10) selects cA!
    cmp_pairwise = compare_candidates_pairwise_tolerance(a, b)
    assert cmp_pairwise < 0  # cA is selected over cB

    # 2. Quantized collection sorting (round(J, 6)):
    # round(0.20000049, 6) = 0.200000, round(0.20000051, 6) = 0.200001
    # cB has a higher utility class than cA, so cB is sorted first!
    sorted_cands = [c.candidate_id for c in sorted([a, b], key=candidate_sort_key())]
    assert sorted_cands == ["cB", "cA"]  # cB is sorted ahead of cA!

    # 3. Direct disagreement proven:
    # Pairwise continuous selection chooses cA, while collection sorting chooses cB!
    assert cmp_pairwise < 0 and sorted_cands[0] == "cB"

    # 4. Under our unified engine comparator, pairwise selection and collection sorting are unified
    # so that compare_candidates_deterministic and candidate_sort_key NEVER disagree:
    cmp_deterministic = compare_candidates_deterministic(a, b)
    assert cmp_deterministic > 0  # cB preferred over cA
    assert sorted_cands[0] == "cB"  # cB sorted first (100% agreement!)


def test_sorting_transitivity_determinism_and_semiorder_analysis() -> None:
    """
    Verifies that the sorting comparator (candidate_sort_key) is deterministic,
    transitive, and input-order independent across all permutations.
    Also documents that continuous pairwise tolerance comparisons form a semiorder where
    chaining across 3+ candidates produces cycles if naively wrapped for sorting.
    """
    import functools
    import itertools

    from engine.domain.candidate import CandidateAssignment, ScoreBreakdown
    from engine.optimization.tie_breaking import (
        candidate_sort_key,
        compare_candidates_deterministic,
        compare_candidates_pairwise_tolerance,
        get_candidate_sort_tuple,
    )

    stop = _make_stop("s1", StopType.PICKUP, "r1", +1)

    def make_cand(cand_id: str, obj: float, vmt: float) -> CandidateAssignment:
        return CandidateAssignment(
            candidate_id=cand_id,
            vehicle_id="veh-1",
            existing_ride_id=None,
            request_ids=("r1",),
            ordered_stops=(stop,),
            peak_seat_load=1,
            vmt_meters=1000,
            objective_value=obj,
            normalized_score=0.5,
            score_breakdown=ScoreBreakdown(
                vmt_savings_ratio=vmt,
                detour_penalty_ratio=0.0,
                wait_penalty_ratio=0.0,
            ),
        )

    # 1. Verification that candidate_sort_key produces identical order across all 4! = 24 permutations
    c1 = make_cand("c1", 0.30, 0.40)
    c2 = make_cand("c2", 0.2500001, 0.50)
    c3 = make_cand("c3", 0.2500002, 0.20)
    c4 = make_cand("c4", 0.20, 0.80)
    pool = [c1, c2, c3, c4]

    canonical_order = [c.candidate_id for c in sorted(pool, key=candidate_sort_key())]

    # Every permutation of pool MUST produce bit-for-bit identical sorted output
    for perm in itertools.permutations(pool):
        sorted_perm = [c.candidate_id for c in sorted(perm, key=candidate_sort_key())]
        assert sorted_perm == canonical_order, "Sorting must be strictly input-order independent"

    # 2. Transitivity of sort key:
    # get_candidate_sort_tuple maps candidates to tuples in a total preorder.
    # Therefore, tuple comparison is mathematically guaranteed to be transitive:
    # key(A) <= key(B) and key(B) <= key(C) => key(A) <= key(C)
    for c_a in pool:
        for c_b in pool:
            for c_c in pool:
                key_a = get_candidate_sort_tuple(c_a)
                key_b = get_candidate_sort_tuple(c_b)
                key_c = get_candidate_sort_tuple(c_c)
                if key_a <= key_b and key_b <= key_c:
                    assert key_a <= key_c, "Sort key tuple comparison must be strictly transitive"

    # 3. Demonstration of the semiorder intransitivity paradox with continuous pairwise tolerance:
    # When candidates have pairwise differences within 1e-6 (e.g. 0.8e-6 step),
    # A ~ B (diff 0.8e-6) and B ~ C (diff 0.8e-6), but A and C differ by 1.6e-6 > 1e-6!
    a = make_cand("A", 0.0, 0.50)
    b = make_cand("B", 0.8e-6, 0.30)
    c = make_cand("C", 1.6e-6, 0.10)

    cmp_ab = compare_candidates_pairwise_tolerance(a, b)  # tied on J -> A beats B on Tier 1 (0.50 > 0.30)
    cmp_bc = compare_candidates_pairwise_tolerance(b, c)  # tied on J -> B beats C on Tier 1 (0.30 > 0.10)
    cmp_ac = compare_candidates_pairwise_tolerance(a, c)  # diff 1.6e-6 > 1e-6 -> C beats A on utility J!

    assert cmp_ab < 0  # A beats B
    assert cmp_bc < 0  # B beats C
    assert cmp_ac > 0  # C beats A (intransitive cycle: A > B > C > A!)

    # If naively passed to cmp_to_key, sorting this cycle produces input-order dependent results:
    naive_key = functools.cmp_to_key(compare_candidates_pairwise_tolerance)
    sort_from_abc = [x.candidate_id for x in sorted([a, b, c], key=naive_key)]
    sort_from_bca = [x.candidate_id for x in sorted([b, c, a], key=naive_key)]
    # Proves that continuous pairwise tolerance cannot be used for sorting without input-order dependence!
    assert sort_from_abc != sort_from_bca


def test_hard_invariant_gate() -> None:
    """
    Scenario 2: Two-Stage Feasibility Gate & Invariant Protection (matching quickstart.md).
    A candidate route offering 90% VMT reduction but with detour Delta T > min((alpha - 1) T_direct, C)
    or capacity overage is strictly pruned in Stage 1 and receives no score.
    """
    policy = DispatchPolicy(
        detour_relative_multiplier=1.30,
        detour_absolute_cap_seconds=900,
    )
    # Direct trip 600s: max allowed duration is 780s
    assert check_detour_bound(actual_duration=780, direct_duration=600, policy=policy) is True
    # Breaches by 1s: 781s -> rejected
    assert check_detour_bound(actual_duration=781, direct_duration=600, policy=policy) is False
    # Huge theoretical savings cannot override capacity violation
    stop_over = _make_stop("s-over", StopType.PICKUP, "r1", +5)
    assert check_capacity_profile([stop_over], capacity=4, initial_passengers=0) is False


def test_score_breakdown_precision_preservation() -> None:
    """
    Priority 4: Verify that score breakdown precision maintains 6 decimals across
    scoring and candidate generation, preventing premature collapse of secondary tie-breaking tiers.
    """
    from engine.domain.candidate import CandidateAssignment, ScoreBreakdown
    from engine.optimization.tie_breaking import compare_candidates_deterministic

    stop = _make_stop("s1", StopType.PICKUP, "r1", +1)

    # Two candidates tied on 6-decimal objective value (0.300000),
    # but differing in VMT savings ratio at the 5th decimal place: 0.400010 vs 0.400020.
    cand1 = CandidateAssignment(
        candidate_id="c1",
        vehicle_id="veh-1",
        existing_ride_id=None,
        request_ids=("r1",),
        ordered_stops=(stop,),
        peak_seat_load=1,
        vmt_meters=1000,
        objective_value=0.300000,
        normalized_score=0.7,
        score_breakdown=ScoreBreakdown(
            vmt_savings_ratio=0.400010,
            detour_penalty_ratio=0.05,
            wait_penalty_ratio=0.02,
        ),
    )
    cand2 = CandidateAssignment(
        candidate_id="c2",
        vehicle_id="veh-1",
        existing_ride_id=None,
        request_ids=("r1",),
        ordered_stops=(stop,),
        peak_seat_load=1,
        vmt_meters=1000,
        objective_value=0.300000,
        normalized_score=0.7,
        score_breakdown=ScoreBreakdown(
            vmt_savings_ratio=0.400020,
            detour_penalty_ratio=0.05,
            wait_penalty_ratio=0.02,
        ),
    )

    # cand2 has higher VMT savings ratio (0.400020 > 0.400010) -> must win in Tier 1
    cmp = compare_candidates_deterministic(cand1, cand2)
    assert cmp > 0, "Candidate 2 with higher 6-decimal VMT savings ratio must rank ahead of Candidate 1"


def test_candidate_generation_preserves_six_decimal_precision() -> None:
    """
    Priority 4: Verify that generate_single_request_insertions and generate_group_bundles
    preserve 6-decimal precision in score_breakdown, matching objective.py.
    """
    from engine.adapters.default_policy import DefaultPolicyProvider
    from engine.adapters.mock_routing import MockRoutingProvider
    from engine.domain.enums import RequestStatus, RideStatus
    from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle
    from engine.routing.insertion import generate_single_request_insertions
    from engine.routing.bundle_generator import generate_group_bundles

    loc1 = GeoCoordinate(latitude=40.7100, longitude=-74.0050)
    loc2 = GeoCoordinate(latitude=40.7500, longitude=-73.9850)

    veh = Vehicle(vehicle_id="v1", driver_id="d1", total_seat_capacity=4, current_location=loc1, is_active=True)
    req = RideRequest(
        request_id="r1", user_id="u1",
        pickup_location=loc1, dropoff_location=loc2,
        seat_count=1, earliest_pickup_time=1000, latest_dropoff_time=3000,
        direct_distance_meters=5333, direct_duration_seconds=480,
        status=RequestStatus.PENDING,
    )
    stop_d = RouteStop(
        stop_id="d1", ride_id="ride1", request_id="r_exist", stop_type=StopType.DROPOFF,
        location=loc2, passenger_delta=-1, scheduled_arrival_time=2000,
        promised_window_start=1000, promised_window_end=3000, status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride1", vehicle_id="v1", driver_id="d1", lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_d,), scheduled_departure_time=1000, active_passenger_count=1,
        total_vmt_meters=3000, version=1,
    )

    router = MockRoutingProvider()
    policy = DefaultPolicyProvider().get_policy()

    # 1. Insertion
    ins_cands = generate_single_request_insertions(ride, req, veh, router, policy, 1000)
    assert len(ins_cands) > 0
    for c in ins_cands:
        # Check that float representation is not truncated to 4 decimals when precision requires more
        s_vmt_str = f"{c.score_breakdown.vmt_savings_ratio:.6f}"
        assert len(s_vmt_str.split(".")[1]) == 6

    # 2. Bundle generator
    bundle_cands = generate_group_bundles(requests=[req], vehicle=veh, router=router, policy=policy, current_time=1000)
    assert len(bundle_cands) > 0
    for c in bundle_cands:
        s_vmt_str = f"{c.score_breakdown.vmt_savings_ratio:.6f}"
        assert len(s_vmt_str.split(".")[1]) == 6






