"""Reproducible benchmark execution suite for 1,000 requests and 200 vehicles (T053)."""

import platform
import time
from typing import Sequence

import numpy as np
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.mock_routing import MockRoutingProvider
from engine.dispatch import DispatchEngine
from engine.domain.enums import RequestStatus, SearchStatus
from engine.domain.models import MatchResult, Ride, RideRequest, Vehicle
from tests.benchmark.conftest import generate_benchmark_scenario


def test_reproducible_benchmark_500ms_sla(
    benchmark_scenario_data: tuple[list[RideRequest], list[Vehicle], list[Ride]],
    in_memory_router: MockRoutingProvider,
    policy_provider: DefaultPolicyProvider,
    spatial_index: H3SpatialIndexAdapter,
) -> None:
    """
    T053: Full reproducible benchmark for 1,000 active requests and 200 vehicles in BOUNDED mode.
    Measures complete end-to-end dispatch path (spatial filtering, insertion/bundling,
    scoring, set packing, Stage 6 validation, and serialization) under 500ms SLA.
    Captures: p50, p95, p99, max latency, timeout rate (<= 0.1%), feasible solution rate (100%).
    Note: The 500 ms SLA applies strictly to BOUNDED mode.
    """
    requests, vehicles, rides = benchmark_scenario_data
    engine = DispatchEngine(
        policy_provider=policy_provider,
        routing_provider=in_memory_router,
        spatial_index=spatial_index,
    )

    latencies_ms: list[float] = []
    timeouts = 0
    feasible_runs = 0
    num_runs = 5
    first_result: MatchResult | None = None

    import gc
    gc.collect()

    # Warmup run to warm JIT/caches
    _ = engine.dispatch_batch(
        requests=requests[:100],
        vehicles=vehicles[:20],
        active_rides=rides[:10],
        current_time=1700000000,
        batch_id="warmup-run",
    )

    for run_idx in range(num_runs):
        t_start = time.perf_counter()
        deadline = time.monotonic() + 0.500  # 500 ms SLA monotonic deadline

        result = engine.dispatch_batch(
            requests=requests,
            vehicles=vehicles,
            active_rides=rides,
            current_time=1700000000,
            batch_id=f"bench-run-{run_idx}",
            deadline=deadline,
            reserved_headroom=0.050,
        )
        elapsed_ms = (time.perf_counter() - t_start) * 1000.0
        latencies_ms.append(elapsed_ms)

        # Timeout check
        if elapsed_ms > 500.0:
            timeouts += 1

        # Feasibility check: no vehicle assigned more than once, no request assigned more than once
        assigned_vehs: set[str] = set()
        assigned_reqs: set[str] = set()
        conflict = False

        for a in result.selected_assignments:
            if a.vehicle_id in assigned_vehs:
                conflict = True
                break
            assigned_vehs.add(a.vehicle_id)

            for rid in a.request_ids:
                if rid in assigned_reqs:
                    conflict = True
                    break
                assigned_reqs.add(rid)

        if not conflict:
            feasible_runs += 1

        if result.search_status != SearchStatus.INCOMPLETE_DEADLINE_EXPIRED:
            if first_result is None:
                first_result = result
            else:
                # Determinism check across identical runs (excluding deadline timeouts)
                assert len(result.selected_assignments) == len(first_result.selected_assignments)
                for a_curr, a_first in zip(result.selected_assignments, first_result.selected_assignments):
                    assert a_curr.vehicle_id == a_first.vehicle_id
                    assert a_curr.request_ids == a_first.request_ids
                    assert a_curr.objective_value == a_first.objective_value

    p50 = float(np.percentile(latencies_ms, 50))
    p95 = float(np.percentile(latencies_ms, 95))
    p99 = float(np.percentile(latencies_ms, 99))
    max_lat = max(latencies_ms)
    timeout_rate = float(timeouts) / float(num_runs)
    feasible_rate = float(feasible_runs) / float(num_runs)

    print("\n--- BENCHMARK RESULTS: BOUNDED MODE (1,000 requests, 200 vehicles) ---")
    print(f"Mode: {engine.config.mode.value} (radius={engine.config.max_search_radius_meters}m, max_vehs={engine.config.max_vehicles_per_request}, max_reqs={engine.config.max_requests_per_vehicle})")
    print(f"Platform: {platform.system()} {platform.machine()} ({platform.processor()})")
    print(f"Python: {platform.python_version()}")
    print(f"Runs: {num_runs}")
    print(f"Latency: p50={p50:.2f}ms, p95={p95:.2f}ms, p99={p99:.2f}ms, max={max_lat:.2f}ms")
    print(f"Timeout Rate: {timeout_rate * 100:.2f}% (Target: <= 0.1%)")
    print(f"Feasible Solution Rate: {feasible_rate * 100:.2f}% (Target: 100%)")
    assert first_result is not None
    print(f"Total Matches in Batch: {len(first_result.selected_assignments)}")
    print(f"Total VMT Savings: {first_result.total_vmt_savings_meters}m")

    # Assertions for SLA verification
    assert timeout_rate <= 0.05, f"Timeout rate exceeded: {timeout_rate}"
    assert feasible_rate == 1.0, f"Feasible solution rate violated: {feasible_rate}"
    assert max_lat <= 500.0, f"Max latency exceeded 500ms SLA: {max_lat:.2f}ms"
