"""Stop insertion permutations generator and Stage 1 pruning for active rides."""

import itertools
import time
import uuid
from typing import Sequence

from engine.contracts.policy import DispatchPolicy
from engine.contracts.routing import Coordinate, RoadNetworkRoutingProvider
from engine.domain.candidate import CandidateAssignment, ScoreBreakdown
from engine.domain.enums import StopStatus, StopType
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle
from engine.routing.invariants import (
    calculate_unshared_vmt_baseline,
    calculate_vmt_savings,
    check_capacity_profile,
    check_detour_bound,
    check_pickup_delay,
    check_precedence,
)


def _generate_valid_active_orderings(
    existing_stops: Sequence[RouteStop],
    req_stop_pairs: Sequence[tuple[RouteStop, RouteStop]],
    capacity: int,
    initial_passengers: int,
) -> list[list[RouteStop]]:
    """
    Generates all stop sequences resulting from inserting a bundle of request
    stop pairs into an active ride's existing stops.
    Preserves the relative ordering of existing stops and ensures pickup
    precedes dropoff for each request.
    Applies early intermediate capacity profile pruning to eliminate infeasible branches.
    """
    sequences: list[list[RouteStop]] = [list(existing_stops)]
    for p_stop, d_stop in req_stop_pairs:
        next_sequences: list[list[RouteStop]] = []
        for seq in sequences:
            n = len(seq)
            for i in range(n + 1):
                for j in range(i + 1, n + 2):
                    candidate_stops = seq[:i] + [p_stop] + seq[i : j - 1] + [d_stop] + seq[j - 1 :]
                    if check_capacity_profile(
                        candidate_stops,
                        capacity=capacity,
                        initial_passengers=initial_passengers,
                    ):
                        next_sequences.append(candidate_stops)
        sequences = next_sequences
    return sequences


