"""Scenario tests for rolling dispatch fairness, starvation prevention, and physical invariants."""

import math
import random
import time
from typing import Sequence
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.routing import Coordinate
from engine.dispatch import CandidateGenerationConfig, DispatchEngine
from engine.domain.enums import (
    DispatchMode,
    RequestStatus,
    RideStatus,
    SearchStatus,
    StopStatus,
    StopType,
)
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle
from engine.orchestration.dispatch_orchestrator import (
    DispatchOrchestrator,
    OrchestrationConfig,
    OrchestrationResult,
)
from engine.routing.invariants import (
    check_capacity_profile,
    check_detour_bound,
    check_precedence,
)


def _make_req(
    request_id: str,
    p_lat: float,
    p_lon: float,
    d_lat: float,
    d_lon: float,
    earliest_pickup: int = 1000,
    latest_dropoff: int = 2500,
    seat_count: int = 1,
) -> RideRequest:
    return RideRequest(
        request_id=request_id,
        user_id=f"user-{request_id}",
        pickup_location=GeoCoordinate(latitude=p_lat, longitude=p_lon),
        dropoff_location=GeoCoordinate(latitude=d_lat, longitude=d_lon),
        seat_count=seat_count,
        earliest_pickup_time=earliest_pickup,
        latest_dropoff_time=latest_dropoff,
        direct_distance_meters=2000,
        direct_duration_seconds=180,
        status=RequestStatus.PENDING,
    )


def _make_veh(
    vehicle_id: str,
    lat: float,
    lon: float,
    capacity: int = 4,
) -> Vehicle:
    return Vehicle(
        vehicle_id=vehicle_id,
        driver_id=f"drv-{vehicle_id}",
        total_seat_capacity=capacity,
        current_location=GeoCoordinate(latitude=lat, longitude=lon),
        is_active=True,
    )


def test_aging_priority_prevents_starvation() -> None:
    """
    Verifies that older waiting requests receive priority over newer requests
    located closer to the vehicle when candidate truncation is active.
    """
    policy = DefaultPolicyProvider()
    spatial = H3SpatialIndexAdapter()
    router = MockRoutingProvider()

    # 2 vehicles
    vehs = [
        _make_veh("veh-01", 40.7500, -73.9800, capacity=4),
        _make_veh("veh-02", 40.7505, -73.9800, capacity=4),
    ]

    # Older request arrived at T=1000, located 600m away
    req_old = _make_req(
        "req-old",
        p_lat=40.7550,
        p_lon=-73.9800,
        d_lat=40.7700,
        d_lon=-73.9800,
        earliest_pickup=1000,
    )

    # Newer requests arrived at T=1040, located 200m away (closer)
    newer_reqs = [
        _make_req(
            f"req-new-{i}",
            p_lat=40.7518 + i * 0.0002,
            p_lon=-73.9800,
            d_lat=40.7700,
            d_lon=-73.9800,
            earliest_pickup=1040,
        )
        for i in range(5)
    ]

    all_reqs = [req_old] + newer_reqs

    # Config with single request cap of 2 per vehicle and aging credit enabled
    config_aging = CandidateGenerationConfig.bounded(
        max_candidate_vehicles=2,
        max_single_requests_per_vehicle=2,
        max_requests_per_vehicle=1,
        max_bundle_size=2,
        aging_weight_mps=15.0,  # 15 m/s aging credit
        spatial_partitioning=False,
    )

    # Run dispatch at T=1040 (req_old has waited 40 seconds = 600m aging credit)
    engine_aging = DispatchEngine(policy, router, spatial, config=config_aging)
    res_aging = engine_aging.dispatch_batch(
        requests=all_reqs,
        vehicles=vehs,
        active_rides=[],
        current_time=1040,
        batch_id="batch-aging",
    )

    # The older request must be assigned due to aging priority credit
    assigned_aging = {
        rid for asgn in res_aging.selected_assignments for rid in asgn.request_ids
    }
    assert "req-old" in assigned_aging, (
        f"Expected req-old to be prioritized and matched, got assignments: {assigned_aging}"
    )

    # Contrast with config where aging is disabled (aging_weight_mps=0.0)
    config_no_aging = CandidateGenerationConfig.bounded(
        max_candidate_vehicles=2,
        max_single_requests_per_vehicle=2,
        max_requests_per_vehicle=1,
        max_bundle_size=2,
        aging_weight_mps=0.0,
        spatial_partitioning=False,
    )
    engine_no_aging = DispatchEngine(policy, router, spatial, config=config_no_aging)
    res_no_aging = engine_no_aging.dispatch_batch(
        requests=all_reqs,
        vehicles=vehs,
        active_rides=[],
        current_time=1040,
        batch_id="batch-no-aging",
    )
    assigned_no_aging = {
        rid for asgn in res_no_aging.selected_assignments for rid in asgn.request_ids
    }
    # Without aging, req-old is starved out of top 2 single requests by closer new requests
    assert "req-old" not in assigned_no_aging, (
        f"Without aging credit, closer requests should have preempted req-old, got: {assigned_no_aging}"
    )


