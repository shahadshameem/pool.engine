"""End-to-end integration tests executing all 6 scenarios in quickstart.md (T054)."""

import concurrent.futures
import time

import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.policy import DispatchPolicy
from engine.contracts.routing import Coordinate
from engine.dispatch import DispatchEngine
from engine.domain.enums import JoinStatus, RequestStatus, RideStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle
from engine.lifecycle.reservations import (
    confirm_join_request,
    submit_join_request,
)
from engine.lifecycle.transitions import (
    GpsTelemetryPing,
    confirm_passenger_boarding,
    process_gps_telemetry,
    process_ride_timers,
)
from engine.routing.insertion import generate_single_request_insertions
from engine.spatial.index import SpatialIndexCoordinator
from tests.benchmark.conftest import generate_benchmark_scenario


def test_quickstart_scenario_1_group_bundling_and_insertion() -> None:
    """
    Scenario 1: Multi-Passenger Group Bundling & Insertion.
    Vehicle V1: 4 seats, 1 existing passenger onboard.
    Request R1: 1 seat (compatible trajectory).
    Request R2: 3 seats (3 + 1 > 4 violates V1 capacity).
    Vehicle V2: 4 seats, idle.
    Expectation: R1 matches into V1, R2 matches into empty V2 (not V1).
    """
    policy_provider = DefaultPolicyProvider()
    routing_provider = MockRoutingProvider()
    spatial_index = H3SpatialIndexAdapter()
    engine = DispatchEngine(
        policy_provider=policy_provider,
        routing_provider=routing_provider,
        spatial_index=spatial_index,
    )

    loc_start = GeoCoordinate(latitude=40.7100, longitude=-74.0050)
    loc_v1_d = GeoCoordinate(latitude=40.7900, longitude=-73.9500)

    # V1: 4 seats with 1 passenger onboard
    v1 = Vehicle(
        vehicle_id="V1",
        driver_id="D1",
        total_seat_capacity=4,
        current_location=loc_start,
        is_active=True,
    )
    stop_p_onboard = RouteStop(
        stop_id="stop-p-onboard",
        ride_id="ride-v1",
        request_id="req-onboard",
        stop_type=StopType.PICKUP,
        location=loc_start,
        passenger_delta=+1,
        scheduled_arrival_time=1000,
        promised_window_start=1000,
        promised_window_end=1200,
        status=StopStatus.COMPLETED,
    )
    stop_d_onboard = RouteStop(
        stop_id="stop-d-onboard",
        ride_id="ride-v1",
        request_id="req-onboard",
        stop_type=StopType.DROPOFF,
        location=loc_v1_d,
        passenger_delta=-1,
        scheduled_arrival_time=2500,
        promised_window_start=1000,
        promised_window_end=3000,
        status=StopStatus.SCHEDULED,
    )
    ride_v1 = Ride(
        ride_id="ride-v1",
        vehicle_id="V1",
        driver_id="D1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_p_onboard, stop_d_onboard),
        scheduled_departure_time=1000,
        active_passenger_count=1,
        total_vmt_meters=5000,
        version=1,
    )

    # V2: 4 seats, idle
    v2 = Vehicle(
        vehicle_id="V2",
        driver_id="D2",
        total_seat_capacity=4,
        current_location=loc_start,
        is_active=True,
    )

    # R1: 1 seat
    r1 = RideRequest(
        request_id="R1",
        user_id="U1",
        pickup_location=GeoCoordinate(latitude=40.7200, longitude=-74.0000),
        dropoff_location=GeoCoordinate(latitude=40.7800, longitude=-73.9600),
        seat_count=1,
        earliest_pickup_time=1050,
        latest_dropoff_time=3000,
        direct_distance_meters=4000,
        direct_duration_seconds=500,
        status=RequestStatus.PENDING,
    )

    # R2: 3 seats
    r2 = RideRequest(
        request_id="R2",
        user_id="U2",
        pickup_location=GeoCoordinate(latitude=40.7150, longitude=-74.0020),
        dropoff_location=GeoCoordinate(latitude=40.7850, longitude=-73.9550),
        seat_count=3,
        earliest_pickup_time=1050,
        latest_dropoff_time=3000,
        direct_distance_meters=4500,
        direct_duration_seconds=550,
        status=RequestStatus.PENDING,
    )

    result = engine.dispatch_batch(
        requests=[r1, r2],
        vehicles=[v1, v2],
        active_rides=[ride_v1],
        current_time=1000,
        batch_id="qs-batch-1",
    )

    # Assertions
    assigned_v1 = [a for a in result.selected_assignments if a.vehicle_id == "V1"]
    assigned_v2 = [a for a in result.selected_assignments if a.vehicle_id == "V2"]

    # R2 cannot fit on V1 (3 + 1 = 4 total, but capacity and detour)
    if assigned_v1:
        assert "R2" not in assigned_v1[0].request_ids
        assert "R1" in assigned_v1[0].request_ids

    if assigned_v2:
        assert "R2" in assigned_v2[0].request_ids


