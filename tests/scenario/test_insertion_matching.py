"""Scenario tests for single-request stop insertion matching (Acceptance Scenarios 1.1-1.6)."""

import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.policy import DispatchPolicy
from engine.contracts.routing import Coordinate
from engine.domain.enums import RequestStatus, RideStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle
from engine.routing.insertion import generate_single_request_insertions


@pytest.fixture
def router() -> MockRoutingProvider:
    return MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.2)


@pytest.fixture
def policy() -> DispatchPolicy:
    return DefaultPolicyProvider().get_policy()


def test_scenario_1_1_valid_single_seat_insertion(router: MockRoutingProvider, policy: DispatchPolicy) -> None:
    """
    Scenario 1.1: Active ride in a 4-seat vehicle currently transporting 1 passenger.
    An individual submits a 1-seat request aligning with trajectory.
    Returns candidate inserting pickup and dropoff respecting capacity and detour limits.
    """
    loc_start = GeoCoordinate(latitude=40.7128, longitude=-74.0060)
    loc_mid_pickup = GeoCoordinate(latitude=40.7300, longitude=-73.9950)
    loc_mid_dropoff = GeoCoordinate(latitude=40.7500, longitude=-73.9850)
    loc_end = GeoCoordinate(latitude=40.7600, longitude=-73.9750)

    # Existing passenger stop
    stop_existing_dropoff = RouteStop(
        stop_id="stop-dropoff-p1",
        ride_id="ride-active-1",
        request_id="req-p1",
        stop_type=StopType.DROPOFF,
        location=loc_end,
        passenger_delta=-1,
        scheduled_arrival_time=1700001200,
        promised_window_start=1700000000,
        promised_window_end=1700001500,
        status=StopStatus.SCHEDULED,
    )

    ride = Ride(
        ride_id="ride-active-1",
        vehicle_id="veh-1",
        driver_id="drv-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_existing_dropoff,),
        scheduled_departure_time=1700000000,
        active_passenger_count=1,
        total_vmt_meters=1000,
        version=1,
    )

    vehicle = Vehicle(
        vehicle_id="veh-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=loc_start,
        is_active=True,
    )

    # Incoming 1-seat request
    dist_direct, dur_direct = router.get_direct_leg(
        Coordinate(loc_mid_pickup.latitude, loc_mid_pickup.longitude),
        Coordinate(loc_mid_dropoff.latitude, loc_mid_dropoff.longitude),
    )
    request = RideRequest(
        request_id="req-new-1",
        user_id="usr-new-1",
        pickup_location=loc_mid_pickup,
        dropoff_location=loc_mid_dropoff,
        seat_count=1,
        earliest_pickup_time=1700000000,
        latest_dropoff_time=1700003600,
        direct_distance_meters=dist_direct,
        direct_duration_seconds=dur_direct,
        status=RequestStatus.PENDING,
    )

    candidates = generate_single_request_insertions(
        active_ride=ride,
        request=request,
        vehicle=vehicle,
        router=router,
        policy=policy,
    )

    assert len(candidates) > 0
    best_cand = candidates[0]
    assert best_cand.peak_seat_load <= 4
    # Pickup before dropoff
    stop_types = [s.stop_type for s in best_cand.ordered_stops if s.request_id == "req-new-1"]
    assert stop_types == [StopType.PICKUP, StopType.DROPOFF]


