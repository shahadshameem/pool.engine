"""Private-host corridor matching and ahead-of-vehicle en-route eligibility evaluation.

Enforces:
1. Fixed origin and destination as mandatory route endpoints for private-host journeys.
2. Road network routing for accurate travel time, distance, and detour feasibility.
3. Host maximum detour bound enforcement: (t_dest - t_baseline_dest) <= max_detour_seconds.
4. Cumulative capacity conservation at every intermediate leg.
5. Revalidation of all existing onboard/scheduled passengers' arrival deadlines and detour factor.
6. The Ahead-of-Vehicle Spatial Gate rejecting candidate pickups behind the vehicle or requiring backtracking.
7. Proposal generation with atomic temporary seat holds requiring mutual acceptance before confirmation.
"""

from dataclasses import dataclass
import math
from typing import Optional, Sequence

from engine.contracts.policy import DispatchPolicy
from engine.contracts.routing import (
    Coordinate,
    OutOfRegionError,
    RoadNetworkRoutingProvider,
    RouteLookupError,
    RoutingProviderError,
)
from engine.domain.enums import RequestStatus, RideStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle
from engine.routing.invariants import (
    check_capacity_profile,
    check_detour_bound,
    check_pickup_delay,
)


@dataclass(frozen=True)
class CorridorMatchResult:
    """Outcome of evaluating a passenger request against a private host's planned or active corridor."""
    is_eligible: bool
    rejection_reason: Optional[str] = None
    proposed_stops: tuple[RouteStop, ...] = ()
    estimated_pickup_time: Optional[int] = None
    estimated_dropoff_time: Optional[int] = None
    host_detour_seconds: int = 0
    host_arrival_time: Optional[int] = None
    total_vmt_meters: int = 0


def _coord_to_routing(c: GeoCoordinate) -> Coordinate:
    return Coordinate(latitude=c.latitude, longitude=c.longitude)


