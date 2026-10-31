"""Unit tests for canonical domain models and enums."""

import pytest
from pydantic import ValidationError

from engine.domain.enums import (
    DriverStatus,
    JoinStatus,
    RequestStatus,
    RideStatus,
    StopStatus,
    StopType,
)
from engine.domain.models import (
    Driver,
    GeoCoordinate,
    JoinRequest,
    MatchResult,
    Ride,
    RideRequest,
    RouteStop,
    User,
    Vehicle,
)
from engine.domain.candidate import CandidateAssignment, ScoreBreakdown


def test_canonical_enums() -> None:
    assert RideStatus.DRAFT.value == "DRAFT"
    assert RideStatus.SCHEDULED.value == "SCHEDULED"
    assert RideStatus.ACTIVE.value == "ACTIVE"
    assert RideStatus.COMPLETED.value == "COMPLETED"
    assert RideStatus.CANCELLED.value == "CANCELLED"
    assert RideStatus.DRIVER_NO_SHOW.value == "DRIVER_NO_SHOW"

    assert StopStatus.SCHEDULED.value == "SCHEDULED"
    assert StopStatus.ARRIVED.value == "ARRIVED"
    assert StopStatus.IN_GRACE_PERIOD.value == "IN_GRACE_PERIOD"
    assert StopStatus.COMPLETED.value == "COMPLETED"
    assert StopStatus.NO_SHOW.value == "NO_SHOW"
    assert StopStatus.SKIPPED.value == "SKIPPED"

    assert JoinStatus.PENDING.value == "PENDING"
    assert JoinStatus.APPROVED.value == "APPROVED"
    assert JoinStatus.REJECTED.value == "REJECTED"
    assert JoinStatus.EXPIRED.value == "EXPIRED"

    assert DriverStatus.OFFLINE.value == "OFFLINE"
    assert DriverStatus.AVAILABLE.value == "AVAILABLE"
    assert DriverStatus.ASSIGNED.value == "ASSIGNED"
    assert DriverStatus.ON_TRIP.value == "ON_TRIP"
    assert DriverStatus.ON_BREAK.value == "ON_BREAK"

    assert StopType.PICKUP.value == "PICKUP"
    assert StopType.DROPOFF.value == "DROPOFF"
    assert StopType.WAYPOINT.value == "WAYPOINT"

    assert RequestStatus.PENDING.value == "PENDING"
    assert RequestStatus.MATCHED.value == "MATCHED"
    assert RequestStatus.IN_TRANSIT.value == "IN_TRANSIT"
    assert RequestStatus.COMPLETED.value == "COMPLETED"
    assert RequestStatus.EXPIRED.value == "EXPIRED"
    assert RequestStatus.CANCELLED.value == "CANCELLED"


def test_geo_coordinate_valid() -> None:
    coord = GeoCoordinate(latitude=40.7128, longitude=-74.0060)
    assert coord.latitude == 40.7128
    assert coord.longitude == -74.0060

    # Bounds
    GeoCoordinate(latitude=-90.0, longitude=-180.0)
    GeoCoordinate(latitude=90.0, longitude=180.0)


def test_geo_coordinate_invalid_bounds() -> None:
    with pytest.raises((ValueError, ValidationError)):
        GeoCoordinate(latitude=90.001, longitude=0.0)
    with pytest.raises((ValueError, ValidationError)):
        GeoCoordinate(latitude=-90.001, longitude=0.0)
    with pytest.raises((ValueError, ValidationError)):
        GeoCoordinate(latitude=0.0, longitude=180.001)
    with pytest.raises((ValueError, ValidationError)):
        GeoCoordinate(latitude=0.0, longitude=-180.001)


def test_geo_coordinate_immutability() -> None:
    coord = GeoCoordinate(latitude=10.0, longitude=20.0)
    with pytest.raises((TypeError, ValidationError)):
        coord.latitude = 15.0


def test_user_model() -> None:
    user = User(
        user_id="user-1234",
        name="Alice",
        accessibility_requirements=["wheelchair"],
        created_at=1700000000,
    )
    assert user.user_id == "user-1234"
    assert user.accessibility_requirements == ["wheelchair"]
    with pytest.raises((TypeError, ValidationError)):
        user.name = "Bob"