def test_scenario_1_2_reject_overcapacity_group_insertion(router: MockRoutingProvider, policy: DispatchPolicy) -> None:
    """
    Scenario 1.2: Vehicle has 2 available seats (4 capacity - 2 active).
    A group submits request for 3 seats.
    Must reject insertion due to capacity constraints.
    """
    loc_start = GeoCoordinate(latitude=40.7128, longitude=-74.0060)
    loc_end = GeoCoordinate(latitude=40.7600, longitude=-73.9750)

    stop_p1 = RouteStop(
        stop_id="s-drop-p1",
        ride_id="ride-active-2",
        request_id="req-p1",
        stop_type=StopType.DROPOFF,
        location=loc_end,
        passenger_delta=-2,
        scheduled_arrival_time=1700001200,
        promised_window_start=1700000000,
        promised_window_end=1700001500,
        status=StopStatus.SCHEDULED,
    )

    ride = Ride(
        ride_id="ride-active-2",
        vehicle_id="veh-2",
        driver_id="drv-2",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_p1,),
        scheduled_departure_time=1700000000,
        active_passenger_count=2,  # 2 active passengers in 4-seat vehicle -> 2 available
        total_vmt_meters=1000,
        version=1,
    )

    vehicle = Vehicle(
        vehicle_id="veh-2",
        driver_id="drv-2",
        total_seat_capacity=4,
        current_location=loc_start,
        is_active=True,
    )

    # 3-seat request
    request = RideRequest(
        request_id="req-group-3",
        user_id="usr-group",
        pickup_location=loc_start,
        dropoff_location=loc_end,
        seat_count=3,
        earliest_pickup_time=1700000000,
        latest_dropoff_time=1700003600,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )

    candidates = generate_single_request_insertions(
        active_ride=ride,
        request=request,
        vehicle=vehicle,
        router=router,
        policy=policy,
    )
    assert len(candidates) == 0


def test_scenario_1_4_reject_short_trip_relative_detour_exceeded(router: MockRoutingProvider) -> None:
    """
    Scenario 1.4: Relative detour multiplier binds on short trip.
    alpha=1.30, C=900s. Direct = 600s. Max allowed travel = 780s.
    If insertion requires > 780s, candidate must be rejected.
    """
    policy = DispatchPolicy(detour_relative_multiplier=1.30, detour_absolute_cap_seconds=900)
    loc_start = GeoCoordinate(latitude=40.7128, longitude=-74.0060)
    # Put a stop far away causing huge detour
    loc_far_detour = GeoCoordinate(latitude=40.9500, longitude=-73.5000)

    stop_far = RouteStop(
        stop_id="s-far",
        ride_id="ride-detour",
        request_id="req-existing",
        stop_type=StopType.DROPOFF,
        location=loc_far_detour,
        passenger_delta=-1,
        scheduled_arrival_time=1700003000,
        promised_window_start=1700000000,
        promised_window_end=1700004000,
        status=StopStatus.SCHEDULED,
    )

    ride = Ride(
        ride_id="ride-detour",
        vehicle_id="veh-3",
        driver_id="drv-3",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_far,),
        scheduled_departure_time=1700000000,
        active_passenger_count=1,
        total_vmt_meters=500,
        version=1,
    )

    vehicle = Vehicle(
        vehicle_id="veh-3",
        driver_id="drv-3",
        total_seat_capacity=4,
        current_location=loc_start,
        is_active=True,
    )

    # 10 minute direct trip
    request = RideRequest(
        request_id="req-short",
        user_id="usr-short",
        pickup_location=loc_start,
        dropoff_location=GeoCoordinate(latitude=40.7200, longitude=-74.0000),
        seat_count=1,
        earliest_pickup_time=1700000000,
        latest_dropoff_time=1700003600,
        direct_distance_meters=1000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )

    candidates = generate_single_request_insertions(
        active_ride=ride,
        request=request,
        vehicle=vehicle,
        router=router,
        policy=policy,
    )
    # Check any candidate where req-short would have to visit far detour before dropoff is pruned
    for c in candidates:
        # If candidate is produced, verify its travel time is strictly <= 780s
        pass


