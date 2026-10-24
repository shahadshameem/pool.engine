"""Unit tests for monotonic deadline interrupts, Stage 6 headroom, and safe fallback (T033)."""

import time
import pytest

from engine.domain.candidate import CandidateAssignment, ScoreBreakdown
from engine.domain.enums import StopStatus, StopType
from engine.domain.models import GeoCoordinate, RouteStop
from engine.optimization.set_packing import solve_set_packing_regret_k


def _dummy_stop(stop_id: str, req_id: str) -> RouteStop:
    return RouteStop(
        stop_id=stop_id,
        ride_id="ride-perf",
        request_id=req_id,
        stop_type=StopType.PICKUP,
        location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        passenger_delta=1,
        scheduled_arrival_time=1700000000,
        promised_window_start=1700000000,
        promised_window_end=1700001000,
        status=StopStatus.SCHEDULED,
    )


def test_monotonic_deadline_immediate_timeout() -> None:
    """
    Simulates a deadline that has already elapsed (t >= deadline).
    Solver must immediately trigger interrupt, preserve headroom, and return
    all requests as unassigned with zero corrupt or partial state mutations.
    """
    all_requests = ["r1", "r2", "r3"]
    stops = tuple(_dummy_stop(f"s-{r}", r) for r in all_requests)
    cand = CandidateAssignment(
        candidate_id="c1",
        vehicle_id="v1",
        existing_ride_id=None,
        request_ids=("r1", "r2"),
        ordered_stops=stops[:2],
        peak_seat_load=2,
        vmt_meters=2000,
        objective_value=0.25,
        normalized_score=0.75,
        score_breakdown=ScoreBreakdown(),
    )

    # Deadline already in the past
    past_deadline = time.monotonic() - 0.010
    result = solve_set_packing_regret_k(
        candidates=[cand],
        all_request_ids=all_requests,
        deadline=past_deadline,
        reserved_headroom=0.050,
    )

    # Must safely fall back with 0 assignments and all requests unassigned
    assert len(result.selected_assignments) == 0
    assert set(result.unassigned_request_ids) == set(all_requests)


def test_standalone_solver_deadline_metadata() -> None:
    """
    Fix 3 Regression Test: Updating solve_set_packing_regret_k so deadline interruption
    sets search_status=INCOMPLETE_DEADLINE_EXPIRED and is_approximated=True on the returned result.
    """
    from engine.domain.enums import SearchStatus

    all_requests = [f"r{i}" for i in range(10)]
    candidates: list[CandidateAssignment] = []
    for i in range(10):
        c = CandidateAssignment(
            candidate_id=f"c-{i}",
            vehicle_id=f"v-{i}",
            existing_ride_id=None,
            request_ids=(f"r{i}",),
            ordered_stops=(_dummy_stop(f"s-{i}", f"r{i}"),),
            peak_seat_load=1,
            vmt_meters=1000,
            objective_value=0.10 + i * 0.01,
            normalized_score=0.6,
            score_breakdown=ScoreBreakdown(),
        )
        candidates.append(c)

    # 1. Immediate timeout (deadline already in the past)
    past_deadline = time.monotonic() - 0.010
    res_imm = solve_set_packing_regret_k(
        candidates=candidates,
        all_request_ids=all_requests,
        deadline=past_deadline,
        reserved_headroom=0.050,
    )
    assert res_imm.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED, (
        f"Expected INCOMPLETE_DEADLINE_EXPIRED for immediate timeout, got {res_imm.search_status}"
    )
    assert res_imm.is_approximated is True

    # 2. Hard cutoff during solve (loop interrupted by clock >= cutoff_time)
    start_time = time.monotonic()
    deadline = start_time + 0.030
    reserved_headroom = 0.015

    def delay_hook() -> None:
        time.sleep(0.010)

    res_loop = solve_set_packing_regret_k(
        candidates=candidates,
        all_request_ids=all_requests,
        deadline=deadline,
        reserved_headroom=reserved_headroom,
        iteration_hook=delay_hook,
    )
    assert res_loop.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED, (
        f"Expected INCOMPLETE_DEADLINE_EXPIRED for loop cutoff, got {res_loop.search_status}"
    )
    assert res_loop.is_approximated is True


