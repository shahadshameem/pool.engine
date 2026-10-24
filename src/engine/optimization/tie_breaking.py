"""Deterministic 4-tier tie-breaking comparator for candidate assignments."""

from typing import Any

from engine.domain.candidate import CandidateAssignment

FLOAT_TOLERANCE = 1e-6


def get_candidate_sort_tuple(
    c: CandidateAssignment,
) -> tuple[float, float, float, float, str, tuple[str, ...], tuple[str, ...], str]:
    """
    Returns a deterministic canonical comparison tuple forming a strict weak ordering.
    To guarantee mathematical transitivity, input-order independence, and eliminate
    intransitive cycles during both sorting and pairwise selection, the primary utility score J
    is partitioned into 1e-6 equivalence classes: round(J, 6).
    Tiers 1, 2, 3 use exact metric values without artificial rounding.
    Tier 4 uses ASCII lexicographical ordering:
       - vehicle_id ASCII string
       - sorted request_ids ASCII tuple
       - canonical ordered_stops stop_id ASCII tuple
       - candidate_id ASCII string
    """
    return (
        -round(c.objective_value, 6),
        -c.score_breakdown.vmt_savings_ratio,
        c.score_breakdown.detour_penalty_ratio,
        c.score_breakdown.wait_penalty_ratio,
        c.vehicle_id,
        tuple(sorted(c.request_ids)),
        tuple(s.stop_id for s in c.ordered_stops),
        c.candidate_id,
    )


def compare_candidates_deterministic(
    a: CandidateAssignment,
    b: CandidateAssignment,
) -> int:
    """
    Compares two candidate assignments under the unified deterministic hierarchy:
    Returns -1 if Candidate A is superior to Candidate B (A ranks before B).
    Returns +1 if Candidate B is superior to Candidate A (B ranks before A).
    Returns 0 if candidates are completely identical.

    Strictly consistent with get_candidate_sort_tuple() to guarantee that pairwise
    selection and collection sorting never disagree, preserving mathematical transitivity,
    determinism, and input-order independence throughout the solver.
    """
    key_a = get_candidate_sort_tuple(a)
    key_b = get_candidate_sort_tuple(b)

    if key_a < key_b:
        return -1
    elif key_a > key_b:
        return 1
    return 0


def candidate_sort_key() -> Any:
    """Returns a Python sort key wrapper using get_candidate_sort_tuple."""
    return get_candidate_sort_tuple


def compare_candidates_pairwise_tolerance(
    a: CandidateAssignment,
    b: CandidateAssignment,
    tolerance: float = FLOAT_TOLERANCE,
) -> int:
    """
    Direct continuous pairwise tolerance comparator without grid quantization.
    Computes |J_A - J_B| <= tolerance continuously.
    Note: As proven by semiorder theory, this continuous pairwise relation is NOT transitive
    across 3+ candidates and cannot be used for collection sorting without causing cycles
    and input-order dependence. Provided for isolated pairwise audits and reference comparison.
    """
    diff_j = a.objective_value - b.objective_value
    if abs(diff_j) > (tolerance + 1e-12):
        return -1 if diff_j > 0.0 else 1

    diff_vmt = a.score_breakdown.vmt_savings_ratio - b.score_breakdown.vmt_savings_ratio
    if diff_vmt != 0.0:
        return -1 if diff_vmt > 0.0 else 1

    diff_detour = a.score_breakdown.detour_penalty_ratio - b.score_breakdown.detour_penalty_ratio
    if diff_detour != 0.0:
        return -1 if diff_detour < 0.0 else 1

    diff_wait = a.score_breakdown.wait_penalty_ratio - b.score_breakdown.wait_penalty_ratio
    if diff_wait != 0.0:
        return -1 if diff_wait < 0.0 else 1

    if a.vehicle_id != b.vehicle_id:
        return -1 if a.vehicle_id < b.vehicle_id else 1

    sorted_reqs_a = tuple(sorted(a.request_ids))
    sorted_reqs_b = tuple(sorted(b.request_ids))
    if sorted_reqs_a != sorted_reqs_b:
        return -1 if sorted_reqs_a < sorted_reqs_b else 1

    stops_a = tuple(s.stop_id for s in a.ordered_stops)
    stops_b = tuple(s.stop_id for s in b.ordered_stops)
    if stops_a != stops_b:
        return -1 if stops_a < stops_b else 1

    if a.candidate_id != b.candidate_id:
        return -1 if a.candidate_id < b.candidate_id else 1

    return 0



