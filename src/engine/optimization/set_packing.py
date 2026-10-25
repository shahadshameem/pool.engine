"""Fleet-wide Set Packing solver with Regret-K heuristic, monotonic deadline, and exact solver."""

import time
import uuid
from typing import Callable, Sequence

from engine.domain.candidate import CandidateAssignment
from engine.domain.enums import DispatchMode, SearchStatus
from engine.domain.models import MatchResult
from engine.optimization.tie_breaking import candidate_sort_key, compare_candidates_deterministic


def solve_set_packing_regret_k(
    candidates: Sequence[CandidateAssignment],
    all_request_ids: Sequence[str],
    deadline: float | None = None,
    reserved_headroom: float = 0.050,
    k: int = 2,
    iteration_hook: Callable[[], None] | None = None,
) -> MatchResult:
    """
    Fleet-wide Set Packing solver using the Regret-K heuristic under a single monotonic deadline.
    Guarantees conflict-free disjoint assignments and safe fallback on deadline interrupts.

    Stage 5 executes the Regret-K heuristic up to (deadline - reserved_headroom), e.g. 450ms.
    Stage 6 uses the reserved 50ms headroom for final conflict-free disjointness revalidation,
    deterministic assignment sorting, and canonical MatchResult serialization.
    """
    start_time = time.monotonic()
    batch_id = f"batch-{uuid.uuid4().hex[:8]}"
    match_id = f"match-{uuid.uuid4().hex[:8]}"

    # Default monotonic deadline: now + 500ms
    effective_deadline = deadline if deadline is not None else (start_time + 0.500)
    cutoff_time = effective_deadline - reserved_headroom

    all_req_set = set(all_request_ids)
    sorted_all_reqs = tuple(sorted(all_req_set))

    # Immediate deadline check (0 budget or past deadline)
    if start_time >= cutoff_time:
        duration_ms = (time.monotonic() - start_time) * 1000.0
        return MatchResult(
            match_id=match_id,
            batch_id=batch_id,
            solver_timestamp=int(time.time()),
            selected_assignments=(),
            unassigned_request_ids=sorted_all_reqs,
            total_vmt_savings_meters=0,
            solve_duration_ms=round(duration_ms, 2),
            search_status=SearchStatus.INCOMPLETE_DEADLINE_EXPIRED,
            is_approximated=True,
        )

    interrupted_by_deadline = False
    try:
        # Filter candidates to only valid ones belonging to the request set
        valid_candidates = [
            c for c in candidates
            if c.vehicle_id
            and c.request_ids
            and len(set(c.request_ids)) == len(c.request_ids)
            and set(c.request_ids).issubset(all_req_set)
        ]
        # Sort candidates deterministically upfront to guarantee candidate input order invariance
        sort_key = candidate_sort_key()
        valid_candidates.sort(key=sort_key)

        # Inverted index: request_id -> list of sorted candidates
        # Also vehicle_id -> list of sorted candidates
        req_to_cands: dict[str, list[CandidateAssignment]] = {r: [] for r in sorted_all_reqs}
        req_to_all_cands: dict[str, list[CandidateAssignment]] = {r: [] for r in sorted_all_reqs}
        veh_to_cands: dict[str, list[CandidateAssignment]] = {}

        for c in valid_candidates:
            for r in c.request_ids:
                req_to_cands[r].append(c)
                req_to_all_cands[r].append(c)
            if c.vehicle_id not in veh_to_cands:
                veh_to_cands[c.vehicle_id] = []
            veh_to_cands[c.vehicle_id].append(c)

        selected_assignments: list[CandidateAssignment] = []
        assigned_requests: set[str] = set()
        assigned_vehicles: set[str] = set()
        unassignable_requests: set[str] = {r for r in sorted_all_reqs if not req_to_cands[r]}

        # Cached regret state: r -> (rounded_regret, regret, c1)
        req_info: dict[str, tuple[float, float, CandidateAssignment]] = {}

        def _update_request(r: str) -> None:
            surviving = [
                c for c in req_to_cands[r]
                if c.vehicle_id not in assigned_vehicles
                and assigned_requests.isdisjoint(c.request_ids)
            ]
            req_to_cands[r] = surviving
            if not surviving:
                unassignable_requests.add(r)
                req_info.pop(r, None)
                return
            c1 = surviving[0]
            alt_idx = min(k - 1, len(surviving) - 1)
            ck = surviving[alt_idx]
            regret = c1.objective_value - ck.objective_value
            req_info[r] = (round(regret, 6), regret, c1)

        for r in sorted_all_reqs:
            if r not in unassignable_requests:
                _update_request(r)

        # Active request list maintained in deterministic sorted order
        active_reqs = [r for r in sorted_all_reqs if r in req_info]

        # =========================================================================
        # Stage 5: Regret-K Heuristic Assignment Loop (Hard Cutoff at cutoff_time)
        # =========================================================================
        while True:
            if iteration_hook is not None:
                iteration_hook()

            # Hard interrupt check: preserve reserved headroom for Stage 6 validation
            if time.monotonic() >= cutoff_time:
                interrupted_by_deadline = True
                break

            if not req_info:
                break

            # Find active request with maximum regret (deterministic ordering over sorted_all_reqs)
            best_req: str | None = None
            max_regret = -float("inf")
            rounded_max_regret = -float("inf")
            best_cand_for_best_req: CandidateAssignment | None = None

            active_reqs = [r for r in active_reqs if r in req_info]
            for r in active_reqs:
                rounded_regret, regret, c1 = req_info[r]

                # Deterministic comparison of regret and candidate tie-breaking
                regret_diff = rounded_regret - rounded_max_regret
                is_better = False
                if regret_diff > 0:
                    is_better = True
                elif regret_diff == 0:
                    if best_cand_for_best_req is not None:
                        cand_cmp = compare_candidates_deterministic(c1, best_cand_for_best_req)
                        if cand_cmp < 0:
                            is_better = True
                        elif cand_cmp == 0 and best_req is not None:
                            if r < best_req:
                                is_better = True
                    else:
                        is_better = True

                if is_better:
                    max_regret = regret
                    rounded_max_regret = rounded_regret
                    best_req = r
                    best_cand_for_best_req = c1

            # If no active request has viable candidates, assignment is complete
            if best_req is None or best_cand_for_best_req is None:
                break

            c_star = best_cand_for_best_req

            # Double check conflict freedom before committing
            if c_star.vehicle_id in assigned_vehicles or any(r in assigned_requests for r in c_star.request_ids):
                _update_request(best_req)
                continue

            # Commit selected candidate
            selected_assignments.append(c_star)
            assigned_vehicles.add(c_star.vehicle_id)
            newly_assigned_reqs = set(c_star.request_ids)
            for r in newly_assigned_reqs:
                assigned_requests.add(r)
                req_info.pop(r, None)

            # Prune only requests affected by the newly assigned vehicle or requests
            affected_requests: set[str] = set()
            for c in veh_to_cands.get(c_star.vehicle_id, []):
                affected_requests.update(c.request_ids)
            for r_assigned in newly_assigned_reqs:
                for c in req_to_all_cands.get(r_assigned, []):
                    affected_requests.update(c.request_ids)

            for r in affected_requests:
                if r not in assigned_requests and r not in unassignable_requests:
                    _update_request(r)

        # =========================================================================
        # Stage 6: Final Verification, Deterministic Tie-Breaking & Serialization
        # (Guaranteed 50ms reserved headroom)
        # =========================================================================
        deadline_expired = interrupted_by_deadline or (time.monotonic() >= cutoff_time)
        cand_status = getattr(candidates, "search_status", None)
        cand_approx = getattr(candidates, "is_approximated", False)

        if deadline_expired or cand_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED:
            effective_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
            effective_approx = True
        elif cand_status == SearchStatus.APPROXIMATED:
            effective_status = SearchStatus.APPROXIMATED
            effective_approx = True
        else:
            effective_status = SearchStatus.COMPLETE
            effective_approx = cand_approx

        # 1. Conflict-free verification: vehicles
        if len(assigned_vehicles) != len(selected_assignments):
            return MatchResult(
                match_id=match_id,
                batch_id=batch_id,
                solver_timestamp=int(time.time()),
                selected_assignments=(),
                unassigned_request_ids=sorted_all_reqs,
                total_vmt_savings_meters=0,
                solve_duration_ms=round((time.monotonic() - start_time) * 1000.0, 2),
                search_status=effective_status,
                is_approximated=effective_approx,
            )

        # 2. Conflict-free verification: requests
        all_assigned_req_list = [r for c in selected_assignments for r in c.request_ids]
        if len(assigned_requests) != len(all_assigned_req_list) or not assigned_requests.issubset(all_req_set):
            return MatchResult(
                match_id=match_id,
                batch_id=batch_id,
                solver_timestamp=int(time.time()),
                selected_assignments=(),
                unassigned_request_ids=sorted_all_reqs,
                total_vmt_savings_meters=0,
                solve_duration_ms=round((time.monotonic() - start_time) * 1000.0, 2),
                search_status=effective_status,
                is_approximated=effective_approx,
            )

        # 3. Deterministic final ordering of selected assignments
        selected_assignments.sort(key=candidate_sort_key())

        # 4. Unassigned requests accounting
        unassigned = tuple(sorted(all_req_set - assigned_requests))
        total_savings = sum(
            int(round(c.vmt_meters * c.score_breakdown.vmt_savings_ratio))
            for c in selected_assignments
        )
        duration_ms = (time.monotonic() - start_time) * 1000.0

        return MatchResult(
            match_id=match_id,
            batch_id=batch_id,
            solver_timestamp=int(time.time()),
            selected_assignments=tuple(selected_assignments),
            unassigned_request_ids=unassigned,
            total_vmt_savings_meters=total_savings,
            solve_duration_ms=round(duration_ms, 2),
            search_status=effective_status,
            is_approximated=effective_approx,
        )

    except Exception:
        # Documented Safe Fallback: verify and preserve conflict-free assignments if available,
        # otherwise return all requests safely unassigned
        duration_ms = (time.monotonic() - start_time) * 1000.0
        deadline_expired = interrupted_by_deadline or (time.monotonic() >= cutoff_time)
        cand_status = getattr(candidates, "search_status", None)
        if not deadline_expired and cand_status != SearchStatus.INCOMPLETE_DEADLINE_EXPIRED:
            raise

        status_on_error = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
        safe_assignments: tuple[CandidateAssignment, ...] = ()
        safe_unassigned: tuple[str, ...] = sorted_all_reqs
        safe_savings = 0
        try:
            assigned_vehs = {c.vehicle_id for c in selected_assignments}
            all_req_list = [r for c in selected_assignments for r in c.request_ids]
            if (
                len(assigned_vehs) == len(selected_assignments)
                and len(set(all_req_list)) == len(all_req_list)
                and set(all_req_list).issubset(all_req_set)
            ):
                safe_assignments = tuple(sorted(selected_assignments, key=candidate_sort_key()))
                safe_unassigned = tuple(sorted(all_req_set - set(all_req_list)))
                safe_savings = sum(
                    int(round(c.vmt_meters * c.score_breakdown.vmt_savings_ratio))
                    for c in safe_assignments
                )
        except Exception:
            safe_assignments = ()
            safe_unassigned = sorted_all_reqs
            safe_savings = 0

        return MatchResult(
            match_id=match_id,
            batch_id=batch_id,
            solver_timestamp=int(time.time()),
            selected_assignments=safe_assignments,
            unassigned_request_ids=safe_unassigned,
            total_vmt_savings_meters=safe_savings,
            solve_duration_ms=round(duration_ms, 2),
            search_status=status_on_error,
            is_approximated=True,
        )



