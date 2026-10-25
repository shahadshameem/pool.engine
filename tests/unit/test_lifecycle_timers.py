"""Unit tests for ride and stop lifecycle state machines, grace timers, and GPS dwell verification."""

import pytest

from engine.contracts.policy import DispatchPolicy
from engine.domain.enums import RideStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, Ride, RouteStop
from engine.lifecycle.transitions import (
    GpsTelemetryPing,
    LifecycleTransitionError,
    confirm_passenger_boarding,
    confirm_passenger_dropoff,
    confirm_ride_departure,
    confirm_stop_arrival,
    process_gps_telemetry,
    process_ride_timers,
    transition_ride_status,
    transition_stop_status,
)


def _create_sample_ride(
    departure_time: int = 10000,
    status: RideStatus = RideStatus.SCHEDULED,
    stops: tuple[RouteStop, ...] = (),
) -> Ride:
    return Ride(
        ride_id="ride-timer-1",
        vehicle_id="veh-1",
        driver_id="drv-1",
        lifecycle_status=status,
        stops=stops,
        scheduled_departure_time=departure_time,
        active_passenger_count=0,
        version=1,
    )


def _create_sample_stop(
    stop_id: str = "stop-p-1",
    ride_id: str = "ride-timer-1",
    request_id: str = "req-1",
    stop_type: StopType = StopType.PICKUP,
    location: GeoCoordinate = GeoCoordinate(latitude=40.7128, longitude=-74.0060),
    status: StopStatus = StopStatus.SCHEDULED,
    scheduled_arrival_time: int = 10000,
    actual_arrival_time: int | None = None,
    dwell_duration_seconds: int = 0,
    dwell_start_time: int | None = None,
) -> RouteStop:
    return RouteStop(
        stop_id=stop_id,
        ride_id=ride_id,
        request_id=request_id,
        stop_type=stop_type,
        location=location,
        passenger_delta=+1 if stop_type == StopType.PICKUP else -1,
        scheduled_arrival_time=scheduled_arrival_time,
        promised_window_start=scheduled_arrival_time,
        promised_window_end=scheduled_arrival_time + 600,
        actual_arrival_time=actual_arrival_time,
        dwell_duration_seconds=dwell_duration_seconds,
        dwell_start_time=dwell_start_time,
        status=status,
    )


# -----------------------------------------------------------------------------
# T045: Exact Timer Boundary Tests
# -----------------------------------------------------------------------------

def test_activation_lead_exact_boundary() -> None:
    """
    T045: Activation lead boundary:
    T_0 = 10000s, scheduled_activation_lead_seconds = 1800s.
    t = T_0 - 1801s (8199s) -> remains SCHEDULED
    t = T_0 - 1800s (8200s) -> transitions from SCHEDULED to ACTIVE
    """
    policy = DispatchPolicy(scheduled_activation_lead_seconds=1800)
    ride = _create_sample_ride(departure_time=10000, status=RideStatus.SCHEDULED)

    # 1 second before activation threshold: remains SCHEDULED
    ride_before = process_ride_timers(ride, current_time=8199, policy=policy)
    assert ride_before.lifecycle_status == RideStatus.SCHEDULED

    # Exactly at activation threshold: transitions to ACTIVE
    ride_active = process_ride_timers(ride, current_time=8200, policy=policy)
    assert ride_active.lifecycle_status == RideStatus.ACTIVE


def test_departure_grace_exact_boundary() -> None:
    """
    T045: Scheduled departure grace boundary:
    T_0 = 10000s, scheduled_departure_grace_seconds = 600s.
    t = T_0 + 600s (10600s) -> ride remains non-no-show
    t = T_0 + 601s (10601s) without departure -> transitions to DRIVER_NO_SHOW
    """
    policy = DispatchPolicy(scheduled_departure_grace_seconds=600)
    ride = _create_sample_ride(departure_time=10000, status=RideStatus.ACTIVE)

    # Exactly at departure grace expiry (t = 10600s): ride remains ACTIVE (not DRIVER_NO_SHOW)
    ride_grace = process_ride_timers(ride, current_time=10600, policy=policy)
    assert ride_grace.lifecycle_status == RideStatus.ACTIVE

    # 1 second past departure grace expiry (t = 10601s): transitions to DRIVER_NO_SHOW
    ride_no_show = process_ride_timers(ride, current_time=10601, policy=policy)
    assert ride_no_show.lifecycle_status == RideStatus.DRIVER_NO_SHOW

    # Also verify for a ride initially in SCHEDULED status
    ride_sched = _create_sample_ride(departure_time=10000, status=RideStatus.SCHEDULED)
    ride_sched_no_show = process_ride_timers(ride_sched, current_time=10601, policy=policy)
    assert ride_sched_no_show.lifecycle_status == RideStatus.DRIVER_NO_SHOW


