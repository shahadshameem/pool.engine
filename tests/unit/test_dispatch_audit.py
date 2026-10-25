"""Adversarial and property-style unit tests for dispatch correctness and audit requirements."""

import random
import time
import pytest
from typing import Sequence

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.mock_routing import MockRoutingProvider
from engine.dispatch import CandidateGenerationConfig, DispatchEngine
from engine.domain.candidate import CandidateAssignment, ScoreBreakdown
from engine.domain.enums import DispatchMode, RequestStatus, SearchStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, RouteStop, RideRequest, Vehicle
from engine.optimization.set_packing import solve_exact_set_packing, solve_set_packing_regret_k


def _dummy_stop(stop_id: str, req_id: str) -> RouteStop:
    return RouteStop(
        stop_id=stop_id,
        ride_id="ride-test",
        request_id=req_id,
        stop_type=StopType.PICKUP,
        location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        passenger_delta=1,
        scheduled_arrival_time=1700000000,
        promised_window_start=1700000000,
        promised_window_end=1700001000,
        status=StopStatus.SCHEDULED,
    )


def test_adversarial_duplicate_requests_within_candidate_exact_solver() -> None:
    """
    Demonstrated defect test:
    If a candidate contains duplicate request IDs (e.g. ('r1', 'r1')),
    solve_exact_set_packing must NOT crash with KeyError during backtracking.
    It must safely discard the malformed candidate and match valid candidates.
    """
    all_requests = ["r1", "r2"]

    # Valid candidate for v1 and r2
    valid_cand = CandidateAssignment(
        candidate_id="c-valid",
        vehicle_id="v1",
        existing_ride_id=None,
        request_ids=("r2",),
        ordered_stops=(_dummy_stop("s-valid", "r2"),),
        peak_seat_load=1,
        vmt_meters=1000,
        objective_value=0.5,
        normalized_score=0.8,
        score_breakdown=ScoreBreakdown(vmt_savings_ratio=0.5),
    )

    # Malformed candidate with duplicate request IDs
    malformed_cand = CandidateAssignment(
        candidate_id="c-malformed",
        vehicle_id="v2",
        existing_ride_id=None,
        request_ids=("r1", "r1"),
        ordered_stops=(_dummy_stop("s-1", "r1"), _dummy_stop("s-2", "r1")),
        peak_seat_load=2,
        vmt_meters=1000,
        objective_value=0.9,
        normalized_score=0.9,
        score_breakdown=ScoreBreakdown(vmt_savings_ratio=0.5),
    )

    result = solve_exact_set_packing(
        candidates=[malformed_cand, valid_cand],
        all_request_ids=all_requests,
    )

    # Valid candidate should be selected, malformed candidate rejected
    assert len(result.selected_assignments) == 1
    assert result.selected_assignments[0].candidate_id == "c-valid"
    assert "r1" in result.unassigned_request_ids


def test_adversarial_duplicate_requests_within_candidate_regret_k() -> None:
    """
    Demonstrated defect test:
    If a candidate contains duplicate request IDs (e.g. ('r1', 'r1')),
    solve_set_packing_regret_k must NOT corrupt the entire matching or abort all assignments.
    It must filter out the malformed candidate and match legitimate candidates.
    """
    all_requests = ["r1", "r2"]

    valid_cand = CandidateAssignment(
        candidate_id="c-valid",
        vehicle_id="v1",
        existing_ride_id=None,
        request_ids=("r2",),
        ordered_stops=(_dummy_stop("s-valid", "r2"),),
        peak_seat_load=1,
        vmt_meters=1000,
        objective_value=0.5,
        normalized_score=0.8,
        score_breakdown=ScoreBreakdown(vmt_savings_ratio=0.5),
    )

    malformed_cand = CandidateAssignment(
        candidate_id="c-malformed",
        vehicle_id="v2",
        existing_ride_id=None,
        request_ids=("r1", "r1"),
        ordered_stops=(_dummy_stop("s-1", "r1"), _dummy_stop("s-2", "r1")),
        peak_seat_load=2,
        vmt_meters=1000,
        objective_value=0.9,
        normalized_score=0.9,
        score_breakdown=ScoreBreakdown(vmt_savings_ratio=0.5),
    )

    result = solve_set_packing_regret_k(
        candidates=[malformed_cand, valid_cand],
        all_request_ids=all_requests,
    )

    assert len(result.selected_assignments) == 1
    assert result.selected_assignments[0].candidate_id == "c-valid"
    assert "r1" in result.unassigned_request_ids


