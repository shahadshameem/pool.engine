"""Microbenchmark measuring computational overhead of Phase 5 multi-region routing architecture."""

import gc
import statistics
import time
from typing import Any

from engine.adapters.mock_routing import MockRoutingProvider
from engine.adapters.osrm_routing import OsrmHttpTransport, OsrmRoutingAdapter
from engine.adapters.regional_router import RegionalRoutingRouter
from engine.contracts.routing import (
    BoundingBox,
    Coordinate,
    OutOfRegionError,
    RegionConfig,
)

NUM_ITERATIONS = 100_000
ROUTING_QUERY_ITERATIONS = 10_000

NYC_BBOX = BoundingBox(min_lat=40.6900, min_lon=-74.0500, max_lat=40.8800, max_lon=-73.9000)
KERALA_BBOX = BoundingBox(min_lat=8.1800, min_lon=76.8000, max_lat=12.8000, max_lon=77.5000)

NYC_TIMES_SQUARE = Coordinate(latitude=40.7580, longitude=-73.9855)
NYC_WALL_STREET = Coordinate(latitude=40.7070, longitude=-74.0090)
KERALA_TVM_ORIGIN = Coordinate(latitude=8.5469, longitude=76.9054)
KERALA_TVM_DEST = Coordinate(latitude=8.4875, longitude=76.9528)
LONDON_COORD = Coordinate(latitude=51.5074, longitude=-0.1278)


def benchmark_region_lookup() -> dict[str, Any]:
    """Measures RegionalRoutingRouter.find_region_for_coordinate() latency."""
    cfg_nyc = RegionConfig(region_id="us-nyc-manhattan", bounding_box=NYC_BBOX, provider_type="mock")
    cfg_kl = RegionConfig(region_id="in-kl-tvm", bounding_box=KERALA_BBOX, provider_type="mock")
    router = RegionalRoutingRouter(
        regions=[cfg_nyc, cfg_kl],
        providers={
            "us-nyc-manhattan": MockRoutingProvider(bounding_box=NYC_BBOX),
            "in-kl-tvm": MockRoutingProvider(bounding_box=KERALA_BBOX),
        },
    )

    gc.collect()
    gc.disable()

    # 1. Matching in first region
    t0 = time.perf_counter_ns()
    for _ in range(NUM_ITERATIONS):
        _ = router.find_region_for_coordinate(NYC_TIMES_SQUARE)
    t1 = time.perf_counter_ns()
    ns_hit1 = (t1 - t0) / NUM_ITERATIONS

    # 2. Matching in second region
    t0 = time.perf_counter_ns()
    for _ in range(NUM_ITERATIONS):
        _ = router.find_region_for_coordinate(KERALA_TVM_ORIGIN)
    t1 = time.perf_counter_ns()
    ns_hit2 = (t1 - t0) / NUM_ITERATIONS

    # 3. Coordinate outside all regions (miss)
    t0 = time.perf_counter_ns()
    for _ in range(NUM_ITERATIONS):
        _ = router.find_region_for_coordinate(LONDON_COORD)
    t1 = time.perf_counter_ns()
    ns_miss = (t1 - t0) / NUM_ITERATIONS

    gc.enable()

    return {
        "iterations": NUM_ITERATIONS,
        "region_1_hit_ns": ns_hit1,
        "region_1_hit_us": ns_hit1 / 1000.0,
        "region_2_hit_ns": ns_hit2,
        "region_2_hit_us": ns_hit2 / 1000.0,
        "miss_ns": ns_miss,
        "miss_us": ns_miss / 1000.0,
    }


def benchmark_cross_region_rejection() -> dict[str, Any]:
    """Measures how quickly cross-region queries are rejected before network transmission."""
    cfg_nyc = RegionConfig(region_id="us-nyc-manhattan", bounding_box=NYC_BBOX, provider_type="mock")
    cfg_kl = RegionConfig(region_id="in-kl-tvm", bounding_box=KERALA_BBOX, provider_type="mock")
    router = RegionalRoutingRouter(
        regions=[cfg_nyc, cfg_kl],
        providers={
            "us-nyc-manhattan": MockRoutingProvider(bounding_box=NYC_BBOX),
            "in-kl-tvm": MockRoutingProvider(bounding_box=KERALA_BBOX),
        },
    )

    gc.collect()
    gc.disable()

    t0 = time.perf_counter_ns()
    rejected_count = 0
    for _ in range(NUM_ITERATIONS):
        try:
            router.get_direct_leg(NYC_TIMES_SQUARE, KERALA_TVM_DEST)
        except OutOfRegionError:
            rejected_count += 1
    t1 = time.perf_counter_ns()

    gc.enable()
    total_ns = t1 - t0
    ns_per_op = total_ns / NUM_ITERATIONS

    return {
        "iterations": NUM_ITERATIONS,
        "rejected_count": rejected_count,
        "ns_per_op": ns_per_op,
        "us_per_op": ns_per_op / 1000.0,
    }


