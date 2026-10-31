"""Benchmark comparing single-connection/blocking event-loop baseline vs Phase 2 pooled offloaded execution.

Executes concurrent HTTP requests against an ASGI application connected to live PostgreSQL
(pool_engine_test on port 5433).
Measures:
- Throughput (Requests per Second - RPS)
- Latency percentiles (p50, p95, p99, max in ms)
- Event-loop responsiveness (heartbeat tick lag in ms during concurrent load)
- Error and timeout counts
"""

import asyncio
import os
import statistics
import time
from typing import Any, Callable

import psycopg

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.mock_routing import MockRoutingProvider
from engine.adapters.postgres_storage import PostgresRideStorage
from engine.domain.models import GeoCoordinate, RideRequest, Vehicle
from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator
from engine.service.app import create_app
from engine.service.client import AsgiTestClient
from engine.service.service import PoolEngineService
from engine.service.telemetry import StructuredLoggerTelemetry

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


def _setup_benchmark_db(storage: PostgresRideStorage, num_vehicles: int = 20) -> None:
    with storage.connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "TRUNCATE vehicles, rides, route_stops, ride_requests, join_requests, seat_holds, idempotency_records CASCADE"
                )
    for i in range(num_vehicles):
        v = Vehicle(
            vehicle_id=f"veh-bench-{i}",
            driver_id=f"driver-bench-{i}",
            current_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
            total_seat_capacity=4,
            is_active=True,
        )
        storage.save_vehicle(v)
        req = RideRequest(
            request_id=f"req-bench-{i}",
            user_id=f"user-bench-{i}",
            pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
            dropoff_location=GeoCoordinate(latitude=40.7300, longitude=-73.9900),
            seat_count=1,
            earliest_pickup_time=1000,
            latest_dropoff_time=3000,
            direct_duration_seconds=300,
            direct_distance_meters=1000,
        )
        storage.save_request(req)


async def run_benchmark_trial(
    app: Any,
    concurrency: int = 10,
    total_requests: int = 100,
    workload: str = "mixed",  # "location", "reads", "mixed"
) -> dict[str, Any]:
    client = AsgiTestClient(app)

    # Event loop responsiveness probe: runs alongside concurrent requests
    heartbeat_lags: list[float] = []
    stop_heartbeat = False

    async def heartbeat_probe() -> None:
        interval = 0.005  # 5 ms target interval
        last_time = time.perf_counter()
        while not stop_heartbeat:
            await asyncio.sleep(interval)
            now = time.perf_counter()
            actual_elapsed = now - last_time
            lag = max(0.0, actual_elapsed - interval)
            heartbeat_lags.append(lag * 1000.0)  # ms
            last_time = now

    heartbeat_task = asyncio.create_task(heartbeat_probe())

    req_latencies: list[float] = []
    errors = 0
    completed = 0
    semaphore = asyncio.Semaphore(concurrency)

    async def worker(req_idx: int) -> None:
        nonlocal errors, completed
        veh_id = f"veh-bench-{req_idx % 20}"
        req_id = f"req-bench-{req_idx % 20}"

        async with semaphore:
            t0 = time.perf_counter()
            try:
                if workload == "location":
                    resp = await client._async_request(
                        "PATCH",
                        f"/v1/vehicles/{veh_id}/location",
                        json_data={"latitude": 40.7128 + req_idx * 0.0001, "longitude": -74.0060},
                    )
                elif workload == "reads":
                    resp = await client._async_request("GET", f"/v1/requests/{req_id}")
                else:
                    if req_idx % 2 == 0:
                        resp = await client._async_request(
                            "PATCH",
                            f"/v1/vehicles/{veh_id}/location",
                            json_data={"latitude": 40.7128 + req_idx * 0.0001, "longitude": -74.0060},
                        )
                    else:
                        resp = await client._async_request("GET", f"/v1/requests/{req_id}")

                t1 = time.perf_counter()
                latency_ms = (t1 - t0) * 1000.0
                req_latencies.append(latency_ms)
                if resp.status_code >= 400:
                    errors += 1
                else:
                    completed += 1
            except Exception:
                errors += 1

    trial_start = time.perf_counter()
    tasks = [asyncio.create_task(worker(i)) for i in range(total_requests)]
    await asyncio.gather(*tasks)
    trial_end = time.perf_counter()

    stop_heartbeat = True
    await heartbeat_task

    total_time = trial_end - trial_start
    rps = total_requests / total_time if total_time > 0 else 0.0

    sorted_latencies = sorted(req_latencies) if req_latencies else [0.0]
    p50 = statistics.median(sorted_latencies)
    p95 = sorted_latencies[int(len(sorted_latencies) * 0.95)] if sorted_latencies else 0.0
    p99 = sorted_latencies[int(len(sorted_latencies) * 0.99)] if sorted_latencies else 0.0
    max_lat = max(sorted_latencies) if sorted_latencies else 0.0

    max_loop_lag = max(heartbeat_lags) if heartbeat_lags else 0.0
    mean_loop_lag = statistics.mean(heartbeat_lags) if heartbeat_lags else 0.0

    return {
        "concurrency": concurrency,
        "total_requests": total_requests,
        "completed": completed,
        "errors": errors,
        "total_time_seconds": round(total_time, 4),
        "rps": round(rps, 2),
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "p99_ms": round(p99, 2),
        "max_ms": round(max_lat, 2),
        "max_event_loop_lag_ms": round(max_loop_lag, 2),
        "mean_event_loop_lag_ms": round(mean_loop_lag, 2),
    }


