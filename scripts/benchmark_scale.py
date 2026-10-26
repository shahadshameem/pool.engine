"""
Scale Validation Benchmark for Pool Engine (Phase 3.5).

Benchmarks dispatch optimization across progressively larger workloads:
- Peak: 150 requests / 60 vehicles
- XLarge: 300 requests / 100 vehicles
- XXLarge: 500 requests / 150 vehicles
- Target: 1,000 requests / 200 vehicles

Measures p50, p95, p99, and max latency, deadline expirations, candidate counts,
routing provider calls, memory delta, and match counts under cold and warm cache.
"""

import argparse
import gc
import json
import os
import random
import statistics
import sys
import time
import tracemalloc
from dataclasses import asdict, dataclass
from typing import Any, Sequence

# Ensure src is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.mock_routing import MockRoutingProvider
from engine.adapters.osrm_routing import OsrmRoutingAdapter
from engine.contracts.routing import Coordinate, RoadNetworkRoutingProvider
from engine.dispatch import (
    CandidateGenerationConfig,
    DispatchEngine,
)
from engine.domain.enums import DispatchMode, RequestStatus, SearchStatus
from engine.domain.models import GeoCoordinate, MatchResult, RideRequest, Vehicle
from engine.service.app import create_app
from engine.service.client import AsgiTestClient

HOTSPOTS = {
    "Downtown": (40.7128, -74.0060),
    "Midtown": (40.7580, -73.9855),
    "Uptown": (40.7829, -73.9654),
}


@dataclass
class WorkloadSpec:
    name: str
    num_requests: int
    num_vehicles: int


WORKLOADS: list[WorkloadSpec] = [
    WorkloadSpec("Peak", 150, 60),
    WorkloadSpec("XLarge", 300, 100),
    WorkloadSpec("XXLarge", 500, 150),
    WorkloadSpec("Target", 1000, 200),
]


def generate_scale_entities(
    spec: WorkloadSpec,
    seed: int,
    base_time: int = 1700000000,
) -> tuple[list[RideRequest], list[Vehicle]]:
    rng = random.Random(seed)

    # 1. Vehicles
    vehicles: list[Vehicle] = []
    for v_idx in range(spec.num_vehicles):
        veh_id = f"veh-{v_idx:04d}"
        sec = rng.choice(["Downtown", "Midtown", "Uptown"])
        c_lat, c_lon = HOTSPOTS[sec]
        v_lat = max(40.7000, min(40.7900, rng.gauss(c_lat, 0.007)))
        v_lon = max(-74.0200, min(-73.9000, rng.gauss(c_lon, 0.007)))
        cap = 4 if v_idx < int(0.80 * spec.num_vehicles) else 6
        veh = Vehicle(
            vehicle_id=veh_id,
            driver_id=f"drv-{v_idx:04d}",
            total_seat_capacity=cap,
            current_location=GeoCoordinate(latitude=round(v_lat, 6), longitude=round(v_lon, 6)),
            is_active=True,
        )
        vehicles.append(veh)

    # 2. Requests (skewed: 50% Midtown, 30% Downtown, 20% Uptown)
    requests: list[RideRequest] = []
    for r_idx in range(spec.num_requests):
        req_id = f"req-{r_idx:04d}"
        r_val = rng.random()
        if r_val < 0.50:
            sec = "Midtown"
        elif r_val < 0.80:
            sec = "Downtown"
        else:
            sec = "Uptown"
        c_lat, c_lon = HOTSPOTS[sec]
        p_lat = max(40.7000, min(40.7900, rng.gauss(c_lat, 0.006)))
        p_lon = max(-74.0200, min(-73.9000, rng.gauss(c_lon, 0.006)))

        d_sec = rng.choice(["Downtown", "Midtown", "Uptown"])
        d_lat_c, d_lon_c = HOTSPOTS[d_sec]
        d_lat = max(40.7000, min(40.7900, rng.gauss(d_lat_c, 0.008)))
        d_lon = max(-74.0200, min(-73.9000, rng.gauss(d_lon_c, 0.008)))

        duration = rng.randint(300, 1200)
        distance = int(duration * 11.11)

        r_seats = rng.random()
        seats = 1 if r_seats < 0.75 else (2 if r_seats < 0.92 else 3)

        req = RideRequest(
            request_id=req_id,
            user_id=f"user-{req_id}",
            pickup_location=GeoCoordinate(latitude=round(p_lat, 6), longitude=round(p_lon, 6)),
            dropoff_location=GeoCoordinate(latitude=round(d_lat, 6), longitude=round(d_lon, 6)),
            seat_count=seats,
            earliest_pickup_time=base_time,
            latest_dropoff_time=base_time + duration + 900,
            direct_distance_meters=distance,
            direct_duration_seconds=duration,
            status=RequestStatus.PENDING,
        )
        requests.append(req)

    return requests, vehicles