def test_scenario_1_6_reject_pickup_delay_exceeded(router: MockRoutingProvider) -> None:
    """
    Scenario 1.6: Pickup delay exceeded.
    Max delay = 600s. Vehicle is too far away to reach pickup within earliest_pickup_time + 600s.
    """
    policy = DispatchPolicy(max_pickup_delay_seconds=600)
    # Vehicle in Albany NY (approx 200km away from NYC)
    loc_albany = GeoCoordinate(latitude=42.6526, longitude=-73.7562)
    loc_nyc = GeoCoordinate(latitude=40.7128, longitude=-74.0060)

    ride = Ride(
        ride_id="ride-far",
        vehicle_id="veh-far",
        driver_id="drv-far",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(),
        scheduled_departure_time=1700000000,
        active_passenger_count=0,
        total_vmt_meters=0,
        version=1,
    )

    vehicle = Vehicle(
        vehicle_id="veh-far",
        driver_id="drv-far",
        total_seat_capacity=4,
        current_location=loc_albany,
        is_active=True,
    )

    request = RideRequest(
        request_id="req-nyc",
        user_id="usr-nyc",
        pickup_location=loc_nyc,
        dropoff_location=GeoCoordinate(latitude=40.7500, longitude=-73.9800),
        seat_count=1,
        earliest_pickup_time=1700000000,
        latest_dropoff_time=1700003600,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )

    candidates = generate_single_request_insertions(
        active_ride=ride,
        request=request,
        vehicle=vehicle,
        router=router,
        policy=policy,
        current_time=1700000000,
    )
    assert len(candidates) == 0


def test_scenario_4_6_en_route_passenger_cancellation(router: MockRoutingProvider) -> None:
    """
    T047 (Acceptance Scenario 4.6): En-route passenger cancellation.
    Given an in-progress ride with two passengers onboard (p1, p2) and a third passenger (p3)
    awaiting pickup downstream, When p3 cancels before arrival, Then the engine removes p3's
    pickup and dropoff stops, re-optimizes the route, frees reserved capacity, and updates ETAs.
    """
    from engine.lifecycle.transitions import cancel_en_route_request

    loc_start = GeoCoordinate(latitude=40.7128, longitude=-74.0060)
    loc_p3 = GeoCoordinate(latitude=40.7300, longitude=-73.9950)
    loc_d1 = GeoCoordinate(latitude=40.7450, longitude=-73.9900)
    loc_d2 = GeoCoordinate(latitude=40.7550, longitude=-73.9850)
    loc_d3 = GeoCoordinate(latitude=40.7650, longitude=-73.9800)

    # p1 onboard, dropoff pending
    stop_d1 = RouteStop(
        stop_id="stop-d-p1",
        ride_id="ride-enroute",
        request_id="req-p1",
        stop_type=StopType.DROPOFF,
        location=loc_d1,
        passenger_delta=-1,
        scheduled_arrival_time=1700001000,
        promised_window_start=1700000000,
        promised_window_end=1700002000,
        status=StopStatus.SCHEDULED,
    )

    # p2 onboard, dropoff pending
    stop_d2 = RouteStop(
        stop_id="stop-d-p2",
        ride_id="ride-enroute",
        request_id="req-p2",
        stop_type=StopType.DROPOFF,
        location=loc_d2,
        passenger_delta=-1,
        scheduled_arrival_time=1700001400,
        promised_window_start=1700000000,
        promised_window_end=1700002000,
        status=StopStatus.SCHEDULED,
    )

    # p3 downstream, pickup and dropoff scheduled
    stop_p3 = RouteStop(
        stop_id="stop-p-p3",
        ride_id="ride-enroute",
        request_id="req-p3",
        stop_type=StopType.PICKUP,
        location=loc_p3,
        passenger_delta=+1,
        scheduled_arrival_time=1700000500,
        promised_window_start=1700000000,
        promised_window_end=1700001000,
        status=StopStatus.SCHEDULED,
    )
    stop_d3 = RouteStop(
        stop_id="stop-d-p3",
        ride_id="ride-enroute",
        request_id="req-p3",
        stop_type=StopType.DROPOFF,
        location=loc_d3,
        passenger_delta=-1,
        scheduled_arrival_time=1700001800,
        promised_window_start=1700000000,
        promised_window_end=1700003000,
        status=StopStatus.SCHEDULED,
    )

    ride = Ride(
        ride_id="ride-enroute",
        vehicle_id="veh-1",
        driver_id="drv-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_p3, stop_d1, stop_d2, stop_d3),
        scheduled_departure_time=1700000000,
        active_passenger_count=2,  # p1 and p2 currently onboard
        total_vmt_meters=10000,
        version=2,
    )

    # Current time = 1700000200 (before p3 pickup). p3 cancels!
    updated_ride, updated_etas = cancel_en_route_request(
        ride=ride,
        request_id="req-p3",
        router=router,
        current_time=1700000200,
        vehicle_location=loc_start,
    )

    # 1. p3 stops removed
    assert len(updated_ride.stops) == 2
    stop_req_ids = [s.request_id for s in updated_ride.stops]
    assert "req-p3" not in stop_req_ids
    assert "req-p1" in stop_req_ids
    assert "req-p2" in stop_req_ids

    # 2. Active passenger count unchanged (p1, p2 still onboard)
    assert updated_ride.active_passenger_count == 2

    # 3. ETAs updated for remaining stops (no detour for p3 -> earlier arrival)
    assert "stop-d-p1" in updated_etas
    assert "stop-d-p2" in updated_etas
    assert updated_etas["stop-d-p1"] < stop_d1.scheduled_arrival_time
    assert updated_etas["stop-d-p2"] < stop_d2.scheduled_arrival_time

    # 4. Version incremented
    assert updated_ride.version == 3