def test_adversarial_heavy_contention_disjointness() -> None:
    """
    Stress test with 10 vehicles and 20 requests where candidates have massive mutual contention.
    Verifies that neither vehicle nor request is ever double-assigned under any circumstances.
    """
    rng = random.Random(12345)
    all_requests = [f"req-{i:02d}" for i in range(20)]
    all_vehicles = [f"veh-{j:02d}" for j in range(10)]

    candidates: list[CandidateAssignment] = []
    c_idx = 0
    for v in all_vehicles:
        for _ in range(15):
            bundle_size = rng.randint(1, 3)
            sampled_reqs = tuple(sorted(rng.sample(all_requests, bundle_size)))
            stops = tuple(_dummy_stop(f"s-{c_idx}-{r}", r) for r in sampled_reqs)
            c = CandidateAssignment(
                candidate_id=f"cand-{c_idx:04d}",
                vehicle_id=v,
                existing_ride_id=None,
                request_ids=sampled_reqs,
                ordered_stops=stops,
                peak_seat_load=bundle_size,
                vmt_meters=1000 * bundle_size,
                objective_value=round(rng.uniform(0.1, 0.9), 4),
                normalized_score=0.75,
                score_breakdown=ScoreBreakdown(vmt_savings_ratio=0.3),
            )
            candidates.append(c)
            c_idx += 1

    result = solve_set_packing_regret_k(candidates=candidates, all_request_ids=all_requests)

    # 1. No vehicle assigned more than once
    assigned_vehs = [c.vehicle_id for c in result.selected_assignments]
    assert len(assigned_vehs) == len(set(assigned_vehs))

    # 2. No request assigned more than once
    assigned_reqs = [r for c in result.selected_assignments for r in c.request_ids]
    assert len(assigned_reqs) == len(set(assigned_reqs))

    # 3. Disjoint partitioned unassigned
    assert set(assigned_reqs).isdisjoint(set(result.unassigned_request_ids))
    assert set(assigned_reqs) | set(result.unassigned_request_ids) == set(all_requests)


def test_search_status_distinction_complete_vs_approximated_vs_interrupted() -> None:
    """
    Verifies search status integrity:
    1. EXACT mode with plenty of time -> COMPLETE, is_approximated=False
    2. BOUNDED mode with plenty of time -> APPROXIMATED, is_approximated=True
    3. Deadline expired before or during candidate search -> INCOMPLETE_DEADLINE_EXPIRED, is_approximated=True
    4. An interrupted search is NEVER reported as COMPLETE or APPROXIMATED.
    """
    engine = DispatchEngine(
        policy_provider=DefaultPolicyProvider(),
        routing_provider=MockRoutingProvider(),
        spatial_index=H3SpatialIndexAdapter(),
    )

    req = RideRequest(
        request_id="req-status-1",
        user_id="user-1",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7200, longitude=-74.0000),
        seat_count=1,
        earliest_pickup_time=1700000000,
        latest_dropoff_time=1700001800,
        direct_distance_meters=1500,
        direct_duration_seconds=200,
        status=RequestStatus.PENDING,
    )
    veh = Vehicle(
        vehicle_id="veh-status-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=40.7130, longitude=-74.0055),
        is_active=True,
    )

    # 1. EXACT mode
    res_exact = engine.dispatch_batch(
        requests=[req],
        vehicles=[veh],
        active_rides=[],
        current_time=1700000000,
        config=CandidateGenerationConfig(mode=DispatchMode.EXACT, max_search_radius_meters=None),
        deadline=time.monotonic() + 5.0,
    )
    assert res_exact.search_status == SearchStatus.COMPLETE
    assert res_exact.is_approximated is False

    # 2. BOUNDED mode
    res_bounded = engine.dispatch_batch(
        requests=[req],
        vehicles=[veh],
        active_rides=[],
        current_time=1700000000,
        config=CandidateGenerationConfig(mode=DispatchMode.BOUNDED),
        deadline=time.monotonic() + 5.0,
    )
    assert res_bounded.search_status == SearchStatus.APPROXIMATED
    assert res_bounded.is_approximated is True

    # 3. Interrupted search (expired deadline)
    res_interrupted = engine.dispatch_batch(
        requests=[req],
        vehicles=[veh],
        active_rides=[],
        current_time=1700000000,
        deadline=time.monotonic() - 0.100,
    )
    assert res_interrupted.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
    assert res_interrupted.is_approximated is True


