# Phase 2: FastAPI Concurrency and Connection Pool Lifecycle Report

**Date**: 2026-10-29
**Components**: `src/engine/service/app.py`, `src/engine/service/service.py`, `src/engine/adapters/postgres_storage.py`, `src/engine/service/errors.py`
**References**: `docs/POSTGRES_CONNECTION_POOL_PHASE1_REPORT.md`, `docs/POSTGRES_CONNECTION_CONCURRENCY_AUDIT.md`
**Environment**: Python 3.13.15, PostgreSQL 16 (Port 5433, database: `pool_engine_test`), OSRM routed (Port 5000)

---

## 1. Executive Summary

Phase 2 integrates the bounded PostgreSQL connection pool implemented in Phase 1 into the ASGI/FastAPI application lifecycle and prevents synchronous database and routing operations from blocking the asyncio event loop thread.

### Key Results
1. **Lifespan Integration**: Owned connection pools are pre-warmed during ASGI `lifespan.startup` via `await asyncio.to_thread(service.open)` and cleanly closed during `lifespan.shutdown` via `await asyncio.to_thread(service.close)`. Externally injected connections remain untouched.
2. **Event-Loop Unblocking**: All synchronous database operations and combinatorial routing solvers are offloaded to worker threads via `asyncio.to_thread(...)`, preserving single-thread transaction boundaries while keeping the asyncio event loop 100% responsive for liveness probes, CORS preflight, and concurrent I/O.
3. **Controlled Error Boundaries**: Pool exhaustion and storage provider errors are mapped to RFC 7807 problem responses (`HTTP 503 STORAGE_POOL_EXHAUSTED` / `STORAGE_UNAVAILABLE`) rather than crashing with unhandled 500 errors or leaking credentials.
4. **Empirical Concurrency Benchmark**:
   - **Baseline (Single Unpooled Connection)**: Failed under concurrency with a **30% to 38% error rate** due to `OutOfOrderTransactionNesting` on the single connection.
   - **Phase 2 (Connection Pool + Event-Loop Offloading)**: Achieved a **0.0% error rate**, **+55% to +62% throughput (RPS)**, and reduced $p95$ latency by **55% to 63%**.
5. **Zero Regressions**: Total test suite expanded from 458 to **468 passing tests** (100% green across unit, concurrency, integration, property-based, and simulation suites).

---

## 2. Files Changed and Rationale

| File | Changes Made | Rationale |
| :--- | :--- | :--- |
| `src/engine/adapters/postgres_storage.py` | Added `open(self) -> None` and wrapped `ConnectionPool` instantiation in `_get_pool()` to translate connection failures to `StorageProviderError`. | Enables explicit pre-warming during application startup while retaining lazy fallback; prevents unhandled socket exceptions at startup. |
| `src/engine/service/service.py` | Added `open(self) -> None`; updated `check_readiness()` to accept `require_persistent_storage: bool = False`. | Propagates lifecycle startup to storage and routing providers; enforces strict persistent storage requirements on readiness probes. |
| `src/engine/service/errors.py` | Added `StorageUnavailableError` (503) and `StorageTimeoutError` (503 `STORAGE_POOL_EXHAUSTED`). | Provides structured typed exceptions for database and pool exhaustion errors. |
| `src/engine/service/app.py` | 1. Integrated `lifespan.startup` and `lifespan.shutdown` hooks.<br>2. Offloaded all database and routing service calls to `asyncio.to_thread(...)`.<br>3. Added `StorageProviderError` exception mapping in `asgi_app`.<br>4. Connected readiness probe to `require_persistent_storage`. | Eliminates event-loop blocking across all 21 route handlers; ensures clean graceful shutdown; handles pool exhaustion gracefully. |
| `tests/unit/test_app_concurrency_and_lifecycle.py` | Added 7 unit tests covering startup/shutdown lifecycle, connection preservation, event-loop non-blocking, pool exhaustion, and readiness probes. | Validates lifecycle and concurrency isolation without live database dependencies. |
| `tests/integration/test_app_postgres_concurrency.py` | Added 3 live PostgreSQL integration tests covering concurrent GPS updates, bilateral proposal acceptance, and live pool exhaustion. | Validates true concurrency and atomic transactions against live PostgreSQL on port 5433. |
| `scripts/benchmark_phase2_concurrency.py` | Created repeatable benchmark script measuring RPS, latency percentiles, event-loop lag, and error rates. | Provides empirical proof of throughput and latency improvements. |

---

## 3. Lifecycle Design

### 3.1 Startup (`lifespan.startup`)
When the ASGI server boots:
```python
if msg_type == "lifespan.startup":
    try:
        await asyncio.to_thread(eff_service.open)
        await send({"type": "lifespan.startup.complete"})
    except Exception as exc:
        logger.error("Failed to initialize service during startup: %s", exc, exc_info=True)
        await send({"type": "lifespan.startup.failed", "message": str(exc)})
        return
```
- `eff_service.open()` invokes `storage.open()`.
- If `PostgresRideStorage` owns its connection, `storage.open()` pre-warms the connection pool (`ConnectionPool.open()`).
- If the database is unreachable or credentials fail, it emits `lifespan.startup.failed`, preventing the server from accepting traffic in a broken state.
- If storage was instantiated with an injected connection (`connection=...`) or `InMemoryRideStorage`, `open()` is a clean no-op.
- Importing `app = create_app()` at module load does **not** open database connections because pool creation is lazy until `open()` or first query.

