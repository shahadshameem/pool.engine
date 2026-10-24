"""Ride and RouteStop lifecycle transitions, timer processors, GPS dwell filter, and en-route cancellation."""

from dataclasses import dataclass
from typing import Optional, Sequence

from engine.contracts.policy import DispatchPolicy
from engine.contracts.routing import Coordinate, RoadNetworkRoutingProvider
from engine.contracts.storage import RideStorageProvider
from engine.domain.enums import RequestStatus, RideStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, Ride, RouteStop
from engine.spatial.lower_bounds import haversine_distance_meters


class LifecycleTransitionError(Exception):
    """Raised on invalid or illegal ride/stop lifecycle state transitions."""
    pass


@dataclass(frozen=True)
class GpsTelemetryPing:
    """GPS location ping from vehicle telematics."""
    vehicle_id: str
    location: GeoCoordinate
    timestamp: int
    speed_kmh: float = 0.0


# Allowed transitions for Ride
_VALID_RIDE_TRANSITIONS: dict[RideStatus, set[RideStatus]] = {
    RideStatus.DRAFT: {RideStatus.SCHEDULED, RideStatus.CANCELLED},
    RideStatus.SCHEDULED: {
        RideStatus.ACTIVE,
        RideStatus.DRIVER_NO_SHOW,
        RideStatus.CANCELLED,
    },
    RideStatus.ACTIVE: {
        RideStatus.ACTIVE,
        RideStatus.COMPLETED,
        RideStatus.CANCELLED,
    },
    RideStatus.COMPLETED: set(),
    RideStatus.CANCELLED: set(),
    RideStatus.DRIVER_NO_SHOW: set(),
}

# Allowed transitions for RouteStop
_VALID_STOP_TRANSITIONS: dict[StopStatus, set[StopStatus]] = {
    StopStatus.SCHEDULED: {
        StopStatus.ARRIVED,
        StopStatus.IN_GRACE_PERIOD,
        StopStatus.SKIPPED,
    },
    StopStatus.ARRIVED: {
        StopStatus.IN_GRACE_PERIOD,
        StopStatus.COMPLETED,
        StopStatus.NO_SHOW,
        StopStatus.SKIPPED,
    },
    StopStatus.IN_GRACE_PERIOD: {
        StopStatus.COMPLETED,
        StopStatus.NO_SHOW,
        StopStatus.SKIPPED,
    },
    StopStatus.COMPLETED: set(),
    StopStatus.NO_SHOW: set(),
    StopStatus.SKIPPED: set(),
}


def transition_ride_status(ride: Ride, target_status: RideStatus) -> Ride:
    """
    Transitions ride to target_status enforcing lifecycle invariants.
    Idempotent if target_status == current_status.
    Raises LifecycleTransitionError on invalid transition.
    """
    current_status = ride.lifecycle_status
    if current_status == target_status:
        return ride

    allowed = _VALID_RIDE_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise LifecycleTransitionError(
            f"Illegal ride lifecycle transition from {current_status.value} to {target_status.value}"
        )

    return ride.model_copy(
        update={
            "lifecycle_status": target_status,
            "version": ride.version + 1,
        }
    )


def transition_stop_status(stop: RouteStop, target_status: StopStatus) -> RouteStop:
    """
    Transitions stop to target_status enforcing lifecycle invariants.
    Idempotent if target_status == current_status.
    Raises LifecycleTransitionError on invalid transition.
    """
    current_status = stop.status
    if current_status == target_status:
        return stop

    allowed = _VALID_STOP_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise LifecycleTransitionError(
            f"Illegal stop lifecycle transition from {current_status.value} to {target_status.value}"
        )

    return stop.model_copy(update={"status": target_status})


def confirm_stop_arrival(stop: RouteStop, current_time: int) -> RouteStop:
    """
    Marks stop as arrived and initiates boarding grace period countdown.
    Idempotent if already in ARRIVED or IN_GRACE_PERIOD.
    """
    if stop.status in (StopStatus.ARRIVED, StopStatus.IN_GRACE_PERIOD):
        return stop

    if stop.status in (StopStatus.COMPLETED, StopStatus.NO_SHOW, StopStatus.SKIPPED):
        raise LifecycleTransitionError(
            f"Cannot mark arrival for stop in terminal state {stop.status.value}"
        )

    return stop.model_copy(
        update={
            "status": StopStatus.IN_GRACE_PERIOD,
            "actual_arrival_time": current_time,
        }
    )


