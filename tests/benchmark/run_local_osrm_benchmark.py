"""Automated benchmark runner for Mock baseline vs Local OSRM on 1,000 req / 200 veh."""

import os
import platform
import statistics
import time
from typing import Any

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.mock_routing import MockRoutingProvider
from engine.adapters.osrm_routing import OsrmRoutingAdapter
from engine.contracts.routing import Coordinate
from engine.dispatch import DispatchEngine
from engine.domain.enums import SearchStatus
from tests.benchmark.conftest import generate_benchmark_scenario

LOCAL_OSRM_URL = "http://localhost:5000"


def run_benchmark_trials() -> dict[str, Any]:
    print("Generating deterministic benchmark scenario (1,000 req / 200 veh, seed=42)...")
    reqs, vehs, rds = generate_benchmark_scenario(seed=42)
    policy = DefaultPolicyProvider()
    spatial = H3SpatialIndexAdapter()

    results: dict[str, Any] = {}

    # ---------------------------------------------------------
    # 1. Mock Routing Baseline (5 trials, 500ms deadline)
    # ---------------------------------------------------------
    print("\n--- 1. Mock Routing Baseline (5 trials) ---")
    mock_latencies: list[float] = []
    mock_matches: list[int] = []
    mock_statuses: list[SearchStatus] = []
    mock_deadlines = 0

    for i in range(5):
        engine = DispatchEngine(policy, MockRoutingProvider(), spatial)
        t0 = time.perf_counter()
        res = engine.dispatch_batch(
            reqs, vehs, rds, current_time=1700000000,
            batch_id=f"mock-trial-{i}", deadline=time.monotonic() + 0.500
        )
        ms = (time.perf_counter() - t0) * 1000.0
        mock_latencies.append(ms)
        mock_matches.append(len(res.selected_assignments))
        mock_statuses.append(res.search_status)
        if res.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED:
            mock_deadlines += 1
        print(f"  Trial {i+1}: {ms:.2f} ms | Matches: {len(res.selected_assignments)} | Status: {res.search_status.name}")

    results["mock"] = {
        "latencies": mock_latencies,
        "p50": statistics.median(mock_latencies),
        "p95": sorted(mock_latencies)[int(0.95 * len(mock_latencies))],
        "p99": sorted(mock_latencies)[-1],
        "max": max(mock_latencies),
        "matches": mock_matches[-1],
        "deadlines": mock_deadlines,
        "status": mock_statuses[-1].name,
    }

    # ---------------------------------------------------------
    # 2. Local OSRM Cold Cache (3 trials under 500ms deadline)
    # Confirm each trial starts with an empty cache!
    # ---------------------------------------------------------
    print("\n--- 2. Local OSRM Cold Cache (3 trials, strict 500ms SLA) ---")
    cold_latencies: list[float] = []
    cold_matches: list[int] = []
    cold_statuses: list[SearchStatus] = []
    cold_deadlines = 0
    cold_requests_counts: list[int] = []

    for i in range(3):
        # Create brand new adapter with empty cache
        adapter = OsrmRoutingAdapter(base_url=LOCAL_OSRM_URL, timeout_seconds=1.0, cache_maxsize=100000)
        assert len(adapter.cache) == 0, "Cache must be strictly empty!"
        engine = DispatchEngine(policy, adapter, spatial)

        t0 = time.perf_counter()
        res = engine.dispatch_batch(
            reqs, vehs, rds, current_time=1700000000,
            batch_id=f"osrm-cold-{i}", deadline=time.monotonic() + 0.500
        )
        ms = (time.perf_counter() - t0) * 1000.0
        cold_latencies.append(ms)
        cold_matches.append(len(res.selected_assignments))
        cold_statuses.append(res.search_status)
        cold_requests_counts.append(adapter.cache_misses)
        if res.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED:
            cold_deadlines += 1
        print(f"  Trial {i+1}: {ms:.2f} ms | Cache Misses: {adapter.cache_misses} | Matches: {len(res.selected_assignments)} | Status: {res.search_status.name}")

    results["osrm_cold"] = {
        "latencies": cold_latencies,
        "p50": statistics.median(cold_latencies),
        "max": max(cold_latencies),
        "matches": cold_matches[-1],
        "deadlines": cold_deadlines,
        "misses": cold_requests_counts[-1],
        "status": cold_statuses[-1].name,
    }

    # ---------------------------------------------------------
    # 3. Local OSRM Warm Cache (5 trials under 500ms deadline)
    # Pre-populate cache, then run 5 consecutive trials!
    # ---------------------------------------------------------
    print("\n--- 3. Local OSRM Warm Cache (5 trials, strict 500ms SLA) ---")
    adapter_warm = OsrmRoutingAdapter(base_url=LOCAL_OSRM_URL, timeout_seconds=1.0, cache_maxsize=100000)
    engine_warm = DispatchEngine(policy, adapter_warm, spatial)

    print("  Populating cache without deadline...")
    t0 = time.perf_counter()
    _ = engine_warm.dispatch_batch(
        reqs, vehs, rds, current_time=1700000000,
        batch_id="cache-warmup", deadline=time.monotonic() + 60.0
    )
    pop_sec = time.perf_counter() - t0
    cached_legs = len(adapter_warm.cache)
    print(f"  Cache populated with {cached_legs} legs in {pop_sec:.2f} s.")

    warm_latencies: list[float] = []
    warm_matches: list[int] = []
    warm_statuses: list[SearchStatus] = []
    warm_deadlines = 0
    warm_hit_rates: list[float] = []

    for i in range(5):
        hits_before = adapter_warm.cache_hits
        misses_before = adapter_warm.cache_misses

        t0 = time.perf_counter()
        res = engine_warm.dispatch_batch(
            reqs, vehs, rds, current_time=1700000000,
            batch_id=f"osrm-warm-{i}", deadline=time.monotonic() + 0.500
        )
        ms = (time.perf_counter() - t0) * 1000.0
        warm_latencies.append(ms)
        warm_matches.append(len(res.selected_assignments))
        warm_statuses.append(res.search_status)
        if res.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED:
            warm_deadlines += 1

        cycle_hits = adapter_warm.cache_hits - hits_before
        cycle_misses = adapter_warm.cache_misses - misses_before
        rate = (cycle_hits / (cycle_hits + cycle_misses) * 100.0) if (cycle_hits + cycle_misses) > 0 else 100.0
        warm_hit_rates.append(rate)

        print(f"  Trial {i+1}: {ms:.2f} ms | Hit Rate: {rate:.1f}% | Matches: {len(res.selected_assignments)} | Status: {res.search_status.name}")

    results["osrm_warm"] = {
        "latencies": warm_latencies,
        "p50": statistics.median(warm_latencies),
        "p95": sorted(warm_latencies)[int(0.95 * len(warm_latencies))],
        "p99": sorted(warm_latencies)[-1],
        "max": max(warm_latencies),
        "matches": warm_matches[-1],
        "deadlines": warm_deadlines,
        "hit_rate": statistics.mean(warm_hit_rates),
        "status": warm_statuses[-1].name,
        "routing_errors": res.routing_errors_count,
    }

    return results


if __name__ == "__main__":
    run_benchmark_trials()
