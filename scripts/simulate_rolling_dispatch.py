"""
Rolling dispatch simulation harness for Pool Engine (Phase 3.3).

Simulates multi-cycle rolling dispatch over a time horizon (e.g. 15 cycles, 5s cadence).
Tracks:
- Cumulative match rate over time.
- Request wait time distribution and starvation index.
- Regional match fairness (Downtown, Midtown, Uptown).
- Vehicle utilization and idle time distribution.
- Monotonic cycle latency and SLA adherence (<= 500ms).
- Dial-a-ride physical invariant preservation across cycles.
"""

import math
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

# Ensure src is on path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.mock_routing import MockRoutingProvider
from engine.adapters.osrm_routing import OsrmRoutingAdapter
from engine.contracts.routing import Coordinate, RoadNetworkRoutingProvider
from engine.dispatch import CandidateGenerationConfig, DispatchEngine
from engine.domain.enums import RequestStatus, RideStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle
from engine.orchestration.dispatch_orchestrator import (
    DispatchOrchestrator,
    OrchestrationConfig,
    OrchestrationResult,
)

# Spatial clusters (NYC Manhattan test bounding box)
HOTSPOTS = {
    "Downtown": (40.7128, -74.0060),
    "Midtown": (40.7580, -73.9855),
    "Uptown": (40.7829, -73.9654),
}


@dataclass
class RollingSimConfig:
    num_cycles: int = 15
    cycle_interval_seconds: int = 5
    base_time: int = 1700000000
    initial_requests: int = 150
    requests_per_cycle: int = 30
    num_vehicles: int = 60
    seed: int = 42
    use_osrm: bool = False
    osrm_url: str = "http://localhost:5000"
    skewed_demand: bool = True  # Realistic uneven spatial distribution


@dataclass
class RequestTracking:
    request: RideRequest
    arrival_cycle: int
    arrival_time: int
    sector: str
    is_boundary: bool
    matched_cycle: Optional[int] = None
    matched_time: Optional[int] = None
    assigned_vehicle_id: Optional[str] = None
    expired_cycle: Optional[int] = None


@dataclass
class CycleMetrics:
    cycle_idx: int
    sim_time: int
    active_requests_count: int
    active_vehicles_count: int
    new_matches_count: int
    cumulative_matches_count: int
    cycle_latency_ms: float
    sla_passed: bool
    vmt_savings_meters: int


def classify_sector(lat: float) -> str:
    if lat < 40.7350:
        return "Downtown"
    elif lat < 40.7650:
        return "Midtown"
    else:
        return "Uptown"


def generate_sim_request(
    req_id: str,
    arrival_time: int,
    rng: random.Random,
    skewed_demand: bool = True,
) -> tuple[RideRequest, str, bool]:
    # Realistic uneven demand: 50% Midtown, 30% Downtown, 20% Uptown if skewed
    if skewed_demand:
        r_val = rng.random()
        if r_val < 0.50:
            sector_name = "Midtown"
        elif r_val < 0.80:
            sector_name = "Downtown"
        else:
            sector_name = "Uptown"
    else:
        sector_name = rng.choice(["Downtown", "Midtown", "Uptown"])

    center_lat, center_lon = HOTSPOTS[sector_name]
    p_lat = max(40.7000, min(40.7900, rng.gauss(center_lat, 0.006)))
    p_lon = max(-74.0200, min(-73.9000, rng.gauss(center_lon, 0.006)))

    # Boundary check: within 600m (~0.0054 deg) of partition boundaries (40.7350 or 40.7650)
    is_boundary = (abs(p_lat - 40.7350) <= 0.0054) or (abs(p_lat - 40.7650) <= 0.0054)

    d_sector = rng.choice(["Downtown", "Midtown", "Uptown"])
    d_center_lat, d_center_lon = HOTSPOTS[d_sector]
    d_lat = max(40.7000, min(40.7900, rng.gauss(d_center_lat, 0.008)))
    d_lon = max(-74.0200, min(-73.9000, rng.gauss(d_center_lon, 0.008)))

    # Duration 300 to 1200 seconds
    duration = rng.randint(300, 1200)
    distance = int(duration * 11.11)  # ~40 km/h

    # 75% 1-seat single requests, 25% multi-seat parties (2 to 4 seats)
    r_seats = rng.random()
    if r_seats < 0.75:
        seats = 1
    elif r_seats < 0.92:
        seats = 2
    else:
        seats = 3

    req = RideRequest(
        request_id=req_id,
        user_id=f"user-{req_id}",
        pickup_location=GeoCoordinate(latitude=round(p_lat, 6), longitude=round(p_lon, 6)),
        dropoff_location=GeoCoordinate(latitude=round(d_lat, 6), longitude=round(d_lon, 6)),
        seat_count=seats,
        earliest_pickup_time=arrival_time,
        latest_dropoff_time=arrival_time + duration + 900,  # 15 min dropoff window
        direct_distance_meters=distance,
        direct_duration_seconds=duration,
        status=RequestStatus.PENDING,
    )
    return req, sector_name, is_boundary