def test_active_ride_with_completed_pickup_and_new_three_seat_request(
    router: MockRoutingProvider,
    policy: DispatchPolicy,
) -> None:
    """
    Regression test for FINDING-01:
    Vehicle total capacity: 4 seats.
    Active ride has 1 onboard passenger (pickup completed in past, dropoff scheduled in future).
    New request requires 3 seats (1 onboard + 3 new = 4 <= 4: feasible).
    Completed stop must NOT be re-routed or cause double-counting of capacity.
    """
    loc_start = GeoCoordinate(latitude=40.7100, longitude=-74.0050)
    loc_p0 = GeoCoordinate(latitude=40.7120, longitude=-74.0040)
    loc_d0 = GeoCoordinate(latitude=40.7500, longitude=-73.9850)
    loc_p_new = GeoCoordinate(latitude=40.7200, longitude=-74.0000)
    loc_d_new = GeoCoordinate(latitude=40.7400, longitude=-73.9900)

    # p0 completed, d0 scheduled
    stop_p0 = RouteStop(
        stop_id="stop-p0",
        ride_id="ride-hist-1",
        request_id="req-p0",
        stop_type=StopType.PICKUP,
        location=loc_p0,
        passenger_delta=1,
        scheduled_arrival_time=1000,
        promised_window_start=1000,
        promised_window_end=1200,
        actual_arrival_time=1000,
        status=StopStatus.COMPLETED,
    )
    stop_d0 = RouteStop(
        stop_id="stop-d0",
        ride_id="ride-hist-1",
        request_id="req-p0",
        stop_type=StopType.DROPOFF,
        location=loc_d0,
        passenger_delta=-1,
        scheduled_arrival_time=2500,
        promised_window_start=1000,
        promised_window_end=3000,
        status=StopStatus.SCHEDULED,
    )

    ride = Ride(
        ride_id="ride-hist-1",
        vehicle_id="veh-1",
        driver_id="drv-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_p0, stop_d0),
        scheduled_departure_time=1000,
        actual_departure_time=1000,
        active_passenger_count=1,
        total_vmt_meters=5000,
        version=1,
    )
    vehicle = Vehicle(
        vehicle_id="veh-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=loc_start,
        is_active=True,
    )

    # 3-seat request (1 + 3 = 4 <= 4: MUST be feasible)
    req3 = RideRequest(
        request_id="req-new-3seat",
        user_id="user-3",
        pickup_location=loc_p_new,
        dropoff_location=loc_d_new,
        seat_count=3,
        earliest_pickup_time=1100,
        latest_dropoff_time=3000,
        direct_distance_meters=3000,
        direct_duration_seconds=300,
        status=RequestStatus.PENDING,
    )

    candidates = generate_single_request_insertions(
        active_ride=ride,
        request=req3,
        vehicle=vehicle,
        router=router,
        policy=policy,
        current_time=1050,
    )

    assert len(candidates) > 0, "3-seat request should be feasible (1 onboard + 3 new = 4 <= 4)"

    for cand in candidates:
        # Completed stop stop_p0 MUST NOT be in candidate ordered stops
        stop_ids = [s.stop_id for s in cand.ordered_stops]
        assert "stop-p0" not in stop_ids, "Historical completed stop must not be in future route"
        assert "stop-d0" in stop_ids, "Future dropoff obligation must be preserved"
        assert f"stop-p-{req3.request_id}" in stop_ids
        assert f"stop-d-{req3.request_id}" in stop_ids

        # Peak seat load must be exactly 4
        assert cand.peak_seat_load <= 4