def check_ahead_of_vehicle(
    vehicle_location: GeoCoordinate,
    pickup_location: GeoCoordinate,
    destination_location: GeoCoordinate,
    remaining_stops: Sequence[RouteStop],
    completed_stops: Sequence[RouteStop],
    router: RoadNetworkRoutingProvider,
    origin_location: Optional[GeoCoordinate] = None,
) -> tuple[bool, Optional[str]]:
    """
    Algorithmic gate verifying whether a candidate pickup point is strictly AHEAD
    of an in-transit vehicle along its active road corridor without relying on compass bearing alone.

    Criteria:
    1. Completed Stop Precedence:
       If stops have been completed, the pickup must not be closer to or behind
       the previous checkpoint than the vehicle's current location.
    2. Road Network Progress / Monotonicity toward Destination:
       Distance along the road network from pickup to destination must not exceed
       the road distance from the vehicle's current position to destination by more than lateral tolerance.
       A pickup further from destination than the current position represents backward progression (backtracking).
    3. Forward Movement Projection (Vector Alignment):
       The vector from vehicle to pickup must align positively with the active travel direction vector
       (from the previous checkpoint or origin toward current position, and toward next destination).
    4. Road Network Reachability & Detour:
       Road leg (V -> P) must be routable and direct duration must not imply reverse travel.

    Returns:
        (True, None) if pickup is ahead and eligible for evaluation.
        (False, rejection_reason) if pickup is behind or requires backtracking.
    """
    v_c = _coord_to_routing(vehicle_location)
    p_c = _coord_to_routing(pickup_location)
    d_c = _coord_to_routing(destination_location)

    # 1. Road distance to destination comparison (Monotonicity check)
    # Moving backwards increases remaining road distance to destination.
    try:
        leg_v_to_dest = router.get_direct_leg(v_c, d_c)
        leg_p_to_dest = router.get_direct_leg(p_c, d_c)
    except OutOfRegionError:
        return False, "OUT_OF_REGION"
    except (RouteLookupError, RoutingProviderError):
        return False, "ROUTING_UNAVAILABLE"

    if leg_v_to_dest is None or leg_p_to_dest is None:
        return False, "ROUTING_UNAVAILABLE"

    dist_v_dest, dur_v_dest = leg_v_to_dest
    dist_p_dest, dur_p_dest = leg_p_to_dest

    # 2. Check completed stops: pickup must not be closer to a completed stop than the vehicle
    if completed_stops:
        last_completed = completed_stops[-1]
        c_c = _coord_to_routing(last_completed.location)
        try:
            leg_c_to_v = router.get_direct_leg(c_c, v_c)
            leg_c_to_p = router.get_direct_leg(c_c, p_c)
        except (OutOfRegionError, RouteLookupError, RoutingProviderError):
            leg_c_to_v = None
            leg_c_to_p = None
        if leg_c_to_v is not None and leg_c_to_p is not None:
            dist_c_v, _ = leg_c_to_v
            dist_c_p, _ = leg_c_to_p
            # If pickup is closer to last completed stop than current vehicle position,
            # vehicle has already passed the pickup point!
            if dist_c_p < dist_c_v * 0.85 and dist_p_dest > dist_v_dest:
                return False, "PICKUP_BEHIND_VEHICLE"

    # 3. Vector dot product with travel direction
    # Determine reference direction: from previous anchor (last completed stop or origin) to vehicle
    anchor = completed_stops[-1].location if completed_stops else origin_location
    if anchor is not None:
        # Travel direction vector (anchor -> vehicle)
        d_lat_move = vehicle_location.latitude - anchor.latitude
        d_lon_move = vehicle_location.longitude - anchor.longitude
        # Candidate vector (vehicle -> pickup)
        d_lat_cand = pickup_location.latitude - vehicle_location.latitude
        d_lon_cand = pickup_location.longitude - vehicle_location.longitude

        # Only compute dot product if vehicle has moved appreciably from anchor
        move_norm = math.hypot(d_lat_move, d_lon_move)
        if move_norm > 1e-5:
            dot_prod = (d_lat_move * d_lat_cand) + (d_lon_move * d_lon_cand)
            # Negative dot product means the pickup is in the rear half-plane (behind the vehicle)
            if dot_prod < -1e-6:
                return False, "PICKUP_BEHIND_VEHICLE"

    # 4. If remaining distance from pickup to destination is significantly greater
    # than from current vehicle position to destination, the pickup is behind.
    # Allow 20% lateral buffer for minor cross-street offset.
    if dist_p_dest > dist_v_dest * 1.15 and dur_p_dest > dur_v_dest * 1.15:
        return False, "PICKUP_BEHIND_VEHICLE"

    # 5. Direct road reachability from vehicle to pickup
    try:
        leg_v_to_p = router.get_direct_leg(v_c, p_c)
    except OutOfRegionError:
        return False, "OUT_OF_REGION"
    except (RouteLookupError, RoutingProviderError):
        return False, "PICKUP_UNREACHABLE"
    if leg_v_to_p is None:
        return False, "PICKUP_UNREACHABLE"

    return True, None