def test_boarding_grace_exact_boundary() -> None:
    """
    T045: Boarding grace exact boundary:
    Stop arrived at T_arr = 1000s, boarding_grace_period_seconds = 180s.
    t = 1000 + 180s = 1180s: passenger boarding is accepted (transitions to COMPLETED).
    t = 1000 + 181s = 1181s without boarding: transitions to NO_SHOW, freeing seats.
    """
    policy = DispatchPolicy(boarding_grace_period_seconds=180)
    stop_arrived = _create_sample_stop(
        stop_id="stop-p-grace",
        status=StopStatus.IN_GRACE_PERIOD,
        actual_arrival_time=1000,
    )
    ride = _create_sample_ride(
        departure_time=1000,
        status=RideStatus.ACTIVE,
        stops=(stop_arrived,),
    )

    # 1. At t = 1180s: Boarding confirmation is accepted
    updated_ride, updated_stop = confirm_passenger_boarding(
        ride=ride,
        stop_id="stop-p-grace",
        current_time=1180,
        policy=policy,
    )
    assert updated_stop.status == StopStatus.COMPLETED
    assert updated_ride.active_passenger_count == 1

    # 2. At t = 1181s: Without boarding confirmation, timer processor marks NO_SHOW
    ride_stale = _create_sample_ride(
        departure_time=1000,
        status=RideStatus.ACTIVE,
        stops=(stop_arrived,),
    )
    ride_timed_out = process_ride_timers(ride_stale, current_time=1181, policy=policy)
    timed_out_stop = ride_timed_out.stops[0]
    assert timed_out_stop.status == StopStatus.NO_SHOW

    # Attempting to board after NO_SHOW is rejected
    with pytest.raises(LifecycleTransitionError, match="NO_SHOW"):
        confirm_passenger_boarding(
            ride=ride_timed_out,
            stop_id="stop-p-grace",
            current_time=1182,
            policy=policy,
        )


# Alias matching quickstart validation guide
test_grace_period_boundaries = test_boarding_grace_exact_boundary



# -----------------------------------------------------------------------------
# T046: GPS Arrival Dwell Filter Tests
# -----------------------------------------------------------------------------

def test_gps_arrival_dwell_passthrough_rejected() -> None:
    """
    T046: Vehicle passing through a geofence at 45 km/h for only 3s
    does NOT trigger arrival. Stop remains SCHEDULED.
    """
    policy = DispatchPolicy(stop_arrival_dwell_seconds=15)
    stop_loc = GeoCoordinate(latitude=40.71280, longitude=-74.00600)
    stop = _create_sample_stop(location=stop_loc, status=StopStatus.SCHEDULED)

    # Vehicle passes through geofence at 45 km/h: enters at t=100, exits at t=103 (3s dwell)
    ping1 = GpsTelemetryPing(
        vehicle_id="veh-1",
        location=GeoCoordinate(latitude=40.71281, longitude=-74.00601),
        timestamp=100,
        speed_kmh=45.0,
    )
    stop_after_ping1 = process_gps_telemetry(stop, ping1, policy=policy)
    assert stop_after_ping1.status == StopStatus.SCHEDULED
    assert stop_after_ping1.dwell_start_time == 100
    assert stop_after_ping1.dwell_duration_seconds == 0

    ping2 = GpsTelemetryPing(
        vehicle_id="veh-1",
        location=GeoCoordinate(latitude=40.71285, longitude=-74.00605),
        timestamp=103,
        speed_kmh=45.0,
    )
    stop_after_ping2 = process_gps_telemetry(stop_after_ping1, ping2, policy=policy)
    assert stop_after_ping2.status == StopStatus.SCHEDULED
    assert stop_after_ping2.dwell_duration_seconds == 3

    # Ping 3 is outside geofence (exited): dwell is broken and resets
    ping3 = GpsTelemetryPing(
        vehicle_id="veh-1",
        location=GeoCoordinate(latitude=40.72000, longitude=-74.02000),  # > 1 km away
        timestamp=105,
        speed_kmh=45.0,
    )
    stop_after_exit = process_gps_telemetry(stop_after_ping2, ping3, policy=policy)
    assert stop_after_exit.status == StopStatus.SCHEDULED
    assert stop_after_exit.dwell_start_time is None
    assert stop_after_exit.dwell_duration_seconds == 0