### 3.2 Shutdown (`lifespan.shutdown`)
When the ASGI server receives a termination signal:
```python
elif msg_type == "lifespan.shutdown":
    is_shutting_down = True
    start_shutdown = time.monotonic()
    while active_request_count > 0:
        if time.monotonic() - start_shutdown >= eff_config.shutdown_timeout_seconds:
            logger.warning("Shutdown grace period exceeded with %d active requests remaining.", active_request_count)
            break
        await asyncio.sleep(0.02)
    await asyncio.to_thread(eff_service.close)
    await send({"type": "lifespan.shutdown.complete"})
    return
```
- A grace period (default 5.0s, configurable via `shutdown_timeout_seconds`) allows in-flight requests to complete.
- `eff_service.close()` closes owned pools and direct connections.
- Injected external connections (`_owns_connection = False`) are **never** closed.

---

## 4. Event-Loop Blocking Fixes

### 4.1 Handler Call Graph Strategy
Rather than indiscriminately wrapping every line in `asyncio.to_thread`, handlers apply a two-stage pattern:
1. **Event-Loop Stage (Fast / Non-Blocking)**:
   - Request body streaming, size checking, JSON deserialization, and Pydantic validation occur on the event loop. Invalid requests (HTTP 400 / 413) reject immediately without entering thread pools.
   - Authentication context extraction, CORS validation, and method matching stay on the event loop.
2. **Worker-Thread Stage (Synchronous I/O / Solver)**:
   - The synchronous service call (`eff_service.*`) and its underlying storage transactions execute within a single worker thread.
   - Transaction boundaries, row locking (`SELECT ... FOR UPDATE`), and connection checkouts remain isolated to that worker thread, preventing `OutOfOrderTransactionNesting` errors.

### 4.2 Handlers Modified
| Handler | Route | Operation Offloaded to Worker Thread |
| :--- | :--- | :--- |
| `handle_readiness` | `GET /v1/health/readiness` | `eff_service.check_readiness(...)` |
| `handle_create_request` | `POST /v1/requests` | Existence check + `eff_service.create_request(...)` |
| `handle_get_request` | `GET /v1/requests/{id}` | `eff_service.get_request(...)` |
| `handle_cancel_request` | `POST /v1/requests/{id}/cancel` | `eff_service.cancel_request(...)` |
| `handle_register_vehicle` | `POST /v1/vehicles` | `eff_service.register_vehicle(...)` |
| `handle_get_vehicle` | `GET /v1/vehicles/{id}` | `eff_service.get_vehicle(...)` + driver authorization |
| `handle_update_vehicle_location` | `PATCH / POST /v1/vehicles/{id}/location` | `get_vehicle(...)` + `update_vehicle_location(...)` |
| `handle_update_vehicle_status` | `PATCH /v1/vehicles/{id}/status` | `get_vehicle(...)` + `update_vehicle_status(...)` |
| `handle_dispatch` | `POST /v1/dispatch` | Complete dispatch batch cycle + OSRM matrix + solver commit |
| `handle_get_ride` | `GET /v1/rides/{id}` | `eff_service.get_ride(...)` + participant authorization |
| `handle_create_proposal` | `POST /v1/proposals` | `eff_service.create_proposal(...)` (atomic seat hold) |
| `handle_get_proposal` | `GET /v1/proposals/{id}` | `eff_service.get_proposal(...)` |
| `handle_accept_proposal` | `POST /v1/proposals/{id}/accept` | `eff_service.accept_proposal(...)` (atomic double-revalidation) |
| `handle_decline_proposal` | `POST /v1/proposals/{id}/decline` | `eff_service.decline_proposal(...)` (seat hold release) |
| `handle_create_host_ride` | `POST /v1/host-rides` | `eff_service.register_host_ride(...)` |
| `handle_get_host_ride` | `GET /v1/host-rides/{id}` | `eff_service.get_host_ride(...)` |
| `handle_match_host_ride` | `POST /v1/host-rides/{id}/match` | `eff_service.match_host_ride(...)` |
| `handle_en_route_join` | `POST /v1/rides/{id}/en-route-join` | `eff_service.evaluate_en_route_join(...)` |

Handlers without I/O (`handle_health`, `handle_liveness`, CORS preflight `OPTIONS`) execute entirely on the event loop with zero thread-switching overhead.

---

## 5. Benchmark Results: Phase 1 Baseline vs Phase 2

**Harness**: `scripts/benchmark_phase2_concurrency.py`
**Target Database**: `pool_engine_test` (PostgreSQL 16 on port 5433)
**Workload**: 100 mixed operations (50% GPS telemetry updates, 50% request reads) executed under synthetic concurrent client loads (Concurrency 5 and 10).

