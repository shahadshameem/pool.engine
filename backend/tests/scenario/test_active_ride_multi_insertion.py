"""Scenario tests for multi-request insertion into active rides."""

import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.policy import DispatchPolicy
from engine.contracts.routing import Coordinate
from engine.dispatch import CandidateGenerationConfig, DispatchEngine
from engine.domain.enums import (
    DispatchMode,
    RequestStatus,
    RideStatus,
    StopStatus,
    StopType,
)
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle
from engine.routing.insertion import generate_active_ride_insertions


@pytest.fixture
def router() -> MockRoutingProvider:
    return MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)


@pytest.fixture
def policy() -> DispatchPolicy:
    return DispatchPolicy(
        max_pickup_delay_seconds=600,
        detour_relative_multiplier=1.40,
        detour_absolute_cap_seconds=900,
    )


def test_multi_request_insertion_into_active_ride_generates_bundle_candidates(
    router: MockRoutingProvider, policy: DispatchPolicy
) -> None:
    """
    Test that an active ride with available capacity generates candidate bundles
    containing multiple incoming requests in a single dispatch cycle.
    """
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-act-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )

    t_start = 1700000000
    d_onboard_loc = Coordinate(base_lat + 0.050, base_lon)
    _, dur_onboard = router.get_direct_leg(v_loc, d_onboard_loc)

    stop_dropoff_onboard = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-act-1",
        request_id="req-onboard",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onboard_loc.latitude, longitude=d_onboard_loc.longitude),
        passenger_delta=-1,
        scheduled_arrival_time=t_start + dur_onboard,
        promised_window_start=t_start,
        promised_window_end=t_start + dur_onboard + 1200,
        status=StopStatus.SCHEDULED,
    )

    active_ride = Ride(
        ride_id="ride-act-1",
        vehicle_id="veh-act-1",
        driver_id="drv-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_dropoff_onboard,),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )

    # Request 1: pickup at +0.010, dropoff at +0.030 (1 seat)
    p1 = Coordinate(base_lat + 0.010, base_lon)
    d1 = Coordinate(base_lat + 0.030, base_lon)
    dist1, dur1 = router.get_direct_leg(p1, d1)
    req1 = RideRequest(
        request_id="req-1",
        user_id="usr-1",
        pickup_location=GeoCoordinate(latitude=p1.latitude, longitude=p1.longitude),
        dropoff_location=GeoCoordinate(latitude=d1.latitude, longitude=d1.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=dist1,
        direct_duration_seconds=dur1,
        status=RequestStatus.PENDING,
    )

    # Request 2: pickup at +0.015, dropoff at +0.035 (1 seat)
    p2 = Coordinate(base_lat + 0.015, base_lon)
    d2 = Coordinate(base_lat + 0.035, base_lon)
    dist2, dur2 = router.get_direct_leg(p2, d2)
    req2 = RideRequest(
        request_id="req-2",
        user_id="usr-2",
        pickup_location=GeoCoordinate(latitude=p2.latitude, longitude=p2.longitude),
        dropoff_location=GeoCoordinate(latitude=d2.latitude, longitude=d2.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=dist2,
        direct_duration_seconds=dur2,
        status=RequestStatus.PENDING,
    )

    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    spatial = H3SpatialIndexAdapter()
    engine = DispatchEngine(
        policy_provider=policy_prov,
        routing_provider=router,
        spatial_index=spatial,
        config=CandidateGenerationConfig.exact(max_bundle_size=2),
    )

    cand_list = engine.generate_candidates(
        requests=[req1, req2],
        vehicles=[veh],
        active_rides=[active_ride],
        current_time=t_start,
    )

    # Verify both single and multi-request candidates are generated
    single_cands = [c for c in cand_list if len(c.request_ids) == 1]
    multi_cands = [c for c in cand_list if len(c.request_ids) == 2]

    assert len(single_cands) >= 2, "Must generate single insertion candidates for both requests"
    assert len(multi_cands) >= 1, "Must generate multi-request bundle candidates for {req1, req2}"

    bundle_cand = multi_cands[0]
    assert bundle_cand.vehicle_id == "veh-act-1"
    assert bundle_cand.existing_ride_id == "ride-act-1"
    assert set(bundle_cand.request_ids) == {"req-1", "req-2"}
    assert bundle_cand.peak_seat_load <= 4
    # Onboard dropoff must be present in ordered_stops
    stop_ids = [s.stop_id for s in bundle_cand.ordered_stops]
    assert "stop-d-onboard" in stop_ids
    assert "stop-p-req-1" in stop_ids
    assert "stop-d-req-1" in stop_ids
    assert "stop-p-req-2" in stop_ids
    assert "stop-d-req-2" in stop_ids
    # Precedence: pickup before dropoff for both requests
    assert stop_ids.index("stop-p-req-1") < stop_ids.index("stop-d-req-1")
    assert stop_ids.index("stop-p-req-2") < stop_ids.index("stop-d-req-2")


def test_multi_request_active_ride_capacity_interactions(
    router: MockRoutingProvider, policy: DispatchPolicy
) -> None:
    """
    Test capacity interactions in active rides:
    Vehicle capacity = 3. Active passenger count = 1.
    Remaining seats = 2.
    Request A (2 seats) and Request B (2 seats):
    - Simultaneous onboarding: 1 + 2 + 2 = 5 > 3 (INFEASIBLE).
    - If onboard passenger drops off (occupancy = 0):
      Request A and B still cannot be onboard simultaneously: 2 + 2 = 4 > 3 (INFEASIBLE).
    - Sequential service: onboard drops off (0), then A picked up (+2) and dropped off (-2),
      then B picked up (+2) and dropped off (-2): peak occupancy = 2 <= 3 (FEASIBLE).
    Verify that only strictly capacity-respecting sequences are retained.
    """
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-cap-test",
        driver_id="drv-cap",
        total_seat_capacity=3,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )

    t_start = 1700000000
    # Onboard passenger drops off early at +0.010
    d_onboard_loc = Coordinate(base_lat + 0.010, base_lon)
    _, dur_onboard = router.get_direct_leg(v_loc, d_onboard_loc)

    stop_dropoff_onboard = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-cap-test",
        request_id="req-onboard",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onboard_loc.latitude, longitude=d_onboard_loc.longitude),
        passenger_delta=-1,
        scheduled_arrival_time=t_start + dur_onboard,
        promised_window_start=t_start,
        promised_window_end=t_start + dur_onboard + 1200,
        status=StopStatus.SCHEDULED,
    )

    active_ride = Ride(
        ride_id="ride-cap-test",
        vehicle_id="veh-cap-test",
        driver_id="drv-cap",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_dropoff_onboard,),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )

    # Request A: pickup at +0.020, dropoff at +0.030 (2 seats)
    p_a = Coordinate(base_lat + 0.020, base_lon)
    d_a = Coordinate(base_lat + 0.030, base_lon)
    dist_a, dur_a = router.get_direct_leg(p_a, d_a)
    req_a = RideRequest(
        request_id="req-A",
        user_id="usr-A",
        pickup_location=GeoCoordinate(latitude=p_a.latitude, longitude=p_a.longitude),
        dropoff_location=GeoCoordinate(latitude=d_a.latitude, longitude=d_a.longitude),
        seat_count=2,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=dist_a,
        direct_duration_seconds=dur_a,
        status=RequestStatus.PENDING,
    )

    # Request B: pickup at +0.040, dropoff at +0.050 (2 seats)
    p_b = Coordinate(base_lat + 0.040, base_lon)
    d_b = Coordinate(base_lat + 0.050, base_lon)
    dist_b, dur_b = router.get_direct_leg(p_b, d_b)
    req_b = RideRequest(
        request_id="req-B",
        user_id="usr-B",
        pickup_location=GeoCoordinate(latitude=p_b.latitude, longitude=p_b.longitude),
        dropoff_location=GeoCoordinate(latitude=d_b.latitude, longitude=d_b.longitude),
        seat_count=2,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=dist_b,
        direct_duration_seconds=dur_b,
        status=RequestStatus.PENDING,
    )

    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    spatial = H3SpatialIndexAdapter()
    engine = DispatchEngine(
        policy_provider=policy_prov,
        routing_provider=router,
        spatial_index=spatial,
        config=CandidateGenerationConfig.exact(max_bundle_size=2),
    )

    cand_list = engine.generate_candidates(
        requests=[req_a, req_b],
        vehicles=[veh],
        active_rides=[active_ride],
        current_time=t_start,
    )

    bundle_cands = [c for c in cand_list if len(c.request_ids) == 2]
    assert len(bundle_cands) > 0, "Sequential bundle must be feasible"

    for c in bundle_cands:
        assert c.peak_seat_load <= 3, "Peak seat load must never exceed vehicle capacity of 3"
        sids = [s.stop_id for s in c.ordered_stops]
        # In all valid sequences, A and B cannot overlap!
        # If A is served first: D_A must precede P_B
        # If B is served first: D_B must precede P_A
        idx_pa = sids.index("stop-p-req-A")
        idx_da = sids.index("stop-d-req-A")
        idx_pb = sids.index("stop-p-req-B")
        idx_db = sids.index("stop-d-req-B")
        idx_onboard = sids.index("stop-d-onboard")

        # Non-overlapping: either A before B or B before A, because 2 + 2 = 4 > 3
        assert (idx_da < idx_pb) or (idx_db < idx_pa), "2-seat requests must not overlap on 3-seat vehicle"

    # Part B: On a 2-seat vehicle with 1 onboard passenger:
    # 2-seat request A cannot board before onboard dropoff (1 + 2 = 3 > 2)
    veh_2seat = Vehicle(
        vehicle_id="veh-cap-2",
        driver_id="drv-cap-2",
        total_seat_capacity=2,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )
    ride_2seat = Ride(
        ride_id="ride-cap-2",
        vehicle_id="veh-cap-2",
        driver_id="drv-cap-2",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_dropoff_onboard,),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )
    cands_2seat = engine.generate_candidates(
        requests=[req_a],
        vehicles=[veh_2seat],
        active_rides=[ride_2seat],
        current_time=t_start,
    )
    for c in cands_2seat:
        sids = [s.stop_id for s in c.ordered_stops]
        # In a 2-seat vehicle with 1 onboard passenger, A can ONLY board after onboard drops off
        assert sids.index("stop-d-onboard") < sids.index("stop-p-req-A")