def measure_workload_memory_mb(
    engine: DispatchEngine,
    router: RoadNetworkRoutingProvider,
    requests: list[RideRequest],
    vehicles: list[Vehicle],
) -> float:
    """Measure peak heap memory allocation delta for the full workload.

    Scope: Python heap allocations tracked by tracemalloc during dispatch_batch.
    Excludes external background daemon memory (OSRM C++ server, PostgreSQL daemon).
    Executed in a dedicated standalone pass to eliminate tracemalloc bytecode
    hook overhead from latency measurements.
    """
    gc.collect()
    tracemalloc.start()
    mem_start = tracemalloc.get_traced_memory()[0]
    _ = engine.dispatch_batch(requests, vehicles, [], 1700000000, deadline=time.monotonic() + 5.0)
    _, mem_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return round((mem_peak - mem_start) / (1024.0 * 1024.0), 2)


def benchmark_single_run(
    engine: DispatchEngine,
    router: RoadNetworkRoutingProvider,
    requests: list[RideRequest],
    vehicles: list[Vehicle],
    cache_state: str,
    deadline_ms: float = 500.0,
) -> dict[str, Any]:
    # Cache management
    if hasattr(router, "clear_cache") and cache_state == "cold":
        router.clear_cache()

    gc.collect()

    t_start = time.perf_counter()
    t_mono_start = time.monotonic()
    res = engine.dispatch_batch(
        requests=requests,
        vehicles=vehicles,
        active_rides=[],
        current_time=1700000000,
        deadline=t_mono_start + (deadline_ms / 1000.0),
    )
    t_end = time.perf_counter()
    dur_ms = (t_end - t_start) * 1000.0

    matched_reqs_count = sum(len(a.request_ids) for a in res.selected_assignments)
    deadline_expired = (
        res.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
        or dur_ms > deadline_ms
    )

    routing_calls = getattr(router, "routing_calls_count", 0)

    return {
        "duration_ms": round(dur_ms, 2),
        "solve_duration_ms": res.solve_duration_ms,
        "search_status": res.search_status.value,
        "is_approximated": res.is_approximated,
        "deadline_expired": deadline_expired,
        "matched_count": matched_reqs_count,
        "total_requests": len(requests),
        "match_rate": round(matched_reqs_count / len(requests), 4) if requests else 0.0,
        "vmt_savings_km": round(res.total_vmt_savings_meters / 1000.0, 2),
        "assignments_count": len(res.selected_assignments),
        "memory_peak_mb": 0.0,
        "routing_calls": routing_calls,
    }