def test_early_returns_unassigned_request_ids_are_sorted() -> None:
    """
    Verifies that unassigned_request_ids in early returns (e.g. no vehicles, or immediate timeout)
    are deterministically sorted, preserving input-order independence.
    """
    engine = DispatchEngine(
        policy_provider=DefaultPolicyProvider(),
        routing_provider=MockRoutingProvider(),
        spatial_index=H3SpatialIndexAdapter(),
    )

    reqs = [
        RideRequest(
            request_id=f"req-{rid}",
            user_id=f"user-{rid}",
            pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
            dropoff_location=GeoCoordinate(latitude=40.7200, longitude=-74.0000),
            seat_count=1,
            earliest_pickup_time=1700000000,
            latest_dropoff_time=1700001800,
            direct_distance_meters=1500,
            direct_duration_seconds=200,
            status=RequestStatus.PENDING,
        )
        for rid in ["delta", "alpha", "charlie", "bravo"]
    ]

    # Stage 1 early return (0 vehicles)
    res_no_vehs = engine.dispatch_batch(
        requests=reqs,
        vehicles=[],
        active_rides=[],
        current_time=1700000000,
    )
    assert res_no_vehs.unassigned_request_ids == ("req-alpha", "req-bravo", "req-charlie", "req-delta")

    # Immediate deadline timeout return
    res_timeout = engine.dispatch_batch(
        requests=reqs,
        vehicles=[Vehicle(
            vehicle_id="veh-1",
            driver_id="drv-1",
            total_seat_capacity=4,
            current_location=GeoCoordinate(latitude=40.7130, longitude=-74.0055),
            is_active=True,
        )],
        active_rides=[],
        current_time=1700000000,
        deadline=time.monotonic() - 0.100,
    )
    assert res_timeout.unassigned_request_ids == ("req-alpha", "req-bravo", "req-charlie", "req-delta")


def test_solve_set_packing_preserves_candidate_list_incomplete_status() -> None:
    """
    Verifies that if solve_set_packing_regret_k is passed a CandidateList whose
    search_status is INCOMPLETE_DEADLINE_EXPIRED, it does not falsely report COMPLETE.
    """
    from engine.dispatch import CandidateList

    all_requests = ["r1"]
    cand = CandidateAssignment(
        candidate_id="c1",
        vehicle_id="v1",
        existing_ride_id=None,
        request_ids=("r1",),
        ordered_stops=(_dummy_stop("s1", "r1"),),
        peak_seat_load=1,
        vmt_meters=1000,
        objective_value=0.5,
        normalized_score=0.8,
        score_breakdown=ScoreBreakdown(),
    )
    cands = CandidateList(
        candidates=[cand],
        search_status=SearchStatus.INCOMPLETE_DEADLINE_EXPIRED,
        is_approximated=True,
    )
    result = solve_set_packing_regret_k(
        candidates=cands,
        all_request_ids=all_requests,
        deadline=time.monotonic() + 5.0,
    )
    assert result.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
    assert result.is_approximated is True


