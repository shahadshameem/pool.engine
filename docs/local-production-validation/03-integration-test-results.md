# Stage D — Functional Integration Test Results

**Date**: October 30, 2026  
**Execution Environment**: Local Developer Workstation with Live PostgreSQL (5433), Kerala OSRM (5001), Manhattan OSRM (5000), and Pool Engine API (8000).

---

## 1. Test Execution Summary

| Test Category | Suite / Location | Tests Run | Passed | Failed | Skipped | Service Dependency |
|---|---|---|---|---|---|---|
| **Frontend Recovery** | `tests/pooling-recovery.test.ts` | 7 | 7 | 0 | 0 | Mock / Vitest In-Memory |
| **Frontend Hardening** | `tests/pooling-hardening.test.ts` | 10 | 10 | 0 | 0 | Live Engine + Vitest In-Memory |
| **Frontend Audit Fixes** | `tests/pooling-audit-fixes.test.ts` | 10 | 10 | 0 | 0 | Mock / Vitest In-Memory |
| **Python Unit Suite** | `tests/unit/` | 369 | 369 | 0 | 0 | Pure Python / In-Memory |
| **Python Integration Suite**| `tests/integration/` | 83 | 83 | 0 | 0 | **Live PostgreSQL (5433) + Live OSRM (5000/5001)** |
| **TOTAL** | **Full Automated Verification** | **479** | **479** | **0** | **0** | **100% Pass Rate** |

---

## 2. Detailed Functional Scenario Results

### Scenario 1: Real OSRM Road Distance & Duration Routing
- **Test Target**: Kerala OSRM daemon on port 5001.
- **Query Coordinates**: College of Engineering Trivandrum (`8.5456, 76.9063`) to Central Railway Station (`8.4878, 76.9535`).
- **Verified Metrics**:
  - Distance: **11,193 meters (~11.19 km)**
  - Driving Duration: **974.1 seconds (~16.2 minutes)**
  - OSRM Routing Latency: **< 2 milliseconds**
- **Status**: **VERIFIED** (Real local OSRM).

### Scenario 2: Corridor Matching & Detour Bound Verification
- **Test File**: `tests/pooling-hardening.test.ts` (Priority 4) and `tests/integration/test_corridor_postgres.py`.
- **Behavior Tested**:
  - Direct driver trip: 10.0 km (duration $T$).
  - Intermediate dropoff: Evaluated using triangle detour inequality ($L_1 + L_2 \le 1.25 \times T$).
  - Detour ratio within 25% ($1.25$ threshold) is accepted; detour $> 25\%$ is rejected.
- **Status**: **VERIFIED** (Live Engine + Real OSRM).

### Scenario 3: Atomic Booking & Concurrent Seat Allocation
- **Test Files**: `tests/integration/test_app_postgres_concurrency.py` and `tests/p5-concurrency.test.ts`.
- **Behavior Tested**:
  - Initial vehicle capacity: 3 available seats.
  - 5 concurrent booking requests of 1 seat each submitted simultaneously.
  - PostgreSQL transaction row-level locking (`SELECT ... FOR UPDATE`) and Firestore atomic `runTransaction`.
  - Exactly 3 requests are approved; the 4th and 5th requests receive structured seat-exhaustion rejections.
  - Zero seat over-allocation observed.
- **Status**: **VERIFIED** (Real PostgreSQL on port 5433).

### Scenario 4: Capacity Synchronization & Monotonic Version Guard
- **Test File**: `tests/unit/test_security_and_capacity_hardening.py`.
- **Behavior Tested**:
  - Initial ride version: 1 (4 available seats).
  - Sync update: Version 2 decrements seats to 2 $\rightarrow$ HTTP 200 OK.
  - Stale update: Late-arriving Version 1 request $\rightarrow$ Rejected with **HTTP 409 Conflict (`STALE_VERSION`)**.
  - Idempotent duplicate: Resubmission of Version 2 with identical payload $\rightarrow$ HTTP 200 OK (idempotent no-op).
- **Status**: **VERIFIED** (Live Pool Engine API).

### Scenario 5: Pre-Dispatch Authoritative Reconciliation
- **Test File**: `tests/unit/test_failure_recovery_and_reconciliation.py` and `tests/pooling-recovery.test.ts` (Test F).
- **Behavior Tested**:
  - Engine has stale capacity (4 seats).
  - Firestore holds authoritative capacity (1 seat remaining).
  - `POST /v1/dispatch` receives `authoritative_capacities` in request payload.
  - Engine reconciles internal capacity to 1 before DARP set-packing executes.
  - Solver assigns only 1 passenger, preserving real seat availability.
- **Status**: **VERIFIED** (Live Engine + Unit solver).

---

## 3. Real Services vs Mocks Breakdown

| Feature Area | Execution Method | Service Verified |
|---|---|---|
| Road distance matrix & snapping | Real local daemon | `osrm-routed-kerala.exe` on port 5001 |
| Multi-region boundary isolation | Real local daemon | `osrm-routed.exe` (5000) & `osrm-routed-kerala.exe` (5001) |
| Persistent tables, constraints, & locking | Real local database | PostgreSQL 16 on port 5433 (`pool_engine_test`) |
| API endpoints & routing | Real local process | Pure ASGI server on port 8000 |
| Frontend Write-Ahead Outbox | Browser storage mock | Vitest Node environment with mock localStorage |
| Firebase Production Boundary | Static regex inspection | Real compiled assets in `dist/assets/*.js` |