def run_scale_benchmarks(
    osrm_url: str = "http://localhost:5000",
    use_osrm: bool = True,
    seeds: Sequence[int] = (42, 123, 999),
    trials_per_seed: int = 3,
    workloads: Sequence[WorkloadSpec] | None = None,
) -> dict[str, Any]:
    active_workloads = workloads or WORKLOADS

    results: dict[str, Any] = {
        "meta": {
            "python_version": sys.version.split()[0],
            "os": os.name,
            "router": "OSRM Live" if use_osrm else "MockRouter",
            "osrm_url": osrm_url if use_osrm else "N/A",
            "sla_ms": 500.0,
            "seeds": list(seeds),
            "trials_per_seed": trials_per_seed,
            "total_trials_per_condition": len(seeds) * trials_per_seed,
            "sample_size_note": (
                "For N=9 trials per condition, p95 and p99 sample indices evaluate to the 9th "
                "sample (sample maximum). Reliable production p99 certification requires N >= 100 trials."
            ),
        },
        "benchmarks": [],
    }

    print("\n" + "=" * 80)
    print(f"=== Starting Pool Engine Scale Benchmark ({'OSRM Live' if use_osrm else 'Mock'}) ===")
    print(f"SLA Target: <= 500 ms | Seeds: {list(seeds)} | Trials: {trials_per_seed}")
    print("=" * 80)

    for spec in active_workloads:
        for cache_state in ["warm", "cold"]:
            latencies: list[float] = []
            durations: list[float] = []
            matches: list[int] = []
            vmts: list[float] = []
            mems: list[float] = []
            expired_count = 0
            total_runs = 0

            print(f"\n>> Workload: {spec.name:8s} ({spec.num_requests:4d}R / {spec.num_vehicles:3d}V) | Cache: {cache_state.upper():4s}")

            for seed in seeds:
                requests, vehicles = generate_scale_entities(spec, seed=seed)

                # Initialize fresh engine & router per seed
                router: RoadNetworkRoutingProvider
                if use_osrm:
                    router = OsrmRoutingAdapter(base_url=osrm_url, timeout_seconds=0.45)
                else:
                    router = MockRoutingProvider()

                spatial = H3SpatialIndexAdapter()
                policy = DefaultPolicyProvider()
                engine = DispatchEngine(
                    policy_provider=policy,
                    routing_provider=router,
                    spatial_index=spatial,
                    config=CandidateGenerationConfig.bounded(
                        spatial_partitioning=True,
                        boundary_buffer_meters=600.0,
                        aging_weight_mps=15.0,
                    ),
                )

                # Warmup run if warm cache requested
                if cache_state == "warm":
                    engine.dispatch_batch(
                        requests=requests,
                        vehicles=vehicles,
                        active_rides=[],
                        current_time=1700000000,
                        deadline=time.monotonic() + 5.0,
                    )

                workload_mem = measure_workload_memory_mb(engine, router, requests, vehicles)
                mems.append(workload_mem)

                for trial in range(trials_per_seed):
                    total_runs += 1
                    run_res = benchmark_single_run(
                        engine=engine,
                        router=router,
                        requests=requests,
                        vehicles=vehicles,
                        cache_state=cache_state,
                    )
                    latencies.append(run_res["duration_ms"])
                    durations.append(run_res["solve_duration_ms"])
                    matches.append(run_res["matched_count"])
                    vmts.append(run_res["vmt_savings_km"])
                    if run_res["deadline_expired"]:
                        expired_count += 1

                    print(
                        f"   Seed {seed} Trial {trial+1}: "
                        f"Latency={run_res['duration_ms']:6.2f} ms | "
                        f"Matches={run_res['matched_count']:3d}/{len(requests)} | "
                        f"Status={run_res['search_status']:20s}"
                    )

            lat_sorted = sorted(latencies)
            p50 = statistics.median(lat_sorted)
            p95_idx = min(len(lat_sorted) - 1, int(0.95 * len(lat_sorted)))
            p99_idx = min(len(lat_sorted) - 1, int(0.99 * len(lat_sorted)))
            p95 = lat_sorted[p95_idx]
            p99 = lat_sorted[p99_idx]
            max_lat = max(lat_sorted)
            sla_compliant = (p99 <= 500.0) and (expired_count == 0)

            summary = {
                "workload": spec.name,
                "requests": spec.num_requests,
                "vehicles": spec.num_vehicles,
                "cache_state": cache_state,
                "total_runs": total_runs,
                "p50_ms": round(p50, 2),
                "p95_ms": round(p95, 2),
                "p99_ms": round(p99, 2),
                "max_ms": round(max_lat, 2),
                "expired_count": expired_count,
                "expired_rate": round(expired_count / total_runs, 4),
                "mean_matches": round(statistics.mean(matches), 1),
                "mean_match_rate": round(statistics.mean(matches) / spec.num_requests, 4),
                "mean_vmt_km": round(statistics.mean(vmts), 2),
                "mean_mem_mb": round(statistics.mean(mems), 2),
                "sla_compliant": sla_compliant,
                "trial_latencies_ms": [round(x, 2) for x in lat_sorted],
                "trial_durations_ms": [round(x, 2) for x in durations],
                "trial_matches": matches,
            }
            results["benchmarks"].append(summary)

            print(
                f"   => Summary: p50={p50:6.2f}ms | p95={p95:6.2f}ms | p99={p99:6.2f}ms | "
                f"Max={max_lat:6.2f}ms | Expired={expired_count}/{total_runs} | "
                f"SLA: {'PASS' if sla_compliant else 'FAIL'}"
            )

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scale Validation Benchmark")
    parser.add_argument("--osrm-url", default="http://localhost:5000")
    parser.add_argument("--mock", action="store_true", help="Use mock router instead of OSRM")
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 123, 999])
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--workload", choices=["Peak", "XLarge", "XXLarge", "Target", "All"], default="All")
    parser.add_argument("--output", default="scale_benchmark_results.json")
    args = parser.parse_args()

    active_wl = WORKLOADS if args.workload == "All" else [w for w in WORKLOADS if w.name == args.workload]

    res = run_scale_benchmarks(
        osrm_url=args.osrm_url,
        use_osrm=not args.mock,
        seeds=args.seeds,
        trials_per_seed=args.trials,
        workloads=active_wl,
    )

    with open(args.output, "w") as f:
        json.dump(res, f, indent=2)
    print(f"\nSaved benchmark results to {args.output}")