def test_adversarial_duplicate_input_request_ids_in_dispatch() -> None:
    """
    Verifies request partition integrity when duplicate input requests are passed into dispatch_batch:
    1. Conflicting duplicates (different fields for same request_id) must be rejected with ValueError.
    2. Identical duplicates (same fields for same request_id) must deduplicate cleanly.
    3. Output assigned and unassigned requests must form a strict partition of unique request IDs.
    """
    engine = DispatchEngine(
        policy_provider=DefaultPolicyProvider(),
        routing_provider=MockRoutingProvider(),
        spatial_index=H3SpatialIndexAdapter(),
    )

    req1_a = RideRequest(
        request_id="req-dup",
        user_id="user-1a",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7200, longitude=-74.0000),
        seat_count=1,
        earliest_pickup_time=1700000000,
        latest_dropoff_time=1700001800,
        direct_distance_meters=1500,
        direct_duration_seconds=200,
        status=RequestStatus.PENDING,
    )
    req1_conflicting = RideRequest(
        request_id="req-dup",
        user_id="user-1b",  # Conflicting user
        pickup_location=GeoCoordinate(latitude=40.7130, longitude=-74.0065),  # Conflicting location
        dropoff_location=GeoCoordinate(latitude=40.7210, longitude=-74.0010),
        seat_count=1,
        earliest_pickup_time=1700000000,
        latest_dropoff_time=1700001800,
        direct_distance_meters=1500,
        direct_duration_seconds=200,
        status=RequestStatus.PENDING,
    )
    req2 = RideRequest(
        request_id="req-unique",
        user_id="user-2",
        pickup_location=GeoCoordinate(latitude=40.7140, longitude=-74.0070),
        dropoff_location=GeoCoordinate(latitude=40.7250, longitude=-74.0020),
        seat_count=1,
        earliest_pickup_time=1700000000,
        latest_dropoff_time=1700001800,
        direct_distance_meters=1500,
        direct_duration_seconds=200,
        status=RequestStatus.PENDING,
    )

    veh = Vehicle(
        vehicle_id="veh-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=40.7125, longitude=-74.0055),
        is_active=True,
    )

    # 1. Conflicting duplicates must be rejected with ValueError
    with pytest.raises(ValueError, match="Conflicting duplicate request detected"):
        engine.dispatch_batch(
            requests=[req1_a, req1_conflicting, req2],
            vehicles=[veh],
            active_rides=[],
            current_time=1700000000,
        )

    # 2. Identical duplicates must deduplicate cleanly
    req1_identical = RideRequest(
        request_id="req-dup",
        user_id="user-1a",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7200, longitude=-74.0000),
        seat_count=1,
        earliest_pickup_time=1700000000,
        latest_dropoff_time=1700001800,
        direct_distance_meters=1500,
        direct_duration_seconds=200,
        status=RequestStatus.PENDING,
    )
    result = engine.dispatch_batch(
        requests=[req1_a, req1_identical, req2],
        vehicles=[veh],
        active_rides=[],
        current_time=1700000000,
    )

    assigned_reqs = [r for c in result.selected_assignments for r in c.request_ids]
    # Unique assigned requests
    assert len(assigned_reqs) == len(set(assigned_reqs))
    # Disjoint partition
    assert set(assigned_reqs).isdisjoint(set(result.unassigned_request_ids))
    # Exactly accounts for every unique input request ID
    assert set(assigned_reqs) | set(result.unassigned_request_ids) == {"req-dup", "req-unique"}


def test_adversarial_duplicate_input_vehicle_ids_in_dispatch() -> None:
    """
    Verifies vehicle validation and deduplication in dispatch_batch:
    1. Conflicting duplicate vehicle records must raise ValueError.
    2. Identical duplicate vehicle records must deduplicate cleanly without error.
    """
    engine = DispatchEngine(
        policy_provider=DefaultPolicyProvider(),
        routing_provider=MockRoutingProvider(),
        spatial_index=H3SpatialIndexAdapter(),
    )

    req = RideRequest(
        request_id="req-1",
        user_id="user-1",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7200, longitude=-74.0000),
        seat_count=1,
        earliest_pickup_time=1700000000,
        latest_dropoff_time=1700001800,
        direct_distance_meters=1500,
        direct_duration_seconds=200,
        status=RequestStatus.PENDING,
    )
    veh1_a = Vehicle(
        vehicle_id="veh-dup",
        driver_id="drv-1a",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=40.7125, longitude=-74.0055),
        is_active=True,
    )
    veh1_conflicting = Vehicle(
        vehicle_id="veh-dup",
        driver_id="drv-1b",  # Conflicting driver
        total_seat_capacity=6,  # Conflicting capacity
        current_location=GeoCoordinate(latitude=40.7126, longitude=-74.0056),
        is_active=True,
    )

    # 1. Conflicting duplicate vehicles must raise ValueError
    with pytest.raises(ValueError, match="Conflicting duplicate vehicle detected"):
        engine.dispatch_batch(
            requests=[req],
            vehicles=[veh1_a, veh1_conflicting],
            active_rides=[],
            current_time=1700000000,
        )

    # 2. Identical duplicate vehicles deduplicate cleanly
    veh1_identical = Vehicle(
        vehicle_id="veh-dup",
        driver_id="drv-1a",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=40.7125, longitude=-74.0055),
        is_active=True,
    )
    result = engine.dispatch_batch(
        requests=[req],
        vehicles=[veh1_a, veh1_identical],
        active_rides=[],
        current_time=1700000000,
    )

    assigned_vehs = [c.vehicle_id for c in result.selected_assignments]
    assert len(assigned_vehs) <= 1
    assert len(assigned_vehs) == len(set(assigned_vehs))