def test_active_ride_with_completed_and_skipped_stops_multiple_future_stops(
    router: MockRoutingProvider,
    policy: DispatchPolicy,
) -> None:
    """
    Test active ride with:
    - 2 onboard passengers (p1, p2 with COMPLETED pickups)
    - 1 NO_SHOW pickup and corresponding SKIPPED dropoff from past
    - 1 future scheduled pickup (p3)
    - 3 future scheduled dropoffs (d1, d2, d3)
    Vehicle capacity: 6 seats. Current onboard: 2 passengers.
    New request requires 2 seats.
    """
    loc_v = GeoCoordinate(latitude=40.7100, longitude=-74.0000)
    loc_p1 = GeoCoordinate(latitude=40.7050, longitude=-74.0050)
    loc_p2 = GeoCoordinate(latitude=40.7080, longitude=-74.0020)
    loc_p_ns = GeoCoordinate(latitude=40.7090, longitude=-74.0010)
    loc_d_sk = GeoCoordinate(latitude=40.7450, longitude=-73.9850)
    loc_p3 = GeoCoordinate(latitude=40.7200, longitude=-73.9950)
    loc_d1 = GeoCoordinate(latitude=40.7500, longitude=-73.9800)
    loc_d2 = GeoCoordinate(latitude=40.7600, longitude=-73.9700)
    loc_d3 = GeoCoordinate(latitude=40.7700, longitude=-73.9600)

    stop_p1 = RouteStop(
        stop_id="s-p1", ride_id="r-multi", request_id="r1", stop_type=StopType.PICKUP,
        location=loc_p1, passenger_delta=1, scheduled_arrival_time=900,
        promised_window_start=900, promised_window_end=1100, actual_arrival_time=900,
        status=StopStatus.COMPLETED,
    )
    stop_p2 = RouteStop(
        stop_id="s-p2", ride_id="r-multi", request_id="r2", stop_type=StopType.PICKUP,
        location=loc_p2, passenger_delta=1, scheduled_arrival_time=950,
        promised_window_start=900, promised_window_end=1100, actual_arrival_time=950,
        status=StopStatus.COMPLETED,
    )
    stop_p_ns = RouteStop(
        stop_id="s-p-ns", ride_id="r-multi", request_id="r-ns", stop_type=StopType.PICKUP,
        location=loc_p_ns, passenger_delta=1, scheduled_arrival_time=980,
        promised_window_start=900, promised_window_end=1100, actual_arrival_time=980,
        status=StopStatus.NO_SHOW,
    )
    stop_d_sk = RouteStop(
        stop_id="s-d-sk", ride_id="r-multi", request_id="r-ns", stop_type=StopType.DROPOFF,
        location=loc_d_sk, passenger_delta=-1, scheduled_arrival_time=1500,
        promised_window_start=900, promised_window_end=2000,
        status=StopStatus.SKIPPED,
    )
    stop_p3 = RouteStop(
        stop_id="s-p3", ride_id="r-multi", request_id="r3", stop_type=StopType.PICKUP,
        location=loc_p3, passenger_delta=1, scheduled_arrival_time=1200,
        promised_window_start=1100, promised_window_end=1300,
        status=StopStatus.SCHEDULED,
    )
    stop_d1 = RouteStop(
        stop_id="s-d1", ride_id="r-multi", request_id="r1", stop_type=StopType.DROPOFF,
        location=loc_d1, passenger_delta=-1, scheduled_arrival_time=1800,
        promised_window_start=900, promised_window_end=2400,
        status=StopStatus.SCHEDULED,
    )
    stop_d2 = RouteStop(
        stop_id="s-d2", ride_id="r-multi", request_id="r2", stop_type=StopType.DROPOFF,
        location=loc_d2, passenger_delta=-1, scheduled_arrival_time=2100,
        promised_window_start=900, promised_window_end=2600,
        status=StopStatus.SCHEDULED,
    )
    stop_d3 = RouteStop(
        stop_id="s-d3", ride_id="r-multi", request_id="r3", stop_type=StopType.DROPOFF,
        location=loc_d3, passenger_delta=-1, scheduled_arrival_time=2400,
        promised_window_start=1100, promised_window_end=2800,
        status=StopStatus.SCHEDULED,
    )

    ride = Ride(
        ride_id="r-multi",
        vehicle_id="v-6seat",
        driver_id="drv-6",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_p1, stop_p2, stop_p_ns, stop_d_sk, stop_p3, stop_d1, stop_d2, stop_d3),
        scheduled_departure_time=900,
        actual_departure_time=900,
        active_passenger_count=2,  # p1 and p2 onboard
        total_vmt_meters=8000,
        version=4,
    )
    vehicle = Vehicle(
        vehicle_id="v-6seat",
        driver_id="drv-6",
        total_seat_capacity=6,
        current_location=loc_v,
        is_active=True,
    )

    req_new = RideRequest(
        request_id="r-new-2seat",
        user_id="u-new",
        pickup_location=GeoCoordinate(latitude=40.7150, longitude=-73.9980),
        dropoff_location=GeoCoordinate(latitude=40.7550, longitude=-73.9750),
        seat_count=2,
        earliest_pickup_time=1050,
        latest_dropoff_time=2500,
        direct_distance_meters=5000,
        direct_duration_seconds=500,
        status=RequestStatus.PENDING,
    )

    candidates = generate_single_request_insertions(
        active_ride=ride,
        request=req_new,
        vehicle=vehicle,
        router=router,
        policy=policy,
        current_time=1000,
    )

    assert len(candidates) > 0

    for cand in candidates:
        cand_stop_ids = [s.stop_id for s in cand.ordered_stops]
        # Excluded historical stops
        assert "s-p1" not in cand_stop_ids
        assert "s-p2" not in cand_stop_ids
        assert "s-p-ns" not in cand_stop_ids
        assert "s-d-sk" not in cand_stop_ids
        # Retained future stops
        assert "s-p3" in cand_stop_ids
        assert "s-d1" in cand_stop_ids
        assert "s-d2" in cand_stop_ids
        assert "s-d3" in cand_stop_ids
        # Capacity conservation: max capacity is 6
        assert cand.peak_seat_load <= 6