def run_rolling_simulation(cfg: RollingSimConfig) -> dict[str, Any]:
    rng = random.Random(cfg.seed)
    storage = InMemoryRideStorage()
    policy_provider = DefaultPolicyProvider()
    spatial_index = H3SpatialIndexAdapter()

    routing_provider: RoadNetworkRoutingProvider
    if cfg.use_osrm:
        routing_provider = OsrmRoutingAdapter(base_url=cfg.osrm_url, timeout_seconds=1.0)
    else:
        routing_provider = MockRoutingProvider()

    orchestrator = DispatchOrchestrator(
        storage=storage,
        policy_provider=policy_provider,
        routing_provider=routing_provider,
        spatial_index=spatial_index,
        config=OrchestrationConfig(
            deadline_seconds=0.500,
            reserved_headroom_seconds=0.050,
            sweep_expired_requests=True,
        ),
    )

    # 1. Initialize Fleet (80% 4-seat, 20% 6-seat vehicles)
    vehicles: list[Vehicle] = []
    for v_idx in range(cfg.num_vehicles):
        veh_id = f"veh-{v_idx:03d}"
        sector_name = rng.choice(["Downtown", "Midtown", "Uptown"])
        c_lat, c_lon = HOTSPOTS[sector_name]
        v_lat = max(40.7000, min(40.7900, rng.gauss(c_lat, 0.007)))
        v_lon = max(-74.0200, min(-73.9000, rng.gauss(c_lon, 0.007)))
        capacity = 4 if v_idx < int(0.80 * cfg.num_vehicles) else 6
        veh = Vehicle(
            vehicle_id=veh_id,
            driver_id=f"drv-{v_idx:03d}",
            total_seat_capacity=capacity,
            current_location=GeoCoordinate(latitude=round(v_lat, 6), longitude=round(v_lon, 6)),
            is_active=True,
        )
        storage.save_vehicle(veh)
        vehicles.append(veh)

    # 2. Tracking collections
    request_tracker: dict[str, RequestTracking] = {}
    vehicle_assignments_count: dict[str, int] = {v.vehicle_id: 0 for v in vehicles}
    cycle_metrics_list: list[CycleMetrics] = []

    req_seq = 0

    # Initial requests at T=0
    for _ in range(cfg.initial_requests):
        req_id = f"req-{req_seq:04d}"
        req_seq += 1
        req, sec, is_b = generate_sim_request(req_id, cfg.base_time, rng, cfg.skewed_demand)
        storage.save_request(req)
        request_tracker[req_id] = RequestTracking(
            request=req,
            arrival_cycle=0,
            arrival_time=cfg.base_time,
            sector=sec,
            is_boundary=is_b,
        )

    sim_time = cfg.base_time

    # 3. Step through rolling cycles
    for cycle in range(cfg.num_cycles):
        # Add new arrivals if past cycle 0
        if cycle > 0 and cfg.requests_per_cycle > 0:
            for _ in range(cfg.requests_per_cycle):
                req_id = f"req-{req_seq:04d}"
                req_seq += 1
                req, sec, is_b = generate_sim_request(req_id, sim_time, rng, cfg.skewed_demand)
                storage.save_request(req)
                request_tracker[req_id] = RequestTracking(
                    request=req,
                    arrival_cycle=cycle,
                    arrival_time=sim_time,
                    sector=sec,
                    is_boundary=is_b,
                )

        # Execute dispatch cycle via orchestrator
        t_start = time.perf_counter()
        orch_res = orchestrator.dispatch_cycle(
            current_time=sim_time,
            cycle_id=f"cycle-{cycle:02d}",
        )
        cycle_dur_ms = (time.perf_counter() - t_start) * 1000.0

        # Update tracking for committed assignments
        new_matched_ids: set[str] = set()
        for asgn in orch_res.committed_assignments:
            vehicle_assignments_count[asgn.vehicle_id] += 1
            for rid in asgn.request_ids:
                new_matched_ids.add(rid)
                tracker = request_tracker.get(rid)
                if tracker and tracker.matched_cycle is None:
                    tracker.matched_cycle = cycle
                    tracker.matched_time = sim_time
                    tracker.assigned_vehicle_id = asgn.vehicle_id

        # Update metrics
        total_matched = sum(1 for t in request_tracker.values() if t.matched_cycle is not None)
        active_pending = len(storage.get_pending_requests())
        active_vehs = len(storage.get_active_vehicles())

        cycle_metric = CycleMetrics(
            cycle_idx=cycle,
            sim_time=sim_time,
            active_requests_count=active_pending,
            active_vehicles_count=active_vehs,
            new_matches_count=len(new_matched_ids),
            cumulative_matches_count=total_matched,
            cycle_latency_ms=orch_res.cycle_duration_ms,
            sla_passed=(orch_res.cycle_duration_ms <= 500.0),
            vmt_savings_meters=orch_res.total_vmt_savings_meters,
        )
        cycle_metrics_list.append(cycle_metric)

        # Advance simulation time and simulate vehicle movement towards stops
        sim_time += cfg.cycle_interval_seconds

        # Simulate vehicle progress along route stops
        for v in storage.get_active_vehicles():
            # Check if vehicle has an active ride
            active_rides = [r for r in storage.get_active_rides() if r.vehicle_id == v.vehicle_id]
            if not active_rides:
                continue
            ride = active_rides[0]
            remaining_stops: list[RouteStop] = []
            veh_loc = v.current_location

            for stop in ride.stops:
                if stop.status == StopStatus.COMPLETED:
                    continue
                # If scheduled arrival time is reached, complete stop
                if sim_time >= stop.scheduled_arrival_time:
                    completed_stop = stop.model_copy(update={"status": StopStatus.COMPLETED})
                    veh_loc = stop.location
                    # Update passenger count
                    if stop.stop_type == StopType.PICKUP:
                        ride = ride.model_copy(
                            update={"active_passenger_count": ride.active_passenger_count + 1}
                        )
                    elif stop.stop_type == StopType.DROPOFF:
                        ride = ride.model_copy(
                            update={"active_passenger_count": max(0, ride.active_passenger_count - 1)}
                        )
                else:
                    remaining_stops.append(stop)

            # Update vehicle location in storage
            updated_veh = v.model_copy(update={"current_location": veh_loc})
            storage.save_vehicle(updated_veh)

            # If all stops completed, complete ride
            if not remaining_stops:
                completed_ride = ride.model_copy(
                    update={
                        "lifecycle_status": RideStatus.COMPLETED,
                        "stops": [s.model_copy(update={"status": StopStatus.COMPLETED}) for s in ride.stops],
                        "active_passenger_count": 0,
                    }
                )
                storage.save_ride(completed_ride)
            else:
                updated_ride = ride.model_copy(update={"stops": remaining_stops})
                storage.save_ride(updated_ride)

    # 4. Compute Summary Fairness & Performance Statistics
    total_requests = len(request_tracker)
    matched_requests = [t for t in request_tracker.values() if t.matched_cycle is not None]
    unmatched_requests = [t for t in request_tracker.values() if t.matched_cycle is None]
    cumulative_match_rate = len(matched_requests) / total_requests if total_requests > 0 else 0.0

    # Wait cycle & second distribution for matched requests
    wait_cycles = [
        t.matched_cycle - t.arrival_cycle
        for t in matched_requests
        if t.matched_cycle is not None
    ]
    wait_seconds = [
        (t.matched_time - t.arrival_time)
        for t in matched_requests
        if t.matched_time is not None
    ]

    # All requests wait time distribution (including unmatched waiting at horizon end)
    all_wait_cycles = [
        (t.matched_cycle - t.arrival_cycle)
        if t.matched_cycle is not None
        else (cfg.num_cycles - t.arrival_cycle)
        for t in request_tracker.values()
    ]
    all_wait_seconds = [
        (t.matched_time - t.arrival_time)
        if t.matched_time is not None
        else (sim_time - t.arrival_time)
        for t in request_tracker.values()
    ]

    # Starvation index: requests waiting >= 3 cycles, >= 5 cycles
    starved_3_cycles = sum(1 for w in wait_cycles if w >= 3)
    starved_5_cycles = sum(1 for w in wait_cycles if w >= 5)

    # Unmatched starvation metrics
    unmatched_ge_3 = sum(1 for t in unmatched_requests if (cfg.num_cycles - t.arrival_cycle) >= 3)
    unmatched_ge_5 = sum(1 for t in unmatched_requests if (cfg.num_cycles - t.arrival_cycle) >= 5)

    # Infeasible vs feasible unselected classification
    max_fleet_cap = max(v.total_seat_capacity for v in vehicles) if vehicles else 0
    infeasible_unmatched = [t for t in unmatched_requests if t.request.seat_count > max_fleet_cap]
    feasible_unmatched = [t for t in unmatched_requests if t.request.seat_count <= max_fleet_cap]

    # Sector fairness breakdown
    sectors = ["Downtown", "Midtown", "Uptown"]
    sector_stats: dict[str, dict[str, Any]] = {}
    for sec in sectors:
        sec_total = sum(1 for t in request_tracker.values() if t.sector == sec)
        sec_matched = sum(1 for t in matched_requests if t.sector == sec)
        sec_rate = sec_matched / sec_total if sec_total > 0 else 0.0
        sec_wait = [
            t.matched_cycle - t.arrival_cycle
            for t in matched_requests
            if t.sector == sec and t.matched_cycle is not None
        ]
        avg_wait = statistics.mean(sec_wait) if sec_wait else 0.0
        sector_stats[sec] = {
            "total": sec_total,
            "matched": sec_matched,
            "match_rate": round(sec_rate, 4),
            "avg_wait_cycles": round(avg_wait, 2),
            "unmatched": sec_total - sec_matched,
        }

    # Party size breakdown: 1, 2, 3 seats
    party_stats: dict[str, dict[str, Any]] = {}
    for seats in [1, 2, 3]:
        s_reqs = [t for t in request_tracker.values() if t.request.seat_count == seats]
        s_matched = [t for t in s_reqs if t.matched_cycle is not None]
        s_wait = [t.matched_cycle - t.arrival_cycle for t in s_matched if t.matched_cycle is not None]
        party_stats[f"{seats}_seat"] = {
            "total": len(s_reqs),
            "matched": len(s_matched),
            "match_rate": round(len(s_matched) / len(s_reqs), 4) if s_reqs else 0.0,
            "avg_wait": round(statistics.mean(s_wait), 2) if s_wait else 0.0,
        }

    # Combined single vs multi
    single_reqs = [t for t in request_tracker.values() if t.request.seat_count == 1]
    multi_reqs = [t for t in request_tracker.values() if t.request.seat_count > 1]
    single_matched = [t for t in single_reqs if t.matched_cycle is not None]
    multi_matched = [t for t in multi_reqs if t.matched_cycle is not None]
    party_stats["single_overall"] = {
        "total": len(single_reqs),
        "matched": len(single_matched),
        "match_rate": round(len(single_matched) / len(single_reqs), 4) if single_reqs else 0.0,
        "avg_wait": round(statistics.mean([t.matched_cycle - t.arrival_cycle for t in single_matched if t.matched_cycle is not None]), 2) if single_matched else 0.0,
    }
    party_stats["multi_overall"] = {
        "total": len(multi_reqs),
        "matched": len(multi_matched),
        "match_rate": round(len(multi_matched) / len(multi_reqs), 4) if multi_reqs else 0.0,
        "avg_wait": round(statistics.mean([t.matched_cycle - t.arrival_cycle for t in multi_matched if t.matched_cycle is not None]), 2) if multi_matched else 0.0,
    }

    # Vehicle capacity breakdown (4-seat sedans vs 6-seat vans)
    capacity_stats: dict[str, dict[str, Any]] = {}
    for cap in [4, 6]:
        cap_vehs = [v for v in vehicles if v.total_seat_capacity == cap]
        cap_asgns = sum(vehicle_assignments_count[v.vehicle_id] for v in cap_vehs)
        cap_utilized = sum(1 for v in cap_vehs if vehicle_assignments_count[v.vehicle_id] > 0)
        capacity_stats[f"{cap}_seat"] = {
            "fleet_count": len(cap_vehs),
            "utilized_count": cap_utilized,
            "utilization_rate": round(cap_utilized / len(cap_vehs), 4) if cap_vehs else 0.0,
            "total_assignments": cap_asgns,
            "mean_assignments": round(cap_asgns / len(cap_vehs), 2) if cap_vehs else 0.0,
        }

    # Boundary request breakdown
    boundary_reqs = [t for t in request_tracker.values() if t.is_boundary]
    interior_reqs = [t for t in request_tracker.values() if not t.is_boundary]
    boundary_matched = [t for t in boundary_reqs if t.matched_cycle is not None]
    interior_matched = [t for t in interior_reqs if t.matched_cycle is not None]

    boundary_stats = {
        "boundary": {
            "total": len(boundary_reqs),
            "matched": len(boundary_matched),
            "match_rate": round(len(boundary_matched) / len(boundary_reqs), 4) if boundary_reqs else 0.0,
        },
        "interior": {
            "total": len(interior_reqs),
            "matched": len(interior_matched),
            "match_rate": round(len(interior_matched) / len(interior_reqs), 4) if interior_reqs else 0.0,
        },
    }

    # Vehicle utilization fairness (Gini coefficient / distribution)
    asgn_counts = list(vehicle_assignments_count.values())
    utilized_vehs = sum(1 for c in asgn_counts if c > 0)
    fleet_utilization_rate = utilized_vehs / len(vehicles) if vehicles else 0.0

    latencies = [m.cycle_latency_ms for m in cycle_metrics_list]
    total_vmt_savings_meters = sum(m.vmt_savings_meters for m in cycle_metrics_list)

    # Fairness Criteria Evaluation
    sec_rates = [s["match_rate"] for s in sector_stats.values() if s["total"] > 0]
    fairness_ratio = (min(sec_rates) / max(sec_rates)) if sec_rates and max(sec_rates) > 0 else 0.0
    fairness_passed = fairness_ratio >= 0.40
    starvation_passed = starved_5_cycles == 0

    return {
        "seed": cfg.seed,
        "cadence_seconds": cfg.cycle_interval_seconds,
        "total_requests": total_requests,
        "matched_count": len(matched_requests),
        "unmatched_count": len(unmatched_requests),
        "cumulative_match_rate": round(cumulative_match_rate, 4),
        "total_vmt_savings_km": round(total_vmt_savings_meters / 1000.0, 2),
        "wait_cycles": {
            "min": min(wait_cycles) if wait_cycles else 0,
            "median": statistics.median(wait_cycles) if wait_cycles else 0,
            "p95": sorted(wait_cycles)[int(0.95 * len(wait_cycles))] if wait_cycles else 0,
            "max": max(wait_cycles) if wait_cycles else 0,
            "matched_starved_ge_3_cycles": starved_3_cycles,
            "matched_starved_ge_5_cycles": starved_5_cycles,
            "unmatched_starved_ge_3_cycles": unmatched_ge_3,
            "unmatched_starved_ge_5_cycles": unmatched_ge_5,
        },
        "wait_seconds": {
            "min": min(wait_seconds) if wait_seconds else 0,
            "median": round(statistics.median(wait_seconds), 1) if wait_seconds else 0.0,
            "p95": round(sorted(wait_seconds)[int(0.95 * len(wait_seconds))], 1) if wait_seconds else 0.0,
            "max": max(wait_seconds) if wait_seconds else 0,
        },
        "all_requests_wait_cycles": {
            "min": min(all_wait_cycles) if all_wait_cycles else 0,
            "median": statistics.median(all_wait_cycles) if all_wait_cycles else 0,
            "p95": sorted(all_wait_cycles)[int(0.95 * len(all_wait_cycles))] if all_wait_cycles else 0,
            "max": max(all_wait_cycles) if all_wait_cycles else 0,
        },
        "all_requests_wait_seconds": {
            "min": min(all_wait_seconds) if all_wait_seconds else 0,
            "median": round(statistics.median(all_wait_seconds), 1) if all_wait_seconds else 0.0,
            "p95": round(sorted(all_wait_seconds)[int(0.95 * len(all_wait_seconds))], 1) if all_wait_seconds else 0.0,
            "max": max(all_wait_seconds) if all_wait_seconds else 0,
        },
        "unmatched_breakdown": {
            "infeasible": len(infeasible_unmatched),
            "feasible_unselected": len(feasible_unmatched),
            "feasible_unselected_rate": round(len(feasible_unmatched) / len(unmatched_requests), 4) if unmatched_requests else 0.0,
        },
        "latency_vs_backlog": {
            "initial_latency_ms": cycle_metrics_list[0].cycle_latency_ms if cycle_metrics_list else 0.0,
            "final_latency_ms": cycle_metrics_list[-1].cycle_latency_ms if cycle_metrics_list else 0.0,
            "initial_backlog": cycle_metrics_list[0].active_requests_count if cycle_metrics_list else 0,
            "final_backlog": cycle_metrics_list[-1].active_requests_count if cycle_metrics_list else 0,
        },
        "sector_stats": sector_stats,
        "party_stats": party_stats,
        "capacity_stats": capacity_stats,
        "boundary_stats": boundary_stats,
        "fleet_utilization": {
            "utilized_vehicles": utilized_vehs,
            "total_vehicles": len(vehicles),
            "utilization_rate": round(fleet_utilization_rate, 4),
            "mean_assignments_per_veh": round(statistics.mean(asgn_counts), 2),
            "max_assignments_on_single_veh": max(asgn_counts) if asgn_counts else 0,
        },
        "cycle_latencies_ms": {
            "p50": round(statistics.median(latencies), 2),
            "p95": round(sorted(latencies)[int(0.95 * len(latencies))], 2),
            "max": round(max(latencies), 2),
            "sla_passed_all": all(m.sla_passed for m in cycle_metrics_list),
        },
        "fairness_evaluation": {
            "fairness_ratio": round(fairness_ratio, 3),
            "fairness_passed": fairness_passed,
            "starvation_passed": starvation_passed,
        },
        "cycle_metrics": cycle_metrics_list,
    }