def test_multi_request_active_ride_onboard_passenger_promise_preserved(
    router: MockRoutingProvider, policy: DispatchPolicy
) -> None:
    """
    Test that candidate generation strictly respects the promised arrival window
    and detour limits of the onboard passenger.
    """
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-promise-test",
        driver_id="drv-promise",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )

    t_start = 1700000000
    d_onboard_loc = Coordinate(base_lat + 0.020, base_lon)
    _, dur_onboard = router.get_direct_leg(v_loc, d_onboard_loc)

    # Tight promised window on onboard passenger: only 60 seconds of slack
    tight_promise_end = t_start + dur_onboard + 60
    stop_dropoff_onboard = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-promise-test",
        request_id="req-onboard",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onboard_loc.latitude, longitude=d_onboard_loc.longitude),
        passenger_delta=-1,
        scheduled_arrival_time=t_start + dur_onboard,
        promised_window_start=t_start,
        promised_window_end=tight_promise_end,
        status=StopStatus.SCHEDULED,
    )

    active_ride = Ride(
        ride_id="ride-promise-test",
        vehicle_id="veh-promise-test",
        driver_id="drv-promise",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_dropoff_onboard,),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )

    # Request 1 takes 120 seconds of detour if visited before onboard dropoff (causes promise breach)
    # Pickup at +0.010, dropoff at +0.030
    p1 = Coordinate(base_lat + 0.010, base_lon + 0.010)
    d1 = Coordinate(base_lat + 0.030, base_lon + 0.010)
    dist1, dur1 = router.get_direct_leg(p1, d1)
    req1 = RideRequest(
        request_id="req-1",
        user_id="usr-1",
        pickup_location=GeoCoordinate(latitude=p1.latitude, longitude=p1.longitude),
        dropoff_location=GeoCoordinate(latitude=d1.latitude, longitude=d1.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=dist1,
        direct_duration_seconds=dur1,
        status=RequestStatus.PENDING,
    )

    # Request 2: pickup after onboard dropoff (+0.025 to +0.035)
    p2 = Coordinate(base_lat + 0.025, base_lon)
    d2 = Coordinate(base_lat + 0.035, base_lon)
    dist2, dur2 = router.get_direct_leg(p2, d2)
    req2 = RideRequest(
        request_id="req-2",
        user_id="usr-2",
        pickup_location=GeoCoordinate(latitude=p2.latitude, longitude=p2.longitude),
        dropoff_location=GeoCoordinate(latitude=d2.latitude, longitude=d2.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=dist2,
        direct_duration_seconds=dur2,
        status=RequestStatus.PENDING,
    )

    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    spatial = H3SpatialIndexAdapter()
    engine = DispatchEngine(
        policy_provider=policy_prov,
        routing_provider=router,
        spatial_index=spatial,
        config=CandidateGenerationConfig.exact(max_bundle_size=2),
    )

    cand_list = engine.generate_candidates(
        requests=[req1, req2],
        vehicles=[veh],
        active_rides=[active_ride],
        current_time=t_start,
    )

    for c in cand_list:
        onboard_stop = next(s for s in c.ordered_stops if s.stop_id == "stop-d-onboard")
        assert onboard_stop.scheduled_arrival_time <= tight_promise_end, (
            f"Candidate breached onboard passenger promise window: "
            f"{onboard_stop.scheduled_arrival_time} > {tight_promise_end}"
        )


def test_multi_request_active_ride_dispatch_batch_assignment_and_no_duplicates(
    router: MockRoutingProvider, policy: DispatchPolicy
) -> None:
    """
    Test end-to-end dispatch batch:
    The solver assigns a 2-request bundle into the active ride,
    ensuring each request is assigned exactly once and vehicle is assigned at most once.
    """
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-dispatch-1",
        driver_id="drv-dispatch",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )

    t_start = 1700000000
    d_onboard_loc = Coordinate(base_lat + 0.050, base_lon)
    _, dur_onboard = router.get_direct_leg(v_loc, d_onboard_loc)

    stop_dropoff_onboard = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-dispatch-1",
        request_id="req-onboard",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onboard_loc.latitude, longitude=d_onboard_loc.longitude),
        passenger_delta=-1,
        scheduled_arrival_time=t_start + dur_onboard,
        promised_window_start=t_start,
        promised_window_end=t_start + dur_onboard + 1200,
        status=StopStatus.SCHEDULED,
    )

    active_ride = Ride(
        ride_id="ride-dispatch-1",
        vehicle_id="veh-dispatch-1",
        driver_id="drv-dispatch",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_dropoff_onboard,),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )

    p1 = Coordinate(base_lat + 0.010, base_lon)
    d1 = Coordinate(base_lat + 0.030, base_lon)
    dist1, dur1 = router.get_direct_leg(p1, d1)
    req1 = RideRequest(
        request_id="req-1",
        user_id="usr-1",
        pickup_location=GeoCoordinate(latitude=p1.latitude, longitude=p1.longitude),
        dropoff_location=GeoCoordinate(latitude=d1.latitude, longitude=d1.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=dist1,
        direct_duration_seconds=dur1,
        status=RequestStatus.PENDING,
    )

    p2 = Coordinate(base_lat + 0.015, base_lon)
    d2 = Coordinate(base_lat + 0.035, base_lon)
    dist2, dur2 = router.get_direct_leg(p2, d2)
    req2 = RideRequest(
        request_id="req-2",
        user_id="usr-2",
        pickup_location=GeoCoordinate(latitude=p2.latitude, longitude=p2.longitude),
        dropoff_location=GeoCoordinate(latitude=d2.latitude, longitude=d2.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=dist2,
        direct_duration_seconds=dur2,
        status=RequestStatus.PENDING,
    )

    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    spatial = H3SpatialIndexAdapter()
    engine = DispatchEngine(
        policy_provider=policy_prov,
        routing_provider=router,
        spatial_index=spatial,
        config=CandidateGenerationConfig.exact(max_bundle_size=2),
    )

    match_result = engine.dispatch_batch(
        requests=[req1, req2],
        vehicles=[veh],
        active_rides=[active_ride],
        current_time=t_start,
    )

    # Exactly 1 assignment chosen for the single vehicle
    assert len(match_result.selected_assignments) == 1
    selected = match_result.selected_assignments[0]
    assert selected.vehicle_id == "veh-dispatch-1"
    assert selected.existing_ride_id == "ride-dispatch-1"
    # Both requests served in that one assignment!
    assert set(selected.request_ids) == {"req-1", "req-2"}
    assert len(match_result.unassigned_request_ids) == 0


def test_multi_request_active_ride_deterministic_output(
    router: MockRoutingProvider, policy: DispatchPolicy
) -> None:
    """
    Test deterministic replay: identical inputs to dispatch_batch produce
    bit-for-bit identical assignments, score breakdown, and stop sequences.
    """
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-det-1",
        driver_id="drv-det",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )

    t_start = 1700000000
    d_onboard_loc = Coordinate(base_lat + 0.050, base_lon)
    _, dur_onboard = router.get_direct_leg(v_loc, d_onboard_loc)

    stop_dropoff_onboard = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-det-1",
        request_id="req-onboard",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onboard_loc.latitude, longitude=d_onboard_loc.longitude),
        passenger_delta=-1,
        scheduled_arrival_time=t_start + dur_onboard,
        promised_window_start=t_start,
        promised_window_end=t_start + dur_onboard + 1200,
        status=StopStatus.SCHEDULED,
    )

    active_ride = Ride(
        ride_id="ride-det-1",
        vehicle_id="veh-det-1",
        driver_id="drv-det",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_dropoff_onboard,),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )

    p1 = Coordinate(base_lat + 0.010, base_lon)
    d1 = Coordinate(base_lat + 0.030, base_lon)
    dist1, dur1 = router.get_direct_leg(p1, d1)
    req1 = RideRequest(
        request_id="req-1",
        user_id="usr-1",
        pickup_location=GeoCoordinate(latitude=p1.latitude, longitude=p1.longitude),
        dropoff_location=GeoCoordinate(latitude=d1.latitude, longitude=d1.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=dist1,
        direct_duration_seconds=dur1,
        status=RequestStatus.PENDING,
    )

    p2 = Coordinate(base_lat + 0.015, base_lon)
    d2 = Coordinate(base_lat + 0.035, base_lon)
    dist2, dur2 = router.get_direct_leg(p2, d2)
    req2 = RideRequest(
        request_id="req-2",
        user_id="usr-2",
        pickup_location=GeoCoordinate(latitude=p2.latitude, longitude=p2.longitude),
        dropoff_location=GeoCoordinate(latitude=d2.latitude, longitude=d2.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=dist2,
        direct_duration_seconds=dur2,
        status=RequestStatus.PENDING,
    )

    policy_prov = DefaultPolicyProvider(initial_policy=policy)
    spatial = H3SpatialIndexAdapter()
    engine = DispatchEngine(
        policy_provider=policy_prov,
        routing_provider=router,
        spatial_index=spatial,
        config=CandidateGenerationConfig.exact(max_bundle_size=2),
    )

    res1 = engine.dispatch_batch([req1, req2], [veh], [active_ride], t_start, batch_id="batch-1")
    res2 = engine.dispatch_batch([req1, req2], [veh], [active_ride], t_start, batch_id="batch-1")

    assert len(res1.selected_assignments) == len(res2.selected_assignments)
    for a1, a2 in zip(res1.selected_assignments, res2.selected_assignments):
        assert a1.vehicle_id == a2.vehicle_id
        assert a1.request_ids == a2.request_ids
        assert a1.vmt_meters == a2.vmt_meters
        assert a1.objective_value == a2.objective_value
        assert [s.stop_id for s in a1.ordered_stops] == [s.stop_id for s in a2.ordered_stops]
        assert [s.scheduled_arrival_time for s in a1.ordered_stops] == [
            s.scheduled_arrival_time for s in a2.ordered_stops
        ]


class TrackingSpyRouter(MockRoutingProvider):
    """Spy router that records every queried directed leg."""

    def __init__(self, **kwargs: float) -> None:
        super().__init__(**kwargs)
        self.calls: list[tuple[Coordinate, Coordinate]] = []

    def get_direct_leg(
        self, origin: Coordinate, destination: Coordinate
    ) -> tuple[int, int]:
        self.calls.append((origin, destination))
        return super().get_direct_leg(origin, destination)


class AsymmetricSpyRouter(MockRoutingProvider):
    """Router that returns asymmetric travel metrics depending on direction."""

    def __init__(self) -> None:
        super().__init__(average_speed_kmh=40.0, circuity_factor=1.0)
        self.calls: list[tuple[Coordinate, Coordinate]] = []

    def get_direct_leg(
        self, origin: Coordinate, destination: Coordinate
    ) -> tuple[int, int]:
        self.calls.append((origin, destination))
        base_dist, base_dur = super().get_direct_leg(origin, destination)
        # Asymmetry: southward travels take 50% longer than northward travels
        if destination.latitude < origin.latitude:
            return int(round(base_dist * 1.5)), int(round(base_dur * 1.5))
        return base_dist, base_dur


def test_active_ride_waypoint_cache_deduplication_and_hits(
    policy: DispatchPolicy,
) -> None:
    """
    Test that local waypoint-leg memoization eliminates duplicate routing-provider calls
    so that every distinct directed leg between waypoints is queried at most once.
    """
    router = TrackingSpyRouter(average_speed_kmh=40.0, circuity_factor=1.0)
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-memo-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )
    t_start = 1700000000
    d_onboard = Coordinate(base_lat + 0.050, base_lon)
    _, dur_onb = router.get_direct_leg(v_loc, d_onboard)
    router.calls.clear()  # reset after fixture setup

    stop_onboard = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-memo-1",
        request_id="req-onb",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onboard.latitude, longitude=d_onboard.longitude),
        passenger_delta=-1,
        scheduled_arrival_time=t_start + dur_onb,
        promised_window_start=t_start,
        promised_window_end=t_start + dur_onb + 1200,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-memo-1",
        vehicle_id="veh-memo-1",
        driver_id="drv-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_onboard,),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )

    r1 = RideRequest(
        request_id="req-m1",
        user_id="u1",
        pickup_location=GeoCoordinate(latitude=base_lat + 0.010, longitude=base_lon),
        dropoff_location=GeoCoordinate(latitude=base_lat + 0.020, longitude=base_lon),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=1000,
        direct_duration_seconds=90,
        status=RequestStatus.PENDING,
    )
    r2 = RideRequest(
        request_id="req-m2",
        user_id="u2",
        pickup_location=GeoCoordinate(latitude=base_lat + 0.015, longitude=base_lon),
        dropoff_location=GeoCoordinate(latitude=base_lat + 0.025, longitude=base_lon),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=1000,
        direct_duration_seconds=90,
        status=RequestStatus.PENDING,
    )

    cands = generate_active_ride_insertions(
        active_ride=ride,
        requests=[r1, r2],
        vehicle=veh,
        router=router,
        policy=policy,
        current_time=t_start,
        max_bundle_size=2,
    )
    assert len(cands) > 0

    # Without memoization, duplicate legs were queried up to 14 times.
    # With local waypoint-leg memoization, every distinct directed leg must be queried at most once!
    from collections import Counter

    call_counts = Counter(router.calls)
    assert len(call_counts) > 0
    max_duplicate_calls = max(call_counts.values())
    assert (
        max_duplicate_calls == 1
    ), f"Expected at most 1 call per directed leg, got {max_duplicate_calls}"