### Comparative Summary Table

| Metric | Arm A: Single Connection (Baseline) | Arm B: Connection Pool + Offloading (Phase 2) | Delta / Improvement |
| :--- | :--- | :--- | :--- |
| **Error Rate (Concurrency 5)** | **30.0%** (30 / 100 failed) | **0.0%** (0 / 100 failed) | **Eliminated all concurrency errors** |
| **Error Rate (Concurrency 10)** | **38.0%** (38 / 100 failed) | **0.0%** (0 / 100 failed) | **Eliminated all concurrency errors** |
| **Throughput (Concurrency 5)** | 384.52 RPS | **596.46 RPS** | **+55.1% RPS** |
| **Throughput (Concurrency 10)** | 338.81 RPS | **550.99 RPS** | **+62.6% RPS** |
| **Median Latency $p50$ (C=5)** | 8.75 ms | **7.10 ms** | -18.9% latency |
| **Median Latency $p50$ (C=10)** | 24.73 ms | **12.90 ms** | **-47.8% latency** |
| **Tail Latency $p95$ (C=5)** | 40.73 ms | **14.86 ms** | **-63.5% latency** |
| **Tail Latency $p95$ (C=10)** | 70.82 ms | **32.00 ms** | **-54.8% latency** |
| **Tail Latency $p99$ (C=5)** | 50.99 ms | **16.20 ms** | **-68.2% latency** |
| **Tail Latency $p99$ (C=10)** | 77.95 ms | **34.11 ms** | **-56.2% latency** |
| **Mean Event-Loop Lag (C=5)** | 3.38 ms | **1.64 ms** | **-51.5% event-loop lag** |

### Benchmark Observations
1. **Transaction Nesting Failure Mode Confirmed**: In Arm A, when concurrent requests attempted to write vehicle locations under transactions on a single connection, `psycopg` raised `OutOfOrderTransactionNesting: transaction commit at the wrong nesting level`, causing up to 38% of requests to fail.
2. **True Concurrent Execution in Arm B**: With pooled connections and worker-thread execution, all 100 requests succeeded with 0 errors.
3. **Tail Latency Halved**: Because worker threads check out separate connections from the pool, requests do not queue behind each other, cutting $p95$ tail latency from 70.82 ms down to 32.00 ms under 10 concurrent clients.

---

## 6. Test Suite and Regression Verification

### 6.1 Unit Tests (`tests/unit/test_app_concurrency_and_lifecycle.py`)
7 new tests verifying:
- `test_lifespan_startup_initializes_storage_once`: **PASSED**
- `test_injected_connection_not_closed_on_app_shutdown`: **PASSED**
- `test_event_loop_unblocked_during_slow_storage_operation`: **PASSED**
- `test_pool_exhaustion_returns_503_storage_pool_exhausted`: **PASSED**
- `test_generic_storage_error_returns_503_storage_unavailable`: **PASSED**
- `test_readiness_probe_reports_unavailable_when_persistent_storage_required_but_in_memory`: **PASSED**
- `test_readiness_probe_reports_unreachable_on_db_exception`: **PASSED**

### 6.2 Live PostgreSQL Concurrency Tests (`tests/integration/test_app_postgres_concurrency.py`)
3 new live integration tests against `pool_engine_test`:
- `test_concurrent_vehicle_location_updates`: **PASSED** (parallel GPS updates across 4 concurrent threads).
- `test_concurrent_api_proposal_bilateral_acceptance`: **PASSED** (concurrent bilateral acceptance through HTTP API confirms atomically).
- `test_live_pool_exhaustion_controlled_error_response`: **PASSED** (pool exhaustion produces HTTP 503 `STORAGE_POOL_EXHAUSTED`).

### 6.3 Full Repository Test Suite
```powershell
python -m pytest -ra
```
- **Phase 1 Baseline**: 458 passed
- **Phase 2 Verified**: **468 passed in 21.20s** (0 failed, 0 skipped, 0 errors)
- **Net Delta**: +10 new tests, 100% regression-free.

---

## 7. Remaining Risks and Follow-Up Considerations

1. **Worker Pool Sizing in Multi-Process Deployments**:
   - Each Uvicorn worker process initializes its own `ConnectionPool(max_size=10)`.
   - When deploying with multiple workers (e.g. `--workers 4`), the database server must accommodate at least $4 \times 10 = 40$ connections plus headroom for administrative tools. PostgreSQL default `max_connections` (100) is sufficient.
2. **High-Frequency GPS Telemetry Ingestion**:
   - While pooled PostgreSQL handles hundreds of location updates per second, high-frequency vehicle telemetry (e.g. 10,000+ pings/sec) will eventually benefit from an in-memory or Redis buffer prior to database persistence.
3. **OSRM HTTP Keep-Alive Sockets**:
   - `OsrmRoutingAdapter` uses synchronous HTTP Keep-Alive transport (`DefaultOsrmTransport`). Because dispatch and corridor matching now run within `asyncio.to_thread`, OSRM network roundtrips no longer block the asyncio event loop.
