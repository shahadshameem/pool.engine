"""Single-request stop insertion permutations generator and Stage 1 pruning."""

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
    into an active ride. Prunes capacity, precedence, detour, and delay violations in Stage 1.
    """
    t_start = current_time if current_time is not None else active_ride.scheduled_departure_time
    # Exclude historical stops (COMPLETED, SKIPPED, NO_SHOW) so they are not treated as future route waypoints
    pending_future_stops = [
        s for s in active_ride.stops
        if s.status in (StopStatus.SCHEDULED, StopStatus.ARRIVED, StopStatus.IN_GRACE_PERIOD)
    ]
    existing_stops = pending_future_stops
    n = len(existing_stops)

    # Compute unshared remaining baseline VMT from vehicle's current location through outstanding stops
    remaining_existing_waypoints = [
        Coordinate(vehicle.current_location.latitude, vehicle.current_location.longitude)
    ] + [
        Coordinate(s.location.latitude, s.location.longitude)
        for s in existing_stops
    ]
    remaining_existing_vmt = 0
    for idx in range(len(existing_stops)):
        leg_dist, _ = router.get_direct_leg(remaining_existing_waypoints[idx], remaining_existing_waypoints[idx + 1])
        remaining_existing_vmt += leg_dist

    p_stop = RouteStop(
        stop_id=f"stop-p-{request.request_id}",
        ride_id=active_ride.ride_id,
        request_id=request.request_id,
        stop_type=StopType.PICKUP,
        location=request.pickup_location,
        passenger_delta=+request.seat_count,
        scheduled_arrival_time=0,
        promised_window_start=request.earliest_pickup_time,
        promised_window_end=request.earliest_pickup_time + policy.max_pickup_delay_seconds,
        status=StopStatus.SCHEDULED,
    )

    d_stop = RouteStop(
        stop_id=f"stop-d-{request.request_id}",
        ride_id=active_ride.ride_id,
        request_id=request.request_id,
        stop_type=StopType.DROPOFF,
        location=request.dropoff_location,
        passenger_delta=-request.seat_count,
        scheduled_arrival_time=0,
        promised_window_start=request.earliest_pickup_time,
        promised_window_end=request.latest_dropoff_time,
        status=StopStatus.SCHEDULED,
    )

    candidates: list[CandidateAssignment] = []

    # Permutations: 0 <= i <= n (pickup), i+1 <= j <= n+1 (dropoff)
    for i in range(n + 1):
        for j in range(i + 1, n + 2):
            candidate_stops = (
                existing_stops[:i]
                + [p_stop]
                + existing_stops[i : j - 1]
                + [d_stop]
                + existing_stops[j - 1 :]
            )

            # Stage 1: Precedence check
            if not check_precedence(candidate_stops):
                continue

            # Stage 1: Capacity profile check
            if not check_capacity_profile(
                candidate_stops,
                capacity=vehicle.total_seat_capacity,
                initial_passengers=active_ride.active_passenger_count,
            ):
                continue

            # Route calculation: start from vehicle current location
            waypoints = [
                Coordinate(vehicle.current_location.latitude, vehicle.current_location.longitude)
            ] + [
                Coordinate(s.location.latitude, s.location.longitude)
                for s in candidate_stops
            ]

            # Calculate route durations and arrival times
            current_clock = t_start
            total_vmt = 0
            updated_stops: list[RouteStop] = []
            arrival_times: dict[str, int] = {}
            feasible = True

            curr_occ = active_ride.active_passenger_count
            peak_occ = curr_occ

            for idx, stop in enumerate(candidate_stops):
                leg_dist, leg_dur = router.get_direct_leg(waypoints[idx], waypoints[idx + 1])
                total_vmt += leg_dist
                current_clock += leg_dur

                curr_occ += stop.passenger_delta
                if curr_occ > peak_occ:
                    peak_occ = curr_occ

                # Record arrival time
                arrival_times[stop.stop_id] = current_clock

                # Dwell time at stop
                current_clock += stop.dwell_duration_seconds

                # Create updated RouteStop with scheduled_arrival_time
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

            # Evaluate pickup delay for incoming request
            p_arrival = arrival_times[p_stop.stop_id]
            d_arrival = arrival_times[d_stop.stop_id]

            if not check_pickup_delay(
                actual_pickup_time=p_arrival,
                requested_pickup_time=request.earliest_pickup_time,
                max_delay=policy.max_pickup_delay_seconds,
            ):
                continue

            # Evaluate detour bound for incoming request
            in_veh_duration = max(0, d_arrival - p_arrival)
            if not check_detour_bound(
                actual_duration=in_veh_duration,
                direct_duration=request.direct_duration_seconds,
                policy=policy,
            ):
                continue

            # Invariant: detours for existing passengers must not breach bounds
            for existing_stop in existing_stops:
                if existing_stop.stop_type == StopType.DROPOFF:
                    new_dropoff_time = arrival_times[existing_stop.stop_id]
                    # If dropoff time exceeds promised window end, prune
                    if new_dropoff_time > existing_stop.promised_window_end:
                        feasible = False
                        break

                    # Check detour bound against original direct duration
                    p_match = next(
                        (s for s in active_ride.stops if s.request_id == existing_stop.request_id and s.stop_type == StopType.PICKUP),
                        None,
                    )
                    if p_match is not None:
                        p_time = arrival_times.get(
                            p_match.stop_id,
                            p_match.actual_arrival_time or p_match.scheduled_arrival_time,
                        )
                        orig_p_time = p_match.actual_arrival_time or p_match.scheduled_arrival_time
                        orig_duration = max(0, existing_stop.scheduled_arrival_time - orig_p_time)
                        if orig_duration > 0:
                            actual_dur = max(0, new_dropoff_time - p_time)
                            if not check_detour_bound(
                                actual_duration=actual_dur,
                                direct_duration=orig_duration,
                                policy=policy,
                            ):
                                feasible = False
                                break

            if not feasible:
                continue

            # Calculate score and utility based strictly on remaining travel baseline
            baseline_vmt = remaining_existing_vmt + request.direct_distance_meters
            vmt_savings = calculate_vmt_savings(baseline_vmt=baseline_vmt, shared_vmt=total_vmt)
            s_vmt = float(vmt_savings) / float(baseline_vmt) if baseline_vmt > 0 else 0.0

            detour_secs = max(0, in_veh_duration - request.direct_duration_seconds)
            p_detour = float(detour_secs) / float(request.direct_duration_seconds) if request.direct_duration_seconds > 0 else 0.0

            wait_secs = max(0, p_arrival - request.earliest_pickup_time)
            p_wait = float(wait_secs) / float(policy.max_pickup_delay_seconds) if policy.max_pickup_delay_seconds > 0 else 0.0

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

            # Request IDs bundle
            all_req_ids = list(set([s.request_id for s in updated_stops]))
            all_req_ids.sort()

            candidate = CandidateAssignment(
                candidate_id=f"cand-{uuid.uuid4().hex[:8]}",
                vehicle_id=vehicle.vehicle_id,
                existing_ride_id=active_ride.ride_id,
                request_ids=(request.request_id,),
                ordered_stops=tuple(updated_stops),
                peak_seat_load=peak_occ,
                vmt_meters=total_vmt,
                objective_value=round(j_raw, 6),
                normalized_score=round(j_display, 4),
                score_breakdown=score_breakdown,
            )
            candidates.append(candidate)

    # Sort descending by objective value
    candidates.sort(key=lambda c: c.objective_value, reverse=True)
    return candidates