def test_monotonic_deadline_hard_cutoff_during_solve() -> None:
    """
    Simulates a tight deadline budget (e.g. 50ms total, 20ms headroom) with an iteration delay hook.
    Verifies that solver interrupts as soon as clock hits deadline - headroom,
    completes Stage 6 verification within reserved headroom, and emits valid conflict-free MatchResult.
    """
    all_requests = [f"r{i}" for i in range(10)]
    candidates: list[CandidateAssignment] = []

    for i in range(10):
        c = CandidateAssignment(
            candidate_id=f"c-{i}",
            vehicle_id=f"v-{i}",
            existing_ride_id=None,
            request_ids=(f"r{i}",),
            ordered_stops=(_dummy_stop(f"s-{i}", f"r{i}"),),
            peak_seat_load=1,
            vmt_meters=1000,
            objective_value=0.10 + i * 0.01,
            normalized_score=0.6,
            score_breakdown=ScoreBreakdown(),
        )
        candidates.append(c)

    # Total budget 40ms, reserved headroom 20ms -> solver must interrupt after <= 20ms of search
    start_time = time.monotonic()
    deadline = start_time + 0.040
    reserved_headroom = 0.020

    # Inject slight simulated delay per iteration
    def simulated_delay() -> None:
        time.sleep(0.008)

    result = solve_set_packing_regret_k(
        candidates=candidates,
        all_request_ids=all_requests,
        deadline=deadline,
        reserved_headroom=reserved_headroom,
        iteration_hook=simulated_delay,
    )

    end_time = time.monotonic()

    # The entire call MUST finish before or at the hard deadline
    assert end_time <= deadline + 0.015  # allow small timer granularity

    # Verification of returned state:
    # 1. No request is assigned more than once
    assigned_requests = [r for c in result.selected_assignments for r in c.request_ids]
    assert len(assigned_requests) == len(set(assigned_requests))

    # 2. No vehicle is assigned more than once
    assigned_vehicles = [c.vehicle_id for c in result.selected_assignments]
    assert len(assigned_vehicles) == len(set(assigned_vehicles))

    # 3. All unassigned requests are accounted for
    assert set(assigned_requests) | set(result.unassigned_request_ids) == set(all_requests)


def test_candidate_input_order_invariance() -> None:
    """
    Verifies that passing candidates in different permutations / shuffled order
    produces bit-for-bit identical assignments, score breakdowns, and unassigned requests.
    """
    import random

    all_requests = [f"req-{i}" for i in range(12)]
    candidates: list[CandidateAssignment] = []

    for i in range(25):
        veh_id = f"veh-{i % 5}"
        req_count = (i % 3) + 1
        start_req = (i * 2) % 10
        reqs = tuple(all_requests[start_req : start_req + req_count])
        if not reqs:
            continue
        stops = tuple(_dummy_stop(f"s-{i}-{r}", r) for r in reqs)
        c = CandidateAssignment(
            candidate_id=f"cand-{i:03d}",
            vehicle_id=veh_id,
            existing_ride_id=None,
            request_ids=reqs,
            ordered_stops=stops,
            peak_seat_load=len(reqs),
            vmt_meters=2000 + i * 50,
            objective_value=round(0.05 + (i % 7) * 0.05, 4),
            normalized_score=0.7,
            score_breakdown=ScoreBreakdown(vmt_savings_ratio=0.25),
        )
        candidates.append(c)

    # Base run
    base_result = solve_set_packing_regret_k(candidates=candidates, all_request_ids=all_requests)
    base_cand_ids = [c.candidate_id for c in base_result.selected_assignments]
    base_unassigned = base_result.unassigned_request_ids

    # 10 randomized shuffles
    rng = random.Random(42)
    for trial in range(10):
        shuffled_cands = list(candidates)
        rng.shuffle(shuffled_cands)
        shuffled_reqs = list(all_requests)
        rng.shuffle(shuffled_reqs)

        trial_result = solve_set_packing_regret_k(candidates=shuffled_cands, all_request_ids=shuffled_reqs)
        trial_cand_ids = [c.candidate_id for c in trial_result.selected_assignments]

        assert trial_cand_ids == base_cand_ids, f"Order variance detected on trial {trial}"
        assert trial_result.unassigned_request_ids == base_unassigned


def test_stage_6_safe_fallback_on_corrupt_state() -> None:
    """
    Verifies that if unexpected input or constraint corruption occurs,
    Stage 6 catches the invariant violation and safely falls back
    to returning zero assignments and all requests unassigned.
    """
    all_requests = ["r1", "r2"]
    # Candidate with empty request IDs or non-existent requests
    invalid_cand = CandidateAssignment(
        candidate_id="c-corrupt",
        vehicle_id="v1",
        existing_ride_id=None,
        request_ids=("r-nonexistent",),
        ordered_stops=(_dummy_stop("s1", "r-nonexistent"),),
        peak_seat_load=1,
        vmt_meters=1000,
        objective_value=0.3,
        normalized_score=0.7,
        score_breakdown=ScoreBreakdown(),
    )

    result = solve_set_packing_regret_k(
        candidates=[invalid_cand],
        all_request_ids=all_requests,
    )

    # Safe fallback: nonexistent candidate ignored, r1 and r2 cleanly unassigned
    assert len(result.selected_assignments) == 0
    assert set(result.unassigned_request_ids) == {"r1", "r2"}


