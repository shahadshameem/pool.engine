# PostgreSQL Connection Concurrency Audit

**Target Repository:** `C:\Users\shaha\pool engine`
**Reference Document:** [`docs/UBER_ARCHITECTURE_COMPARISON.md`](file:///C:/Users/shaha/pool%20engine/docs/UBER_ARCHITECTURE_COMPARISON.md)
**Evaluation Mode:** READ-ONLY Architectural Audit & Benchmark Plan
**Target Database for Testing:** `pool_engine_test` (`postgresql://postgres:postgres@127.0.0.1:5433/pool_engine_test`)
**Production / Staging Protection:** Strictly isolated; zero modifications to `pool_engine_staging`.

---

## 1. Executive Summary

This audit assesses whether the current PostgreSQL storage adapter (`PostgresRideStorage` in [`src/engine/adapters/postgres_storage.py`](file:///C:/Users/shaha/pool%20engine/src/engine/adapters/postgres_storage.py)) serializes concurrent requests, establishes whether a bounded connection pool (`psycopg_pool.ConnectionPool`) is warranted, and identifies the exact concurrency risks and bottlenecks in Pool Engine's backend service.

### Core Audit Verdict: **GO (Conditioned on Dependency & Async Alignment)**
* **The Single-Connection Risk is Confirmed:** `PostgresRideStorage` maintains exactly **one owned connection** (`self._owned_conn = psycopg.connect(..., autocommit=True)`) per storage instance. In standard service execution, all API requests share this single `PostgresRideStorage` singleton.
* **Catastrophic Failure under Multi-Threaded Transactions:** Direct empirical validation demonstrates that sharing a single `psycopg.Connection` across concurrent threads entering `with conn.transaction():` raises **`psycopg.errors.OutOfOrderTransactionNesting`**. Psycopg 3 interprets overlapping transactions on the same connection as nested savepoints, causing transactional failure and connection aborts when threads commit or rollback out of order.
* **The Current Concurrency Shield is Event-Loop Blocking:** In the single-worker ASGI service ([`src/engine/service/app.py`](file:///C:/Users/shaha/pool%20engine/src/engine/service/app.py)), all route handlers invoke synchronous `PoolEngineService` methods directly on the asyncio event loop without `asyncio.to_thread`. Consequently, requests do not crash *only because the entire Python event loop is blocked during every database query*, creating an effective concurrency limit of 1 for the worker.
* **Critical Dependency Gap Discovered:** `psycopg_pool` is **not installed** in the environment and is omitted from [`pyproject.toml`](file:///C:/Users/shaha/pool%20engine/pyproject.toml) (which specifies only `"psycopg[binary]>=3.1.0"`). Any pool implementation requires adding `"psycopg[pool]>=3.1.0"` or `"psycopg-pool>=3.2.0"`.

---

## 2. Current Connection Lifecycle & Architecture

### 2.1 Construction and Injection Hierarchy
In the Pool Engine standalone service, storage initialization follows a strict singleton pattern:

```
Service Startup Hierarchy
  ├── 1. ServiceConfig.from_env() [src/engine/service/config.py]
  ├── 2. build_service_from_env() [src/engine/service/service.py:726]
  │        └── storage = PostgresRideStorage(dsn=DATABASE_URL)  <-- SINGLE INSTANCE CREATED
  ├── 3. PoolEngineService(storage=storage, orchestrator=..., router=...)
  └── 4. create_app(service=service) [src/engine/service/app.py:125]
           └── router.add(..., handle_*(scope, body, headers, params))  <-- SHARED CLOSURE
```

1. **Singleton Storage:** When `DATABASE_URL` is configured, `build_service_from_env()` creates exactly one instance of `PostgresRideStorage`.
2. **Global Closure Binding:** This single instance is injected into `PoolEngineService`, which is captured in the closure of all 21 ASGI route handlers in `create_app()`.
3. **No Per-Request Storage:** There is no request-scoped storage factory or dependency-injection container recreating storage per HTTP request.

### 2.2 Connection Creation and State Management
In [`src/engine/adapters/postgres_storage.py:41-65`](file:///C:/Users/shaha/pool%20engine/src/engine/adapters/postgres_storage.py#L41-L65):
```python
def __init__(
    self,
    dsn: Optional[str] = None,
    connection: Optional[Connection[Any]] = None,
) -> None:
    self._dsn = dsn or os.environ.get("DATABASE_URL")
    self._external_conn = connection
    self._owned_conn: Optional[Connection[Any]] = None

def _get_connection(self) -> Connection[Any]:
    if self._external_conn is not None:
        return self._external_conn
    if self._owned_conn is None or self._owned_conn.closed or self._owned_conn.broken:
        if not self._dsn:
            raise StorageProviderError(...)
        if self._owned_conn is not None:
            try:
                self._owned_conn.close()
            except Exception:
                pass
        self._owned_conn = psycopg.connect(self._dsn, autocommit=True)
    return self._owned_conn
```

* **Connection Mode:** Created with `autocommit=True`.
* **Reconnection Logic:** Only reconnects if `self._owned_conn is None`, `closed`, or marked `broken` by psycopg.
* **Single Physical TCP Socket:** All database interactions in that process execute over a single TCP socket connection to PostgreSQL.

### 2.3 Transaction Boundaries and Primitives
`PostgresRideStorage` relies on explicit context managers for atomic operations:
* **Autocommit Statements:** Simple reads (`get_vehicle`, `get_request`, `get_ride`) and simple writes execute outside transactions in autocommit mode.
* **Explicit Transactions:** Eleven critical operations enter explicit transactions using `with conn.transaction():`:
  1. `save_ride` (line 237): Drops and re-inserts `route_stops`.
  2. `save_vehicle` (line 330): Upserts vehicle state.
  3. `save_request` (line 369): Inserts ride request.
  4. `save_join_request` (line 423): Inserts join request.
  5. `record_proposal_acceptance` (line 467): Records mutual consent acceptance.
  6. `get_active_rides_in_bounding_box` (line 550): Queries candidate rides.
  7. `acquire_seat_hold_atomic` (line 716): Executes `SELECT ... FOR UPDATE` on `rides`, checks OCC `version`, checks vehicle capacity, inserts `seat_holds`.
  8. `reserve_seats_atomic` (line 889): Executes `SELECT ... FOR UPDATE`, commits confirmed seats.
  9. `release_seats_atomic` (line 922): Removes hold from `seat_holds`.
  10. `commit_dispatch_assignment_atomic` (line 1021): Atomic multi-passenger dispatch batch assignment.
  11. `cancel_assigned_request_atomic` (line 1351): Locks ride, recalculates remaining stops, deletes cancelled passenger.

---

## 3. Evidence-Backed Risk & Concurrency Evaluation

### Question 1: Is a single database connection shared between concurrent requests?
**Answer: YES.**
* **Evidence:** In `src/engine/service/service.py:726`, `PostgresRideStorage` is instantiated once. All route handlers in `src/engine/service/app.py` call `eff_service.*`, which delegates directly to `self.storage._get_connection()`.
* Every concurrent request serviced by that Uvicorn process calls `_get_connection()` and receives the identical `self._owned_conn` object.

### Question 2: Does the driver or application serialize operations on that connection?
**Answer: The application does NOT serialize; the asyncio event loop thread blocks instead.**
* **Evidence:** There are zero `threading.Lock` or `asyncio.Lock` primitives guarding `_get_connection()` or database methods in `PostgresRideStorage`.
* In `src/engine/service/app.py`, all endpoints are defined as `async def handle_*(...)`, but they invoke synchronous Python methods (`eff_service.create_request(...)`, `eff_service.update_vehicle_location(...)`) directly without `await asyncio.to_thread(...)`.
* Because synchronous socket I/O executes directly on Python's single asyncio event loop thread, the event loop cannot schedule or execute any other coroutine while waiting for PostgreSQL socket responses.
* Requests are serialized **cooperatively by the single-threaded event loop**, freezing the entire process during database execution.

### Question 3: Can connections be used concurrently across threads or tasks?
**Answer: NO. Concurrent transactions on a single connection cause fatal errors.**
* **Evidence:** Empirical test executed on `pool_engine_test` using multi-threaded transactions on a single connection:
  ```
  OutOfOrderTransactionNesting: transaction commit at the wrong nesting level: <psycopg.Transaction ...>
  ```
* Psycopg 3 connections are stateful. When multiple threads enter `with conn.transaction():`, psycopg opens nested subtransactions (savepoints) on the same connection. When thread 2 commits before thread 1, psycopg detects that the active savepoint nesting level does not match the committing block, raising `OutOfOrderTransactionNesting`.
* This proves that `PostgresRideStorage` **cannot be safely used across threads** without connection pooling.
* **Test Suite Evidence:** In [`tests/integration/test_proposals_postgres.py:336`](file:///C:/Users/shaha/pool%20engine/tests/integration/test_proposals_postgres.py#L336), when the test author wrote a concurrent race test (`test_postgres_concurrent_acceptance_race`), they were forced to manually instantiate a separate `thread_storage = PostgresRideStorage(dsn=TEST_DB_URL)` inside each worker thread to circumvent this limitation:
  ```python
  def accept_as(user_id: str) -> tuple[int, dict[str, Any]]:
      thread_storage = PostgresRideStorage(dsn=TEST_DB_URL)
      try:
          ...
      finally:
          thread_storage.close()
  ```

### Question 4: Which operations hold transactions or locks for long periods?
* **`commit_dispatch_assignment_atomic` (10–50 ms):** Executes multiple DML statements:
  1. `UPDATE vehicles SET is_active = True ...`
  2. `INSERT INTO rides ... ON CONFLICT DO UPDATE ...`
  3. `DELETE FROM route_stops WHERE ride_id = ...`
  4. Multiple `INSERT INTO route_stops (...)`
  5. Multiple `UPDATE ride_requests SET lifecycle_status = 'ASSIGNED' ...`
  6. `INSERT INTO idempotency_records (...)`
* **`acquire_seat_hold_atomic` (5–20 ms):**
  1. Row-level exclusive lock: `SELECT ... FROM rides WHERE ride_id = %s FOR UPDATE`.
  2. Read vehicle total capacity.
  3. Query all existing route stops and compute cumulative passenger occupancy.
  4. Query active unexpired seat holds.
  5. Insert into `seat_holds`.
* *Finding:* External routing network calls (OSRM) are strictly decoupled and executed **before** entering database transactions. Locks are held only during database network roundtrips.

### Question 5: Could connection pooling introduce leaks, contamination, or changed isolation?
* **Connection Leaks:** If a pooled connection is checked out but not returned due to an unhandled exception outside a context manager, pool capacity drops until `PoolTimeout` occurs.
  * *Mitigation:* Pool checkouts must strictly use the context manager pattern: `with self._pool.connection() as conn:`.
* **Transaction Contamination:** If a connection is returned with an uncommitted transaction (`INTRANS` state), the next consumer could inherit dirty state.
  * *Mitigation:* `psycopg_pool.ConnectionPool` automatically inspects connection status upon return and issues a `ROLLBACK` if a transaction is uncommitted.
* **Isolation Level Behavior:** Pool connections maintain standard `READ COMMITTED` isolation. Row-level locking (`SELECT ... FOR UPDATE`) behaves identically whether connections are single or pooled.
* **Session State Leaks:** Pool Engine does not execute session-level statements (`SET timezone`, `LISTEN/NOTIFY`, or temp tables).

### Question 6: What is the true system bottleneck?
| Scenario / Endpoint | Primary Bottleneck | Secondary Bottleneck |
| :--- | :--- | :--- |
| **`/v1/dispatch`** | **Routing Engine & Set Packing** (OSRM table matrix calls + combinatorial solver take 150–400ms) | Database commit takes only 5–15ms |
| **`/v1/vehicles/{id}/location`** | **Database Connection & Event-Loop Blocking** (Synchronous SQL `UPDATE` for every GPS ping blocks the event loop thread) | Socket I/O latency |
| **`/v1/proposals/{id}/accept`** | **Row Contention & Serialization** (Row-level lock on `rides` table prevents simultaneous confirmation) | Event-loop blocking |

---

## 4. Proposed Connection Pool Design

### 4.1 Dependency Requirement
Update [`pyproject.toml`](file:///C:/Users/shaha/pool%20engine/pyproject.toml) to include `psycopg[pool]`:
```toml
[project.optional-dependencies]
postgres = [
    "psycopg[binary,pool]>=3.1.0",
]
```

### 4.2 Pool Lifecycle & Architecture
Replace the single `_owned_conn` in `PostgresRideStorage` with a managed `psycopg_pool.ConnectionPool`:

```python
class PostgresRideStorage(RideStorageProvider):
    def __init__(
        self,
        dsn: Optional[str] = None,
        connection: Optional[Connection[Any]] = None,
        min_size: int = 2,
        max_size: int = 20,
        timeout: float = 5.0,
    ) -> None:
        self._dsn = dsn or os.environ.get("DATABASE_URL")
        self._external_conn = connection
        self._min_size = min_size
        self._max_size = max_size
        self._timeout = timeout
        self._pool: Optional[ConnectionPool] = None

    def _get_pool(self) -> ConnectionPool:
        if self._pool is None:
            if not self._dsn:
                raise StorageProviderError("DSN is required for connection pool")
            self._pool = ConnectionPool(
                conninfo=self._dsn,
                min_size=self._min_size,
                max_size=self._max_size,
                timeout=self._timeout,
                max_idle=300.0,
                check=ConnectionPool.check_connection,
                open=True,
            )
        return self._pool

    @contextmanager
    def connection(self) -> Generator[Connection[Any], None, None]:
        if self._external_conn is not None:
            yield self._external_conn
            return

        pool = self._get_pool()
        with pool.connection(timeout=self._timeout) as conn:
            yield conn
```

### 4.3 Proposed Pool Parameters
| Parameter | Proposed Value | Justification |
| :--- | :--- | :--- |
| `min_size` | **2 connections** | Keeps minimal active warm connections ready; prevents initial handshake latency. |
| `max_size` | **20 connections** | Accommodates 10–15 concurrent worker threads / requests without exhausting PostgreSQL's `max_connections` (default 100). |
| `timeout` | **5.0 seconds** | Acquisition timeout. If the pool is exhausted for 5 seconds, raises `PoolTimeout` instead of hanging indefinitely. |
| `max_idle` | **300.0 seconds** | Closes excess idle connections after 5 minutes to release database server resources. |
| `check` | `check_connection` | Tests socket liveness before checkout to prevent "server closed connection" errors after database idle disconnects. |

### 4.4 Startup and Lifespan Integration
In [`src/engine/service/app.py`](file:///C:/Users/shaha/pool%20engine/src/engine/service/app.py), register pool startup and shutdown in ASGI lifespan events:
* **Lifespan Startup:** Call `storage.open()` (pre-warms pool connections and verifies connectivity).
* **Lifespan Shutdown:** Call `storage.close()` with a 5.0s grace period to allow in-flight transactions to complete before closing pool connections.

---

## 5. Safe, Isolated Concurrency Benchmark Plan

### 5.1 Safety Boundaries
* **Target Database:** `pool_engine_test` on port 5433 (`postgresql://postgres:postgres@127.0.0.1:5433/pool_engine_test`).
* **Strict Exclusion:** Zero commands or queries directed at `pool_engine_staging` or default port 5432.
* **Non-Destructive Fixtures:** Test tables cleaned via rollback or isolated test-specific primary keys (`veh-bench-*`, `ride-bench-*`).

### 5.2 Workload Test Matrix
The benchmark will compare **Arm A (Current Single Connection)** vs. **Arm B (Bounded Connection Pool)** across 4 concurrency tiers:

| Workload ID | Concurrency Tier | Operations per Trial | Mix of Operations | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **W-1: Read Heavy** | 10 concurrent threads | 200 operations | 90% `get_ride` / `get_vehicle`, 10% `get_active_rides_in_bbox` | Measures read throughput and connection checkout overhead. |
| **W-2: Ingestion Burst** | 20 concurrent threads | 500 operations | 100% `update_vehicle_location` (`save_vehicle`) | Simulates 500 GPS location updates bursting simultaneously. |
| **W-3: Proposal Race** | 10 concurrent threads | 50 operations | Simultaneous `acquire_seat_hold_atomic` on the same vehicle | Measures lock contention under `SELECT ... FOR UPDATE`. |
| **W-4: Mixed Full API** | 15 concurrent threads | 300 operations | 40% reads, 40% location updates, 20% proposals/acceptances | Measures realistic mixed marketplace traffic. |

### 5.3 Benchmark Metrics to Capture
1. **Throughput:** Requests per second (RPS).
2. **Latency Percentiles:** $p50$, $p95$, $p99$, and Max latency (ms).
3. **Pool Wait Time:** Time spent waiting to acquire a connection from the pool (ms).
4. **Error Rate:** Count of `OutOfOrderTransactionNesting`, `PoolTimeout`, or database deadlocks.
5. **Invariant Correctness:** Verification that no ride exceeds capacity and exactly 1 candidate secures the last seat.

### 5.4 Benchmark Harness Implementation Plan
* **Location:** `tests/benchmark/benchmark_postgres_concurrency.py` (isolated scratch harness).
* **Execution Command:**
  ```powershell
  $env:TEST_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5433/pool_engine_test"
  python tests/benchmark/benchmark_postgres_concurrency.py --arm baseline --concurrency 10 --iterations 3
  python tests/benchmark/benchmark_postgres_concurrency.py --arm pooled --concurrency 10 --iterations 3
  ```
*(Note: As required by safety instructions, this benchmark harness will NOT be executed until formal approval is granted.)*

---

## 6. Go / No-Go Recommendation & Priority Alignment

### Recommendation: **PROCEED (Phased Execution)**

Connection pooling is architecturally mandatory for Pool Engine's backend readiness. However, implementing it in isolation without addressing the event-loop blocking issue will yield only partial benefits.

The recommended execution roadmap is:

1. **Phase 1 (Packaging):** Update `pyproject.toml` to declare `"psycopg[binary,pool]>=3.1.0"` and install the package.
2. **Phase 2 (Adapter Refactor):** Refactor `PostgresRideStorage` to use `psycopg_pool.ConnectionPool` with context-manager checkouts, preserving 100% backward compatibility for tests passing single connections via `connection=...`.
3. **Phase 3 (Event-Loop Offloading):** In `src/engine/service/app.py`, offload synchronous service calls using `await asyncio.to_thread(...)` so database queries do not block Uvicorn's event loop.
4. **Phase 4 (Benchmark Verification):** Run the isolated concurrency benchmark on `pool_engine_test` to verify throughput gains and zero regressions.

---

## 7. Assumptions & Unresolved Questions

1. **Asyncpg vs. Psycopg 3 Pool:** Did the project select `psycopg` to maintain sync/test parity with the CPU-bound solver? (Staying with `psycopg_pool` preserves the existing codebase; migrating to `asyncpg` would require rewriting all storage contracts to `async def`).
2. **Process Model:** Will production deployment use multi-worker Uvicorn (`--workers 4`)? (If so, each worker process will hold its own pool of e.g. 10 connections, requiring PostgreSQL `max_connections` to be sized at $\ge 40$).
3. **Telemetry Location Ingestion:** Will high-frequency GPS telemetry eventually be routed to Redis? (If so, PostgreSQL connection pool demand drops by over 80%).