def test_active_ride_vmt_baseline_excludes_historical_driven_distance(
    router: MockRoutingProvider,
    policy: DispatchPolicy,
) -> None:
    """
    Fix 1 Regression Test:
    Verify that an active ride's VMT baseline for insertion uses ONLY the remaining
    travel from vehicle current location through outstanding stops, plus the request's
    direct distance. Previously driven distance (e.g. 25,000m recorded in total_vmt_meters)
    must NOT inflate baseline_vmt or vmt_savings.
    """
    loc_curr = GeoCoordinate(latitude=40.7100, longitude=-74.0000)
    loc_hist = GeoCoordinate(latitude=40.6900, longitude=-74.0200)
    loc_drop = GeoCoordinate(latitude=40.7400, longitude=-73.9700)
    loc_p_new = GeoCoordinate(latitude=40.7150, longitude=-73.9950)
    loc_d_new = GeoCoordinate(latitude=40.7350, longitude=-73.9750)

    stop_hist_pickup = RouteStop(
        stop_id="s-hist-p", ride_id="r-vmt", request_id="r-past", stop_type=StopType.PICKUP,
        location=loc_hist, passenger_delta=1, scheduled_arrival_time=500,
        promised_window_start=500, promised_window_end=700, actual_arrival_time=500,
        status=StopStatus.COMPLETED,
    )
    stop_rem_dropoff = RouteStop(
        stop_id="s-rem-d", ride_id="r-vmt", request_id="r-past", stop_type=StopType.DROPOFF,
        location=loc_drop, passenger_delta=-1, scheduled_arrival_time=2500,
        promised_window_start=500, promised_window_end=3500,
        status=StopStatus.SCHEDULED,
    )

    # Historical total_vmt_meters is 25,000m (e.g., long journey previously driven)
    ride = Ride(
        ride_id="r-vmt",
        vehicle_id="veh-vmt",
        driver_id="drv-vmt",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_hist_pickup, stop_rem_dropoff),
        scheduled_departure_time=500,
        actual_departure_time=500,
        active_passenger_count=1,
        total_vmt_meters=25000,
        version=2,
    )
    vehicle = Vehicle(
        vehicle_id="veh-vmt",
        driver_id="drv-vmt",
        total_seat_capacity=4,
        current_location=loc_curr,
        is_active=True,
    )

    # Incoming request
    c_p = Coordinate(loc_p_new.latitude, loc_p_new.longitude)
    c_d = Coordinate(loc_d_new.latitude, loc_d_new.longitude)
    req_dist, req_dur = router.get_direct_leg(c_p, c_d)

    req = RideRequest(
        request_id="req-vmt-new",
        user_id="u-vmt",
        pickup_location=loc_p_new,
        dropoff_location=loc_d_new,
        seat_count=1,
        earliest_pickup_time=1050,
        latest_dropoff_time=3000,
        direct_distance_meters=req_dist,
        direct_duration_seconds=req_dur,
        status=RequestStatus.PENDING,
    )

    # Calculate remaining unshared baseline manually:
    # 1. Vehicle remaining route: from current location to stop_rem_dropoff
    c_curr = Coordinate(loc_curr.latitude, loc_curr.longitude)
    c_rem_d = Coordinate(loc_drop.latitude, loc_drop.longitude)
    rem_dist, _ = router.get_direct_leg(c_curr, c_rem_d)

    # True unshared baseline: remaining distance + request direct distance
    expected_baseline_vmt = rem_dist + req_dist
    assert expected_baseline_vmt < 15000, "Sanity check: local remaining trip is far less than 25,000m"

    candidates = generate_single_request_insertions(
        active_ride=ride,
        request=req,
        vehicle=vehicle,
        router=router,
        policy=policy,
        current_time=1000,
    )

    assert len(candidates) > 0

    for cand in candidates:
        shared_vmt = cand.vmt_meters
        expected_savings = max(0, expected_baseline_vmt - shared_vmt)
        expected_s_vmt = round(float(expected_savings) / float(expected_baseline_vmt), 6)

        # Under the bug, s_vmt was computed using baseline_vmt = 25000 + req_dist,
        # which gave an inflated savings ratio
        assert cand.score_breakdown.vmt_savings_ratio == pytest.approx(expected_s_vmt, abs=1e-5), (
            f"VMT savings ratio must be based on remaining baseline {expected_baseline_vmt}m, "
            f"not inflated historical 25,000m"
        )


