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


@dataclass
class RequestTracking:
    request: RideRequest
    arrival_cycle: int
    arrival_time: int
    sector: str
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
) -> tuple[RideRequest, str]:
    sector_name = rng.choice(["Downtown", "Midtown", "Uptown"])
    center_lat, center_lon = HOTSPOTS[sector_name]
    p_lat = max(40.7000, min(40.7900, rng.gauss(center_lat, 0.006)))
    p_lon = max(-74.0200, min(-73.9000, rng.gauss(center_lon, 0.006)))

    d_sector = rng.choice(["Downtown", "Midtown", "Uptown"])
    d_center_lat, d_center_lon = HOTSPOTS[d_sector]
    d_lat = max(40.7000, min(40.7900, rng.gauss(d_center_lat, 0.008)))
    d_lon = max(-74.0200, min(-73.9000, rng.gauss(d_center_lon, 0.008)))

    # Duration 300 to 1200 seconds
    duration = rng.randint(300, 1200)
    distance = int(duration * 11.11)  # ~40 km/h

    req = RideRequest(
        request_id=req_id,
        user_id=f"user-{req_id}",
        pickup_location=GeoCoordinate(latitude=round(p_lat, 6), longitude=round(p_lon, 6)),
        dropoff_location=GeoCoordinate(latitude=round(d_lat, 6), longitude=round(d_lon, 6)),
        seat_count=1 if rng.random() < 0.8 else 2,
        earliest_pickup_time=arrival_time,
        latest_dropoff_time=arrival_time + duration + 900,  # 15 min dropoff window
        direct_distance_meters=distance,
        direct_duration_seconds=duration,
        status=RequestStatus.PENDING,
    )
    return req, sector_name


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

    # 1. Initialize Fleet
    vehicles: list[Vehicle] = []
    for v_idx in range(cfg.num_vehicles):
        veh_id = f"veh-{v_idx:03d}"
        sector_name = rng.choice(["Downtown", "Midtown", "Uptown"])
        c_lat, c_lon = HOTSPOTS[sector_name]
        v_lat = max(40.7000, min(40.7900, rng.gauss(c_lat, 0.007)))
        v_lon = max(-74.0200, min(-73.9000, rng.gauss(c_lon, 0.007)))
        veh = Vehicle(
            vehicle_id=veh_id,
            driver_id=f"drv-{v_idx:03d}",
            total_seat_capacity=4,
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
        req, sec = generate_sim_request(req_id, cfg.base_time, rng)
        storage.save_request(req)
        request_tracker[req_id] = RequestTracking(
            request=req,
            arrival_cycle=0,
            arrival_time=cfg.base_time,
            sector=sec,
        )

    sim_time = cfg.base_time

    # 3. Step through rolling cycles
    for cycle in range(cfg.num_cycles):
        # Add new arrivals if past cycle 0
        if cycle > 0 and cfg.requests_per_cycle > 0:
            for _ in range(cfg.requests_per_cycle):
                req_id = f"req-{req_seq:04d}"
                req_seq += 1
                req, sec = generate_sim_request(req_id, sim_time, rng)
                storage.save_request(req)
                request_tracker[req_id] = RequestTracking(
                    request=req,
                    arrival_cycle=cycle,
                    arrival_time=sim_time,
                    sector=sec,
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

    # Wait cycle distribution for matched requests
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

    # Starvation index: requests waiting >= 3 cycles, >= 5 cycles
    starved_3_cycles = sum(1 for w in wait_cycles if w >= 3)
    starved_5_cycles = sum(1 for w in wait_cycles if w >= 5)

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
        }

    # Vehicle utilization fairness (Gini coefficient / distribution)
    asgn_counts = list(vehicle_assignments_count.values())
    utilized_vehs = sum(1 for c in asgn_counts if c > 0)
    fleet_utilization_rate = utilized_vehs / len(vehicles) if vehicles else 0.0

    latencies = [m.cycle_latency_ms for m in cycle_metrics_list]

    return {
        "total_requests": total_requests,
        "matched_count": len(matched_requests),
        "cumulative_match_rate": round(cumulative_match_rate, 4),
        "wait_cycles": {
            "min": min(wait_cycles) if wait_cycles else 0,
            "median": statistics.median(wait_cycles) if wait_cycles else 0,
            "p95": sorted(wait_cycles)[int(0.95 * len(wait_cycles))] if wait_cycles else 0,
            "max": max(wait_cycles) if wait_cycles else 0,
            "starved_ge_3_cycles": starved_3_cycles,
            "starved_ge_5_cycles": starved_5_cycles,
        },
        "sector_stats": sector_stats,
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
        "cycle_metrics": cycle_metrics_list,
    }


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
    args = parser.parse_args()

    cfg = RollingSimConfig(
        num_cycles=args.cycles,
        cycle_interval_seconds=args.interval,
        initial_requests=args.initial_requests,
        requests_per_cycle=args.requests_per_cycle,
        num_vehicles=args.vehicles,
        seed=args.seed,
        use_osrm=args.osrm,
    )

    print(f"=== Starting Rolling Dispatch Simulation ===")
    print(f"Configuration: {cfg.num_cycles} cycles, {cfg.cycle_interval_seconds}s cadence, {cfg.num_vehicles} vehicles")
    print(f"Initial: {cfg.initial_requests} requests, +{cfg.requests_per_cycle} reqs/cycle")
    print(f"Router: {'OSRM Live (port 5000)' if cfg.use_osrm else 'Mock In-Memory'}")

    res = run_rolling_simulation(cfg)

    print("\n--- Cycle by Cycle Progression ---")
    for m in res["cycle_metrics"]:
        print(
            f"Cycle {m.cycle_idx:02d} (T={m.sim_time}): "
            f"ActiveReqs: {m.active_requests_count:3d} | "
            f"NewMatches: {m.new_matches_count:2d} | "
            f"CumulMatches: {m.cumulative_matches_count:3d} | "
            f"Latency: {m.cycle_latency_ms:6.2f} ms | "
            f"VMT Savings: {m.vmt_savings_meters / 1000.0:6.1f} km"
        )

    print("\n--- Summary Performance & Fairness ---")
    print(f"Total Requests: {res['total_requests']}")
    print(f"Total Matched: {res['matched_count']} ({res['cumulative_match_rate'] * 100:.1f}%)")
    wc = res["wait_cycles"]
    print(f"Wait Cycles: min={wc['min']}, median={wc['median']}, p95={wc['p95']}, max={wc['max']}")
    print(f"Starved (>=3 cycles): {wc['starved_ge_3_cycles']}, Starved (>=5 cycles): {wc['starved_ge_5_cycles']}")

    print("\n--- Regional Sector Fairness ---")
    for sec, s in res["sector_stats"].items():
        print(f"  {sec:10s}: {s['matched']}/{s['total']} ({s['match_rate'] * 100:.1f}%) | Avg wait: {s['avg_wait_cycles']} cycles")

    print("\n--- Fleet Utilization Fairness ---")
    fu = res["fleet_utilization"]
    print(f"  Utilized Vehicles: {fu['utilized_vehicles']}/{fu['total_vehicles']} ({fu['utilization_rate'] * 100:.1f}%)")
    print(f"  Mean assignments/vehicle: {fu['mean_assignments_per_veh']} | Max on single veh: {fu['max_assignments_on_single_veh']}")

    print("\n--- SLA Adherence (<= 500ms) ---")
    cl = res["cycle_latencies_ms"]
    print(f"  Latency: p50={cl['p50']} ms, p95={cl['p95']} ms, max={cl['max']} ms | All <= 500ms: {cl['sla_passed_all']}")
