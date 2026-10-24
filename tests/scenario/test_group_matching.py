"""Scenario tests for multi-passenger group trip bundles (Acceptance Scenario 1.2)."""

import dataclasses
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.policy import DispatchPolicy
from engine.domain.enums import RequestStatus, StopType
from engine.domain.models import GeoCoordinate, RideRequest, Vehicle
from engine.routing.bundle_generator import generate_group_bundles


@pytest.fixture
def router() -> MockRoutingProvider:
    return MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.2)


@pytest.fixture
def policy() -> DispatchPolicy:
    return dataclasses.replace(DefaultPolicyProvider().get_policy(), max_pickup_delay_seconds=300)


def test_scenario_1_2_group_bundle_formation(router: MockRoutingProvider, policy: DispatchPolicy) -> None:
    """
    Test forming group bundles for an available 4-seat vehicle:
    Request A (2 seats) and Request B (2 seats) can bundle together (2 + 2 = 4 <= 4).
    Request C (3 seats) cannot bundle with Request A (2 + 3 = 5 > 4).
    Groups are NEVER split.
    """
    loc_veh = GeoCoordinate(latitude=40.7100, longitude=-74.0050)
    loc_a_p = GeoCoordinate(latitude=40.7128, longitude=-74.0060)
    loc_a_d = GeoCoordinate(latitude=40.7300, longitude=-73.9950)

    loc_b_p = GeoCoordinate(latitude=40.7150, longitude=-74.0040)
    loc_b_d = GeoCoordinate(latitude=40.7350, longitude=-73.9920)

    loc_c_p = GeoCoordinate(latitude=40.7180, longitude=-74.0020)
    loc_c_d = GeoCoordinate(latitude=40.7400, longitude=-73.9900)

    vehicle = Vehicle(
        vehicle_id="veh-avail-1",
        driver_id="drv-avail-1",
        total_seat_capacity=4,
        current_location=loc_veh,
        is_active=True,
    )

    req_a = RideRequest(
        request_id="req-A",
        user_id="usr-A",
        pickup_location=loc_a_p,
        dropoff_location=loc_a_d,
        seat_count=2,
        earliest_pickup_time=1700000000,
        latest_dropoff_time=1700003600,
        direct_distance_meters=2500,
        direct_duration_seconds=300,
        status=RequestStatus.PENDING,
    )

    req_b = RideRequest(
        request_id="req-B",
        user_id="usr-B",
        pickup_location=loc_b_p,
        dropoff_location=loc_b_d,
        seat_count=2,
        earliest_pickup_time=1700000000,
        latest_dropoff_time=1700003600,
        direct_distance_meters=2700,
        direct_duration_seconds=320,
        status=RequestStatus.PENDING,
    )

    req_c = RideRequest(
        request_id="req-C",
        user_id="usr-C",
        pickup_location=loc_c_p,
        dropoff_location=loc_c_d,
        seat_count=3,
        earliest_pickup_time=1700000000,
        latest_dropoff_time=1700003600,
        direct_distance_meters=2900,
        direct_duration_seconds=350,
        status=RequestStatus.PENDING,
    )

    # Bundle evaluation with A, B, C
    bundles = generate_group_bundles(
        vehicle=vehicle,
        requests=[req_a, req_b, req_c],
        router=router,
        policy=policy,
        current_time=1700000000,
    )

    # Check that any bundle containing A & B does not exceed capacity 4
    for b in bundles:
        assert b.peak_seat_load <= 4
        # Verify pickup before dropoff for all requests in bundle
        for r_id in b.request_ids:
            stops = [s.stop_type for s in b.ordered_stops if s.request_id == r_id]
            assert stops == [StopType.PICKUP, StopType.DROPOFF]

        # Verify A and C are NEVER together in the same bundle
        assert not ("req-A" in b.request_ids and "req-C" in b.request_ids)
        # Verify B and C are NEVER together in the same bundle (2 + 3 = 5 > 4)
        assert not ("req-B" in b.request_ids and "req-C" in b.request_ids)


# Alias matching quickstart validation guide
test_group_bundle_capacity = test_scenario_1_2_group_bundle_formation


