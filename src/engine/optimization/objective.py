"""Multi-objective utility scoring, display normalization, and breakdown computation."""

from typing import Sequence

from engine.contracts.policy import DispatchPolicy
from engine.domain.candidate import ScoreBreakdown
from engine.domain.models import RideRequest


def calculate_objective_utility(
    s_vmt: float,
    p_detour: float,
    p_wait: float,
    p_idle: float,
    policy: DispatchPolicy,
) -> float:
    """
    Computes composite raw utility J:
    J = w_vmt * S_vmt - w_detour * P_detour - w_wait * P_wait - w_idle * P_idle.
    Raw range: [-(1.0 - w_vmt), +w_vmt], for default weights: [-0.60, +0.40].
    Validates policy weights and enforces bounds on component metrics.
    """
    policy.validate()

    clamped_s_vmt = max(0.0, min(1.0, s_vmt))
    clamped_p_detour = max(0.0, min(1.0, p_detour))
    clamped_p_wait = max(0.0, min(1.0, p_wait))
    clamped_p_idle = max(0.0, min(1.0, p_idle))

    return (
        policy.weight_vmt_reduction * clamped_s_vmt
        - policy.weight_passenger_detour * clamped_p_detour
        - policy.weight_passenger_wait * clamped_p_wait
        - policy.weight_driver_idle * clamped_p_idle
    )


def calculate_display_score(
    raw_utility: float,
    policy: DispatchPolicy,
) -> float:
    """
    Normalizes raw utility J into [0.0, 1.0] display score:
    J_display = J + (1.0 - w_vmt), clamped strictly to [0.0, 1.0].
    """
    policy.validate()
    normalized = raw_utility + (1.0 - policy.weight_vmt_reduction)
    return max(0.0, min(1.0, normalized))


def calculate_candidate_score(
    vmt_baseline: int,
    vmt_pooled: int,
    requests: Sequence[RideRequest],
    arrival_times: dict[str, int],
    idle_time_seconds: int = 0,
    shift_time_seconds: int = 0,
    policy: DispatchPolicy | None = None,
) -> tuple[float, float, ScoreBreakdown]:
    """
    Calculates itemized ScoreBreakdown, raw utility J, and normalized display score.
    Enforces non-negative baseline handling, bounded penalty normalization,
    and strict policy parameter validation.
    """
    active_policy = policy if policy is not None else DispatchPolicy()
    active_policy.validate()

    # 1. VMT reduction ratio: S_vmt in [0.0, 1.0]
    if vmt_baseline > 0:
        vmt_savings = max(0, vmt_baseline - vmt_pooled)
        s_vmt = max(0.0, min(1.0, float(vmt_savings) / float(vmt_baseline)))
    else:
        s_vmt = 0.0

    # 2. Detour penalty ratio: P_detour in [0.0, 1.0]
    detour_penalties: list[float] = []
    for req in requests:
        p_id = f"stop-p-{req.request_id}"
        d_id = f"stop-d-{req.request_id}"
        if p_id in arrival_times and d_id in arrival_times:
            in_veh_dur = max(0, arrival_times[d_id] - arrival_times[p_id])
            detour_secs = max(0, in_veh_dur - req.direct_duration_seconds)
            max_allowed_detour = min(
                (active_policy.detour_relative_multiplier - 1.0) * req.direct_duration_seconds,
                float(active_policy.detour_absolute_cap_seconds),
            )
            pen = float(detour_secs) / max_allowed_detour if max_allowed_detour > 0 else 0.0
            detour_penalties.append(max(0.0, min(1.0, pen)))
        else:
            detour_penalties.append(0.0)

    p_detour = (sum(detour_penalties) / float(len(detour_penalties))) if detour_penalties else 0.0
    p_detour = max(0.0, min(1.0, p_detour))

    # 3. Wait penalty ratio: P_wait in [0.0, 1.0]
    wait_penalties: list[float] = []
    for req in requests:
        p_id = f"stop-p-{req.request_id}"
        if p_id in arrival_times:
            wait_secs = max(0, arrival_times[p_id] - req.earliest_pickup_time)
            max_delay = float(active_policy.max_pickup_delay_seconds)
            pen = float(wait_secs) / max_delay if max_delay > 0 else 0.0
            wait_penalties.append(max(0.0, min(1.0, pen)))
        else:
            wait_penalties.append(0.0)

    p_wait = (sum(wait_penalties) / float(len(wait_penalties))) if wait_penalties else 0.0
    p_wait = max(0.0, min(1.0, p_wait))

    # 4. Driver idle penalty: P_idle in [0.0, 1.0]
    if shift_time_seconds > 0:
        p_idle = max(0.0, min(1.0, float(max(0, idle_time_seconds)) / float(shift_time_seconds)))
    else:
        p_idle = 0.0

    j_raw = calculate_objective_utility(
        s_vmt=s_vmt,
        p_detour=p_detour,
        p_wait=p_wait,
        p_idle=p_idle,
        policy=active_policy,
    )
    j_display = calculate_display_score(j_raw, active_policy)

    breakdown = ScoreBreakdown(
        vmt_savings_ratio=round(s_vmt, 6),
        detour_penalty_ratio=round(p_detour, 6),
        wait_penalty_ratio=round(p_wait, 6),
        driver_idle_penalty_ratio=round(p_idle, 6),
    )

    return j_raw, j_display, breakdown