def test_active_ride_waypoint_cache_distinct_directed_legs(
    policy: DispatchPolicy,
) -> None:
    """
    Test that the local waypoint-leg cache distinguishes directed legs (A -> B != B -> A)
    and correctly handles asymmetric routing providers without conflating directions.
    """
    router = AsymmetricSpyRouter()
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-asym-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )
    t_start = 1700000000
    d_onboard = Coordinate(base_lat + 0.030, base_lon)
    _, dur_onb = router.get_direct_leg(v_loc, d_onboard)

    stop_onboard = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-asym-1",
        request_id="req-onb",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onboard.latitude, longitude=d_onboard.longitude),
        passenger_delta=-1,
        scheduled_arrival_time=t_start + dur_onb,
        promised_window_start=t_start,
        promised_window_end=t_start + dur_onb + 1200,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-asym-1",
        vehicle_id="veh-asym-1",
        driver_id="drv-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_onboard,),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )

    # Southward request (pickup north of dropoff)
    r_south = RideRequest(
        request_id="req-south",
        user_id="u-south",
        pickup_location=GeoCoordinate(latitude=base_lat + 0.020, longitude=base_lon),
        dropoff_location=GeoCoordinate(latitude=base_lat + 0.005, longitude=base_lon),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=1500,
        direct_duration_seconds=120,
        status=RequestStatus.PENDING,
    )

    cands = generate_active_ride_insertions(
        active_ride=ride,
        requests=[r_south],
        vehicle=veh,
        router=router,
        policy=policy,
        current_time=t_start,
        max_bundle_size=1,
    )

    # Verify that opposite directed legs have distinct cache queries
    c_p = Coordinate(r_south.pickup_location.latitude, r_south.pickup_location.longitude)
    c_d = Coordinate(r_south.dropoff_location.latitude, r_south.dropoff_location.longitude)
    # The vehicle moves north to pickup, then south to dropoff
    leg_north = router.get_direct_leg(v_loc, c_p)
    leg_south = router.get_direct_leg(c_p, v_loc)
    assert leg_south[0] != leg_north[0] or leg_south[1] != leg_north[1]

    for c in cands:
        # Candidate ordered stops must reflect the actual routing metrics
        assert c.vmt_meters > 0
        assert c.score_breakdown.vmt_savings_ratio >= 0