def confirm_passenger_boarding(
    ride: Ride,
    stop_id: str,
    current_time: int,
    policy: DispatchPolicy = DispatchPolicy(),
) -> tuple[Ride, RouteStop]:
    """
    Explicitly confirms passenger boarding at a pickup stop.
    Enforces exact boarding grace period bound (t <= T_arr + boarding_grace_period_seconds).
    Updates stop to COMPLETED and increments ride active_passenger_count.
    """
    target_stop: Optional[RouteStop] = None
    target_idx: Optional[int] = None
    for idx, s in enumerate(ride.stops):
        if s.stop_id == stop_id:
            target_stop = s
            target_idx = idx
            break

    if target_stop is None or target_idx is None:
        raise ValueError(f"Stop {stop_id} not found in ride {ride.ride_id}")

    if target_stop.stop_type != StopType.PICKUP:
        raise LifecycleTransitionError(
            f"Cannot board passenger: stop {stop_id} is not a PICKUP stop"
        )

    if target_stop.status == StopStatus.COMPLETED:
        return ride, target_stop

    if target_stop.status == StopStatus.NO_SHOW:
        raise LifecycleTransitionError(f"Cannot board passenger: stop {stop_id} is already NO_SHOW")

    if target_stop.status == StopStatus.SKIPPED:
        raise LifecycleTransitionError(f"Cannot board passenger: stop {stop_id} is already SKIPPED")

    if target_stop.status not in (StopStatus.ARRIVED, StopStatus.IN_GRACE_PERIOD):
        raise LifecycleTransitionError(
            f"Cannot board passenger: stop {stop_id} has not arrived (current status: {target_stop.status.value})"
        )

    # Check exact boarding grace boundary
    if target_stop.actual_arrival_time is not None:
        elapsed = current_time - target_stop.actual_arrival_time
        if elapsed > policy.boarding_grace_period_seconds:
            raise LifecycleTransitionError(
                f"Cannot board passenger: boarding grace period expired ({elapsed}s > {policy.boarding_grace_period_seconds}s)"
            )

    updated_stop = target_stop.model_copy(update={"status": StopStatus.COMPLETED})
    new_stops = list(ride.stops)
    new_stops[target_idx] = updated_stop

    updated_ride = ride.model_copy(
        update={
            "stops": tuple(new_stops),
            "active_passenger_count": ride.active_passenger_count + updated_stop.passenger_delta,
            "version": ride.version + 1,
        }
    )
    return updated_ride, updated_stop


def confirm_passenger_dropoff(
    ride: Ride,
    stop_id: str,
    current_time: int,
) -> tuple[Ride, RouteStop]:
    """
    Confirms passenger dropoff at a dropoff stop.
    Updates stop to COMPLETED, decrements active_passenger_count,
    and transitions ride to COMPLETED if all stops are done.
    """
    target_stop: Optional[RouteStop] = None
    target_idx: Optional[int] = None
    for idx, s in enumerate(ride.stops):
        if s.stop_id == stop_id:
            target_stop = s
            target_idx = idx
            break

    if target_stop is None or target_idx is None:
        raise ValueError(f"Stop {stop_id} not found in ride {ride.ride_id}")

    if target_stop.status == StopStatus.COMPLETED:
        return ride, target_stop

    if target_stop.stop_type != StopType.DROPOFF:
        raise LifecycleTransitionError(f"Stop {stop_id} is not a DROPOFF stop")

    updated_stop = target_stop.model_copy(
        update={
            "status": StopStatus.COMPLETED,
            "actual_arrival_time": current_time,
        }
    )
    new_stops = list(ride.stops)
    new_stops[target_idx] = updated_stop

    all_done = all(s.status in (StopStatus.COMPLETED, StopStatus.SKIPPED, StopStatus.NO_SHOW) for s in new_stops)
    new_ride_status = RideStatus.COMPLETED if all_done else ride.lifecycle_status

    updated_ride = ride.model_copy(
        update={
            "stops": tuple(new_stops),
            "active_passenger_count": max(0, ride.active_passenger_count + updated_stop.passenger_delta),
            "lifecycle_status": new_ride_status,
            "version": ride.version + 1,
        }
    )
    return updated_ride, updated_stop