def run_full_comparison() -> dict[str, Any]:
    if not TEST_DB_URL:
        raise RuntimeError("TEST_DATABASE_URL or DATABASE_URL must be set for benchmark.")

    print("=" * 70)
    print("POOL ENGINE CONCURRENCY BENCHMARK: PHASE 1 vs PHASE 2")
    print(f"Target Database: {TEST_DB_URL}")
    print("=" * 70)

    # Arm 1: Single unpooled connection (Phase 1 Baseline with direct connection)
    direct_conn = psycopg.connect(TEST_DB_URL, autocommit=True)
    storage_arm1 = PostgresRideStorage(connection=direct_conn)
    _setup_benchmark_db(storage_arm1)
    router = MockRoutingProvider()
    spatial = H3SpatialIndexAdapter()
    policy = DefaultPolicyProvider()
    orch1 = DispatchOrchestrator(storage=storage_arm1, policy_provider=policy, routing_provider=router, spatial_index=spatial)
    service1 = PoolEngineService(storage=storage_arm1, orchestrator=orch1, router=router, telemetry=StructuredLoggerTelemetry())
    app1 = create_app(service=service1)

    print("\n[Running Arm A: Single Unpooled Connection Baseline]")
    res_arm1_c5 = asyncio.run(run_benchmark_trial(app1, concurrency=5, total_requests=100, workload="mixed"))
    print(f"  Concurrency 5:  RPS={res_arm1_c5['rps']} | p50={res_arm1_c5['p50_ms']}ms | p95={res_arm1_c5['p95_ms']}ms | Max Loop Lag={res_arm1_c5['max_event_loop_lag_ms']}ms | Errors={res_arm1_c5['errors']}")

    res_arm1_c10 = asyncio.run(run_benchmark_trial(app1, concurrency=10, total_requests=100, workload="mixed"))
    print(f"  Concurrency 10: RPS={res_arm1_c10['rps']} | p50={res_arm1_c10['p50_ms']}ms | p95={res_arm1_c10['p95_ms']}ms | Max Loop Lag={res_arm1_c10['max_event_loop_lag_ms']}ms | Errors={res_arm1_c10['errors']}")
    direct_conn.close()

    # Arm 2: Bounded Connection Pool (min=2, max=10) with asyncio.to_thread offloading (Phase 2)
    storage_arm2 = PostgresRideStorage(dsn=TEST_DB_URL, min_size=2, max_size=10, timeout=5.0)
    _setup_benchmark_db(storage_arm2)
    orch2 = DispatchOrchestrator(storage=storage_arm2, policy_provider=policy, routing_provider=router, spatial_index=spatial)
    service2 = PoolEngineService(storage=storage_arm2, orchestrator=orch2, router=router, telemetry=StructuredLoggerTelemetry())
    app2 = create_app(service=service2)

    print("\n[Running Arm B: Bounded Connection Pool (max=10) + Event-Loop Offloading (Phase 2)]")
    res_arm2_c5 = asyncio.run(run_benchmark_trial(app2, concurrency=5, total_requests=100, workload="mixed"))
    print(f"  Concurrency 5:  RPS={res_arm2_c5['rps']} | p50={res_arm2_c5['p50_ms']}ms | p95={res_arm2_c5['p95_ms']}ms | Max Loop Lag={res_arm2_c5['max_event_loop_lag_ms']}ms | Errors={res_arm2_c5['errors']}")

    res_arm2_c10 = asyncio.run(run_benchmark_trial(app2, concurrency=10, total_requests=100, workload="mixed"))
    print(f"  Concurrency 10: RPS={res_arm2_c10['rps']} | p50={res_arm2_c10['p50_ms']}ms | p95={res_arm2_c10['p95_ms']}ms | Max Loop Lag={res_arm2_c10['max_event_loop_lag_ms']}ms | Errors={res_arm2_c10['errors']}")
    storage_arm2.close()

    return {
        "arm_a_single_conn": {"c5": res_arm1_c5, "c10": res_arm1_c10},
        "arm_b_pooled": {"c5": res_arm2_c5, "c10": res_arm2_c10},
    }


if __name__ == "__main__":
    results = run_full_comparison()
    import json
    print("\n" + json.dumps(results, indent=2))