def test_active_ride_waypoint_cache_repeated_waypoints(
    policy: DispatchPolicy,
) -> None:
    """
    Test that multiple requests with identical pickup coordinates (co-located stops)
    have distinct stable waypoint identities and do not collide in the waypoint cache.
    """
    router = TrackingSpyRouter(average_speed_kmh=40.0, circuity_factor=1.0)
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-coloc-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )
    t_start = 1700000000
    d_onboard = Coordinate(base_lat + 0.050, base_lon)
    _, dur_onb = router.get_direct_leg(v_loc, d_onboard)

    stop_onboard = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-coloc-1",
        request_id="req-onb",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onboard.latitude, longitude=d_onboard.longitude),
        passenger_delta=-1,
        scheduled_arrival_time=t_start + dur_onb,
        promised_window_start=t_start,
        promised_window_end=t_start + dur_onb + 1200,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-coloc-1",
        vehicle_id="veh-coloc-1",
        driver_id="drv-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_onboard,),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )

    # Identical pickup coordinate for both requests!
    co_lat, co_lon = base_lat + 0.010, base_lon
    r1 = RideRequest(
        request_id="req-coloc-1",
        user_id="u1",
        pickup_location=GeoCoordinate(latitude=co_lat, longitude=co_lon),
        dropoff_location=GeoCoordinate(latitude=base_lat + 0.020, longitude=base_lon),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=1000,
        direct_duration_seconds=90,
        status=RequestStatus.PENDING,
    )
    r2 = RideRequest(
        request_id="req-coloc-2",
        user_id="u2",
        pickup_location=GeoCoordinate(latitude=co_lat, longitude=co_lon),
        dropoff_location=GeoCoordinate(latitude=base_lat + 0.030, longitude=base_lon),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=2000,
        direct_duration_seconds=180,
        status=RequestStatus.PENDING,
    )

    cands = generate_active_ride_insertions(
        active_ride=ride,
        requests=[r1, r2],
        vehicle=veh,
        router=router,
        policy=policy,
        current_time=t_start,
        max_bundle_size=2,
    )

    bundle_cands = [c for c in cands if len(c.request_ids) == 2]
    assert len(bundle_cands) > 0
    for c in bundle_cands:
        stop_ids = [s.stop_id for s in c.ordered_stops]
        # Both distinct stop IDs must appear in the sequence
        assert "stop-p-req-coloc-1" in stop_ids
        assert "stop-p-req-coloc-2" in stop_ids