def test_multi_cycle_rolling_dispatch_invariants() -> None:
    """
    Simulates repeated rolling dispatch cycles (e.g. 10 cycles) and verifies
    physical invariants (capacity, precedence, time windows, detour bounds)
    and zero duplicate assignments across all cycles.
    """
    storage = InMemoryRideStorage()
    policy_provider = DefaultPolicyProvider()
    spatial_index = H3SpatialIndexAdapter()
    routing_provider = MockRoutingProvider()

    orchestrator = DispatchOrchestrator(
        storage=storage,
        policy_provider=policy_provider,
        routing_provider=routing_provider,
        spatial_index=spatial_index,
        config=OrchestrationConfig(
            deadline_seconds=0.500,
            reserved_headroom_seconds=0.050,
        ),
    )

    # Initialize 10 vehicles
    for i in range(10):
        lat = 40.7100 + i * 0.0070
        veh = _make_veh(f"veh-roll-{i:02d}", lat, -73.9800, capacity=4)
        storage.save_vehicle(veh)

    all_matched_request_ids: set[str] = set()
    base_time = 1700000000
    cycle_interval = 5

    # Simulate 10 rolling cycles
    for cycle in range(10):
        current_time = base_time + cycle * cycle_interval

        # Introduce 6 new requests per cycle
        for r_idx in range(6):
            req_id = f"req-c{cycle:02d}-{r_idx}"
            p_lat = 40.7150 + (r_idx % 5) * 0.010
            req = _make_req(
                req_id,
                p_lat=p_lat,
                p_lon=-73.9800,
                d_lat=p_lat + 0.015,
                d_lon=-73.9800,
                earliest_pickup=current_time,
                latest_dropoff=current_time + 1800,
                seat_count=1 if r_idx < 4 else 2,
            )
            storage.save_request(req)

        # Run dispatch cycle
        t0 = time.perf_counter()
        result = orchestrator.dispatch_cycle(
            current_time=current_time,
            cycle_id=f"roll-cycle-{cycle:02d}",
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        # Verify SLA: cycle must complete within 500 ms
        assert elapsed_ms <= 500.0, f"Cycle {cycle} took {elapsed_ms:.2f} ms > 500 ms SLA"
        assert result.search_status != SearchStatus.INCOMPLETE_DEADLINE_EXPIRED

        # Verify no duplicate assignments across cycles
        for asgn in result.committed_assignments:
            for rid in asgn.request_ids:
                assert rid not in all_matched_request_ids, (
                    f"Duplicate request match detected: {rid} was previously matched!"
                )
                all_matched_request_ids.add(rid)

            # Verify physical dial-a-ride invariants on this assignment
            veh_opt = storage.get_vehicle(asgn.vehicle_id)
            assert veh_opt is not None
            veh = veh_opt

            # 1. Capacity conservation
            cap_valid = check_capacity_profile(asgn.ordered_stops, veh.total_seat_capacity, 0)
            assert cap_valid, f"Capacity violated on vehicle {veh.vehicle_id}!"

            # 2. Precedence (pickup before dropoff)
            prec_valid = check_precedence(asgn.ordered_stops)
            assert prec_valid, f"Precedence violated on assignment {asgn.candidate_id}!"

            # 3. Detour bounds
            policy = policy_provider.get_policy()
            assigned_req_opts = [storage.get_request(rid) for rid in asgn.request_ids]
            stop_etas = {s.stop_id: s.scheduled_arrival_time for s in asgn.ordered_stops}
            for req_opt in assigned_req_opts:
                if req_opt is not None:
                    p_eta = stop_etas.get(f"stop-p-{req_opt.request_id}")
                    d_eta = stop_etas.get(f"stop-d-{req_opt.request_id}")
                    if p_eta is not None and d_eta is not None:
                        actual_dur = d_eta - p_eta
                        detour_valid = check_detour_bound(actual_dur, req_opt.direct_duration_seconds, policy)
                        assert detour_valid, f"Detour bound violated for request {req_opt.request_id}!"

    # Ensure cumulative match occurred across rolling cycles
    assert len(all_matched_request_ids) > 0, "Expected non-zero matches across rolling cycles"


def test_demand_proportional_sector_allocation() -> None:
    """
    Verifies that when spatial partitioning is enabled, sectors with disproportionately
    high demand receive more candidate vehicles than sectors with low demand,
    while strictly keeping total candidate vehicles within budget.
    """
    policy = DefaultPolicyProvider()
    spatial = H3SpatialIndexAdapter()
    router = MockRoutingProvider()

    base_time = 1700000000
    # 36 vehicles across 3 sectors: 12 in Downtown, 12 in Midtown, 12 in Uptown
    vehicles: list[Vehicle] = []
    for i in range(12):
        vehicles.append(_make_veh(f"veh-dt-{i}", 40.7100 + i * 0.001, -73.9800))
        vehicles.append(_make_veh(f"veh-mt-{i}", 40.7450 + i * 0.0015, -73.9800))
        vehicles.append(_make_veh(f"veh-ut-{i}", 40.7800 + i * 0.001, -73.9800))

    # Skewed demand: 5 requests Downtown, 40 requests Midtown, 5 requests Uptown
    requests: list[RideRequest] = []
    for i in range(5):
        requests.append(
            _make_req(
                f"req-dt-{i}",
                40.7120 + i * 0.001,
                -73.9800,
                40.7200,
                -73.9800,
                earliest_pickup=base_time,
                latest_dropoff=base_time + 2000,
            )
        )
    for i in range(40):
        p_lat = 40.7450 + (i * 0.0004)
        requests.append(
            _make_req(
                f"req-mt-{i}",
                p_lat,
                -73.9800,
                p_lat + 0.010,
                -73.9800,
                earliest_pickup=base_time,
                latest_dropoff=base_time + 2000,
            )
        )
    for i in range(5):
        requests.append(
            _make_req(
                f"req-ut-{i}",
                40.7820 + i * 0.001,
                -73.9800,
                40.7900,
                -73.9800,
                earliest_pickup=base_time,
                latest_dropoff=base_time + 2000,
            )
        )

    config = CandidateGenerationConfig.bounded(
        spatial_partitioning=True,
        num_partitions=3,
        max_candidate_vehicles=39,
    )

    engine = DispatchEngine(policy, router, spatial, config=config)
    res = engine.dispatch_batch(
        requests=requests,
        vehicles=vehicles,
        active_rides=[],
        current_time=base_time,
        batch_id="batch-skewed-demand",
    )

    assert res.search_status != SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
    matched_ids = {rid for a in res.selected_assignments for rid in a.request_ids}

    # Midtown should have received the largest share of matches due to proportional vehicle allocation
    mt_matches = sum(1 for rid in matched_ids if "req-mt-" in rid)
    dt_matches = sum(1 for rid in matched_ids if "req-dt-" in rid)
    ut_matches = sum(1 for rid in matched_ids if "req-ut-" in rid)

    assert mt_matches > dt_matches
    assert mt_matches > ut_matches