def test_driver_model_valid_and_bounds() -> None:
    loc = GeoCoordinate(latitude=40.7128, longitude=-74.0060)
    driver = Driver(
        driver_id="drv-1",
        name="Bob",
        active_status=DriverStatus.AVAILABLE,
        current_location=loc,
        shift_start_time=1700000000,
        shift_end_time=1700028800,
        total_idle_seconds=120,
    )
    assert driver.driver_id == "drv-1"
    assert driver.total_idle_seconds == 120

    with pytest.raises((ValueError, ValidationError)):
        Driver(
            driver_id="drv-1",
            name="Bob",
            active_status=DriverStatus.AVAILABLE,
            current_location=loc,
            shift_start_time=1700000000,
            shift_end_time=1700028800,
            total_idle_seconds=-5,
        )


def test_vehicle_model_valid_and_capacity_bounds() -> None:
    loc = GeoCoordinate(latitude=40.7128, longitude=-74.0060)
    vehicle = Vehicle(
        vehicle_id="veh-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        luggage_capacity_units=2,
        current_location=loc,
        is_active=True,
    )
    assert vehicle.total_seat_capacity == 4

    # Capacity bounds [1, 50]
    with pytest.raises((ValueError, ValidationError)):
        Vehicle(
            vehicle_id="veh-1",
            driver_id="drv-1",
            total_seat_capacity=0,
            luggage_capacity_units=2,
            current_location=loc,
            is_active=True,
        )
    with pytest.raises((ValueError, ValidationError)):
        Vehicle(
            vehicle_id="veh-1",
            driver_id="drv-1",
            total_seat_capacity=51,
            luggage_capacity_units=2,
            current_location=loc,
            is_active=True,
        )


def test_route_stop_and_ride_models() -> None:
    loc = GeoCoordinate(latitude=40.7128, longitude=-74.0060)
    stop1 = RouteStop(
        stop_id="stop-1",
        ride_id="ride-1",
        request_id="req-1",
        stop_type=StopType.PICKUP,
        location=loc,
        passenger_delta=1,
        scheduled_arrival_time=1700000600,
        promised_window_start=1700000000,
        promised_window_end=1700001200,
        actual_arrival_time=None,
        dwell_duration_seconds=0,
        dwell_start_time=None,
        status=StopStatus.SCHEDULED,
    )
    assert stop1.passenger_delta == 1

    ride = Ride(
        ride_id="ride-1",
        vehicle_id="veh-1",
        driver_id="drv-1",
        lifecycle_status=RideStatus.SCHEDULED,
        stops=(stop1,),
        scheduled_departure_time=1700000600,
        actual_departure_time=None,
        active_passenger_count=0,
        total_vmt_meters=0,
        version=1,
    )
    assert ride.version == 1

    # Version must be >= 1
    with pytest.raises((ValueError, ValidationError)):
        Ride(
            ride_id="ride-1",
            vehicle_id="veh-1",
            driver_id="drv-1",
            lifecycle_status=RideStatus.SCHEDULED,
            stops=(stop1,),
            scheduled_departure_time=1700000600,
            actual_departure_time=None,
            active_passenger_count=0,
            total_vmt_meters=0,
            version=0,
        )

    # Active passengers must be >= 0
    with pytest.raises((ValueError, ValidationError)):
        Ride(
            ride_id="ride-1",
            vehicle_id="veh-1",
            driver_id="drv-1",
            lifecycle_status=RideStatus.SCHEDULED,
            stops=(stop1,),
            scheduled_departure_time=1700000600,
            actual_departure_time=None,
            active_passenger_count=-1,
            total_vmt_meters=0,
            version=1,
        )


