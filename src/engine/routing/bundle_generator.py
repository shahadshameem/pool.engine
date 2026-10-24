"""Multi-request group trip bundle generator for available vehicles."""

import itertools
import uuid
from typing import Sequence

from engine.contracts.policy import DispatchPolicy
from engine.contracts.routing import Coordinate, RoadNetworkRoutingProvider
from engine.domain.candidate import CandidateAssignment, ScoreBreakdown
from engine.domain.enums import StopStatus, StopType
from engine.domain.models import RideRequest, RouteStop, Vehicle
from engine.routing.invariants import (
    calculate_unshared_vmt_baseline,
    calculate_vmt_savings,
    check_capacity_profile,
    check_detour_bound,
    check_pickup_delay,
    check_precedence,
)


def _generate_valid_orderings(requests: Sequence[RideRequest]) -> list[list[RouteStop]]:
    """
    Generates all stop sequences for a set of requests where pickup precedes dropoff
    for each request. Uses recursive insertion to bound permutation growth.
    """
    if not requests:
        return []

    def make_stops_for_req(req: RideRequest) -> tuple[RouteStop, RouteStop]:
        p = RouteStop(
            stop_id=f"stop-p-{req.request_id}",
            ride_id="ride-new",
            request_id=req.request_id,
            stop_type=StopType.PICKUP,
            location=req.pickup_location,
            passenger_delta=+req.seat_count,
            scheduled_arrival_time=0,
            promised_window_start=req.earliest_pickup_time,
            promised_window_end=req.earliest_pickup_time,
            status=StopStatus.SCHEDULED,
        )
        d = RouteStop(
            stop_id=f"stop-d-{req.request_id}",
            ride_id="ride-new",
            request_id=req.request_id,
            stop_type=StopType.DROPOFF,
            location=req.dropoff_location,
            passenger_delta=-req.seat_count,
            scheduled_arrival_time=0,
            promised_window_start=req.earliest_pickup_time,
            promised_window_end=req.latest_dropoff_time,
            status=StopStatus.SCHEDULED,
        )
        return p, d

    req_stops = [make_stops_for_req(r) for r in requests]

    # Start with first request's [P, D]
    sequences: list[list[RouteStop]] = [[req_stops[0][0], req_stops[0][1]]]

    # Iteratively insert subsequent requests
    for p_stop, d_stop in req_stops[1:]:
        next_sequences: list[list[RouteStop]] = []
        for seq in sequences:
            n = len(seq)
            for i in range(n + 1):
                for j in range(i + 1, n + 2):
                    new_seq = seq[:i] + [p_stop] + seq[i : j - 1] + [d_stop] + seq[j - 1 :]
                    next_sequences.append(new_seq)
        sequences = next_sequences

    return sequences