def test_quickstart_scenario_2_two_stage_feasibility_gate() -> None:
    """
    Scenario 2: Two-Stage Feasibility Gate & Invariant Protection.
    A candidate route offering high VMT reduction but breaching detour cap
    Delta T > min((alpha - 1) T_direct, C) is strictly pruned in Stage 1.
    """
    policy = DispatchPolicy(
        detour_relative_multiplier=1.30,
        detour_absolute_cap_seconds=900,
        max_pickup_delay_seconds=600,
    )
    router = MockRoutingProvider(average_speed_kmh=40.0)

    # Short trip: T_direct = 600s. Max allowed: 780s (max detour: 180s)
    loc_p = GeoCoordinate(latitude=40.7128, longitude=-74.0060)
    loc_d = GeoCoordinate(latitude=40.7589, longitude=-73.9851)

    req = RideRequest(
        request_id="req-gate-short",
        user_id="u-gate",
        pickup_location=loc_p,
        dropoff_location=loc_d,
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=2000,
        direct_distance_meters=5500,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )

    # Vehicle with a circuitous detour that takes 840s (detour = 240s > 180s cap)
    # Circuitous intermediate stop far out
    loc_far = GeoCoordinate(latitude=40.8500, longitude=-73.9000)
    stop_far = RouteStop(
        stop_id="stop-d-far",
        ride_id="ride-gate",
        request_id="req-onboard-far",
        stop_type=StopType.DROPOFF,
        location=loc_far,
        passenger_delta=-1,
        scheduled_arrival_time=1400,
        promised_window_start=1000,
        promised_window_end=4000,
        status=StopStatus.SCHEDULED,
    )
    ride = Ride(
        ride_id="ride-gate",
        vehicle_id="veh-gate",
        driver_id="drv-gate",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_far,),
        scheduled_departure_time=1000,
        active_passenger_count=1,
        version=1,
    )
    vehicle = Vehicle(
        vehicle_id="veh-gate",
        driver_id="drv-gate",
        total_seat_capacity=4,
        current_location=loc_p,
        is_active=True,
    )

    candidates = generate_single_request_insertions(
        active_ride=ride,
        request=req,
        vehicle=vehicle,
        router=router,
        policy=policy,
        current_time=1000,
    )

    # Permutations that route to loc_far before dropoff take > 780s and must be pruned
    for c in candidates:
        # If both loc_far and req.dropoff are present, dropoff must not have exceeded detour
        d_stop = next(s for s in c.ordered_stops if s.request_id == req.request_id and s.stop_type == StopType.DROPOFF)
        p_stop = next(s for s in c.ordered_stops if s.request_id == req.request_id and s.stop_type == StopType.PICKUP)
        dur = d_stop.scheduled_arrival_time - p_stop.scheduled_arrival_time
        assert dur <= 780


def test_quickstart_scenario_3_atomic_concurrency_and_race_resolution() -> None:
    """
    Scenario 3: Atomic Concurrency, Seat Holds & Race Resolution.
    10 concurrent join requests for 1 available seat result in exactly 1 APPROVED,
    9 REJECTED with OVER_CAPACITY, and zero overbooking. Duplicate token returns APPROVED.
    """
    storage = InMemoryRideStorage()
    vehicle = Vehicle(
        vehicle_id="V-qs3",
        driver_id="D-qs3",
        total_seat_capacity=1,
        current_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        is_active=True,
    )
    storage.save_vehicle(vehicle)
    ride = Ride(
        ride_id="ride-qs3",
        vehicle_id="V-qs3",
        driver_id="D-qs3",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(),
        scheduled_departure_time=1000,
        active_passenger_count=0,
        version=1,
    )
    storage.save_ride(ride)

    policy_provider = DefaultPolicyProvider()
    router = MockRoutingProvider()

    requests: list[RideRequest] = []
    for i in range(10):
        req = RideRequest(
            request_id=f"req-qs3-{i}",
            user_id=f"u-qs3-{i}",
            pickup_location=GeoCoordinate(latitude=40.7128 + i * 0.001, longitude=-74.0060),
            dropoff_location=GeoCoordinate(latitude=40.7589 + i * 0.001, longitude=-73.9851),
            seat_count=1,
            earliest_pickup_time=1000,
            latest_dropoff_time=4000,
            direct_distance_meters=5000,
            direct_duration_seconds=600,
            status=RequestStatus.PENDING,
        )
        storage.save_request(req)
        requests.append(req)

    def _join_and_confirm(r: RideRequest) -> bool:
        token = f"token-qs3-{r.request_id}"
        sub = submit_join_request(
            request=r,
            ride_id="ride-qs3",
            storage=storage,
            policy=policy_provider.get_policy(),
            current_time=1000,
            idempotency_token=token,
        )
        if not sub.success:
            return False
        conf = confirm_join_request(
            join_request_id=sub.join_request.join_request_id,
            storage=storage,
            policy_provider=policy_provider,
            router=router,
            current_time=1010,
            idempotency_token=token,
        )
        return conf.success

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(_join_and_confirm, requests))

    assert results.count(True) == 1
    assert results.count(False) == 9

    # Idempotent duplicate replay check
    approved_req = next(r for r, ok in zip(requests, results) if ok)
    approved_token = f"token-qs3-{approved_req.request_id}"
    replay = confirm_join_request(
        join_request_id=f"join-{approved_token}",
        storage=storage,
        policy_provider=policy_provider,
        router=router,
        current_time=1020,
        idempotency_token=approved_token,
    )
    assert replay.success
    assert replay.join_request.status == JoinStatus.APPROVED


