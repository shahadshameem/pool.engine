"""Small-instance exact solver comparison tests and empirical optimality gap (T032)."""

import pytest

from engine.domain.candidate import CandidateAssignment, ScoreBreakdown
from engine.domain.enums import StopStatus, StopType
from engine.domain.models import GeoCoordinate, RouteStop
from engine.optimization.set_packing import solve_exact_set_packing, solve_set_packing_regret_k


def _dummy_stop(stop_id: str, req_id: str) -> RouteStop:
    return RouteStop(
        stop_id=stop_id,
        ride_id="ride-opt",
        request_id=req_id,
        stop_type=StopType.PICKUP,
        location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        passenger_delta=1,
        scheduled_arrival_time=1700000000,
        promised_window_start=1700000000,
        promised_window_end=1700001000,
        status=StopStatus.SCHEDULED,
    )


def _build_candidate(cand_id: str, veh_id: str, req_ids: tuple[str, ...], obj_val: float) -> CandidateAssignment:
    stops = tuple(_dummy_stop(f"s-{cand_id}-{r}", r) for r in req_ids)
    return CandidateAssignment(
        candidate_id=cand_id,
        vehicle_id=veh_id,
        existing_ride_id=None,
        request_ids=req_ids,
        ordered_stops=stops,
        peak_seat_load=len(req_ids),
        vmt_meters=1000 * len(req_ids),
        objective_value=obj_val,
        normalized_score=max(0.0, min(1.0, obj_val + 0.6)),
        score_breakdown=ScoreBreakdown(vmt_savings_ratio=0.3),
    )


def test_optimality_gap_sparse_regime() -> None:
    """
    Sparse regime: 6 requests, 4 vehicles, mostly non-overlapping candidates.
    Heuristic should match or closely approximate exact optimal.
    """
    all_requests = [f"r{i}" for i in range(1, 7)]
    candidates = [
        _build_candidate("c1", "v1", ("r1", "r2"), 0.35),
        _build_candidate("c2", "v2", ("r3", "r4"), 0.32),
        _build_candidate("c3", "v3", ("r5",), 0.15),
        _build_candidate("c4", "v4", ("r6",), 0.18),
    ]

    exact_res = solve_exact_set_packing(candidates=candidates, all_request_ids=all_requests)
    heur_res = solve_set_packing_regret_k(candidates=candidates, all_request_ids=all_requests)

    j_exact = sum(c.objective_value for c in exact_res.selected_assignments)
    j_heur = sum(c.objective_value for c in heur_res.selected_assignments)

    assert j_heur <= j_exact + 1e-6
    # In sparse non-overlapping regime, heuristic finds the global optimum
    gap = (j_exact - j_heur) / j_exact if j_exact > 0 else 0.0
    assert gap == pytest.approx(0.0, abs=1e-6)


def test_optimality_gap_dense_regime() -> None:
    """
    Dense regime: 8 requests contending across 3 vehicles with overlapping bundle choices.
    Evaluates empirical optimality gap: (J*_exact - J_heuristic) / J*_exact.
    Notice: Optimality verified on this fixture does NOT imply a universal mathematical guarantee for large batches.
    """
    all_requests = [f"r{i}" for i in range(1, 9)]
    candidates = [
        # Vehicle 1 choices
        _build_candidate("c1_a", "v1", ("r1", "r2"), 0.30),
        _build_candidate("c1_b", "v1", ("r1", "r3"), 0.34),
        _build_candidate("c1_c", "v1", ("r2", "r4"), 0.28),
        # Vehicle 2 choices
        _build_candidate("c2_a", "v2", ("r3", "r4"), 0.25),
        _build_candidate("c2_b", "v2", ("r4", "r5"), 0.31),
        _build_candidate("c2_c", "v2", ("r5", "r6"), 0.29),
        # Vehicle 3 choices
        _build_candidate("c3_a", "v3", ("r6", "r7"), 0.33),
        _build_candidate("c3_b", "v3", ("r7", "r8"), 0.35),
        _build_candidate("c3_c", "v3", ("r6", "r8"), 0.32),
    ]

    exact_res = solve_exact_set_packing(candidates=candidates, all_request_ids=all_requests)
    heur_res = solve_set_packing_regret_k(candidates=candidates, all_request_ids=all_requests)

    j_exact = sum(c.objective_value for c in exact_res.selected_assignments)
    j_heur = sum(c.objective_value for c in heur_res.selected_assignments)

    assert j_heur <= j_exact + 1e-6
    gap = (j_exact - j_heur) / j_exact if j_exact > 0 else 0.0
    # Heuristic gap on dense test fixture should be within 10%
    assert gap <= 0.10


def test_optimality_gap_constrained_regime() -> None:
    """
    Constrained regime: 10 requests, only 2 vehicles.
    Multiple requests cannot be served and must be returned cleanly to unassigned queue.
    """
    all_requests = [f"r{i}" for i in range(1, 11)]
    candidates = [
        _build_candidate("c1_big", "v1", ("r1", "r2", "r3"), 0.40),
        _build_candidate("c1_small", "v1", ("r1", "r4"), 0.25),
        _build_candidate("c2_big", "v2", ("r4", "r5", "r6"), 0.38),
        _build_candidate("c2_alt", "v2", ("r7", "r8"), 0.30),
    ]

    exact_res = solve_exact_set_packing(candidates=candidates, all_request_ids=all_requests)
    heur_res = solve_set_packing_regret_k(candidates=candidates, all_request_ids=all_requests)

    j_exact = sum(c.objective_value for c in exact_res.selected_assignments)
    j_heur = sum(c.objective_value for c in heur_res.selected_assignments)

    assert j_heur <= j_exact + 1e-6
    gap = (j_exact - j_heur) / j_exact if j_exact > 0 else 0.0
    assert gap <= 0.15

    # Check unassigned requests count
    assigned_count = sum(len(c.request_ids) for c in heur_res.selected_assignments)
    assert len(heur_res.unassigned_request_ids) == len(all_requests) - assigned_count


# Alias matching quickstart validation guide
test_ilp_reference_gap = test_optimality_gap_constrained_regime