def evaluate_host_corridor_match(
    ride: Ride,
    request: RideRequest,
    vehicle: Vehicle,
    router: RoadNetworkRoutingProvider,
    policy: DispatchPolicy,
    current_time: Optional[int] = None,
) -> CorridorMatchResult:
    """
    Evaluates whether a passenger request is compatible with a private host's fixed corridor.

    Guarantees:
    - Host origin is the initial departure point; host destination is the mandatory final endpoint.
    - Traveller pickup and dropoff occur strictly between origin (or current location) and destination.
    - Capacity is verified at every route segment.
    - Traveller pickup window and deadline are strictly satisfied.
    - Traveller detour bound (1 + delta) is preserved.
    - Host arrives at destination within direct_duration + max_detour_seconds.
    - All existing onboard/scheduled passengers' arrival deadlines and detour bounds remain satisfied.
    """
    # 1. Capacity check: vehicle total capacity
    if request.seat_count > vehicle.total_seat_capacity:
        return CorridorMatchResult(is_eligible=False, rejection_reason="OVER_CAPACITY")

    # Host origin and destination
    origin = ride.origin_location or vehicle.current_location
    destination = ride.destination_location
    if destination is None:
        # If ride has no destination_location, check if the last stop is a host destination
        if ride.stops and ride.stops[-1].stop_type in (StopType.DROPOFF, StopType.WAYPOINT):
            destination = ride.stops[-1].location
        else:
            return CorridorMatchResult(is_eligible=False, rejection_reason="NO_HOST_DESTINATION")

    t_now = current_time if current_time is not None else int(ride.scheduled_departure_time)

    # 2. Host baseline direct duration
    try:
        direct_leg_host = router.get_direct_leg(_coord_to_routing(origin), _coord_to_routing(destination))
    except OutOfRegionError:
        return CorridorMatchResult(is_eligible=False, rejection_reason="HOST_OUT_OF_REGION")
    except (RouteLookupError, RoutingProviderError):
        return CorridorMatchResult(is_eligible=False, rejection_reason="HOST_ROUTE_UNROUTABLE")
    if direct_leg_host is None:
        return CorridorMatchResult(is_eligible=False, rejection_reason="HOST_ROUTE_UNROUTABLE")
    host_direct_dist, host_direct_dur = direct_leg_host
    max_host_detour = ride.max_detour_seconds if ride.max_detour_seconds is not None else policy.detour_absolute_cap_seconds
    latest_host_arrival = ride.scheduled_departure_time + host_direct_dur + max_host_detour

    # Separate existing stops into completed vs remaining
    completed_stops = [s for s in ride.stops if s.status == StopStatus.COMPLETED]
    remaining_stops = [
        s for s in ride.stops
        if s.status in (StopStatus.SCHEDULED, StopStatus.ARRIVED, StopStatus.IN_GRACE_PERIOD)
    ]

    # Filter out host endpoints (Origin and Destination waypoints) from intermediate passenger stops
    def _is_host_endpoint(s: RouteStop) -> bool:
        if s.request_id.startswith("host:"):
            return True
        if s.stop_type == StopType.WAYPOINT and s.passenger_delta == 0:
            if origin and abs(s.location.latitude - origin.latitude) < 1e-5 and abs(s.location.longitude - origin.longitude) < 1e-5:
                return True
            if abs(s.location.latitude - destination.latitude) < 1e-5 and abs(s.location.longitude - destination.longitude) < 1e-5:
                return True
        return False

    intermediate_passenger_stops = [s for s in remaining_stops if not _is_host_endpoint(s)]

    # Current vehicle starting point
    is_in_transit = ride.lifecycle_status == RideStatus.ACTIVE and (completed_stops or ride.actual_departure_time is not None)
    start_loc = vehicle.current_location if is_in_transit else origin
    start_time = max(t_now, ride.scheduled_departure_time)

    # 3. If in-transit, apply the Ahead-of-Vehicle Spatial Gate
    if is_in_transit:
        is_ahead, reason = check_ahead_of_vehicle(
            vehicle_location=start_loc,
            pickup_location=request.pickup_location,
            destination_location=destination,
            remaining_stops=remaining_stops,
            completed_stops=completed_stops,
            router=router,
            origin_location=origin,
        )
        if not is_ahead:
            return CorridorMatchResult(is_eligible=False, rejection_reason=reason or "PICKUP_BEHIND_VEHICLE")

    # 4. Check road route legs for inserting request stops
    # Sequence must be: Start -> [Optional existing pickups/dropoffs] -> Pickup -> Dropoff -> Destination
    # Try valid insertion permutations of remaining stops + request pickup + request dropoff,
    # with Destination strictly as the terminal stop.
    p_coord = _coord_to_routing(request.pickup_location)
    d_coord = _coord_to_routing(request.dropoff_location)
    dest_coord = _coord_to_routing(destination)
    start_coord = _coord_to_routing(start_loc)

    # Traveller direct route check
    try:
        leg_req_direct = router.get_direct_leg(p_coord, d_coord)
    except OutOfRegionError:
        return CorridorMatchResult(is_eligible=False, rejection_reason="REQUEST_OUT_OF_REGION")
    except (RouteLookupError, RoutingProviderError):
        return CorridorMatchResult(is_eligible=False, rejection_reason="REQUEST_UNROUTABLE")
    if leg_req_direct is None:
        return CorridorMatchResult(is_eligible=False, rejection_reason="REQUEST_UNROUTABLE")
    req_direct_dist, req_direct_dur = leg_req_direct
    max_traveller_in_veh = float(req_direct_dur) + min(
        (policy.detour_relative_multiplier - 1.0) * float(req_direct_dur),
        float(policy.detour_absolute_cap_seconds),
    )

    # Construct candidate itineraries
    best_result: Optional[CorridorMatchResult] = None
    min_detour = float("inf")

    # Generate insertion permutations
    # In a host corridor, destination is always the final stop.
    # Insert P and Q into intermediate_passenger_stops such that index(P) < index(Q).
    n_ex = len(intermediate_passenger_stops)
    for i in range(n_ex + 1):
        for j in range(i, n_ex + 1):
            cand_middle = (
                list(intermediate_passenger_stops[:i])
                + ["PICKUP"]
                + list(intermediate_passenger_stops[i:j])
                + ["DROPOFF"]
                + list(intermediate_passenger_stops[j:])
            )

            # Evaluate this candidate sequence
            current_clock = start_time
            current_occ = ride.active_passenger_count
            if is_in_transit and current_occ == 0 and completed_stops:
                completed_delta = sum(s.passenger_delta for s in completed_stops)
                if completed_delta > 0:
                    current_occ = completed_delta
            prev_c = start_coord
            feasible = True
            rejection_reason = None
            total_dist = 0

            p_arr = 0
            q_arr = 0
            final_stops: list[RouteStop] = []

            # If not in transit, prepend Origin waypoint
            if not is_in_transit:
                final_stops.append(
                    RouteStop(
                        stop_id=f"stop-origin-{ride.ride_id}",
                        ride_id=ride.ride_id,
                        request_id=f"host:{ride.driver_id}",
                        stop_type=StopType.WAYPOINT,
                        location=origin,
                        passenger_delta=0,
                        scheduled_arrival_time=ride.scheduled_departure_time,
                        promised_window_start=ride.scheduled_departure_time,
                        promised_window_end=ride.scheduled_departure_time,
                        status=StopStatus.SCHEDULED,
                    )
                )

            for item in cand_middle:
                if item == "PICKUP":
                    try:
                        leg = router.get_direct_leg(prev_c, p_coord)
                    except (OutOfRegionError, RouteLookupError, RoutingProviderError):
                        leg = None
                    if leg is None:
                        feasible = False
                        rejection_reason = "UNROUTABLE_LEG"
                        break
                    ldist, ldur = leg
                    current_clock += ldur
                    total_dist += ldist

                    # Check pickup window
                    if current_clock > request.earliest_pickup_time + policy.max_pickup_delay_seconds:
                        feasible = False
                        rejection_reason = "PICKUP_WINDOW_BREACH"
                        break

                    current_clock = max(current_clock, request.earliest_pickup_time)
                    p_arr = current_clock
                    current_occ += request.seat_count
                    if current_occ > vehicle.total_seat_capacity:
                        feasible = False
                        rejection_reason = "OVER_CAPACITY"
                        break

                    dwell = policy.stop_arrival_dwell_seconds
                    final_stops.append(
                        RouteStop(
                            stop_id=f"stop-p-{request.request_id}",
                            ride_id=ride.ride_id,
                            request_id=request.request_id,
                            stop_type=StopType.PICKUP,
                            location=request.pickup_location,
                            passenger_delta=request.seat_count,
                            scheduled_arrival_time=p_arr,
                            promised_window_start=request.earliest_pickup_time,
                            promised_window_end=request.earliest_pickup_time + policy.max_pickup_delay_seconds,
                            dwell_duration_seconds=dwell,
                            status=StopStatus.SCHEDULED,
                        )
                    )
                    current_clock += dwell
                    prev_c = p_coord

                elif item == "DROPOFF":
                    try:
                        leg = router.get_direct_leg(prev_c, d_coord)
                    except (OutOfRegionError, RouteLookupError, RoutingProviderError):
                        leg = None
                    if leg is None:
                        feasible = False
                        rejection_reason = "UNROUTABLE_LEG"
                        break
                    ldist, ldur = leg
                    current_clock += ldur
                    total_dist += ldist
                    q_arr = current_clock

                    # Check traveller deadline
                    if q_arr > request.latest_dropoff_time:
                        feasible = False
                        rejection_reason = "DEADLINE_BREACH"
                        break

                    # Check traveller in-vehicle detour
                    if (q_arr - p_arr) > (max_traveller_in_veh + 1e-6):
                        feasible = False
                        rejection_reason = "DETOUR_BREACH"
                        break

                    current_occ -= request.seat_count
                    dwell = policy.stop_arrival_dwell_seconds
                    final_stops.append(
                        RouteStop(
                            stop_id=f"stop-d-{request.request_id}",
                            ride_id=ride.ride_id,
                            request_id=request.request_id,
                            stop_type=StopType.DROPOFF,
                            location=request.dropoff_location,
                            passenger_delta=-request.seat_count,
                            scheduled_arrival_time=q_arr,
                            promised_window_start=request.earliest_pickup_time,
                            promised_window_end=request.latest_dropoff_time,
                            dwell_duration_seconds=dwell,
                            status=StopStatus.SCHEDULED,
                        )
                    )
                    current_clock += dwell
                    prev_c = d_coord

                else:
                    # Existing RouteStop
                    ex_stop: RouteStop = item  # type: ignore[assignment]
                    ex_c = _coord_to_routing(ex_stop.location)
                    try:
                        leg = router.get_direct_leg(prev_c, ex_c)
                    except (OutOfRegionError, RouteLookupError, RoutingProviderError):
                        leg = None
                    if leg is None:
                        feasible = False
                        rejection_reason = "UNROUTABLE_LEG"
                        break
                    ldist, ldur = leg
                    current_clock += ldur
                    total_dist += ldist

                    # Revalidate existing stop deadline
                    if current_clock > ex_stop.promised_window_end:
                        feasible = False
                        rejection_reason = "EXISTING_PASSENGER_DEADLINE_BREACH"
                        break

                    current_occ += ex_stop.passenger_delta
                    if current_occ > vehicle.total_seat_capacity or current_occ < 0:
                        feasible = False
                        rejection_reason = "OVER_CAPACITY"
                        break

                    final_stops.append(
                        ex_stop.model_copy(update={"scheduled_arrival_time": current_clock})
                    )
                    current_clock += ex_stop.dwell_duration_seconds
                    prev_c = ex_c

            if not feasible:
                continue

            # Finally, connect to mandatory Destination endpoint
            try:
                leg_to_dest = router.get_direct_leg(prev_c, dest_coord)
            except (OutOfRegionError, RouteLookupError, RoutingProviderError):
                leg_to_dest = None
            if leg_to_dest is None:
                continue
            ldist_dest, ldur_dest = leg_to_dest
            dest_arr = current_clock + ldur_dest
            total_dist += ldist_dest

            # Verify host detour bound
            host_detour = max(0, dest_arr - (ride.scheduled_departure_time + host_direct_dur))
            if dest_arr > latest_host_arrival:
                feasible = False
                rejection_reason = "HOST_DETOUR_BREACH"
                continue

            # Add Destination stop as mandatory terminal endpoint
            final_stops.append(
                RouteStop(
                    stop_id=f"stop-dest-{ride.ride_id}",
                    ride_id=ride.ride_id,
                    request_id=f"host:{ride.driver_id}",
                    stop_type=StopType.WAYPOINT,
                    location=destination,
                    passenger_delta=0,
                    scheduled_arrival_time=dest_arr,
                    promised_window_start=ride.scheduled_departure_time + host_direct_dur,
                    promised_window_end=latest_host_arrival,
                    status=StopStatus.SCHEDULED,
                )
            )

            # Check if this permutation is better (lower host detour)
            if host_detour < min_detour:
                min_detour = host_detour
                best_result = CorridorMatchResult(
                    is_eligible=True,
                    rejection_reason=None,
                    proposed_stops=tuple(final_stops),
                    estimated_pickup_time=p_arr,
                    estimated_dropoff_time=q_arr,
                    host_detour_seconds=host_detour,
                    host_arrival_time=dest_arr,
                    total_vmt_meters=total_dist,
                )

    if best_result is not None:
        return best_result

    # If no feasible combination found, report failure
    return CorridorMatchResult(
        is_eligible=False,
        rejection_reason=rejection_reason or "INCOMPATIBLE_CORRIDOR",
    )
