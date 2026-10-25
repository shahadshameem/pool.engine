"""Multi-request group trip bundle generator for available vehicles."""

import itertools
import time
import uuid
from typing import Sequence

from engine.contracts.policy import DispatchPolicy
from engine.contracts.routing import (
    Coordinate,
    RoadNetworkRoutingProvider,
    RouteLookupError,
    RouteTimeoutError,
    RoutingProviderError,
    validate_route_leg,
)
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
    deadline: float | None = None,
    reserved_headroom: float = 0.050,
    max_bundle_requests: int | None = None,
    shared_leg_cache: dict[tuple[str, str], tuple[int, int] | None] | None = None,
    shared_routing_errors: list[RoutingProviderError] | None = None,
    propagate_routing_errors: bool = False,
) -> list[CandidateAssignment]:
    """
    Forms multi-passenger group trip bundles for an available vehicle.
    Evaluates combinations of 1, 2, or 3 compatible requests and prunes
    capacity, precedence, detour, and delay violations in Stage 1 using
    local directed waypoint-leg memoization and admissible prefix branch-and-bound DFS.
    """
    valid_candidates: list[CandidateAssignment] = []
    eligible_requests = [r for r in requests if r.seat_count <= vehicle.total_seat_capacity]
    if not eligible_requests:
        return []

    # Pre-compute coordinates and stable waypoint IDs for vehicle and all eligible stops
    v_stop_id = f"veh:{vehicle.vehicle_id}"
    v_coord = Coordinate(vehicle.current_location.latitude, vehicle.current_location.longitude)
    stop_coords: dict[str, Coordinate] = {v_stop_id: v_coord}
    for req in eligible_requests:
        stop_coords[f"stop-p-{req.request_id}"] = Coordinate(
            req.pickup_location.latitude, req.pickup_location.longitude
        )
        stop_coords[f"stop-d-{req.request_id}"] = Coordinate(
            req.dropoff_location.latitude, req.dropoff_location.longitude
        )

    # Leg cache: (from_id, to_id) -> (distance_meters, duration_seconds) | None
    # Keyed by stable waypoint identity; preserves directionality. None indicates unroutable leg.
    leg_cache: dict[tuple[str, str], tuple[int, int] | None] = (
        shared_leg_cache if shared_leg_cache is not None else {}
    )

    def get_cached_leg(from_id: str, to_id: str) -> tuple[int, int] | None:
        cache_key = (from_id, to_id)
        if cache_key in leg_cache:
            return leg_cache[cache_key]

        from_coord = stop_coords[from_id]
        to_coord = stop_coords[to_id]
        try:
            raw_leg = router.get_direct_leg(from_coord, to_coord)
            validated = validate_route_leg(from_coord, to_coord, raw_leg)
            leg_cache[cache_key] = validated
            return validated
        except RoutingProviderError as err:
            leg_cache[cache_key] = None
            if shared_routing_errors is not None:
                shared_routing_errors.append(err)
            if propagate_routing_errors:
                raise
            return None
        except (TimeoutError, ConnectionError) as net_err:
            wrapped = (
                RouteTimeoutError(str(net_err))
                if isinstance(net_err, TimeoutError)
                else RouteLookupError(str(net_err))
            )
            leg_cache[cache_key] = None
            if shared_routing_errors is not None:
                shared_routing_errors.append(wrapped)
            if propagate_routing_errors:
                raise wrapped from net_err
            return None

    # Pre-index stop IDs, deadlines and bounds for all eligible requests once
    req_p_id: dict[str, str] = {r.request_id: f"stop-p-{r.request_id}" for r in eligible_requests}
    req_d_id: dict[str, str] = {r.request_id: f"stop-d-{r.request_id}" for r in eligible_requests}
    req_p_deadlines: dict[str, int] = {
        r.request_id: r.earliest_pickup_time + policy.max_pickup_delay_seconds
        for r in eligible_requests
    }
    req_max_allowed_durs: dict[str, float] = {
        r.request_id: float(r.direct_duration_seconds)
        + min(
            (policy.detour_relative_multiplier - 1.0) * float(r.direct_duration_seconds),
            float(policy.detour_absolute_cap_seconds),
        )
        for r in eligible_requests
    }

    deadline_hit = False

    # Evaluate bundles of size 1, 2, ..., max_bundle_size
    for bundle_size in range(1, min(max_bundle_size, len(eligible_requests)) + 1):
        if deadline_hit:
            break
        # For multi-passenger bundles (size >= 2), restrict combinatorial combinations
        # to the top max_bundle_requests if specified. Single-request bundles (size == 1)
        # evaluate the full eligible_requests sequence.
        if bundle_size > 1 and max_bundle_requests is not None:
            combo_pool: Sequence[RideRequest] = eligible_requests[:max_bundle_requests]
        else:
            combo_pool = eligible_requests

        for req_subset in itertools.combinations(combo_pool, bundle_size):
            if deadline is not None and time.monotonic() > deadline - reserved_headroom:
                deadline_hit = True
                break

            req_list = list(req_subset)
            num_reqs = len(req_list)

            # Fast path for single-request bundles: deterministic 2-stop sequence (P -> D)
            if num_reqs == 1:
                r = req_list[0]
                p_id = req_p_id[r.request_id]
                d_id = req_d_id[r.request_id]
                leg1 = get_cached_leg(v_stop_id, p_id)
                if leg1 is None:
                    continue
                leg1_dist, leg1_dur = leg1
                arr_p = current_time + leg1_dur
                if arr_p > req_p_deadlines[r.request_id]:
                    continue
                leg2 = get_cached_leg(p_id, d_id)
                if leg2 is None:
                    continue
                leg2_dist, leg2_dur = leg2
                arr_d = arr_p + leg2_dur
                if arr_d > r.latest_dropoff_time:
                    continue
                if (arr_d - arr_p) > (req_max_allowed_durs[r.request_id] + 1e-6):
                    continue

                total_vmt = leg1_dist + leg2_dist
                baseline_vmt = calculate_unshared_vmt_baseline(req_subset)
                vmt_savings = calculate_vmt_savings(baseline_vmt=baseline_vmt, shared_vmt=total_vmt)
                s_vmt = float(vmt_savings) / float(baseline_vmt) if baseline_vmt > 0 else 0.0

                p_detour = 0.0
                total_wait = max(0, arr_p - r.earliest_pickup_time)
                p_wait = (
                    float(total_wait) / float(policy.max_pickup_delay_seconds)
                    if policy.max_pickup_delay_seconds > 0
                    else 0.0
                )
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

                stop_p = RouteStop(
                    stop_id=p_id,
                    ride_id="ride-new",
                    request_id=r.request_id,
                    stop_type=StopType.PICKUP,
                    location=r.pickup_location,
                    passenger_delta=r.seat_count,
                    scheduled_arrival_time=arr_p,
                    promised_window_start=r.earliest_pickup_time,
                    promised_window_end=r.earliest_pickup_time + policy.max_pickup_delay_seconds,
                    status=StopStatus.SCHEDULED,
                )
                stop_d = RouteStop(
                    stop_id=d_id,
                    ride_id="ride-new",
                    request_id=r.request_id,
                    stop_type=StopType.DROPOFF,
                    location=r.dropoff_location,
                    passenger_delta=-r.seat_count,
                    scheduled_arrival_time=arr_d,
                    promised_window_start=r.earliest_pickup_time,
                    promised_window_end=r.latest_dropoff_time,
                    status=StopStatus.SCHEDULED,
                )

                candidate = CandidateAssignment(
                    candidate_id=f"cand-{uuid.uuid4().hex[:8]}",
                    vehicle_id=vehicle.vehicle_id,
                    existing_ride_id=None,
                    request_ids=(r.request_id,),
                    ordered_stops=(stop_p, stop_d),
                    peak_seat_load=r.seat_count,
                    vmt_meters=total_vmt,
                    objective_value=round(j_raw, 6),
                    normalized_score=round(j_display, 4),
                    score_breakdown=score_breakdown,
                )
                valid_candidates.append(candidate)
                continue

            # Pre-index deadlines and bounds for fast lookup
            p_deadlines = [req_p_deadlines[r.request_id] for r in req_list]
            d_deadlines = [r.latest_dropoff_time for r in req_list]
            max_allowed_durs = [req_max_allowed_durs[r.request_id] for r in req_list]

            p_ids = [req_p_id[r.request_id] for r in req_list]
            d_ids = [req_d_id[r.request_id] for r in req_list]
            p_deltas = [r.seat_count for r in req_list]
            d_deltas = [-r.seat_count for r in req_list]
            p_dwells = [0] * num_reqs
            d_dwells = [0] * num_reqs

            current_stops_encoded: list[int] = []  # +(idx+1) for pickup, -(idx+1) for dropoff
            p_arr_times = [0] * num_reqs
            d_arr_times = [0] * num_reqs
            # req_status: 0 = not picked up, 1 = picked up, 2 = dropped off
            req_status = [0] * num_reqs
            step_counter = 0

            def search_bundles(
                current_occ: int,
                peak_occ: int,
                current_clock: int,
                prev_stop_id: str,
                total_vmt: int,
            ) -> None:
                nonlocal valid_candidates, deadline_hit, step_counter

                step_counter += 1
                if (
                    deadline is not None
                    and (step_counter & 31 == 0)
                    and time.monotonic() > deadline - reserved_headroom
                ):
                    deadline_hit = True
                    return

                # Admissible temporal lookahead pruning:
                # 1. Unvisited pickups: arrival cannot be earlier than current_clock.
                #    If current_clock > p_deadline, every continuation violates check_pickup_delay.
                # 2. Picked-up requests: in-vehicle duration so far is (current_clock - p_arr).
                #    If (current_clock - p_arr) > max_allowed_dur, dropoff in any continuation
                #    arrives at or after current_clock, so in-vehicle detour strictly violates check_detour_bound.
                # 3. Dropoff deadline: if current_clock > d_deadline, dropoff in any continuation
                #    arrives at or after current_clock, so latest_dropoff_time is strictly violated.
                for i in range(num_reqs):
                    if req_status[i] == 0 and current_clock > p_deadlines[i]:
                        return
                    if req_status[i] != 2 and current_clock > d_deadlines[i]:
                        return
                    if req_status[i] == 1:
                        p_arr = p_arr_times[i]
                        if (current_clock - p_arr) > (max_allowed_durs[i] + 1e-6):
                            return

                # Base case: all requests picked up and dropped off
                if all(st == 2 for st in req_status):
                    baseline_vmt = calculate_unshared_vmt_baseline(req_subset)
                    total_direct_dur = sum(r.direct_duration_seconds for r in req_subset)

                    vmt_savings = calculate_vmt_savings(baseline_vmt=baseline_vmt, shared_vmt=total_vmt)
                    s_vmt = float(vmt_savings) / float(baseline_vmt) if baseline_vmt > 0 else 0.0

                    total_detour = sum(
                        max(
                            0,
                            (d_arr_times[i] - p_arr_times[i])
                            - req_list[i].direct_duration_seconds,
                        )
                        for i in range(num_reqs)
                    )
                    p_detour = (
                        float(total_detour) / float(total_direct_dur)
                        if total_direct_dur > 0
                        else 0.0
                    )

                    total_wait = sum(
                        max(0, p_arr_times[i] - req_list[i].earliest_pickup_time)
                        for i in range(num_reqs)
                    )
                    p_wait = (
                        float(total_wait) / float(num_reqs * policy.max_pickup_delay_seconds)
                        if policy.max_pickup_delay_seconds > 0
                        else 0.0
                    )
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

                    # Build updated RouteStop instances only for confirmed feasible candidates
                    updated_stops: list[RouteStop] = []
                    for code in current_stops_encoded:
                        if code > 0:
                            idx = code - 1
                            r = req_list[idx]
                            updated_stops.append(
                                RouteStop(
                                    stop_id=p_ids[idx],
                                    ride_id="ride-new",
                                    request_id=r.request_id,
                                    stop_type=StopType.PICKUP,
                                    location=r.pickup_location,
                                    passenger_delta=p_deltas[idx],
                                    scheduled_arrival_time=p_arr_times[idx],
                                    promised_window_start=r.earliest_pickup_time,
                                    promised_window_end=r.earliest_pickup_time,
                                    status=StopStatus.SCHEDULED,
                                )
                            )
                        else:
                            idx = -code - 1
                            r = req_list[idx]
                            updated_stops.append(
                                RouteStop(
                                    stop_id=d_ids[idx],
                                    ride_id="ride-new",
                                    request_id=r.request_id,
                                    stop_type=StopType.DROPOFF,
                                    location=r.dropoff_location,
                                    passenger_delta=d_deltas[idx],
                                    scheduled_arrival_time=d_arr_times[idx],
                                    promised_window_start=r.earliest_pickup_time,
                                    promised_window_end=r.latest_dropoff_time,
                                    status=StopStatus.SCHEDULED,
                                )
                            )

                    candidate = CandidateAssignment(
                        candidate_id=f"cand-{uuid.uuid4().hex[:8]}",
                        vehicle_id=vehicle.vehicle_id,
                        existing_ride_id=None,
                        request_ids=tuple(sorted(r.request_id for r in req_list)),
                        ordered_stops=tuple(updated_stops),
                        peak_seat_load=peak_occ,
                        vmt_meters=total_vmt,
                        objective_value=round(j_raw, 6),
                        normalized_score=round(j_display, 4),
                        score_breakdown=score_breakdown,
                    )
                    valid_candidates.append(candidate)
                    return

                # Branch 1: Pickups for unvisited requests
                for i in range(num_reqs):
                    if req_status[i] == 0:
                        new_occ = current_occ + p_deltas[i]
                        if new_occ > vehicle.total_seat_capacity:
                            continue

                        p_id = p_ids[i]
                        leg = get_cached_leg(prev_stop_id, p_id)
                        if leg is None:
                            continue
                        leg_dist, leg_dur = leg
                        arr = current_clock + leg_dur
                        if arr > p_deadlines[i]:
                            continue

                        dep = arr + p_dwells[i]
                        req_status[i] = 1
                        p_arr_times[i] = arr
                        current_stops_encoded.append(i + 1)

                        search_bundles(
                            current_occ=new_occ,
                            peak_occ=max(peak_occ, new_occ),
                            current_clock=dep,
                            prev_stop_id=p_id,
                            total_vmt=total_vmt + leg_dist,
                        )

                        current_stops_encoded.pop()
                        req_status[i] = 0

                # Branch 2: Dropoffs for picked-up requests
                for i in range(num_reqs):
                    if req_status[i] == 1:
                        new_occ = current_occ + d_deltas[i]
                        d_id = d_ids[i]
                        leg = get_cached_leg(prev_stop_id, d_id)
                        if leg is None:
                            continue
                        leg_dist, leg_dur = leg
                        arr = current_clock + leg_dur
                        if arr > d_deadlines[i]:
                            continue
                        p_arr = p_arr_times[i]
                        in_veh_dur = max(0, arr - p_arr)
                        if in_veh_dur > (max_allowed_durs[i] + 1e-6):
                            continue

                        dep = arr + d_dwells[i]
                        req_status[i] = 2
                        d_arr_times[i] = arr
                        current_stops_encoded.append(-(i + 1))

                        search_bundles(
                            current_occ=new_occ,
                            peak_occ=peak_occ,
                            current_clock=dep,
                            prev_stop_id=d_id,
                            total_vmt=total_vmt + leg_dist,
                        )

                        current_stops_encoded.pop()
                        req_status[i] = 1

            search_bundles(
                current_occ=0,
                peak_occ=0,
                current_clock=current_time,
                prev_stop_id=v_stop_id,
                total_vmt=0,
            )
            if deadline_hit:
                break

    # Sort descending by objective value
    valid_candidates.sort(key=lambda c: c.objective_value, reverse=True)
    return valid_candidates