def test_deadline_expiry_immediately_before_solver() -> None:
    """
    Tests solver behavior when candidate generation or pre-solver check expires before solver starts.
    Verifies INCOMPLETE_DEADLINE_EXPIRED, is_approximated=True, 0 assignments, all unassigned.
    """
    all_requests = ["r1", "r2"]
    cand = CandidateAssignment(
        candidate_id="c1",
        vehicle_id="v1",
        existing_ride_id=None,
        request_ids=("r1",),
        ordered_stops=(_dummy_stop("s1", "r1"),),
        peak_seat_load=1,
        vmt_meters=1000,
        objective_value=0.5,
        normalized_score=0.8,
        score_breakdown=ScoreBreakdown(),
    )

    # Past deadline before solver starts
    past_deadline = time.monotonic() - 0.010
    result = solve_set_packing_regret_k(
        candidates=[cand],
        all_request_ids=all_requests,
        deadline=past_deadline,
        reserved_headroom=0.010,
    )

    assert result.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
    assert result.is_approximated is True
    assert len(result.selected_assignments) == 0
    assert result.unassigned_request_ids == ("r1", "r2")


def test_deadline_expiry_during_solver_preserves_conflict_free_partial_results() -> None:
    """
    Tests solver behavior when the monotonic deadline expires mid-solve.
    Verifies that:
    1. Loop terminates cleanly.
    2. Conflict-free partial assignments selected before interrupt are preserved.
    3. Status is reported as INCOMPLETE_DEADLINE_EXPIRED, is_approximated=True.
    4. Assigned + unassigned strictly partitions the request set.
    """
    all_requests = ["r1", "r2", "r3", "r4"]
    c1 = CandidateAssignment(
        candidate_id="c1",
        vehicle_id="v1",
        existing_ride_id=None,
        request_ids=("r1",),
        ordered_stops=(_dummy_stop("s1", "r1"),),
        peak_seat_load=1,
        vmt_meters=1000,
        objective_value=0.9,
        normalized_score=0.9,
        score_breakdown=ScoreBreakdown(),
    )
    c2 = CandidateAssignment(
        candidate_id="c2",
        vehicle_id="v2",
        existing_ride_id=None,
        request_ids=("r2",),
        ordered_stops=(_dummy_stop("s2", "r2"),),
        peak_seat_load=1,
        vmt_meters=1000,
        objective_value=0.8,
        normalized_score=0.8,
        score_breakdown=ScoreBreakdown(),
    )

    # Budget 30ms, headroom 15ms -> cutoff at 15ms
    start = time.monotonic()
    deadline = start + 0.030
    reserved_headroom = 0.015

    iteration_count = 0

    def slow_hook() -> None:
        nonlocal iteration_count
        iteration_count += 1
        # Commit on first iteration, sleep past cutoff on second iteration
        if iteration_count >= 2:
            time.sleep(0.025)

    result = solve_set_packing_regret_k(
        candidates=[c1, c2],
        all_request_ids=all_requests,
        deadline=deadline,
        reserved_headroom=reserved_headroom,
        iteration_hook=slow_hook,
    )

    assert result.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
    assert result.is_approximated is True
    # At least one candidate was selected before interrupt
    assert len(result.selected_assignments) >= 1
    assigned = [r for c in result.selected_assignments for r in c.request_ids]
    assert len(assigned) == len(set(assigned))
    assert set(assigned).isdisjoint(set(result.unassigned_request_ids))
    assert set(assigned) | set(result.unassigned_request_ids) == set(all_requests)