def test_gps_arrival_continuous_dwell_accepted() -> None:
    """
    T046: Vehicle dwelling continuously within geofence for >= 15s triggers ARRIVED.
    GPS arrival alone does NOT establish passenger boarded (Stop is NOT COMPLETED).
    """
    policy = DispatchPolicy(stop_arrival_dwell_seconds=15)
    stop_loc = GeoCoordinate(latitude=40.71280, longitude=-74.00600)
    stop = _create_sample_stop(location=stop_loc, status=StopStatus.SCHEDULED)

    # Ping at t = 200: enters geofence
    p1 = GpsTelemetryPing(
        vehicle_id="veh-1",
        location=GeoCoordinate(latitude=40.71281, longitude=-74.00601),
        timestamp=200,
        speed_kmh=0.0,
    )
    s1 = process_gps_telemetry(stop, p1, policy=policy)
    assert s1.status == StopStatus.SCHEDULED
    assert s1.dwell_start_time == 200

    # Ping at t = 210: 10s elapsed (still < 15s)
    p2 = GpsTelemetryPing(
        vehicle_id="veh-1",
        location=GeoCoordinate(latitude=40.71281, longitude=-74.00601),
        timestamp=210,
        speed_kmh=0.0,
    )
    s2 = process_gps_telemetry(s1, p2, policy=policy)
    assert s2.status == StopStatus.SCHEDULED
    assert s2.dwell_duration_seconds == 10

    # Ping at t = 215: exactly 15s elapsed (dwell >= 15s) -> ARRIVED
    p3 = GpsTelemetryPing(
        vehicle_id="veh-1",
        location=GeoCoordinate(latitude=40.71280, longitude=-74.00600),
        timestamp=215,
        speed_kmh=0.0,
    )
    s3 = process_gps_telemetry(s2, p3, policy=policy)
    # Verification of Requirement 4: GPS arrival transitions to ARRIVED/IN_GRACE_PERIOD, NOT COMPLETED
    assert s3.status in (StopStatus.ARRIVED, StopStatus.IN_GRACE_PERIOD)
    assert s3.actual_arrival_time == 215


# -----------------------------------------------------------------------------
# Transitions & Invariants Verification
# -----------------------------------------------------------------------------

def test_invalid_state_transitions_rejected() -> None:
    """Verifies that illegal lifecycle transitions raise LifecycleTransitionError."""
    ride = _create_sample_ride(status=RideStatus.CANCELLED)
    with pytest.raises(LifecycleTransitionError):
        transition_ride_status(ride, RideStatus.ACTIVE)

    stop = _create_sample_stop(status=StopStatus.SCHEDULED)
    with pytest.raises(LifecycleTransitionError):
        # Cannot complete without arrival
        transition_stop_status(stop, StopStatus.COMPLETED)


def test_idempotent_lifecycle_transitions() -> None:
    """Repeated identical transitions are idempotent and safe."""
    ride = _create_sample_ride(status=RideStatus.ACTIVE)
    same_ride = transition_ride_status(ride, RideStatus.ACTIVE)
    assert same_ride.lifecycle_status == RideStatus.ACTIVE

    stop = _create_sample_stop(status=StopStatus.ARRIVED)
    same_stop = transition_stop_status(stop, StopStatus.ARRIVED)
    assert same_stop.status == StopStatus.ARRIVED