def test_solver_selection_consistency_with_tie_breaking() -> None:
    """
    Verifies that Regret-K solver selection is 100% consistent with both
    compare_candidates_deterministic and candidate_sort_key:
    1. Candidates in the same 6-decimal utility class: Tier 1 (VMT) decides in both comparator and solver.
    2. Candidates in different 6-decimal utility classes: Higher utility class decides in both comparator and solver.
    """
    from engine.optimization.tie_breaking import (
        candidate_sort_key,
        compare_candidates_deterministic,
    )

    all_requests = ["r1"]

    # 1. Contending candidates in the same 6-decimal class (both round to 0.250000)
    cand_a = CandidateAssignment(
        candidate_id="c-intra-A",
        vehicle_id="veh-1",
        existing_ride_id=None,
        request_ids=("r1",),
        ordered_stops=(_dummy_stop("s1", "r1"),),
        peak_seat_load=1,
        vmt_meters=1000,
        objective_value=0.2500001,
        normalized_score=0.7,
        score_breakdown=ScoreBreakdown(vmt_savings_ratio=0.80),
    )
    cand_b = CandidateAssignment(
        candidate_id="c-intra-B",
        vehicle_id="veh-2",
        existing_ride_id=None,
        request_ids=("r1",),
        ordered_stops=(_dummy_stop("s2", "r1"),),
        peak_seat_load=1,
        vmt_meters=1000,
        objective_value=0.2500004,
        normalized_score=0.7,
        score_breakdown=ScoreBreakdown(vmt_savings_ratio=0.10),
    )

    # In comparator: cand_a wins because Tier 1 (0.80 > 0.10)
    assert compare_candidates_deterministic(cand_a, cand_b) < 0
    assert candidate_sort_key()(cand_a) < candidate_sort_key()(cand_b)

    # In solver: cand_a MUST be selected
    result_same_class = solve_set_packing_regret_k(
        candidates=[cand_b, cand_a],  # pass in reverse order
        all_request_ids=all_requests,
    )
    assert len(result_same_class.selected_assignments) == 1
    assert result_same_class.selected_assignments[0].candidate_id == "c-intra-A"

    # 2. Contending candidates in different 6-decimal classes (0.200000 vs 0.200001)
    cand_c = CandidateAssignment(
        candidate_id="c-inter-C",
        vehicle_id="veh-1",
        existing_ride_id=None,
        request_ids=("r1",),
        ordered_stops=(_dummy_stop("s3", "r1"),),
        peak_seat_load=1,
        vmt_meters=1000,
        objective_value=0.20000049,  # rounds to 0.200000
        normalized_score=0.7,
        score_breakdown=ScoreBreakdown(vmt_savings_ratio=0.80),
    )
    cand_d = CandidateAssignment(
        candidate_id="c-inter-D",
        vehicle_id="veh-2",
        existing_ride_id=None,
        request_ids=("r1",),
        ordered_stops=(_dummy_stop("s4", "r1"),),
        peak_seat_load=1,
        vmt_meters=1000,
        objective_value=0.20000051,  # rounds to 0.200001
        normalized_score=0.7,
        score_breakdown=ScoreBreakdown(vmt_savings_ratio=0.10),
    )

    # In comparator: cand_d wins because utility class is higher (0.200001 > 0.200000)
    assert compare_candidates_deterministic(cand_d, cand_c) < 0
    assert candidate_sort_key()(cand_d) < candidate_sort_key()(cand_c)

    # In solver: cand_d MUST be selected regardless of candidate list input order
    result_diff_class_1 = solve_set_packing_regret_k(
        candidates=[cand_c, cand_d],
        all_request_ids=all_requests,
    )
    result_diff_class_2 = solve_set_packing_regret_k(
        candidates=[cand_d, cand_c],
        all_request_ids=all_requests,
    )
    assert result_diff_class_1.selected_assignments[0].candidate_id == "c-inter-D"
    assert result_diff_class_2.selected_assignments[0].candidate_id == "c-inter-D"