def solve_exact_set_packing(
    candidates: Sequence[CandidateAssignment],
    all_request_ids: Sequence[str],
) -> MatchResult:
    """
    Exact Branch-and-Bound / Backtracking solver for small instances (N <= 50, V <= 15).
    Guarantees provably global optimal composite utility J* to evaluate empirical optimality gaps.
    """
    start_time = time.monotonic()
    all_req_set = set(all_request_ids)

    valid_cands = [
        c for c in candidates
        if c.vehicle_id
        and c.request_ids
        and len(set(c.request_ids)) == len(c.request_ids)
        and set(c.request_ids).issubset(all_req_set)
    ]
    # Sort descending by utility to prune subtrees faster
    valid_cands.sort(key=candidate_sort_key())

    best_selection: list[CandidateAssignment] = []
    best_utility = -float("inf")

    def backtrack(
        idx: int,
        current_selection: list[CandidateAssignment],
        current_utility: float,
        used_vehicles: set[str],
        used_requests: set[str],
    ) -> None:
        nonlocal best_selection, best_utility

        if current_utility > best_utility:
            best_utility = current_utility
            best_selection = list(current_selection)

        if idx >= len(valid_cands):
            return

        # Prune if upper bound cannot beat best_utility
        remaining_possible = sum(max(0.0, c.objective_value) for c in valid_cands[idx:])
        if current_utility + remaining_possible <= best_utility:
            return

        cand = valid_cands[idx]

        # Branch 1: include cand if feasible
        if cand.vehicle_id not in used_vehicles and not any(r in used_requests for r in cand.request_ids):
            used_vehicles.add(cand.vehicle_id)
            used_requests.update(cand.request_ids)
            current_selection.append(cand)

            backtrack(idx + 1, current_selection, current_utility + cand.objective_value, used_vehicles, used_requests)

            current_selection.pop()
            used_vehicles.remove(cand.vehicle_id)
            for r in cand.request_ids:
                used_requests.remove(r)

        # Branch 2: exclude cand
        backtrack(idx + 1, current_selection, current_utility, used_vehicles, used_requests)

    backtrack(0, [], 0.0, set(), set())

    # Build MatchResult
    best_selection.sort(key=candidate_sort_key())
    assigned_reqs = {r for c in best_selection for r in c.request_ids}
    unassigned = tuple(sorted(all_req_set - assigned_reqs))
    total_savings = sum(
        int(round(c.vmt_meters * c.score_breakdown.vmt_savings_ratio))
        for c in best_selection
    )
    duration_ms = (time.monotonic() - start_time) * 1000.0

    return MatchResult(
        match_id=f"exact-{uuid.uuid4().hex[:8]}",
        batch_id=f"batch-{uuid.uuid4().hex[:8]}",
        solver_timestamp=int(time.time()),
        selected_assignments=tuple(best_selection),
        unassigned_request_ids=unassigned,
        total_vmt_savings_meters=total_savings,
        solve_duration_ms=round(duration_ms, 2),
        dispatch_mode=DispatchMode.EXACT,
        search_status=SearchStatus.COMPLETE,
        is_approximated=False,
    )
