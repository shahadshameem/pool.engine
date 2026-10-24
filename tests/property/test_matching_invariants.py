"""Property-based tests for deterministic batch optimization invariants (T031)."""

from hypothesis import given, strategies as st

from engine.domain.candidate import CandidateAssignment, ScoreBreakdown
from engine.domain.enums import StopStatus, StopType
from engine.domain.models import GeoCoordinate, RouteStop
from engine.optimization.set_packing import solve_set_packing_regret_k


def _dummy_stop(stop_id: str, req_id: str) -> RouteStop:
    return RouteStop(
        stop_id=stop_id,
        ride_id="ride-prop",
        request_id=req_id,
        stop_type=StopType.PICKUP,
        location=GeoCoordinate(latitude=40.0, longitude=-74.0),
        passenger_delta=1,
        scheduled_arrival_time=1700000000,
        promised_window_start=1700000000,
        promised_window_end=1700001000,
        status=StopStatus.SCHEDULED,
    )


@st.composite
def random_candidate_pool_strategy(draw: st.DrawFn) -> tuple[list[CandidateAssignment], list[str]]:
    """Generates randomized candidate assignment bundles with possible vehicle and request contention."""
    num_requests = draw(st.integers(min_value=2, max_value=8))
    num_vehicles = draw(st.integers(min_value=1, max_value=4))
    num_candidates = draw(st.integers(min_value=1, max_value=15))

    request_ids = [f"req-{i}" for i in range(num_requests)]
    vehicle_ids = [f"veh-{j}" for j in range(num_vehicles)]

    candidates: list[CandidateAssignment] = []
    for c_idx in range(num_candidates):
        v_id = draw(st.sampled_from(vehicle_ids))
        bundle_size = draw(st.integers(min_value=1, max_value=min(3, num_requests)))
        c_reqs = tuple(sorted(draw(st.lists(st.sampled_from(request_ids), min_size=bundle_size, max_size=bundle_size, unique=True))))
        if not c_reqs:
            continue
        obj_val = draw(st.floats(min_value=-0.5, max_value=0.4))
        stops = tuple(_dummy_stop(f"s-{c_idx}-{r}", r) for r in c_reqs)

        candidate = CandidateAssignment(
            candidate_id=f"cand-{c_idx}",
            vehicle_id=v_id,
            existing_ride_id=None,
            request_ids=c_reqs,
            ordered_stops=stops,
            peak_seat_load=len(c_reqs),
            vmt_meters=1000 * len(c_reqs),
            objective_value=obj_val,
            normalized_score=max(0.0, min(1.0, obj_val + 0.6)),
            score_breakdown=ScoreBreakdown(),
        )
        candidates.append(candidate)

    return candidates, request_ids


@given(data=random_candidate_pool_strategy())
def test_property_solver_determinism_and_conflict_free_assignments(
    data: tuple[list[CandidateAssignment], list[str]]
) -> None:
    candidates, all_requests = data

    # Run solver twice on identical inputs
    result_1 = solve_set_packing_regret_k(candidates=candidates, all_request_ids=all_requests)
    result_2 = solve_set_packing_regret_k(candidates=candidates, all_request_ids=all_requests)

    # 1. Determinism: bit-for-bit identical winning candidates in both runs
    assert len(result_1.selected_assignments) == len(result_2.selected_assignments)
    cands_1 = [c.candidate_id for c in result_1.selected_assignments]
    cands_2 = [c.candidate_id for c in result_2.selected_assignments]
    assert cands_1 == cands_2
    assert result_1.unassigned_request_ids == result_2.unassigned_request_ids

    # 2. Invariant: Disjoint Requests (no request assigned to more than one vehicle)
    assigned_requests: list[str] = []
    assigned_vehicles: list[str] = []
    for winning_bundle in result_1.selected_assignments:
        for r_id in winning_bundle.request_ids:
            assigned_requests.append(r_id)
        assigned_vehicles.append(winning_bundle.vehicle_id)

    # Every request appears at most once
    assert len(assigned_requests) == len(set(assigned_requests))

    # Every vehicle appears at most once
    assert len(assigned_vehicles) == len(set(assigned_vehicles))

    # 3. Unassigned requests completeness: assigned + unassigned == all_requests
    expected_all = set(all_requests)
    actual_all = set(assigned_requests) | set(result_1.unassigned_request_ids)
    assert actual_all.issubset(expected_all)