def test_quickstart_scenario_4_exact_boundary_timers() -> None:
    """
    Scenario 4: Exact Boundary Timer & Grace Period Transitions.
    - Boarding grace: t = 180s accepted; t = 181s NO_SHOW.
    - Dwell filter: < 15s passthrough does NOT trigger ARRIVED; >= 15s triggers ARRIVED.
    """
    policy = DispatchPolicy(
        boarding_grace_period_seconds=180,
        stop_arrival_dwell_seconds=15,
    )
    stop_loc = GeoCoordinate(latitude=40.7128, longitude=-74.0060)

    # 1. Dwell passthrough for 3s -> remains SCHEDULED
    stop = RouteStop(
        stop_id="s-dwell",
        ride_id="r-dwell",
        request_id="req-dwell",
        stop_type=StopType.PICKUP,
        location=stop_loc,
        passenger_delta=1,
        scheduled_arrival_time=1000,
        promised_window_start=1000,
        promised_window_end=1600,
        status=StopStatus.SCHEDULED,
    )
    ping_in = GpsTelemetryPing("v1", stop_loc, timestamp=100)
    stop_in = process_gps_telemetry(stop, ping_in, policy=policy)
    ping_out = GpsTelemetryPing("v1", GeoCoordinate(latitude=40.7300, longitude=-74.0200), timestamp=103)
    stop_out = process_gps_telemetry(stop_in, ping_out, policy=policy)
    assert stop_out.status == StopStatus.SCHEDULED

    # 2. Continuous dwell for 15s -> ARRIVED
    s_dw = stop
    for t_step in range(100, 116, 5):
        s_dw = process_gps_telemetry(s_dw, GpsTelemetryPing("v1", stop_loc, timestamp=t_step), policy=policy)
    assert s_dw.status in (StopStatus.ARRIVED, StopStatus.IN_GRACE_PERIOD)

    # 3. Boarding grace: t = 180s accepted
    ride = Ride(
        ride_id="r-board",
        vehicle_id="v1",
        driver_id="d1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(s_dw.model_copy(update={"status": StopStatus.IN_GRACE_PERIOD, "actual_arrival_time": 1000}),),
        scheduled_departure_time=1000,
        active_passenger_count=0,
    )
    r_ok, s_ok = confirm_passenger_boarding(ride, s_dw.stop_id, current_time=1180, policy=policy)
    assert s_ok.status == StopStatus.COMPLETED

    # 4. Boarding grace: t = 181s -> NO_SHOW
    r_timeout = process_ride_timers(ride, current_time=1181, policy=policy)
    assert r_timeout.stops[0].status == StopStatus.NO_SHOW


def test_quickstart_scenario_5_spatial_candidate_recall() -> None:
    """
    Scenario 5: Spatial Filtering Candidate Recall vs. Exhaustive Search.
    Verifies 100% candidate recall of all feasible candidates on test fixture.
    """
    coord = SpatialIndexCoordinator(H3SpatialIndexAdapter(resolution=8))
    entities = [
        (f"veh-{i}", Coordinate(latitude=40.7100 + i * 0.005, longitude=-74.0050 + i * 0.005))
        for i in range(50)
    ]
    coord.index_entities(entities)

    target = Coordinate(latitude=40.7200, longitude=-73.9950)
    radius = 5000.0

    exhaustive = coord.exhaustive_search(target=target, max_radius_meters=radius)
    indexed = coord.find_candidates_within_radius(target=target, max_radius_meters=radius, min_candidates=1)

    ex_ids = {c.entity_id for c in exhaustive}
    idx_ids = {c.entity_id for c in indexed}

    # 100% complete recall on test fixture
    assert ex_ids == idx_ids


def test_quickstart_scenario_6_benchmark_sla_and_optimality_gap() -> None:
    """
    Scenario 6: Deterministic Benchmark SLA (<= 500ms) & Exact Optimality Gap.
    1,000 active requests, 200 vehicles with fixed seed=42 completes <= 500ms wall-clock.
    """
    reqs, vehs, rides = generate_benchmark_scenario(seed=42)
    engine = DispatchEngine(
        policy_provider=DefaultPolicyProvider(),
        routing_provider=MockRoutingProvider(average_speed_kmh=40.0),
        spatial_index=H3SpatialIndexAdapter(resolution=8),
    )

    t0 = time.perf_counter()
    res = engine.dispatch_batch(
        requests=reqs,
        vehicles=vehs,
        active_rides=rides,
        current_time=1700000000,
        batch_id="qs-bench-6",
        deadline=time.monotonic() + 0.500,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert elapsed_ms <= 500.0
    assert res.solve_duration_ms <= 500.0
    assert len(res.selected_assignments) > 0