def generate_group_bundles(
    vehicle: Vehicle,
    requests: Sequence[RideRequest],
    router: RoadNetworkRoutingProvider,
    policy: DispatchPolicy,
    current_time: int = 1700000000,
    max_bundle_size: int = 3,
) -> list[CandidateAssignment]:
    """
    Forms multi-passenger group trip bundles for an available vehicle.
    Evaluates combinations of 1, 2, or 3 compatible requests and prunes
    capacity, precedence, detour, and delay violations in Stage 1.
    """
    valid_candidates: list[CandidateAssignment] = []
    eligible_requests = [r for r in requests if r.seat_count <= vehicle.total_seat_capacity]

    # Evaluate bundles of size 1, 2, ..., max_bundle_size
    for bundle_size in range(1, min(max_bundle_size, len(eligible_requests)) + 1):
        for req_subset in itertools.combinations(eligible_requests, bundle_size):
            # Generate all orderings where pickup precedes dropoff
            orderings = _generate_valid_orderings(req_subset)

            for stops in orderings:
                # Stage 1: Fast Capacity Check
                if not check_capacity_profile(stops, capacity=vehicle.total_seat_capacity, initial_passengers=0):
                    continue

                # Stage 1: Precedence Check
                if not check_precedence(stops):
                    continue

                # Road network routing evaluation
                waypoints = [
                    Coordinate(vehicle.current_location.latitude, vehicle.current_location.longitude)
                ] + [
                    Coordinate(s.location.latitude, s.location.longitude)
                    for s in stops
                ]

                current_clock = current_time
                total_vmt = 0
                arrival_times: dict[str, int] = {}
                updated_stops: list[RouteStop] = []
                feasible = True

                curr_occ = 0
                peak_occ = 0

                for idx, stop in enumerate(stops):
                    leg_dist, leg_dur = router.get_direct_leg(waypoints[idx], waypoints[idx + 1])
                    total_vmt += leg_dist
                    current_clock += leg_dur

                    curr_occ += stop.passenger_delta
                    if curr_occ > peak_occ:
                        peak_occ = curr_occ

                    arrival_times[stop.stop_id] = current_clock
                    current_clock += stop.dwell_duration_seconds

                    updated_stops.append(
                        RouteStop(
                            stop_id=stop.stop_id,
                            ride_id=stop.ride_id,
                            request_id=stop.request_id,
                            stop_type=stop.stop_type,
                            location=stop.location,
                            passenger_delta=stop.passenger_delta,
                            scheduled_arrival_time=arrival_times[stop.stop_id],
                            promised_window_start=stop.promised_window_start,
                            promised_window_end=stop.promised_window_end,
                            status=stop.status,
                        )
                    )

                # Check temporal bounds for each request in the bundle
                for req in req_subset:
                    p_id = f"stop-p-{req.request_id}"
                    d_id = f"stop-d-{req.request_id}"
                    p_time = arrival_times[p_id]
                    d_time = arrival_times[d_id]

                    if not check_pickup_delay(
                        actual_pickup_time=p_time,
                        requested_pickup_time=req.earliest_pickup_time,
                        max_delay=policy.max_pickup_delay_seconds,
                    ):
                        feasible = False
                        break

                    in_veh_dur = max(0, d_time - p_time)
                    if not check_detour_bound(
                        actual_duration=in_veh_dur,
                        direct_duration=req.direct_duration_seconds,
                        policy=policy,
                    ):
                        feasible = False
                        break

                if not feasible:
                    continue

                # Scoring calculation
                baseline_vmt = calculate_unshared_vmt_baseline(req_subset)
                vmt_savings = calculate_vmt_savings(baseline_vmt=baseline_vmt, shared_vmt=total_vmt)
                s_vmt = float(vmt_savings) / float(baseline_vmt) if baseline_vmt > 0 else 0.0

                total_detour = sum(
                    max(0, (arrival_times[f"stop-d-{r.request_id}"] - arrival_times[f"stop-p-{r.request_id}"]) - r.direct_duration_seconds)
                    for r in req_subset
                )
                total_direct_dur = sum(r.direct_duration_seconds for r in req_subset)
                p_detour = float(total_detour) / float(total_direct_dur) if total_direct_dur > 0 else 0.0

                total_wait = sum(
                    max(0, arrival_times[f"stop-p-{r.request_id}"] - r.earliest_pickup_time)
                    for r in req_subset
                )
                p_wait = float(total_wait) / float(len(req_subset) * policy.max_pickup_delay_seconds) if policy.max_pickup_delay_seconds > 0 else 0.0

                p_idle = 0.0

                j_raw = (
                    policy.weight_vmt_reduction * s_vmt
                    - policy.weight_passenger_detour * p_detour
                    - policy.weight_passenger_wait * p_wait
                    - policy.weight_driver_idle * p_idle
                )
                j_display = max(0.0, min(1.0, j_raw + (1.0 - policy.weight_vmt_reduction)))

                score_breakdown = ScoreBreakdown(
                    vmt_savings_ratio=round(s_vmt, 6),
                    detour_penalty_ratio=round(p_detour, 6),
                    wait_penalty_ratio=round(p_wait, 6),
                    driver_idle_penalty_ratio=round(p_idle, 6),
                )

                candidate = CandidateAssignment(
                    candidate_id=f"cand-{uuid.uuid4().hex[:8]}",
                    vehicle_id=vehicle.vehicle_id,
                    existing_ride_id=None,
                    request_ids=tuple(sorted([r.request_id for r in req_subset])),
                    ordered_stops=tuple(updated_stops),
                    peak_seat_load=peak_occ,
                    vmt_meters=total_vmt,
                    objective_value=round(j_raw, 6),
                    normalized_score=round(j_display, 4),
                    score_breakdown=score_breakdown,
                )
                valid_candidates.append(candidate)

    # Sort descending by objective value
    valid_candidates.sort(key=lambda c: c.objective_value, reverse=True)
    return valid_candidates