def confirm_ride_departure(ride: Ride, departure_time: int) -> Ride:
    """
    Confirms vehicle trip start and departs origin.
    Sets actual_departure_time and transitions SCHEDULED ride to ACTIVE.
    """
    if ride.actual_departure_time is not None:
        return ride

    new_status = RideStatus.ACTIVE if ride.lifecycle_status == RideStatus.SCHEDULED else ride.lifecycle_status
    return ride.model_copy(
        update={
            "actual_departure_time": departure_time,
            "lifecycle_status": new_status,
            "version": ride.version + 1,
        }
    )


def process_gps_telemetry(
    stop: RouteStop,
    ping: GpsTelemetryPing,
    policy: DispatchPolicy = DispatchPolicy(),
    geofence_radius_meters: float = 100.0,
) -> RouteStop:
    """
    Evaluates continuous dwell within the stop geofence.
    - Passthrough: vehicle in geofence for < stop_arrival_dwell_seconds (e.g. 3s at 45 km/h)
      does NOT trigger arrival.
    - Continuous Dwell: vehicle inside geofence for >= stop_arrival_dwell_seconds triggers ARRIVED / IN_GRACE_PERIOD.
    - Dwell Break: if vehicle exits geofence before threshold, dwell resets to 0.
    """
    if stop.status != StopStatus.SCHEDULED:
        return stop

    dist = haversine_distance_meters(
        Coordinate(ping.location.latitude, ping.location.longitude),
        Coordinate(stop.location.latitude, stop.location.longitude),
    )

    if dist <= geofence_radius_meters:
        # Inside geofence
        if stop.dwell_start_time is None:
            # First ping inside geofence
            return stop.model_copy(
                update={
                    "dwell_start_time": ping.timestamp,
                    "dwell_duration_seconds": 0,
                }
            )
        else:
            dwell_duration = max(0, ping.timestamp - stop.dwell_start_time)
            if dwell_duration >= policy.stop_arrival_dwell_seconds:
                # Dwell threshold satisfied! Transition to IN_GRACE_PERIOD (arrived)
                return stop.model_copy(
                    update={
                        "status": StopStatus.IN_GRACE_PERIOD,
                        "actual_arrival_time": ping.timestamp,
                        "dwell_start_time": stop.dwell_start_time,
                        "dwell_duration_seconds": dwell_duration,
                    }
                )
            else:
                return stop.model_copy(
                    update={
                        "dwell_duration_seconds": dwell_duration,
                    }
                )
    else:
        # Outside geofence: reset dwell if was dwelling
        if stop.dwell_start_time is not None:
            return stop.model_copy(
                update={
                    "dwell_start_time": None,
                    "dwell_duration_seconds": 0,
                }
            )
        return stop