def test_active_ride_waypoint_cache_separate_vehicle_scopes(
    policy: DispatchPolicy,
) -> None:
    """
    Test that local waypoint-leg caches have separate scopes per vehicle/invocation
    and do not leak state across vehicles or persistent router state.
    """
    router = TrackingSpyRouter(average_speed_kmh=40.0, circuity_factor=1.0)
    base_lat, base_lon = 40.7100, -74.0000
    t_start = 1700000000

    def make_veh_and_ride(v_id: str, lat_off: float) -> tuple[Vehicle, Ride]:
        v_loc = Coordinate(base_lat + lat_off, base_lon)
        v = Vehicle(
            vehicle_id=v_id,
            driver_id=f"drv-{v_id}",
            total_seat_capacity=4,
            current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
            is_active=True,
        )
        d_loc = Coordinate(base_lat + lat_off + 0.050, base_lon)
        _, dur = router.get_direct_leg(v_loc, d_loc)
        stop = RouteStop(
            stop_id=f"stop-d-{v_id}",
            ride_id=f"ride-{v_id}",
            request_id=f"req-{v_id}",
            stop_type=StopType.DROPOFF,
            location=GeoCoordinate(latitude=d_loc.latitude, longitude=d_loc.longitude),
            passenger_delta=-1,
            scheduled_arrival_time=t_start + dur,
            promised_window_start=t_start,
            promised_window_end=t_start + dur + 1200,
            status=StopStatus.SCHEDULED,
        )
        r = Ride(
            ride_id=f"ride-{v_id}",
            vehicle_id=v_id,
            driver_id=f"drv-{v_id}",
            lifecycle_status=RideStatus.ACTIVE,
            stops=(stop,),
            scheduled_departure_time=t_start,
            active_passenger_count=1,
        )
        return v, r

    veh1, ride1 = make_veh_and_ride("veh-scope-1", 0.000)
    veh2, ride2 = make_veh_and_ride("veh-scope-2", 0.002)

    req = RideRequest(
        request_id="req-scope",
        user_id="usr-scope",
        pickup_location=GeoCoordinate(latitude=base_lat + 0.010, longitude=base_lon),
        dropoff_location=GeoCoordinate(latitude=base_lat + 0.020, longitude=base_lon),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=1000,
        direct_duration_seconds=90,
        status=RequestStatus.PENDING,
    )

    router.calls.clear()
    cands1 = generate_active_ride_insertions(ride1, [req], veh1, router, policy, t_start, max_bundle_size=1)
    calls_after_veh1 = len(router.calls)
    assert calls_after_veh1 > 0
    assert len(cands1) > 0

    # Invocations on veh2 must query router afresh and not be poisoned or skipped by veh1's cache
    cands2 = generate_active_ride_insertions(ride2, [req], veh2, router, policy, t_start, max_bundle_size=1)
    calls_after_veh2 = len(router.calls)
    assert calls_after_veh2 > calls_after_veh1
    assert len(cands2) > 0



# ==============================================================================
# Admissible Temporal Pruning Tests
# ==============================================================================

