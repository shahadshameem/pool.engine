# Stage E — Failure and Recovery Test Results

**Date**: October 30, 2026  
**Objective**: Verify the system's ability to survive unexpected process crashes, service degradation, network partitions, and race conditions without corrupting vehicle capacity or confirmed passenger bookings.

---

## 1. Failure Injection Matrix & Verified Outcomes

```
+----+------------------------------------+---------------------------------------------+---------------+
| #  | Failure Scenario                   | Engine & Frontend Recovery Mechanism        | Verification  |
+----+------------------------------------+---------------------------------------------+---------------+
| 1  | Pool Engine API Restart            | In-flight requests drain; cold-start buffer | PASS (Verified)|
| 2  | OSRM Service Unavailable           | 3-state Circuit Breaker -> Geometric bound  | PASS (Verified)|
| 3  | PostgreSQL Unavailable             | Readiness probe fails (503); clean errors   | PASS (Verified)|
| 4  | PostgreSQL Restored                | Transparent pool reconnection               | PASS (Verified)|
| 5  | API Request Timeout (> 4.0s)       | AbortController aborts; circuit breaker logs| PASS (Verified)|
| 6  | Duplicate Capacity Event           | Idempotency token deduplication             | PASS (Verified)|
| 7  | Out-of-Order Capacity Sync         | HTTP 409 Conflict (STALE_VERSION)           | PASS (Verified)|
| 8  | Stale Version Update               | Monotonic version comparison rejects update | PASS (Verified)|
| 9  | Browser Closed with Pending Outbox | Outbox persisted before fetch; re-flushed   | PASS (Verified)|
| 10 | Container / Process Restart        | Disk-backed PostgreSQL volume retains state | PASS (Verified)|
| 11 | Host / VPS Reboot Recovery         | Auto-restart policy + Pre-dispatch sync     | PASS (Verified)|
| 12 | Concurrent Booking Contention      | Atomic Firestore runTransaction & PG locks  | PASS (Verified)|
+----+------------------------------------+---------------------------------------------+---------------+
```

---

## 2. Detailed Failure Scenario Analysis

### 1. Pool Engine Process Restart (`test_resilience_api_service_restart_recovery`)
- **Injection**: Service process abruptly closed and restarted.
- **Observed Behavior**:
  - In `src/engine/service/app.py`, `lifespan.shutdown` initiates a 5.0-second drain period for active HTTP connections.
  - Upon restart, `_pending_capacities` buffers any capacity sync events received before vehicle registration completes.
  - When the driver's vehicle registers, buffered seat counts are automatically applied without throwing conflict errors.
- **Result**: **PASS**.

### 2. OSRM Service Unavailable (`test_resilience_kerala_offline_manhattan_healthy`)
- **Injection**: Port 5001 closed or set to non-existent port (`127.0.0.1:5998`).
- **Observed Behavior**:
  - `RegionalRoutingRouter` detects unreachable port during health check; marks `in-kl-tvm.healthy = false`.
  - Frontend client detects 3 consecutive request failures; `poolEngineCircuitBreaker` transitions from `CLOSED` to `OPEN`.
  - Frontend calls fail-fast and fall back to Haversine corridor distance matching.
  - **Zero ride searches or booking requests fail for campus users**.
- **Result**: **PASS**.

### 3. PostgreSQL Database Outage & Restoration
- **Injection**: PostgreSQL connection severed.
- **Observed Behavior**:
  - `GET /v1/health/readiness` immediately reports `ready: false` with HTTP 503 (`storage: degraded`).
  - Read-only health probe protects against routing dispatch to an engine that cannot persist assignments.
  - When PostgreSQL is brought back online, connection pool reconnects transparently on next request.
  - `GET /v1/health/readiness` returns HTTP 200 (`ready: true`).
- **Result**: **PASS**.

### 4. Browser Closed with In-Flight Outbox Event (`tests/pooling-recovery.test.ts` Test A & B)
- **Injection**: Host accepts booking, writing event to outbox, but browser window is terminated before HTTP response completes.
- **Observed Behavior**:
  - `CapacitySyncManager.queueSync()` persists the update to `localStorage` **prior** to invoking `fetch()`.
  - When the browser restarts and the application reloads, `window.addEventListener('online')` and `document.addEventListener('visibilitychange')` automatically flush the outbox.
  - Idempotency token prevents duplicate seat decrements.
- **Result**: **PASS**.

### 5. Concurrent Booking Contention & Zero Over-Allocation (`tests/p5-concurrency.test.ts`)
- **Injection**: 5 simultaneous booking requests sent for a ride with only 2 available seats.
- **Observed Behavior**:
  - Atomic Firestore `runTransaction` reads current `availableSeats`.
  - The first two requests decrement seats ($2 \rightarrow 1 \rightarrow 0$) and succeed.
  - Remaining 3 requests encounter `availableSeats < requestedSeats` within the transaction, aborting with structured `SEATS_UNAVAILABLE` errors.
  - Final confirmed seat count strictly equals 2; zero over-allocation.
- **Result**: **PASS**.

---

## 3. Durability Evaluation Across Restarts

| Storage Tier | Data Residing Here | Durability Guarantee | Recovery Mechanism |
|---|---|---|---|
| **Cloud Firestore** | Confirmed bookings, user profiles, active rides | **Authoritative & Permanent** | Multi-region replication by Google Cloud. Survived by all client/engine restarts. |
| **PostgreSQL Database** | Dispatch history, vehicles, route stops | **Persistent (Disk-Backed)** | Stored in Docker volume `pgdata_production` or host directory `pg_portable/data`. Survives reboot. |
| **Write-Ahead Outbox** | Pending capacity sync events | **Durable per Browser** | Stored in `localStorage` before network transmission. Survives browser restart. |
| **In-Memory Cache** | Cold-start buffer, route cache | **Ephemeral** | Reconstructed automatically upon startup via pre-dispatch reconciliation with Firestore. |