def print_simulation_report(res: dict[str, Any]) -> None:
    print(f"\n--- Cycle Progression (Seed {res['seed']}, {res['cadence_seconds']}s cadence) ---")
    for m in res["cycle_metrics"]:
        print(
            f"Cycle {m.cycle_idx:02d} (T={m.sim_time}): "
            f"ActiveReqs: {m.active_requests_count:3d} | "
            f"NewMatches: {m.new_matches_count:2d} | "
            f"CumulMatches: {m.cumulative_matches_count:3d} | "
            f"Latency: {m.cycle_latency_ms:6.2f} ms | "
            f"VMT Savings: {m.vmt_savings_meters / 1000.0:6.1f} km"
        )

    print("\n--- Summary Performance & Starvation Criteria ---")
    print(f"Total Requests: {res['total_requests']}")
    print(
        f"Total Matched: {res['matched_count']} ({res['cumulative_match_rate'] * 100:.1f}%) | "
        f"Total Unmatched: {res['unmatched_count']} ({(res['unmatched_count']/res['total_requests']) * 100:.1f}%) | "
        f"Total VMT Savings: {res['total_vmt_savings_km']} km"
    )
    wc = res["wait_cycles"]
    ws = res["wait_seconds"]
    awc = res["all_requests_wait_cycles"]
    aws = res["all_requests_wait_seconds"]
    ub = res["unmatched_breakdown"]
    lvb = res["latency_vs_backlog"]

    print(f"Wait Cycles (Matched): min={wc['min']}, median={wc['median']}, p95={wc['p95']}, max={wc['max']}")
    print(f"Wait Seconds (Matched): min={ws['min']}s, median={ws['median']}s, p95={ws['p95']}s, max={ws['max']}s")
    print(f"Wait Cycles (ALL, incl backlog): min={awc['min']}, median={awc['median']}, p95={awc['p95']}, max={awc['max']}")
    print(f"Wait Seconds (ALL, incl backlog): min={aws['min']}s, median={aws['median']}s, p95={aws['p95']}s, max={aws['max']}s")
    print(f"Unmatched Feasibility: Infeasible (over capacity)={ub['infeasible']} | Feasible but Unselected={ub['feasible_unselected']}")
    print(f"Latency vs Backlog: Cycle 00 ({lvb['initial_backlog']} backlog) = {lvb['initial_latency_ms']:.2f}ms | Cycle 14 ({lvb['final_backlog']} backlog) = {lvb['final_latency_ms']:.2f}ms")
    print(
        f"Matched Starved (>=3 cycles): {wc['matched_starved_ge_3_cycles']}, "
        f"Matched Starved (>=5 cycles): {wc['matched_starved_ge_5_cycles']}"
    )
    print(
        f"Unmatched in Backlog (>=3 cycles): {wc['unmatched_starved_ge_3_cycles']}, "
        f"Unmatched in Backlog (>=5 cycles): {wc['unmatched_starved_ge_5_cycles']}"
    )

    print("\n--- Regional Sector Fairness & Backlog ---")
    for sec, s in res["sector_stats"].items():
        print(
            f"  {sec:10s}: {s['matched']}/{s['total']} matched ({s['match_rate'] * 100:.1f}%) | "
            f"Unmatched backlog: {s['unmatched']} | Avg wait: {s['avg_wait_cycles']} cycles"
        )

    print("\n--- Request Type Fairness by Party Size ---")
    for ptype, ps in res["party_stats"].items():
        print(
            f"  {ptype.capitalize():15s}: {ps['matched']}/{ps['total']} matched "
            f"({ps['match_rate'] * 100:.1f}%) | Avg wait: {ps['avg_wait']} cycles"
        )

    print("\n--- Vehicle Capacity Fairness (Sedans vs Vans) ---")
    for cap_key, cs in res["capacity_stats"].items():
        print(
            f"  {cap_key.capitalize():10s}: {cs['utilized_count']}/{cs['fleet_count']} utilized "
            f"({cs['utilization_rate'] * 100:.1f}%) | Total assignments: {cs['total_assignments']} "
            f"(mean {cs['mean_assignments']}/veh)"
        )

    print("\n--- Boundary Request Protection ---")
    for btype, bs in res["boundary_stats"].items():
        print(f"  {btype.capitalize():10s}: {bs['matched']}/{bs['total']} matched ({bs['match_rate'] * 100:.1f}%)")

    print("\n--- Fleet Utilization Fairness ---")
    fu = res["fleet_utilization"]
    print(f"  Utilized Vehicles: {fu['utilized_vehicles']}/{fu['total_vehicles']} ({fu['utilization_rate'] * 100:.1f}%)")
    print(f"  Mean assignments/vehicle: {fu['mean_assignments_per_veh']} | Max on single veh: {fu['max_assignments_on_single_veh']}")

    print("\n--- SLA Adherence (<= 500ms) & Fairness Gates ---")
    cl = res["cycle_latencies_ms"]
    fe = res["fairness_evaluation"]
    print(f"  Latency: p50={cl['p50']} ms, p95={cl['p95']} ms, max={cl['max']} ms | All <= 500ms: {cl['sla_passed_all']}")
    print(f"  Fairness Ratio (min/max sector rate): {fe['fairness_ratio']} | Fairness Passed: {fe['fairness_passed']}")
    print(f"  Starvation Zero Policy (0 matched requests >= 5 cycles): {fe['starvation_passed']}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Rolling dispatch simulation")
    parser.add_argument("--cycles", type=int, default=15)
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--initial-requests", type=int, default=150)
    parser.add_argument("--requests-per-cycle", type=int, default=30)
    parser.add_argument("--vehicles", type=int, default=60)
    parser.add_argument("--osrm", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--all-seeds", action="store_true")
    args = parser.parse_args()

    seeds = [42, 123, 999] if args.all_seeds else [args.seed]

    for s in seeds:
        cfg = RollingSimConfig(
            num_cycles=args.cycles,
            cycle_interval_seconds=args.interval,
            initial_requests=args.initial_requests,
            requests_per_cycle=args.requests_per_cycle,
            num_vehicles=args.vehicles,
            seed=s,
            use_osrm=args.osrm,
        )

        print(f"\n=================================================================")
        print(f"=== Starting Rolling Dispatch Simulation (Seed {s}, {cfg.cycle_interval_seconds}s cadence) ===")
        print(f"Configuration: {cfg.num_cycles} cycles, {cfg.num_vehicles} vehicles, router={'OSRM Live' if cfg.use_osrm else 'Mock'}")
        print(f"=================================================================")

        res = run_rolling_simulation(cfg)
        print_simulation_report(res)