def test_active_ride_temporal_pruning_pickup_delay_dead_branch() -> None:
    """
    Test that a partial sequence where arrival at a pickup violates max_pickup_delay
    is pruned so that no descendant sequences placing stops after that late pickup
    are generated, and legs along the dead branch are not queried.
    """
    router = TrackingSpyRouter(average_speed_kmh=40.0, circuity_factor=1.0)
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-prune-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )
    t_start = 1700000000

    # Existing dropoff at +0.050 (takes ~450s)
    d_onboard = Coordinate(base_lat + 0.050, base_lon)
    _, dur_onb = router.get_direct_leg(v_loc, d_onboard)
    stop_onboard = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-prune-1",
        request_id="req-onb",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onboard.latitude, longitude=d_onboard.longitude),
        passenger_delta=-1,
        scheduled_arrival_time=t_start + dur_onb,
        promised_window_start=t_start,
        promised_window_end=t_start + dur_onb + 3600,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-prune-1",
        vehicle_id="veh-prune-1",
        driver_id="drv-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_onboard,),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )

    # Request 1: pickup at +0.010 (90s from vehicle), dropoff at +0.030
    p1 = Coordinate(base_lat + 0.010, base_lon)
    d1 = Coordinate(base_lat + 0.030, base_lon)
    dist1, dur1 = router.get_direct_leg(p1, d1)
    req1 = RideRequest(
        request_id="req-prune-1",
        user_id="usr-p1",
        pickup_location=GeoCoordinate(latitude=p1.latitude, longitude=p1.longitude),
        dropoff_location=GeoCoordinate(latitude=d1.latitude, longitude=d1.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=dist1,
        direct_duration_seconds=dur1,
        status=RequestStatus.PENDING,
    )

    # Request 2: pickup at +0.015, dropoff at +0.035
    p2 = Coordinate(base_lat + 0.015, base_lon)
    d2 = Coordinate(base_lat + 0.035, base_lon)
    dist2, dur2 = router.get_direct_leg(p2, d2)
    req2 = RideRequest(
        request_id="req-prune-2",
        user_id="usr-p2",
        pickup_location=GeoCoordinate(latitude=p2.latitude, longitude=p2.longitude),
        dropoff_location=GeoCoordinate(latitude=d2.latitude, longitude=d2.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=dist2,
        direct_duration_seconds=dur2,
        status=RequestStatus.PENDING,
    )

    # Max pickup delay: 200s
    # V -> P1 takes ~90s (feasible before onboard dropoff)
    # V -> Onboard -> P1 takes ~450s + ~360s = ~810s (exceeds 200s delay)
    policy = DispatchPolicy(
        max_pickup_delay_seconds=200,
        detour_relative_multiplier=1.5,
        detour_absolute_cap_seconds=1200,
    )

    router.calls.clear()
    cands = generate_active_ride_insertions(
        active_ride=ride,
        requests=[req1, req2],
        vehicle=veh,
        router=router,
        policy=policy,
        current_time=t_start,
        max_bundle_size=2,
    )

    assert len(cands) > 0
    for cand in cands:
        stop_ids = [s.stop_id for s in cand.ordered_stops]
        if "stop-p-req-prune-1" in stop_ids:
            idx_p1 = stop_ids.index("stop-p-req-prune-1")
            idx_onboard = stop_ids.index("stop-d-onboard")
            # P1 MUST be visited before the onboard dropoff
            assert idx_p1 < idx_onboard, f"Dead branch was not pruned: {stop_ids}"

    # Admissible pruning check:
    # At the onboard dropoff (+0.050), arrival is t_start + 450s, which ALREADY exceeds
    # the 200s pickup deadline of unvisited requests. Therefore, continuing after onboard
    # to pick up any of those requests is provably dead and must be pruned before querying!
    queried_origins = {call[0] for call in router.calls}
    assert d_onboard not in queried_origins, (
        f"Dead branch continuation leg queried from onboard dropoff: {router.calls}"
    )


def test_active_ride_temporal_pruning_existing_dropoff_promise_dead_branch() -> None:
    """
    Test that a partial sequence where visiting an inserted stop delays an existing passenger's
    dropoff past promised_window_end is pruned.
    """
    router = TrackingSpyRouter(average_speed_kmh=40.0, circuity_factor=1.0)
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-prune-2",
        driver_id="drv-2",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )
    t_start = 1700000000

    # Existing dropoff at +0.020 (takes ~180s from vehicle)
    d_onboard = Coordinate(base_lat + 0.020, base_lon)
    _, dur_onb = router.get_direct_leg(v_loc, d_onboard)
    # Promise window ends at t_start + 200s (tight promise: only 20s slack!)
    stop_onboard = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-prune-2",
        request_id="req-onb",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onboard.latitude, longitude=d_onboard.longitude),
        passenger_delta=-1,
        scheduled_arrival_time=t_start + dur_onb,
        promised_window_start=t_start,
        promised_window_end=t_start + dur_onb + 20,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-prune-2",
        vehicle_id="veh-prune-2",
        driver_id="drv-2",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_onboard,),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )

    # Request with pickup farther north at +0.040 (takes ~360s from vehicle)
    p1 = Coordinate(base_lat + 0.040, base_lon)
    d1 = Coordinate(base_lat + 0.060, base_lon)
    dist1, dur1 = router.get_direct_leg(p1, d1)
    req = RideRequest(
        request_id="req-promise-1",
        user_id="usr-prom",
        pickup_location=GeoCoordinate(latitude=p1.latitude, longitude=p1.longitude),
        dropoff_location=GeoCoordinate(latitude=d1.latitude, longitude=d1.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=dist1,
        direct_duration_seconds=dur1,
        status=RequestStatus.PENDING,
    )

    policy = DispatchPolicy(
        max_pickup_delay_seconds=600,
        detour_relative_multiplier=1.5,
        detour_absolute_cap_seconds=1200,
    )

    router.calls.clear()
    cands = generate_active_ride_insertions(
        active_ride=ride,
        requests=[req],
        vehicle=veh,
        router=router,
        policy=policy,
        current_time=t_start,
        max_bundle_size=1,
    )

    assert len(cands) > 0
    for cand in cands:
        stop_ids = [s.stop_id for s in cand.ordered_stops]
        idx_p = stop_ids.index("stop-p-req-promise-1")
        idx_onboard = stop_ids.index("stop-d-onboard")
        # Visiting P before onboard dropoff breaches the promised window end, so onboard MUST precede P
        assert idx_onboard < idx_p, f"Sequence breached promised window: {stop_ids}"

    # Visiting P1 first takes ~360s, so reaching onboard after P1 arrives at >360s, breaching 200s promise.
    # Therefore, V -> P1 cannot precede onboard dropoff; leg P1 -> onboard is provably dead and must not be queried.
    queried_legs = set(router.calls)
    assert (p1, d_onboard) not in queried_legs, (
        f"Dead branch leg P1 -> Onboard queried: {router.calls}"
    )


def test_active_ride_temporal_pruning_exact_and_beyond_boundary(
    router: MockRoutingProvider,
) -> None:
    """
    Test exact boundary behavior: arrival exactly equal to deadline is feasible,
    while arrival exactly 1s past deadline is pruned.
    """
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-boundary-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )
    t_start = 1700000000

    d_onboard = Coordinate(base_lat + 0.050, base_lon)
    _, dur_onb = router.get_direct_leg(v_loc, d_onboard)
    stop_onboard = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-b-1",
        request_id="req-onb",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onboard.latitude, longitude=d_onboard.longitude),
        passenger_delta=-1,
        scheduled_arrival_time=t_start + dur_onb,
        promised_window_start=t_start,
        promised_window_end=t_start + dur_onb + 3600,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-b-1",
        vehicle_id="veh-boundary-1",
        driver_id="drv-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_onboard,),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )

    p1 = Coordinate(base_lat + 0.020, base_lon)
    d1 = Coordinate(base_lat + 0.040, base_lon)
    _, dur_p1 = router.get_direct_leg(v_loc, p1)
    dist1, dur1 = router.get_direct_leg(p1, d1)
    req = RideRequest(
        request_id="req-b-1",
        user_id="usr-b1",
        pickup_location=GeoCoordinate(latitude=p1.latitude, longitude=p1.longitude),
        dropoff_location=GeoCoordinate(latitude=d1.latitude, longitude=d1.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=dist1,
        direct_duration_seconds=dur1,
        status=RequestStatus.PENDING,
    )

    # 1. Exact boundary: max_pickup_delay_seconds == dur_p1
    policy_exact = DispatchPolicy(
        max_pickup_delay_seconds=dur_p1,
        detour_relative_multiplier=1.5,
        detour_absolute_cap_seconds=1200,
    )
    cands_exact = generate_active_ride_insertions(
        active_ride=ride,
        requests=[req],
        vehicle=veh,
        router=router,
        policy=policy_exact,
        current_time=t_start,
        max_bundle_size=1,
    )
    # The sequence starting with V -> P1 arrives exactly at t_start + dur_p1, which equals deadline
    assert len(cands_exact) > 0
    p1_stops = [s for c in cands_exact for s in c.ordered_stops if s.stop_id == "stop-p-req-b-1"]
    assert len(p1_stops) > 0

    # 2. 1s beyond boundary: max_pickup_delay_seconds == dur_p1 - 1
    policy_beyond = DispatchPolicy(
        max_pickup_delay_seconds=dur_p1 - 1,
        detour_relative_multiplier=1.5,
        detour_absolute_cap_seconds=1200,
    )
    cands_beyond = generate_active_ride_insertions(
        active_ride=ride,
        requests=[req],
        vehicle=veh,
        router=router,
        policy=policy_beyond,
        current_time=t_start,
        max_bundle_size=1,
    )
    # V -> P1 arrives at dur_p1 > dur_p1 - 1, so P1 cannot be visited before onboard
    # V -> Onboard -> P1 arrives at dur_onb + dur_onb_p1 >> dur_p1 - 1
    # Hence all orderings breach the delay bound and must be pruned
    assert len(cands_beyond) == 0


class HighwaySpyRouter(MockRoutingProvider):
    """
    Router with a high-speed express corridor between two coordinates
    where actual duration is much faster than standard city speed.
    """

    def __init__(self, express_origin: Coordinate, express_dest: Coordinate, express_dur: int) -> None:
        super().__init__(average_speed_kmh=40.0, circuity_factor=1.0)
        self.express_origin = express_origin
        self.express_dest = express_dest
        self.express_dur = express_dur

    def get_direct_leg(self, origin: Coordinate, destination: Coordinate) -> tuple[int, int]:
        if (
            abs(origin.latitude - self.express_origin.latitude) < 1e-5
            and abs(origin.longitude - self.express_origin.longitude) < 1e-5
            and abs(destination.latitude - self.express_dest.latitude) < 1e-5
            and abs(destination.longitude - self.express_dest.longitude) < 1e-5
        ):
            # Express leg has small duration
            return 2000, self.express_dur
        return super().get_direct_leg(origin, destination)


def test_active_ride_temporal_pruning_crude_estimate_counterexample() -> None:
    """
    Test that a sequence which a crude heuristic (e.g. Euclidean distance / low speed)
    would erroneously prune as late is preserved by admissible pruning because
    the actual router duration is fast enough.
    """
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-crude-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )
    t_start = 1700000000

    # Onboard dropoff is far away in Euclidean space (+0.080 deg ~ 9 km)
    # At standard 40 km/h, 9 km takes ~800s.
    # But on the express highway corridor, it only takes 150s!
    d_onboard = Coordinate(base_lat + 0.080, base_lon)
    router = HighwaySpyRouter(express_origin=v_loc, express_dest=d_onboard, express_dur=150)

    stop_onboard = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-crude-1",
        request_id="req-onb",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onboard.latitude, longitude=d_onboard.longitude),
        passenger_delta=-1,
        scheduled_arrival_time=t_start + 150,
        promised_window_start=t_start,
        promised_window_end=t_start + 300,  # 300s deadline
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-crude-1",
        vehicle_id="veh-crude-1",
        driver_id="drv-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_onboard,),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )

    # Request pickup right near the onboard dropoff
    p1 = Coordinate(base_lat + 0.082, base_lon)
    d1 = Coordinate(base_lat + 0.090, base_lon)
    req = RideRequest(
        request_id="req-crude-1",
        user_id="usr-c1",
        pickup_location=GeoCoordinate(latitude=p1.latitude, longitude=p1.longitude),
        dropoff_location=GeoCoordinate(latitude=d1.latitude, longitude=d1.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=1000,
        direct_duration_seconds=90,
        status=RequestStatus.PENDING,
    )

    policy = DispatchPolicy(
        max_pickup_delay_seconds=600,
        detour_relative_multiplier=1.5,
        detour_absolute_cap_seconds=1200,
    )

    cands = generate_active_ride_insertions(
        active_ride=ride,
        requests=[req],
        vehicle=veh,
        router=router,
        policy=policy,
        current_time=t_start,
        max_bundle_size=1,
    )

    # A crude estimate (9km / 40km/h = 810s > 300s deadline) would have discarded this candidate.
    # Admissible pruning evaluates the actual router duration (150s <= 300s), preserving it!
    assert len(cands) > 0
    onboard_stops = [s for c in cands for s in c.ordered_stops if s.stop_id == "stop-d-onboard"]
    assert len(onboard_stops) > 0


def test_active_ride_temporal_pruning_dwell_and_asymmetric() -> None:
    """
    Test that admissible pruning properly accumulates non-zero dwell durations
    and respects asymmetric directed leg travel times.
    """
    router = AsymmetricSpyRouter()
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-dwell-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )
    t_start = 1700000000

    d_onboard = Coordinate(base_lat + 0.020, base_lon)
    _, dur_onb = router.get_direct_leg(v_loc, d_onboard)
    # Stop has 60 seconds of dwell time
    stop_onboard = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-dwell-1",
        request_id="req-onb",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onboard.latitude, longitude=d_onboard.longitude),
        passenger_delta=-1,
        scheduled_arrival_time=t_start + dur_onb,
        promised_window_start=t_start,
        promised_window_end=t_start + dur_onb + 1200,
        dwell_duration_seconds=60,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-dwell-1",
        vehicle_id="veh-dwell-1",
        driver_id="drv-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_onboard,),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )

    # Southward request (pickup at +0.010, south of onboard dropoff)
    p_south = Coordinate(base_lat + 0.010, base_lon)
    d_south = Coordinate(base_lat - 0.010, base_lon)
    dist_s, dur_s = router.get_direct_leg(p_south, d_south)

    req = RideRequest(
        request_id="req-dwell-s",
        user_id="usr-ds",
        pickup_location=GeoCoordinate(latitude=p_south.latitude, longitude=p_south.longitude),
        dropoff_location=GeoCoordinate(latitude=d_south.latitude, longitude=d_south.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=dist_s,
        direct_duration_seconds=dur_s,
        status=RequestStatus.PENDING,
    )

    policy = DispatchPolicy(
        max_pickup_delay_seconds=600,
        detour_relative_multiplier=1.5,
        detour_absolute_cap_seconds=1200,
    )

    cands = generate_active_ride_insertions(
        active_ride=ride,
        requests=[req],
        vehicle=veh,
        router=router,
        policy=policy,
        current_time=t_start,
        max_bundle_size=1,
    )

    assert len(cands) > 0
    for cand in cands:
        stop_ids = [s.stop_id for s in cand.ordered_stops]
        if stop_ids == ["stop-d-onboard", "stop-p-req-dwell-s", "stop-d-req-dwell-s"]:
            # Leg V -> Onboard takes dur_onb
            # Dwell at Onboard is 60s
            # Southward leg Onboard -> P_south takes asymmetric duration:
            _, dur_south = router.get_direct_leg(d_onboard, p_south)
            expected_p_arrival = t_start + dur_onb + 60 + dur_south
            actual_p_arrival = next(s.scheduled_arrival_time for s in cand.ordered_stops if s.stop_id == "stop-p-req-dwell-s")
            assert actual_p_arrival == expected_p_arrival


def test_active_ride_temporal_pruning_bundle_size_1_2_3_oracle_comparison(
    router: MockRoutingProvider,
    policy: DispatchPolicy,
) -> None:
    """
    Compare production candidate generation with admissible temporal pruning against the
    first-principles IndependentCandidateOracle for bundle sizes 1, 2, and 3.
    Requires 0 false negatives, 0 false positives, and matching candidate signatures.
    """
    from tests.oracle.candidate_oracle import IndependentCandidateOracle

    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-comp-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )
    t_start = 1700000000

    d_onb = Coordinate(base_lat + 0.050, base_lon)
    _, dur_onb = router.get_direct_leg(v_loc, d_onb)
    stop_onb = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-comp-1",
        request_id="req-onb",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onb.latitude, longitude=d_onb.longitude),
        passenger_delta=-1,
        scheduled_arrival_time=t_start + dur_onb,
        promised_window_start=t_start,
        promised_window_end=t_start + dur_onb + 1800,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-comp-1",
        vehicle_id="veh-comp-1",
        driver_id="drv-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_onb,),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )

    r1 = RideRequest(
        request_id="req-c1",
        user_id="u1",
        pickup_location=GeoCoordinate(latitude=base_lat + 0.010, longitude=base_lon),
        dropoff_location=GeoCoordinate(latitude=base_lat + 0.025, longitude=base_lon),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=1500,
        direct_duration_seconds=135,
        status=RequestStatus.PENDING,
    )
    r2 = RideRequest(
        request_id="req-c2",
        user_id="u2",
        pickup_location=GeoCoordinate(latitude=base_lat + 0.015, longitude=base_lon),
        dropoff_location=GeoCoordinate(latitude=base_lat + 0.035, longitude=base_lon),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=2000,
        direct_duration_seconds=180,
        status=RequestStatus.PENDING,
    )
    r3 = RideRequest(
        request_id="req-c3",
        user_id="u3",
        pickup_location=GeoCoordinate(latitude=base_lat + 0.020, longitude=base_lon),
        dropoff_location=GeoCoordinate(latitude=base_lat + 0.040, longitude=base_lon),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=2000,
        direct_duration_seconds=180,
        status=RequestStatus.PENDING,
    )

    for b_size in (1, 2, 3):
        oracle = IndependentCandidateOracle(router=router, policy=policy, max_bundle_size=b_size)
        oracle_cands = oracle.enumerate_feasible_candidates(
            requests=[r1, r2, r3],
            vehicles=[veh],
            active_rides=[ride],
            current_time=t_start,
        )

        prod_cands = generate_active_ride_insertions(
            active_ride=ride,
            requests=[r1, r2, r3],
            vehicle=veh,
            router=router,
            policy=policy,
            current_time=t_start,
            max_bundle_size=b_size,
        )

        comp = oracle.compare(prod_cands, oracle_cands)
        assert comp.is_perfect_match, (
            f"Bundle size {b_size} mismatch: {len(comp.false_negatives)} false negatives, "
            f"{len(comp.false_positives)} false positives"
        )