def test_ride_request_and_join_request() -> None:
    loc1 = GeoCoordinate(latitude=40.7128, longitude=-74.0060)
    loc2 = GeoCoordinate(latitude=40.7589, longitude=-73.9851)

    req = RideRequest(
        request_id="req-1",
        user_id="usr-1",
        pickup_location=loc1,
        dropoff_location=loc2,
        seat_count=2,
        earliest_pickup_time=1700000000,
        latest_dropoff_time=1700003600,
        direct_distance_meters=5000,
        direct_duration_seconds=900,
        status=RequestStatus.PENDING,
        matched_ride_id=None,
    )
    assert req.seat_count == 2
    assert req.direct_duration_seconds == 900

    # Negative direct duration
    with pytest.raises((ValueError, ValidationError)):
        RideRequest(
            request_id="req-1",
            user_id="usr-1",
            pickup_location=loc1,
            dropoff_location=loc2,
            seat_count=2,
            earliest_pickup_time=1700000000,
            latest_dropoff_time=1700003600,
            direct_distance_meters=5000,
            direct_duration_seconds=-10,
            status=RequestStatus.PENDING,
            matched_ride_id=None,
        )

    join = JoinRequest(
        join_request_id="join-1",
        ride_id="ride-1",
        request_id="req-1",
        user_id="usr-1",
        seat_count=2,
        submitted_at=1700000000,
        expires_at=1700000300,
        status=JoinStatus.PENDING,
        idempotency_token="idem-tok-123",
    )
    assert join.expires_at == 1700000300


def test_candidate_assignment_and_match_result() -> None:
    loc = GeoCoordinate(latitude=40.7128, longitude=-74.0060)
    stop = RouteStop(
        stop_id="stop-1",
        ride_id="ride-1",
        request_id="req-1",
        stop_type=StopType.PICKUP,
        location=loc,
        passenger_delta=1,
        scheduled_arrival_time=1700000600,
        promised_window_start=1700000000,
        promised_window_end=1700001200,
        actual_arrival_time=None,
        dwell_duration_seconds=0,
        dwell_start_time=None,
        status=StopStatus.SCHEDULED,
    )
    breakdown = ScoreBreakdown(
        vmt_savings_ratio=0.25,
        detour_penalty_ratio=0.10,
        wait_penalty_ratio=0.05,
        driver_idle_penalty_ratio=0.02,
    )
    candidate = CandidateAssignment(
        candidate_id="cand-1",
        vehicle_id="veh-1",
        existing_ride_id=None,
        request_ids=("req-1",),
        ordered_stops=(stop,),
        peak_seat_load=1,
        vmt_meters=4500,
        objective_value=0.15,
        normalized_score=0.75,
        score_breakdown=breakdown,
    )
    assert candidate.peak_seat_load == 1

    result = MatchResult(
        match_id="match-1",
        batch_id="batch-1",
        solver_timestamp=1700000600,
        selected_assignments=(candidate,),
        unassigned_request_ids=(),
        total_vmt_savings_meters=1500,
        solve_duration_ms=45.2,
    )
    assert result.total_vmt_savings_meters == 1500


def test_multi_objective_scoring_bounds_and_normalization() -> None:
    from engine.contracts.policy import DispatchPolicy
    from engine.optimization.objective import (
        calculate_display_score,
        calculate_objective_utility,
    )

    policy = DispatchPolicy(
        weight_vmt_reduction=0.40,
        weight_passenger_detour=0.30,
        weight_passenger_wait=0.20,
        weight_driver_idle=0.10,
    )

    # 1. Maximum possible utility: 100% VMT reduction, 0 penalties
    # J = 0.40 * 1.0 - 0.30 * 0.0 - 0.20 * 0.0 - 0.10 * 0.0 = +0.40
    j_max = calculate_objective_utility(
        s_vmt=1.0, p_detour=0.0, p_wait=0.0, p_idle=0.0, policy=policy
    )
    assert pytest.approx(j_max, 1e-6) == 0.40
    j_disp_max = calculate_display_score(j_max, policy)
    assert pytest.approx(j_disp_max, 1e-6) == 1.0

    # 2. Minimum possible utility: 0% VMT reduction, max penalties
    # J = 0.40 * 0.0 - (0.30 + 0.20 + 0.10) * 1.0 = -0.60
    j_min = calculate_objective_utility(
        s_vmt=0.0, p_detour=1.0, p_wait=1.0, p_idle=1.0, policy=policy
    )
    assert pytest.approx(j_min, 1e-6) == -0.60
    j_disp_min = calculate_display_score(j_min, policy)
    assert pytest.approx(j_disp_min, 1e-6) == 0.0

    # 3. Intermediate balanced case
    # J = 0.40 * 0.5 - 0.30 * 0.2 - 0.20 * 0.1 - 0.10 * 0.0 = 0.20 - 0.06 - 0.02 - 0 = 0.12
    j_mid = calculate_objective_utility(
        s_vmt=0.5, p_detour=0.2, p_wait=0.1, p_idle=0.0, policy=policy
    )
    assert pytest.approx(j_mid, 1e-6) == 0.12
    j_disp_mid = calculate_display_score(j_mid, policy)
    assert pytest.approx(j_disp_mid, 1e-6) == 0.72

    # 4. Range check: J in [-(1 - w_vmt), w_vmt]
    assert -(1.0 - policy.weight_vmt_reduction) <= j_mid <= policy.weight_vmt_reduction
    assert 0.0 <= j_disp_mid <= 1.0


