"""
Unit tests for the Local Ride-Matching Playground (Phase 8).

Verifies:
1. Scenario generation repeatability across identical seeds.
2. Invariant verification (capacity profile, precedence, uniqueness).
3. Latency percentile and SLA threshold calculations.
4. Unified playground client execution in in-process mode.
5. Benchmark experiment runner execution and timing isolation.
"""

import pytest

from engine.domain.enums import StopType
from engine.domain.models import GeoCoordinate, RouteStop
from playground.client import PlaygroundClient
from playground.scenario import (
    calculate_benchmark_stats,
    generate_scenario,
    run_experiment,
    verify_correctness,
)


def test_scenario_generation_deterministic_repeatability() -> None:
    """Verifies that identical seeds produce bit-for-bit identical requests and vehicles."""
    s1 = generate_scenario(num_requests=20, num_vehicles=5, seed=123)
    s2 = generate_scenario(num_requests=20, num_vehicles=5, seed=123)
    s_diff = generate_scenario(num_requests=20, num_vehicles=5, seed=999)

    assert len(s1.requests) == 20
    assert len(s1.vehicles) == 5
    assert s1.requests == s2.requests
    assert s1.vehicles == s2.vehicles

    # Different seeds must produce different coordinates
    assert s1.requests != s_diff.requests


def test_calculate_benchmark_stats() -> None:
    """Verifies p50, p95, p99, min, max, mean, and SLA breach counting."""
    # 100 durations: 1.0 to 100.0 ms, plus one at 460ms and one at 520ms
    durations = [float(i) for i in range(1, 101)]
    durations.append(460.0)  # > 450 ms cutoff
    durations.append(520.0)  # > 500 ms SLA breach

    stats = calculate_benchmark_stats(durations)
    assert stats.total_runs == 102
    assert stats.min_ms == 1.0
    assert stats.max_ms == 520.0
    assert stats.runs_over_450ms == 2
    assert stats.runs_over_500ms == 1
    assert stats.p50_ms == pytest.approx(51.5, abs=1.0)
    assert stats.p95_ms > 95.0
    assert stats.p99_ms > 100.0

    # Empty durations edge case
    empty_stats = calculate_benchmark_stats([])
    assert empty_stats.total_runs == 0
    assert empty_stats.p50_ms == 0.0


def test_verify_correctness_precedence_violation() -> None:
    """Detects when a dropoff occurs before its corresponding pickup."""
    loc = GeoCoordinate(latitude=40.75, longitude=-73.98)
    invalid_stops = [
        RouteStop(
            stop_id="s1",
            ride_id="r1",
            request_id="req-1",
            stop_type=StopType.DROPOFF,  # Dropoff first!
            location=loc,
            passenger_delta=-1,
            scheduled_arrival_time=1000,
            promised_window_start=900,
            promised_window_end=1100,
        ),
        RouteStop(
            stop_id="s2",
            ride_id="r1",
            request_id="req-1",
            stop_type=StopType.PICKUP,  # Pickup second!
            location=loc,
            passenger_delta=1,
            scheduled_arrival_time=1200,
            promised_window_start=1100,
            promised_window_end=1300,
        ),
    ]

    assignments = [{"vehicle_id": "veh-1", "request_ids": ["req-1"], "stops": invalid_stops}]
    audit = verify_correctness(assignments, {"veh-1": {"total_seat_capacity": 4}})
    assert audit.all_passed is False
    assert audit.precedence_passed is False
    assert any("precedence" in err.lower() for err in audit.issues)


def test_verify_correctness_capacity_violation() -> None:
    """Detects when cumulative occupancy exceeds vehicle seat capacity."""
    loc = GeoCoordinate(latitude=40.75, longitude=-73.98)
    overcap_stops = [
        RouteStop(
            stop_id="s1",
            ride_id="r1",
            request_id="req-1",
            stop_type=StopType.PICKUP,
            location=loc,
            passenger_delta=3,
            scheduled_arrival_time=1000,
            promised_window_start=900,
            promised_window_end=1100,
        ),
        RouteStop(
            stop_id="s2",
            ride_id="r1",
            request_id="req-2",
            stop_type=StopType.PICKUP,
            location=loc,
            passenger_delta=3,  # 3 + 3 = 6 > capacity of 4
            scheduled_arrival_time=1100,
            promised_window_start=1000,
            promised_window_end=1200,
        ),
    ]

    assignments = [{"vehicle_id": "veh-1", "request_ids": ["req-1", "req-2"], "stops": overcap_stops}]
    audit = verify_correctness(assignments, {"veh-1": {"total_seat_capacity": 4}})
    assert audit.all_passed is False
    assert audit.capacity_passed is False
    assert any("capacity" in err.lower() for err in audit.issues)


def test_verify_correctness_uniqueness_violation() -> None:
    """Detects when a single request is assigned to multiple vehicles in the same cycle."""
    assignments = [
        {"vehicle_id": "veh-1", "request_ids": ["req-shared"], "stops": []},
        {"vehicle_id": "veh-2", "request_ids": ["req-shared"], "stops": []},
    ]
    audit = verify_correctness(assignments, {})
    assert audit.all_passed is False
    assert audit.uniqueness_passed is False
    assert any("multiple times" in err.lower() for err in audit.issues)