def test_two_sequential_3_seat_requests_on_4_seat_vehicle_bundle_successfully(router: MockRoutingProvider) -> None:
    """
    Fix 4 Regression Test 1:
    Two sequential 3-seat requests on a 4-seat vehicle (combined sum = 6 > 4)
    must NOT be rejected at bundle generation. They are feasible because
    maximum simultaneous passenger load is 3 <= 4 along the route P1 -> D1 -> P2 -> D2.
    """
    policy = DispatchPolicy(max_pickup_delay_seconds=600)
    vehicle = Vehicle(
        vehicle_id="veh-seq-1",
        driver_id="drv-seq-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=40.7100, longitude=-74.0050),
        is_active=True,
    )

    # Request 1: 3 seats, from A to B
    req1 = RideRequest(
        request_id="req-seq-1",
        user_id="usr-seq-1",
        pickup_location=GeoCoordinate(latitude=40.7120, longitude=-74.0050),
        dropoff_location=GeoCoordinate(latitude=40.7200, longitude=-74.0050),
        seat_count=3,
        earliest_pickup_time=1000,
        latest_dropoff_time=2000,
        direct_distance_meters=1000,
        direct_duration_seconds=120,
        status=RequestStatus.PENDING,
    )

    # Request 2: 3 seats, from B to C (begins at req1 dropoff)
    req2 = RideRequest(
        request_id="req-seq-2",
        user_id="usr-seq-2",
        pickup_location=GeoCoordinate(latitude=40.7210, longitude=-74.0050),
        dropoff_location=GeoCoordinate(latitude=40.7300, longitude=-74.0050),
        seat_count=3,
        earliest_pickup_time=1000,
        latest_dropoff_time=2000,
        direct_distance_meters=1000,
        direct_duration_seconds=120,
        status=RequestStatus.PENDING,
    )

    bundles = generate_group_bundles(
        vehicle=vehicle,
        requests=[req1, req2],
        router=router,
        policy=policy,
        current_time=1000,
    )

    seq_bundles = [
        b for b in bundles
        if "req-seq-1" in b.request_ids and "req-seq-2" in b.request_ids
    ]
    assert len(seq_bundles) > 0, "Sequential bundle with sum(seats)=6 > capacity=4 must be formed"
    for b in seq_bundles:
        assert b.peak_seat_load == 3, f"Simultaneous peak load must be 3, got {b.peak_seat_load}"
        assert b.peak_seat_load <= vehicle.total_seat_capacity


def test_two_overlapping_3_seat_requests_on_4_seat_vehicle_rejected(router: MockRoutingProvider) -> None:
    """
    Fix 4 Regression Test 2:
    Two overlapping 3-seat requests on a 4-seat vehicle must be rejected
    because simultaneous passenger load would reach 3 + 3 = 6 > 4 during overlap,
    and pickup delay bounds prohibit non-overlapping sequential execution.
    """
    # max_pickup_delay_seconds=120 prevents req-ov-2 from waiting until req-ov-1 completes
    policy = DispatchPolicy(max_pickup_delay_seconds=120)
    vehicle = Vehicle(
        vehicle_id="veh-ov-1",
        driver_id="drv-ov-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=40.7100, longitude=-74.0050),
        is_active=True,
    )

    # Request 1: 3 seats, from A to C (trip takes ~300s)
    req1 = RideRequest(
        request_id="req-ov-1",
        user_id="usr-ov-1",
        pickup_location=GeoCoordinate(latitude=40.7120, longitude=-74.0050),
        dropoff_location=GeoCoordinate(latitude=40.7400, longitude=-74.0050),
        seat_count=3,
        earliest_pickup_time=1000,
        latest_dropoff_time=2000,
        direct_distance_meters=3500,
        direct_duration_seconds=300,
        status=RequestStatus.PENDING,
    )

    # Request 2: 3 seats, from B to D (B is between A and C, pickup at 1000)
    req2 = RideRequest(
        request_id="req-ov-2",
        user_id="usr-ov-2",
        pickup_location=GeoCoordinate(latitude=40.7200, longitude=-74.0050),
        dropoff_location=GeoCoordinate(latitude=40.7500, longitude=-74.0050),
        seat_count=3,
        earliest_pickup_time=1000,
        latest_dropoff_time=2000,
        direct_distance_meters=3500,
        direct_duration_seconds=300,
        status=RequestStatus.PENDING,
    )

    bundles = generate_group_bundles(
        vehicle=vehicle,
        requests=[req1, req2],
        router=router,
        policy=policy,
        current_time=1000,
    )

    ov_bundles = [
        b for b in bundles
        if "req-ov-1" in b.request_ids and "req-ov-2" in b.request_ids
    ]
    assert len(ov_bundles) == 0, "Overlapping requests exceeding vehicle capacity must be rejected"