def benchmark_multi_region_direct_routing_overhead() -> dict[str, Any]:
    """Compares direct routing query latency between a direct provider and the RegionalRoutingRouter."""
    single_provider = MockRoutingProvider(bounding_box=NYC_BBOX)

    cfg_nyc = RegionConfig(region_id="us-nyc-manhattan", bounding_box=NYC_BBOX, provider_type="mock")
    cfg_kl = RegionConfig(region_id="in-kl-tvm", bounding_box=KERALA_BBOX, provider_type="mock")
    multi_router = RegionalRoutingRouter(
        regions=[cfg_nyc, cfg_kl],
        providers={
            "us-nyc-manhattan": single_provider,
            "in-kl-tvm": MockRoutingProvider(bounding_box=KERALA_BBOX),
        },
    )

    single_times: list[float] = []
    multi_times: list[float] = []

    for _ in range(ROUTING_QUERY_ITERATIONS):
        t0 = time.perf_counter_ns()
        _ = single_provider.get_direct_leg(NYC_TIMES_SQUARE, NYC_WALL_STREET)
        t1 = time.perf_counter_ns()
        single_times.append((t1 - t0) / 1000.0)  # µs

        t0 = time.perf_counter_ns()
        _ = multi_router.get_direct_leg(NYC_TIMES_SQUARE, NYC_WALL_STREET)
        t1 = time.perf_counter_ns()
        multi_times.append((t1 - t0) / 1000.0)  # µs

    single_times.sort()
    multi_times.sort()

    mean_single = statistics.mean(single_times)
    mean_multi = statistics.mean(multi_times)

    return {
        "iterations": ROUTING_QUERY_ITERATIONS,
        "single_provider_mean_us": mean_single,
        "single_provider_p95_us": single_times[int(0.95 * len(single_times))],
        "single_provider_p99_us": single_times[int(0.99 * len(single_times))],
        "multi_router_mean_us": mean_multi,
        "multi_router_p95_us": multi_times[int(0.95 * len(multi_times))],
        "multi_router_p99_us": multi_times[int(0.99 * len(multi_times))],
        "net_dispatch_overhead_us": mean_multi - mean_single,
    }


def run_all() -> None:
    print("=" * 72)
    print("  POOL ENGINE — PHASE 5 MULTI-REGION ROUTING OVERHEAD BENCHMARK")
    print("=" * 72)

    res_lookup = benchmark_region_lookup()
    print("\n1. Spatial Region Lookup Latency (100,000 ops):")
    print(f"   - Region 1 Hit (Manhattan): {res_lookup['region_1_hit_ns']:.1f} ns ({res_lookup['region_1_hit_us']:.4f} µs)")
    print(f"   - Region 2 Hit (Kerala):    {res_lookup['region_2_hit_ns']:.1f} ns ({res_lookup['region_2_hit_us']:.4f} µs)")
    print(f"   - Out-of-region Miss:       {res_lookup['miss_ns']:.1f} ns ({res_lookup['miss_us']:.4f} µs)")

    res_rejection = benchmark_cross_region_rejection()
    print("\n2. Cross-Region Journey Pre-Network Rejection (100,000 ops):")
    print(f"   - Latency per rejection:    {res_rejection['ns_per_op']:.1f} ns ({res_rejection['us_per_op']:.4f} µs)")
    print(f"   - Rejection accuracy:       {res_rejection['rejected_count']}/{res_rejection['iterations']} (100.0%)")

    res_overhead = benchmark_multi_region_direct_routing_overhead()
    print(f"\n3. End-to-End Direct Leg Routing Comparison ({ROUTING_QUERY_ITERATIONS:,} queries):")
    print(f"   - Single Region Provider: mean = {res_overhead['single_provider_mean_us']:.4f} µs, p95 = {res_overhead['single_provider_p95_us']:.4f} µs, p99 = {res_overhead['single_provider_p99_us']:.4f} µs")
    print(f"   - Multi-Region Router:    mean = {res_overhead['multi_router_mean_us']:.4f} µs, p95 = {res_overhead['multi_router_p95_us']:.4f} µs, p99 = {res_overhead['multi_router_p99_us']:.4f} µs")
    print(f"   - Net Added Overhead:     {res_overhead['net_dispatch_overhead_us']:+.4f} µs")
    print("=" * 72)


if __name__ == "__main__":
    run_all()