def test_playground_client_in_process_lifecycle() -> None:
    """Verifies that PlaygroundClient works end-to-end against an in-process ASGI service."""
    client = PlaygroundClient()  # In-process default
    assert client.is_in_process is True

    # 1. Health check
    health = client.get_health()
    assert health["ready"] is True

    # 2. Register vehicle
    code, v_res = client.register_vehicle(
        vehicle_id="veh-test-01",
        driver_id="drv-test-01",
        total_seat_capacity=4,
        latitude=40.7580,
        longitude=-73.9855,
    )
    assert code == 201
    assert v_res["vehicle_id"] == "veh-test-01"

    # 3. Submit request
    code, r_res = client.submit_ride_request(
        request_id="req-test-01",
        user_id="user-01",
        pickup_lat=40.7580,
        pickup_lon=-73.9855,
        dropoff_lat=40.7829,
        dropoff_lon=-73.9654,
        seat_count=1,
    )
    assert code == 201
    assert r_res["request_id"] == "req-test-01"

    # 4. Run dispatch
    code, d_res = client.run_dispatch(current_time=1700000000)
    assert code == 200
    assert "committed_assignments" in d_res
    assert len(d_res["committed_assignments"]) == 1
    assert d_res["committed_assignments"][0]["vehicle_id"] == "veh-test-01"

    # 5. Cancel request
    code, c_res = client.cancel_request("req-test-01")
    assert code == 200
    assert c_res["status"] == "CANCELLED"


def test_run_experiment_reproducibility_and_invariants() -> None:
    """Verifies that run_experiment executes isolated trials and passes invariant checks."""
    exp = run_experiment(
        num_requests=10,
        num_vehicles=5,
        num_runs=3,
        seed=101,
        use_osrm=False,  # Mock routing for fast unit test
        deadline_seconds=0.500,
    )

    assert exp.num_requests == 10
    assert exp.num_vehicles == 5
    assert exp.num_runs == 3
    assert exp.seed == 101
    assert "Mock Routing" in exp.routing_backend
    assert exp.statistics.total_runs == 3
    assert exp.statistics.p50_ms > 0.0
    assert exp.correctness.all_passed is True
    assert len(exp.raw_runs) == 3


def test_playground_client_host_corridor_and_en_route_join() -> None:
    """Verifies that PlaygroundClient correctly supports host corridor and en-route join operations."""
    import time
    client = PlaygroundClient()
    now = int(time.time())

    # 1. Register host ride: Midtown -> Wall St
    c_host, res_host = client.register_host_ride(
        driver_id="usr-host-play",
        origin_lat=40.7580,
        origin_lon=-73.9855,
        dest_lat=40.7070,
        dest_lon=-74.0090,
        scheduled_departure_time=now + 300,
        available_seats=3,
        max_detour_seconds=900,
    )
    assert c_host == 201
    ride_id = res_host["ride_id"]
    veh_id = res_host["vehicle_id"]
    assert res_host["available_seats"] == 3
    assert res_host["direct_duration_seconds"] > 0

    # 2. Register compatible traveller
    c_req, _ = client.submit_ride_request(
        request_id="req-play-c1",
        user_id="usr-play-c1",
        pickup_lat=40.7410,
        pickup_lon=-73.9897,
        dropoff_lat=40.7128,
        dropoff_lon=-74.0060,
        seat_count=1,
        earliest_pickup_time=now + 300,
        latest_dropoff_time=now + 3600,
    )
    assert c_req == 201

    # 3. Match corridor
    c_match, res_match = client.match_host_ride(ride_id, request_id="req-play-c1")
    assert c_match == 200
    props = res_match["proposals"]
    assert len(props) == 1
    prop_id = props[0]["proposal_id"]

    # 4. Bilateral acceptance
    c_a1, res_a1 = client.accept_proposal(prop_id, user_id="usr-host-play", current_time=now + 300)
    assert c_a1 == 200
    assert res_a1["is_confirmed"] is False

    c_a2, res_a2 = client.accept_proposal(prop_id, user_id="usr-play-c1", current_time=now + 300)
    assert c_a2 == 200
    assert res_a2["is_confirmed"] is True

    # 5. In-transit simulated movement to 14th St
    c_loc, _ = client.update_vehicle_progress(
        vehicle_id=veh_id,
        latitude=40.7350,
        longitude=-73.9910,
        ride_id=ride_id,
        completed_stop_ids=[f"stop-origin-{ride_id}", "stop-p-req-play-c1"],
        current_time=now + 500,
    )
    assert c_loc == 200

    # 6. Behind pickup (34th St) -> Rejected by spatial gate
    client.submit_ride_request(
        request_id="req-play-behind",
        user_id="usr-play-behind",
        pickup_lat=40.7505,
        pickup_lon=-73.9876,
        dropoff_lat=40.7070,
        dropoff_lon=-74.0090,
        seat_count=1,
        earliest_pickup_time=now + 500,
        latest_dropoff_time=now + 3600,
    )
    c_beh, res_beh = client.evaluate_en_route_join(ride_id, "req-play-behind", current_time=now + 500)
    assert c_beh == 409
    assert res_beh["eligible"] is False
    assert res_beh["rejection_reason"] == "PICKUP_BEHIND_VEHICLE"

    # 7. Ahead pickup (Canal St) -> Accepted by spatial gate
    client.submit_ride_request(
        request_id="req-play-ahead",
        user_id="usr-play-ahead",
        pickup_lat=40.7180,
        pickup_lon=-74.0010,
        dropoff_lat=40.7128,
        dropoff_lon=-74.0060,
        seat_count=1,
        earliest_pickup_time=now + 500,
        latest_dropoff_time=now + 3600,
    )
    c_ah, res_ah = client.evaluate_en_route_join(ride_id, "req-play-ahead", current_time=now + 500)
    assert c_ah == 200
    assert res_ah["eligible"] is True
    assert res_ah["proposal"] is not None