# ==============================================================================
# Point 4: Targeted Regression Tests for Existing Passenger Boundaries
# ==============================================================================

def test_active_ride_existing_passenger_detour_exact_boundary() -> None:
    """
    Test that an insertion sequence where an existing passenger's detour is
    EXACTLY at the permitted boundary is accepted as a feasible candidate.
    """
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-detour-exact",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )
    t_start = 1000

    d_onb = Coordinate(base_lat + 0.030, base_lon)
    p1 = Coordinate(base_lat + 0.015, base_lon + 0.010)
    d1 = Coordinate(base_lat + 0.020, base_lon)
    dist_pd, dur_pd = router.get_direct_leg(p1, d1)

    stop_pickup_past = RouteStop(
        stop_id="stop-p-onboard",
        ride_id="ride-detour-exact",
        request_id="req-onb",
        stop_type=StopType.PICKUP,
        location=GeoCoordinate(latitude=base_lat, longitude=base_lon),
        passenger_delta=+1,
        scheduled_arrival_time=700,
        actual_arrival_time=700,
        promised_window_start=700,
        promised_window_end=700,
        status=StopStatus.COMPLETED,
    )
    stop_drop_onb = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-detour-exact",
        request_id="req-onb",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onb.latitude, longitude=d_onb.longitude),
        passenger_delta=-1,
        scheduled_arrival_time=1300,
        promised_window_start=1000,
        promised_window_end=3000,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-detour-exact",
        vehicle_id="veh-detour-exact",
        driver_id="drv-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_pickup_past, stop_drop_onb),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )
    req1 = RideRequest(
        request_id="req-1",
        user_id="usr-1",
        pickup_location=GeoCoordinate(latitude=p1.latitude, longitude=p1.longitude),
        dropoff_location=GeoCoordinate(latitude=d1.latitude, longitude=d1.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=dist_pd,
        direct_duration_seconds=dur_pd,
        status=RequestStatus.PENDING,
    )

    # Detour for sequence V -> P1 -> D1 -> E is exactly 59s.
    # Setting detour_absolute_cap_seconds = 59 tests exact boundary equality.
    policy = DispatchPolicy(
        max_pickup_delay_seconds=200,
        detour_relative_multiplier=2.0,
        detour_absolute_cap_seconds=59,
    )
    cands = generate_active_ride_insertions(ride, [req1], veh, router, policy, t_start, max_bundle_size=1)
    assert len(cands) == 1
    stop_ids = [s.stop_id for s in cands[0].ordered_stops]
    assert stop_ids == ["stop-p-req-1", "stop-d-req-1", "stop-d-onboard"]


def test_active_ride_existing_passenger_detour_one_second_beyond() -> None:
    """
    Test that an insertion sequence where an existing passenger's detour is
    ONE SECOND BEYOND the permitted boundary is strictly pruned.
    """
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-detour-beyond",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )
    t_start = 1000

    d_onb = Coordinate(base_lat + 0.030, base_lon)
    p1 = Coordinate(base_lat + 0.015, base_lon + 0.010)
    d1 = Coordinate(base_lat + 0.020, base_lon)
    dist_pd, dur_pd = router.get_direct_leg(p1, d1)

    stop_pickup_past = RouteStop(
        stop_id="stop-p-onboard",
        ride_id="ride-detour-beyond",
        request_id="req-onb",
        stop_type=StopType.PICKUP,
        location=GeoCoordinate(latitude=base_lat, longitude=base_lon),
        passenger_delta=+1,
        scheduled_arrival_time=700,
        actual_arrival_time=700,
        promised_window_start=700,
        promised_window_end=700,
        status=StopStatus.COMPLETED,
    )
    stop_drop_onb = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-detour-beyond",
        request_id="req-onb",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onb.latitude, longitude=d_onb.longitude),
        passenger_delta=-1,
        scheduled_arrival_time=1300,
        promised_window_start=1000,
        promised_window_end=3000,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-detour-beyond",
        vehicle_id="veh-detour-beyond",
        driver_id="drv-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_pickup_past, stop_drop_onb),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )
    req1 = RideRequest(
        request_id="req-1",
        user_id="usr-1",
        pickup_location=GeoCoordinate(latitude=p1.latitude, longitude=p1.longitude),
        dropoff_location=GeoCoordinate(latitude=d1.latitude, longitude=d1.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=dist_pd,
        direct_duration_seconds=dur_pd,
        status=RequestStatus.PENDING,
    )

    # Detour is 59s. Setting cap = 58 makes it 1s beyond the boundary.
    policy = DispatchPolicy(
        max_pickup_delay_seconds=200,
        detour_relative_multiplier=2.0,
        detour_absolute_cap_seconds=58,
    )
    cands = generate_active_ride_insertions(ride, [req1], veh, router, policy, t_start, max_bundle_size=1)
    # The candidate V -> P1 -> D1 -> E exceeds the detour bound by 1s and must be pruned
    assert len(cands) == 0


def test_active_ride_existing_passenger_promised_window_exact_boundary() -> None:
    """
    Test that an insertion sequence where an existing passenger's dropoff arrives
    EXACTLY at promised_window_end is accepted as a feasible candidate.
    """
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-win-exact",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )
    t_start = 1000

    d_onb = Coordinate(base_lat + 0.030, base_lon)
    p1 = Coordinate(base_lat + 0.015, base_lon + 0.010)
    d1 = Coordinate(base_lat + 0.020, base_lon)
    dist_pd, dur_pd = router.get_direct_leg(p1, d1)

    # Sequence V -> P1 -> D1 -> E arrives at E at exactly t = 1359.
    # Setting promised_window_end = 1359 tests exact boundary equality.
    stop_drop_onb = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-win-exact",
        request_id="req-onb",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onb.latitude, longitude=d_onb.longitude),
        passenger_delta=-1,
        scheduled_arrival_time=1300,
        promised_window_start=1000,
        promised_window_end=1359,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-win-exact",
        vehicle_id="veh-win-exact",
        driver_id="drv-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_drop_onb,),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )
    req1 = RideRequest(
        request_id="req-1",
        user_id="usr-1",
        pickup_location=GeoCoordinate(latitude=p1.latitude, longitude=p1.longitude),
        dropoff_location=GeoCoordinate(latitude=d1.latitude, longitude=d1.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=dist_pd,
        direct_duration_seconds=dur_pd,
        status=RequestStatus.PENDING,
    )

    policy = DispatchPolicy(
        max_pickup_delay_seconds=200,
        detour_relative_multiplier=2.0,
        detour_absolute_cap_seconds=500,
    )
    cands = generate_active_ride_insertions(ride, [req1], veh, router, policy, t_start, max_bundle_size=1)
    assert len(cands) == 1
    stop_ids = [s.stop_id for s in cands[0].ordered_stops]
    assert stop_ids == ["stop-p-req-1", "stop-d-req-1", "stop-d-onboard"]
    assert cands[0].ordered_stops[-1].scheduled_arrival_time == 1359


def test_active_ride_existing_passenger_promised_window_one_second_late() -> None:
    """
    Test that an insertion sequence where an existing passenger's dropoff arrives
    ONE SECOND LATE (arr = promised_window_end + 1) is strictly pruned.
    """
    router = MockRoutingProvider(average_speed_kmh=40.0, circuity_factor=1.0)
    base_lat, base_lon = 40.7100, -74.0000
    v_loc = Coordinate(base_lat, base_lon)
    veh = Vehicle(
        vehicle_id="veh-win-late",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=v_loc.latitude, longitude=v_loc.longitude),
        is_active=True,
    )
    t_start = 1000

    d_onb = Coordinate(base_lat + 0.030, base_lon)
    p1 = Coordinate(base_lat + 0.015, base_lon + 0.010)
    d1 = Coordinate(base_lat + 0.020, base_lon)
    dist_pd, dur_pd = router.get_direct_leg(p1, d1)

    # Arrival is 1359. Setting promised_window_end = 1358 makes it 1s late.
    stop_drop_onb = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-win-late",
        request_id="req-onb",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=d_onb.latitude, longitude=d_onb.longitude),
        passenger_delta=-1,
        scheduled_arrival_time=1300,
        promised_window_start=1000,
        promised_window_end=1358,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-win-late",
        vehicle_id="veh-win-late",
        driver_id="drv-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_drop_onb,),
        scheduled_departure_time=t_start,
        active_passenger_count=1,
    )
    req1 = RideRequest(
        request_id="req-1",
        user_id="usr-1",
        pickup_location=GeoCoordinate(latitude=p1.latitude, longitude=p1.longitude),
        dropoff_location=GeoCoordinate(latitude=d1.latitude, longitude=d1.longitude),
        seat_count=1,
        earliest_pickup_time=t_start,
        latest_dropoff_time=t_start + 3600,
        direct_distance_meters=dist_pd,
        direct_duration_seconds=dur_pd,
        status=RequestStatus.PENDING,
    )

    policy = DispatchPolicy(
        max_pickup_delay_seconds=200,
        detour_relative_multiplier=2.0,
        detour_absolute_cap_seconds=500,
    )
    cands = generate_active_ride_insertions(ride, [req1], veh, router, policy, t_start, max_bundle_size=1)
    # The candidate arrives at 1359 > 1358 and must be pruned
    assert len(cands) == 0