def test_distinct_boarding_and_departure_events() -> None:
    """
    GPS arrival, passenger boarding, and ride departure must be distinct events.
    """
    stop = _create_sample_stop(status=StopStatus.SCHEDULED)
    ride = _create_sample_ride(status=RideStatus.ACTIVE, stops=(stop,))

    # 1. Driver or GPS triggers arrival
    stop_arr = confirm_stop_arrival(stop, current_time=1000)
    assert stop_arr.status in (StopStatus.ARRIVED, StopStatus.IN_GRACE_PERIOD)
    assert stop_arr.actual_arrival_time == 1000

    # 2. Passenger boarding confirmed separately
    ride_with_stop = ride.model_copy(update={"stops": (stop_arr,)})
    ride_boarded, stop_boarded = confirm_passenger_boarding(
        ride=ride_with_stop,
        stop_id=stop.stop_id,
        current_time=1050,
    )
    assert stop_boarded.status == StopStatus.COMPLETED
    assert ride_boarded.active_passenger_count == 1
    assert ride_boarded.actual_departure_time is None  # Not yet departed

    # 3. Ride departure confirmed separately
    ride_departed = confirm_ride_departure(ride_boarded, departure_time=1060)
    assert ride_departed.actual_departure_time == 1060


def test_confirm_passenger_boarding_rejects_dropoff_stop() -> None:
    """
    Fix 3 Regression: confirm_passenger_boarding must reject non-PICKUP stops
    with LifecycleTransitionError, preserving state without decrementing active passengers.
    """
    dropoff_stop = _create_sample_stop(
        stop_id="stop-d-1",
        stop_type=StopType.DROPOFF,
        status=StopStatus.ARRIVED,
        actual_arrival_time=1000,
    )
    ride = _create_sample_ride(status=RideStatus.ACTIVE, stops=(dropoff_stop,))
    ride = ride.model_copy(update={"active_passenger_count": 1})

    with pytest.raises(LifecycleTransitionError, match="not a PICKUP stop"):
        confirm_passenger_boarding(
            ride=ride,
            stop_id=dropoff_stop.stop_id,
            current_time=1010,
        )

    # Verify state was not corrupted
    assert ride.active_passenger_count == 1
    assert dropoff_stop.status == StopStatus.ARRIVED


def test_confirm_ride_departure_rejects_terminal_rides() -> None:
    """
    Verifies that calling confirm_ride_departure on a ride in terminal state
    (CANCELLED, DRIVER_NO_SHOW, or COMPLETED) raises LifecycleTransitionError.
    """
    for status in (RideStatus.CANCELLED, RideStatus.DRIVER_NO_SHOW, RideStatus.COMPLETED):
        ride = _create_sample_ride(status=status)
        with pytest.raises(LifecycleTransitionError, match="terminal state"):
            confirm_ride_departure(ride, departure_time=1050)


def test_process_ride_timers_completes_ride_when_all_stops_no_show() -> None:
    """
    Verifies that when a pickup stop expires to NO_SHOW and its downstream dropoff
    is marked SKIPPED, leaving all stops in terminal status with zero active passengers,
    the ride transitions from ACTIVE to COMPLETED.
    """
    p_stop = _create_sample_stop(
        stop_id="stop-p-ns",
        request_id="req-ns-1",
        stop_type=StopType.PICKUP,
        status=StopStatus.IN_GRACE_PERIOD,
        actual_arrival_time=1000,
    )
    d_stop = _create_sample_stop(
        stop_id="stop-d-ns",
        request_id="req-ns-1",
        stop_type=StopType.DROPOFF,
        status=StopStatus.SCHEDULED,
        scheduled_arrival_time=1500,
    )
    ride = _create_sample_ride(
        departure_time=1000,
        status=RideStatus.ACTIVE,
        stops=(p_stop, d_stop),
    )

    policy = DispatchPolicy(boarding_grace_period_seconds=180)
    # At t = 1000 + 181 = 1181: boarding grace expires
    timed_out_ride = process_ride_timers(ride, current_time=1181, policy=policy)

    assert timed_out_ride.stops[0].status == StopStatus.NO_SHOW
    assert timed_out_ride.stops[1].status == StopStatus.SKIPPED
    assert timed_out_ride.active_passenger_count == 0
    assert timed_out_ride.lifecycle_status == RideStatus.COMPLETED