def test_unexpected_programming_error_raises_in_solver() -> None:
    """
    Verifies that unexpected programming errors during solver execution
    cannot be silently masked and presented as successful dispatches.
    If an unexpected exception occurs without deadline expiration, the solver must raise.
    """
    all_requests = ["r1", "r2", "r3"]
    c1 = CandidateAssignment(
        candidate_id="c1",
        vehicle_id="v1",
        existing_ride_id=None,
        request_ids=("r1",),
        ordered_stops=(_dummy_stop("s1", "r1"),),
        peak_seat_load=1,
        vmt_meters=1000,
        objective_value=0.9,
        normalized_score=0.9,
        score_breakdown=ScoreBreakdown(),
    )
    c2 = CandidateAssignment(
        candidate_id="c2",
        vehicle_id="v2",
        existing_ride_id=None,
        request_ids=("r2",),
        ordered_stops=(_dummy_stop("s2", "r2"),),
        peak_seat_load=1,
        vmt_meters=1000,
        objective_value=0.8,
        normalized_score=0.8,
        score_breakdown=ScoreBreakdown(),
    )

    call_count = 0

    def failing_hook() -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise RuntimeError("Unexpected internal solver defect on iteration 2")

    # With plenty of deadline headroom, the unexpected error must NOT be masked
    with pytest.raises(RuntimeError, match="Unexpected internal solver defect"):
        solve_set_packing_regret_k(
            candidates=[c1, c2],
            all_request_ids=all_requests,
            deadline=time.monotonic() + 5.0,
            iteration_hook=failing_hook,
        )


def test_deadline_timeout_fallback_validation_failure_discards_corrupt_assignments() -> None:
    """
    Verifies that when deadline expires, fallback assignments are strictly validated
    for vehicle uniqueness, request uniqueness, and membership in all_request_ids.
    If corrupted assignments exist, they are safely discarded and all requests remain unassigned.
    """
    all_requests = ["r1", "r2"]

    # Candidate c_bad has a request 'r_alien' not in all_requests
    c_bad = CandidateAssignment(
        candidate_id="c-bad",
        vehicle_id="v1",
        existing_ride_id=None,
        request_ids=("r_alien",),
        ordered_stops=(_dummy_stop("s-alien", "r_alien"),),
        peak_seat_load=1,
        vmt_meters=1000,
        objective_value=0.9,
        normalized_score=0.9,
        score_breakdown=ScoreBreakdown(),
    )

    # Calling solver with past deadline
    result = solve_set_packing_regret_k(
        candidates=[c_bad],
        all_request_ids=all_requests,
        deadline=time.monotonic() - 0.100,
    )

    assert result.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
    assert result.is_approximated is True
    assert len(result.selected_assignments) == 0
    assert result.unassigned_request_ids == ("r1", "r2")


def test_exact_solver_completeness_and_no_masked_errors() -> None:
    """
    Verifies that solve_exact_set_packing reports COMPLETE only when
    the search finishes successfully, and does not swallow unexpected errors.
    """
    all_requests = ["r1", "r2"]
    cand = CandidateAssignment(
        candidate_id="c1",
        vehicle_id="v1",
        existing_ride_id=None,
        request_ids=("r1",),
        ordered_stops=(_dummy_stop("s1", "r1"),),
        peak_seat_load=1,
        vmt_meters=1000,
        objective_value=0.8,
        normalized_score=0.8,
        score_breakdown=ScoreBreakdown(),
    )

    result = solve_exact_set_packing(
        candidates=[cand],
        all_request_ids=all_requests,
    )
    assert result.search_status == SearchStatus.COMPLETE
    assert result.is_approximated is False
    assert result.dispatch_mode == DispatchMode.EXACT
    assert len(result.selected_assignments) == 1
    assert result.unassigned_request_ids == ("r2",)