def process_ride_timers(
    ride: Ride,
    current_time: int,
    policy: DispatchPolicy = DispatchPolicy(),
) -> Ride:
    """
    Deterministic periodic sweep of ride and stop timers.
    1. Activation Lead: t >= T_0 - scheduled_activation_lead_seconds transitions SCHEDULED -> ACTIVE.
    2. Departure Grace: t > T_0 + scheduled_departure_grace_seconds without departure transitions -> DRIVER_NO_SHOW.
    3. Boarding Grace: t > T_arr + boarding_grace_period_seconds without boarding transitions stop -> NO_SHOW,
       and automatically marks downstream dropoffs SKIPPED.
    """
    updated_ride = ride
    mutated = False

    # 1. Ride Level Departure / Activation Timers
    if updated_ride.lifecycle_status in (RideStatus.SCHEDULED, RideStatus.ACTIVE):
        # Check departure grace first: no departure confirmed past grace window
        if (
            updated_ride.actual_departure_time is None
            and current_time > updated_ride.scheduled_departure_time + policy.scheduled_departure_grace_seconds
        ):
            updated_ride = updated_ride.model_copy(
                update={
                    "lifecycle_status": RideStatus.DRIVER_NO_SHOW,
                    "version": updated_ride.version + 1,
                }
            )
            mutated = True
        elif (
            updated_ride.lifecycle_status == RideStatus.SCHEDULED
            and current_time >= updated_ride.scheduled_departure_time - policy.scheduled_activation_lead_seconds
        ):
            updated_ride = updated_ride.model_copy(
                update={
                    "lifecycle_status": RideStatus.ACTIVE,
                    "version": updated_ride.version + 1,
                }
            )
            mutated = True

    # 2. Stop Level Boarding Grace Timers
    new_stops: list[RouteStop] = []
    stops_mutated = False
    no_show_req_ids: set[str] = set()

    for s in updated_ride.stops:
        if (
            s.status in (StopStatus.ARRIVED, StopStatus.IN_GRACE_PERIOD)
            and s.actual_arrival_time is not None
            and current_time > s.actual_arrival_time + policy.boarding_grace_period_seconds
        ):
            # Boarding grace expired! Mark NO_SHOW
            updated_s = s.model_copy(update={"status": StopStatus.NO_SHOW})
            new_stops.append(updated_s)
            no_show_req_ids.add(s.request_id)
            stops_mutated = True
        else:
            new_stops.append(s)

    # If any pickup timed out to NO_SHOW, skip corresponding downstream dropoffs
    if no_show_req_ids:
        final_stops: list[RouteStop] = []
        for s in new_stops:
            if s.request_id in no_show_req_ids and s.stop_type == StopType.DROPOFF and s.status == StopStatus.SCHEDULED:
                final_stops.append(s.model_copy(update={"status": StopStatus.SKIPPED}))
                stops_mutated = True
            else:
                final_stops.append(s)
        new_stops = final_stops

    if stops_mutated:
        updated_ride = updated_ride.model_copy(
            update={
                "stops": tuple(new_stops),
                "version": updated_ride.version + 1,
            }
        )

    return updated_ride


def cancel_en_route_request(
    ride: Ride,
    request_id: str,
    router: RoadNetworkRoutingProvider,
    current_time: int,
    vehicle_location: Optional[GeoCoordinate] = None,
    storage: Optional[RideStorageProvider] = None,
) -> tuple[Ride, dict[str, int]]:
    """
    Handles en-route cancellation of a downstream passenger before vehicle arrival.
    Removes pickup and dropoff stops, re-optimizes the route, updates ETAs for remaining passengers,
    and increments the ride version.
    """
    stops_for_req = [s for s in ride.stops if s.request_id == request_id]
    if not stops_for_req:
        return ride, {}

    # Passenger cannot cancel pickup if already boarded
    for s in stops_for_req:
        if s.stop_type == StopType.PICKUP and s.status == StopStatus.COMPLETED:
            raise LifecycleTransitionError(
                f"Passenger {request_id} has already boarded; cannot cancel en-route"
            )

    remaining_stops = [s for s in ride.stops if s.request_id != request_id]

    # Re-calculate ETAs for remaining stops starting from current vehicle location
    start_coord = (
        Coordinate(vehicle_location.latitude, vehicle_location.longitude)
        if vehicle_location is not None
        else Coordinate(ride.stops[0].location.latitude, ride.stops[0].location.longitude)
    )

    waypoints = [start_coord] + [
        Coordinate(s.location.latitude, s.location.longitude) for s in remaining_stops
    ]

    clock = current_time
    total_vmt = 0
    updated_etas: dict[str, int] = {}
    new_stops: list[RouteStop] = []

    for idx, stop in enumerate(remaining_stops):
        if stop.status == StopStatus.COMPLETED:
            new_stops.append(stop)
            updated_etas[stop.stop_id] = stop.scheduled_arrival_time
            continue

        leg_dist, leg_dur = router.get_direct_leg(waypoints[idx], waypoints[idx + 1])
        total_vmt += leg_dist
        clock += leg_dur
        new_arrival = clock
        updated_etas[stop.stop_id] = new_arrival
        clock += stop.dwell_duration_seconds
        new_stops.append(stop.model_copy(update={"scheduled_arrival_time": new_arrival}))

    updated_ride = ride.model_copy(
        update={
            "stops": tuple(new_stops),
            "total_vmt_meters": total_vmt,
            "version": ride.version + 1,
        }
    )

    if storage is not None:
        storage.save_ride(updated_ride)
        stored_req = storage.get_request(request_id)
        if stored_req is not None:
            storage.save_request(stored_req.model_copy(update={"status": RequestStatus.CANCELLED}))

    return updated_ride, updated_etas