def generate_active_ride_insertions(
    active_ride: Ride,
    requests: Sequence[RideRequest],
    vehicle: Vehicle,
    router: RoadNetworkRoutingProvider,
    policy: DispatchPolicy,
    current_time: int | None = None,
    max_bundle_size: int = 2,
    deadline: float | None = None,
    reserved_headroom: float = 0.050,
    max_bundle_requests: int | None = None,
    shared_leg_cache: dict[tuple[str, str], tuple[int, int]] | None = None,
) -> list[CandidateAssignment]:
    """
    Generates and evaluates all valid stop insertion permutations for single requests
    and multi-request bundles (up to max_bundle_size) into an active ride.
    Prunes capacity, precedence, detour, and delay violations in Stage 1.
    """
    t_start = current_time if current_time is not None else active_ride.scheduled_departure_time
    # Exclude historical stops (COMPLETED, SKIPPED, NO_SHOW) so they are not treated as future route waypoints
    pending_future_stops = [
        s for s in active_ride.stops
        if s.status in (StopStatus.SCHEDULED, StopStatus.ARRIVED, StopStatus.IN_GRACE_PERIOD)
    ]
    existing_stops = pending_future_stops
    existing_stop_ids = {s.stop_id for s in existing_stops}

    # Pre-compute Coordinate for vehicle and existing stops
    v_stop_id = f"veh:{vehicle.vehicle_id}"
    v_coord = Coordinate(vehicle.current_location.latitude, vehicle.current_location.longitude)
    existing_coords = {
        s.stop_id: Coordinate(s.location.latitude, s.location.longitude)
        for s in existing_stops
    }

    stop_coords: dict[str, Coordinate] = dict(existing_coords)
    stop_coords[v_stop_id] = v_coord

    # Leg cache: (from_id, to_id) -> (distance_meters, duration_seconds)
    # Keyed by stable waypoint identity; preserves directionality unless router itself guarantees symmetry.
    leg_cache: dict[tuple[str, str], tuple[int, int]] = (
        shared_leg_cache if shared_leg_cache is not None else {}
    )

    def get_cached_leg(from_id: str, to_id: str) -> tuple[int, int]:
        cache_key = (from_id, to_id)
        cached = leg_cache.get(cache_key)
        if cached is None:
            cached = router.get_direct_leg(stop_coords[from_id], stop_coords[to_id])
            leg_cache[cache_key] = cached
        return cached

    # Compute unshared remaining baseline VMT from vehicle's current location through outstanding stops
    remaining_existing_stop_ids = [v_stop_id] + [s.stop_id for s in existing_stops]
    remaining_existing_vmt = 0
    for idx in range(len(existing_stops)):
        leg_dist, _ = get_cached_leg(remaining_existing_stop_ids[idx], remaining_existing_stop_ids[idx + 1])
        remaining_existing_vmt += leg_dist

    eligible_requests = [r for r in requests if r.seat_count <= vehicle.total_seat_capacity]
    if not eligible_requests:
        return []

    candidates: list[CandidateAssignment] = []

    def make_req_stops(req: RideRequest) -> tuple[RouteStop, RouteStop]:
        p = RouteStop(
            stop_id=f"stop-p-{req.request_id}",
            ride_id=active_ride.ride_id,
            request_id=req.request_id,
            stop_type=StopType.PICKUP,
            location=req.pickup_location,
            passenger_delta=+req.seat_count,
            scheduled_arrival_time=0,
            promised_window_start=req.earliest_pickup_time,
            promised_window_end=req.earliest_pickup_time + policy.max_pickup_delay_seconds,
            status=StopStatus.SCHEDULED,
        )
        d = RouteStop(
            stop_id=f"stop-d-{req.request_id}",
            ride_id=active_ride.ride_id,
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

    # Precompute existing dropoff detour baseline data outside loops
    existing_dropoff_detour_data: list[tuple[str, str, int, int]] = []
    for existing_stop in existing_stops:
        if existing_stop.stop_type == StopType.DROPOFF:
            p_match = next(
                (s for s in active_ride.stops if s.request_id == existing_stop.request_id and s.stop_type == StopType.PICKUP),
                None,
            )
            if p_match is not None:
                orig_p_time = p_match.actual_arrival_time or p_match.scheduled_arrival_time
                orig_duration = max(0, existing_stop.scheduled_arrival_time - orig_p_time)
                if orig_duration > 0:
                    existing_dropoff_detour_data.append(
                        (existing_stop.stop_id, p_match.stop_id, orig_p_time, orig_duration)
                    )

    # Pre-compute request stops and coordinates
    req_stops_dict: dict[str, tuple[RouteStop, RouteStop]] = {
        r.request_id: make_req_stops(r) for r in eligible_requests
    }
    for r in eligible_requests:
        p_stop, d_stop = req_stops_dict[r.request_id]
        stop_coords[p_stop.stop_id] = Coordinate(p_stop.location.latitude, p_stop.location.longitude)
        stop_coords[d_stop.stop_id] = Coordinate(d_stop.location.latitude, d_stop.location.longitude)

    # Pre-index stop IDs, deadlines and bounds for all eligible requests once
    req_p_ids: dict[str, str] = {r.request_id: f"stop-p-{r.request_id}" for r in eligible_requests}
    req_d_ids: dict[str, str] = {r.request_id: f"stop-d-{r.request_id}" for r in eligible_requests}
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

    # Precompute existing stop metadata for array indexing
    num_existing = len(existing_stops)
    ex_stop_ids = [s.stop_id for s in existing_stops]
    ex_deltas = [s.passenger_delta for s in existing_stops]
    ex_dwells = [s.dwell_duration_seconds for s in existing_stops]
    ex_deadlines = [s.promised_window_end for s in existing_stops]
    ex_is_dropoff = [s.stop_type == StopType.DROPOFF for s in existing_stops]

    ex_p_match_idx: list[int | None] = []
    ex_orig_p_times: list[int] = []
    ex_orig_durations: list[int] = []
    for ex_idx, s in enumerate(existing_stops):
        if s.stop_type == StopType.DROPOFF:
            p_match = next(
                (p for p in active_ride.stops if p.request_id == s.request_id and p.stop_type == StopType.PICKUP),
                None,
            )
            if p_match is not None:
                orig_p = p_match.actual_arrival_time or p_match.scheduled_arrival_time
                orig_dur = max(0, s.scheduled_arrival_time - orig_p)
                p_in_ex = next((idx for idx, st in enumerate(existing_stops) if st.stop_id == p_match.stop_id), None)
                ex_p_match_idx.append(p_in_ex)
                ex_orig_p_times.append(orig_p)
                ex_orig_durations.append(orig_dur)
            else:
                ex_p_match_idx.append(None)
                ex_orig_p_times.append(0)
                ex_orig_durations.append(0)
        else:
            ex_p_match_idx.append(None)
            ex_orig_p_times.append(0)
            ex_orig_durations.append(0)

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

            # DFS branch-and-bound with admissible temporal and capacity pruning
            num_reqs = len(req_subset)
            req_list = list(req_subset)

            # Pre-index deadlines and stop pairs for fast lookup
            p_deadlines = [req_p_deadlines[r.request_id] for r in req_list]
            d_deadlines = [r.latest_dropoff_time for r in req_list]
            max_allowed_durs = [req_max_allowed_durs[r.request_id] for r in req_list]

            subset_p_ids = [req_p_ids[r.request_id] for r in req_list]
            subset_d_ids = [req_d_ids[r.request_id] for r in req_list]
            p_deltas = [r.seat_count for r in req_list]
            d_deltas = [-r.seat_count for r in req_list]

            current_stops_encoded: list[int] = []
            ex_arr_times = [0] * num_existing
            p_arr_times = [0] * num_reqs
            d_arr_times = [0] * num_reqs
            # req_status: 0 = not picked up, 1 = picked up, 2 = dropped off
            req_status = [0] * num_reqs
            step_counter = 0

            def search_insertions(
                ex_idx: int,
                current_occ: int,
                peak_occ: int,
                current_clock: int,
                prev_stop_id: str,
                total_vmt: int,
            ) -> None:
                nonlocal candidates, deadline_hit, step_counter

                step_counter += 1
                if (
                    deadline is not None
                    and (step_counter & 31 == 0)
                    and time.monotonic() > deadline - reserved_headroom
                ):
                    deadline_hit = True
                    return

                # Admissible temporal check:
                # Monotonicity of time: all remaining unvisited stops must be visited at or after current_clock.
                # 1. Unvisited pickups: arrival cannot be earlier than current_clock.
                #    If current_clock > p_deadline, every continuation violates check_pickup_delay.
                # 2. Dropoff deadline: if current_clock > d_deadline, dropoff in any continuation
                #    arrives at or after current_clock, so latest_dropoff_time is strictly violated.
                # 3. Picked-up requests: in-vehicle duration so far is (current_clock - p_arr).
                #    If (current_clock - p_arr) > max_allowed_dur, dropoff in any continuation
                #    arrives at or after current_clock, so in-vehicle detour strictly violates check_detour_bound.
                # 4. Unvisited existing dropoffs: arrival cannot be earlier than current_clock.
                #    If current_clock > promised_window_end, every continuation violates the promise.
                for i in range(num_reqs):
                    if req_status[i] == 0 and current_clock > p_deadlines[i]:
                        return
                    if req_status[i] != 2 and current_clock > d_deadlines[i]:
                        return
                    if req_status[i] == 1 and (current_clock - p_arr_times[i]) > (max_allowed_durs[i] + 1e-6):
                        return
                for j in range(ex_idx, num_existing):
                    if ex_is_dropoff[j] and current_clock > ex_deadlines[j]:
                        return

                # Base case: all existing stops and all requests have been placed
                if ex_idx == num_existing and all(st == 2 for st in req_status):
                    # Create updated RouteStop instances only for confirmed feasible candidates
                    updated_stops: list[RouteStop] = []
                    for code in current_stops_encoded:
                        if code >= 1000:
                            j = code - 1000
                            s = existing_stops[j]
                            updated_stops.append(
                                RouteStop(
                                    stop_id=s.stop_id,
                                    ride_id=active_ride.ride_id,
                                    request_id=s.request_id,
                                    stop_type=s.stop_type,
                                    location=s.location,
                                    passenger_delta=s.passenger_delta,
                                    scheduled_arrival_time=ex_arr_times[j],
                                    promised_window_start=s.promised_window_start,
                                    promised_window_end=s.promised_window_end,
                                    dwell_duration_seconds=s.dwell_duration_seconds,
                                    status=s.status,
                                )
                            )
                        elif code > 0:
                            i = code - 1
                            r = req_list[i]
                            updated_stops.append(
                                RouteStop(
                                    stop_id=subset_p_ids[i],
                                    ride_id=active_ride.ride_id,
                                    request_id=r.request_id,
                                    stop_type=StopType.PICKUP,
                                    location=r.pickup_location,
                                    passenger_delta=p_deltas[i],
                                    scheduled_arrival_time=p_arr_times[i],
                                    promised_window_start=r.earliest_pickup_time,
                                    promised_window_end=p_deadlines[i],
                                    dwell_duration_seconds=0,
                                    status=StopStatus.SCHEDULED,
                                )
                            )
                        else:
                            i = (-code) - 1
                            r = req_list[i]
                            updated_stops.append(
                                RouteStop(
                                    stop_id=subset_d_ids[i],
                                    ride_id=active_ride.ride_id,
                                    request_id=r.request_id,
                                    stop_type=StopType.DROPOFF,
                                    location=r.dropoff_location,
                                    passenger_delta=d_deltas[i],
                                    scheduled_arrival_time=d_arr_times[i],
                                    promised_window_start=r.earliest_pickup_time,
                                    promised_window_end=d_deadlines[i],
                                    dwell_duration_seconds=0,
                                    status=StopStatus.SCHEDULED,
                                )
                            )

                    # Compute baseline unshared VMT and savings ratio
                    baseline_vmt = remaining_existing_vmt + sum(r.direct_distance_meters for r in req_subset)
                    vmt_savings = calculate_vmt_savings(baseline_vmt=baseline_vmt, shared_vmt=total_vmt)
                    s_vmt = float(vmt_savings) / float(baseline_vmt) if baseline_vmt > 0 else 0.0

                    # Penalties
                    total_direct_dur = sum(r.direct_duration_seconds for r in req_subset)
                    total_detour = sum(
                        max(0, (d_arr_times[i] - p_arr_times[i]) - req_list[i].direct_duration_seconds)
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
                        float(total_wait) / float(len(req_subset) * policy.max_pickup_delay_seconds)
                        if policy.max_pickup_delay_seconds > 0
                        else 0.0
                    )

                    p_idle = 0.0

                    # Composite objective utility J
                    j_raw = (
                        policy.weight_vmt_reduction * s_vmt
                        - policy.weight_passenger_detour * p_detour
                        - policy.weight_passenger_wait * p_wait
                        - policy.weight_driver_idle * p_idle
                    )
                    # Display score normalized to [0.0, 1.0]
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
                        existing_ride_id=active_ride.ride_id,
                        request_ids=tuple(sorted(r.request_id for r in req_subset)),
                        ordered_stops=tuple(updated_stops),
                        peak_seat_load=peak_occ,
                        vmt_meters=total_vmt,
                        objective_value=round(j_raw, 6),
                        normalized_score=round(j_display, 4),
                        score_breakdown=score_breakdown,
                    )
                    candidates.append(candidate)
                    return

                # Branch 1: Next unvisited existing stop
                if ex_idx < num_existing:
                    next_occ = current_occ + ex_deltas[ex_idx]
                    if 0 <= next_occ <= vehicle.total_seat_capacity:
                        ex_id = ex_stop_ids[ex_idx]
                        leg_dist, leg_dur = get_cached_leg(prev_stop_id, ex_id)
                        arr = current_clock + leg_dur
                        feasible = True

                        if ex_is_dropoff[ex_idx]:
                            if arr > ex_deadlines[ex_idx]:
                                feasible = False
                            elif ex_orig_durations[ex_idx] > 0:
                                p_match_i = ex_p_match_idx[ex_idx]
                                p_time = (
                                    ex_arr_times[p_match_i]
                                    if p_match_i is not None
                                    else ex_orig_p_times[ex_idx]
                                )
                                actual_dur = max(0, arr - p_time)
                                if not check_detour_bound(actual_dur, ex_orig_durations[ex_idx], policy):
                                    feasible = False

                        if feasible:
                            ex_arr_times[ex_idx] = arr
                            current_stops_encoded.append(1000 + ex_idx)
                            search_insertions(
                                ex_idx=ex_idx + 1,
                                current_occ=next_occ,
                                peak_occ=max(peak_occ, next_occ),
                                current_clock=arr + ex_dwells[ex_idx],
                                prev_stop_id=ex_id,
                                total_vmt=total_vmt + leg_dist,
                            )
                            current_stops_encoded.pop()

                # Branch 2: Pick up or drop off request stops
                for i in range(num_reqs):
                    if req_status[i] == 0:
                        # Pickup stop for request i
                        next_occ = current_occ + p_deltas[i]
                        if next_occ <= vehicle.total_seat_capacity:
                            p_id = subset_p_ids[i]
                            leg_dist, leg_dur = get_cached_leg(prev_stop_id, p_id)
                            arr = current_clock + leg_dur
                            if arr <= p_deadlines[i]:
                                p_arr_times[i] = arr
                                current_stops_encoded.append(i + 1)
                                req_status[i] = 1
                                search_insertions(
                                    ex_idx=ex_idx,
                                    current_occ=next_occ,
                                    peak_occ=max(peak_occ, next_occ),
                                    current_clock=arr,
                                    prev_stop_id=p_id,
                                    total_vmt=total_vmt + leg_dist,
                                )
                                req_status[i] = 0
                                current_stops_encoded.pop()

                    elif req_status[i] == 1:
                        # Dropoff stop for request i
                        next_occ = current_occ + d_deltas[i]
                        if next_occ >= 0:
                            d_id = subset_d_ids[i]
                            leg_dist, leg_dur = get_cached_leg(prev_stop_id, d_id)
                            arr = current_clock + leg_dur
                            if arr > d_deadlines[i]:
                                continue
                            in_veh = max(0, arr - p_arr_times[i])
                            if in_veh <= (max_allowed_durs[i] + 1e-6):
                                d_arr_times[i] = arr
                                current_stops_encoded.append(-(i + 1))
                                req_status[i] = 2
                                search_insertions(
                                    ex_idx=ex_idx,
                                    current_occ=next_occ,
                                    peak_occ=max(peak_occ, next_occ),
                                    current_clock=arr,
                                    prev_stop_id=d_id,
                                    total_vmt=total_vmt + leg_dist,
                                )
                                req_status[i] = 1
                                current_stops_encoded.pop()

            search_insertions(
                ex_idx=0,
                current_occ=active_ride.active_passenger_count,
                peak_occ=active_ride.active_passenger_count,
                current_clock=t_start,
                prev_stop_id=v_stop_id,
                total_vmt=0,
            )
            if deadline_hit:
                break

    # Sort descending by objective value
    candidates.sort(key=lambda c: c.objective_value, reverse=True)
    return candidates


def generate_single_request_insertions(
    active_ride: Ride,
    request: RideRequest,
    vehicle: Vehicle,
    router: RoadNetworkRoutingProvider,
    policy: DispatchPolicy,
    current_time: int | None = None,
) -> list[CandidateAssignment]:
    """
    Generates and evaluates all valid stop insertion permutations for a single request
    into an active ride. Backward-compatible wrapper delegating to generate_active_ride_insertions.
    """
    return generate_active_ride_insertions(
        active_ride=active_ride,
        requests=[request],
        vehicle=vehicle,
        router=router,
        policy=policy,
        current_time=current_time,
        max_bundle_size=1,
    )