def test_scoring_edge_cases_and_policy_validation() -> None:
    from engine.contracts.policy import DispatchPolicy
    from engine.optimization.objective import (
        calculate_candidate_score,
        calculate_display_score,
        calculate_objective_utility,
    )

    # 1. Invalid policy weight rejection
    invalid_policy_neg = DispatchPolicy(
        weight_vmt_reduction=-0.1,
        weight_passenger_detour=0.5,
        weight_passenger_wait=0.3,
        weight_driver_idle=0.3,
    )
    with pytest.raises(ValueError):
        calculate_objective_utility(0.5, 0.2, 0.1, 0.0, invalid_policy_neg)

    with pytest.raises(ValueError):
        calculate_display_score(0.2, invalid_policy_neg)

    with pytest.raises(ValueError):
        calculate_candidate_score(
            vmt_baseline=1000,
            vmt_pooled=800,
            requests=[],
            arrival_times={},
            policy=invalid_policy_neg,
        )

    # 2. Zero baseline & negative baseline handling
    valid_policy = DispatchPolicy()
    j_raw, j_disp, breakdown = calculate_candidate_score(
        vmt_baseline=0,
        vmt_pooled=1000,
        requests=[],
        arrival_times={},
        policy=valid_policy,
    )
    assert breakdown.vmt_savings_ratio == 0.0
    assert 0.0 <= j_disp <= 1.0

    j_raw_neg, j_disp_neg, breakdown_neg = calculate_candidate_score(
        vmt_baseline=-500,
        vmt_pooled=1000,
        requests=[],
        arrival_times={},
        policy=valid_policy,
    )
    assert breakdown_neg.vmt_savings_ratio == 0.0

    # 3. Pooled VMT greater than baseline -> savings 0.0
    j_raw_worse, j_disp_worse, breakdown_worse = calculate_candidate_score(
        vmt_baseline=5000,
        vmt_pooled=6000,
        requests=[],
        arrival_times={},
        policy=valid_policy,
    )
    assert breakdown_worse.vmt_savings_ratio == 0.0

    # 4. Penalty bounds clamping with excessive detour / wait
    loc = GeoCoordinate(latitude=40.7128, longitude=-74.0060)
    req = RideRequest(
        request_id="req-edge",
        user_id="u1",
        pickup_location=loc,
        dropoff_location=loc,
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=5000,
        direct_distance_meters=2000,
        direct_duration_seconds=300,
    )

    # Huge wait and detour
    arrival_times = {
        "stop-p-req-edge": 3000,  # wait = 2000s >> max_delay (600s)
        "stop-d-req-edge": 8000,  # in_veh = 5000s >> max_detour
    }
    j_pen, j_disp_pen, breakdown_pen = calculate_candidate_score(
        vmt_baseline=2000,
        vmt_pooled=1500,
        requests=[req],
        arrival_times=arrival_times,
        idle_time_seconds=99999,
        shift_time_seconds=100,  # idle > shift
        policy=valid_policy,
    )
    assert breakdown_pen.detour_penalty_ratio == 1.0
    assert breakdown_pen.wait_penalty_ratio == 1.0
    assert breakdown_pen.driver_idle_penalty_ratio == 1.0
    assert 0.0 <= j_disp_pen <= 1.0


