# Stage 3.7: End-to-End Staging Verification Report

**Date:** October 27, 2026  
**Projects Audited:**
- Backend: `C:\Users\shaha\pool engine`
- Frontend: `C:\Users\shaha\Wmate V10`
**Environment:** Windows 10 Home Single Language (64-bit), Python 3.13.15, Node.js v22  

---

## 1. Executive Summary & Area Status Scorecard

This audit verified the live staging infrastructure across PostgreSQL 18.6, backend service execution, OSRM road routing isolation, Firebase token verification, and frontend integration guardrails.

```
┌──────────────────────────────────────┬──────────┬────────────────────────────────────────────────────────┐
│ Area                                 │ Status   │ Key Evidence                                           │
├──────────────────────────────────────┼──────────┼────────────────────────────────────────────────────────┤
│ 1. PostgreSQL 18.6 & Schema          │ PASS     │ Port 5432 active, 7 tables verified, .env.staging safe │
│ 2. Backend Integration & Persistence │ PASS     │ 30/30 live PG tests passed, Uvicorn reports healthy    │
│ 3. OSRM Road Network Routing         │ BLOCKED  │ Port 5000 untouched (NYC); Kerala OSRM port 5001 missing│
│ 4. Firebase Authentication Verif.    │ PASS*    │ Project IDs match (waymate-v3); forged tokens rejected │
│ 5. Frontend Integration & Safety     │ PASS     │ 85/85 tests passed, build OK, VITE_USE_POOL_ENGINE=off │
│ 6. End-to-End Staging Lifecycle Flow │ PASS**   │ Host ride, proposal, bilateral accept, hold release OK │
└──────────────────────────────────────┴──────────┴────────────────────────────────────────────────────────┘
```
*\* Genuine protocol verification passed; live browser end-to-end token requires manual user Google sign-in.*  
*\*\* Complete database and proposal lifecycle verified; regional road network routing blocked pending Kerala OSRM on port 5001.*

---

## 2. Area 1: PostgreSQL 18.6 Environment & Schema Verification

### 2.1 Service & Port Verification
- **Windows Service:** `postgresql-x64-18` (PID: `28120`, Status: `Running`)
- **Port Listener:** `0.0.0.0:5432` (IPv4) and `[::]:5432` (IPv6)
- **Engine Version:** `PostgreSQL 18.6 on x86_64-windows, compiled by msvc-19.44.35229, 64-bit`

### 2.2 Database & Table Verification
Connected via `psycopg 3.3.6` using the local staging configuration:
- `pool_engine_staging`: Verified present with **all 7 expected tables**:
  1. `vehicles` (0 rows)
  2. `rides` (0 rows)
  3. `route_stops` (0 rows)
  4. `ride_requests` (0 rows)
  5. `join_requests` (0 rows)
  6. `seat_holds` (0 rows)
  7. `idempotency_records` (0 rows)
- `pool_engine_test`: Verified present with all 7 expected tables (isolated for automated test truncation).

### 2.3 Secrets & Git Hygiene
- `git check-ignore -v .env.staging`: `.gitignore:70:.env.*`
- `git ls-files --error-unmatch .env.staging`: Confirmed untracked.
- No database credentials, passwords, or secrets are tracked or exposed in git.

### 2.4 Silent Fallback Prevention
In `src/engine/service/service.py:1294-1300`:
```python
require_persistent = source.get("REQUIRE_PERSISTENT_STORAGE", "").lower().strip() in ("true", "1", "yes")
if require_persistent and not db_url:
    raise ValueError("Persistent storage is required (REQUIRE_PERSISTENT_STORAGE=true), but DATABASE_URL is not set.")
```
Silent fallback to in-memory storage is strictly prohibited when `REQUIRE_PERSISTENT_STORAGE=true`.

### 2.5 PostgreSQL 18.6 Compatibility
- `schema.sql` DDL, PostGIS/spatial index statements, serializable row locking (`SELECT ... FOR UPDATE`), and transactional seat holds executed without syntax errors, deprecations, or dialect incompatibilities.

---

## 3. Area 2: Backend Integration & Persistence Tests

### 3.1 Test Execution Against Live Database
Executed using `TEST_DATABASE_URL=postgresql://postgres:***@127.0.0.1:5432/pool_engine_test`:

```
============================= test session starts =============================
platform win32 -- Python 3.13.15, pytest-9.1.1, pluggy-1.7.0
rootdir: C:\Users\shaha\pool engine
collected 30 items

tests\integration\test_postgres_integration.py ..........                [ 33%]
tests\integration\test_api_postgres.py .                                 [ 36%]
tests\integration\test_cancellation_postgres.py ......                   [ 56%]
tests\integration\test_corridor_postgres.py ....                         [ 70%]
tests\integration\test_orchestrator_postgres.py ....                     [ 83%]
tests\integration\test_proposals_postgres.py .....                       [100%]

============================= 30 passed in 4.44s ==============================
```
- **Total Integration Tests Passed:** 30 / 30 (0 skipped, 0 mocked).
- **Backend Unit Tests:** 281 / 281 passed in 5.17s (`pytest tests/unit/`).

### 3.2 Database Isolation Verification
- Tested by inserting a canary vehicle record into `pool_engine_staging`.
- Executed the full 30-test suite against `pool_engine_test` (which truncates all tables on each test run).
- Confirmed the canary record in `pool_engine_staging` was **completely untouched and intact**.

### 3.3 Backend Daemon Execution & Health Probe
- Launched Uvicorn daemon on `127.0.0.1:8000` loading `.env.staging`:
  - `GET http://127.0.0.1:8000/v1/health/liveness`: Returns **HTTP 200** `{"status": "alive", "service": "pool-engine"}`.
  - `GET http://127.0.0.1:8000/v1/health/readiness`: Reports persistent storage as **`healthy`**:
    ```json
    {
      "ready": false,
      "status": "not_ready",
      "components": {
        "storage": "healthy",
        "routing": "degraded",
        "routing_error": "Routing backend health probe failed"
      }
    }
    ```

---

## 4. Area 3: OSRM Road Network Routing & Port Safeguards

### 4.1 Active Process Inspection (Port 5000)
- **Port 5000:** Occupied by PID `19208`:
  `osrm-routed.exe -a CH -p 5000 -t 8 C:\Users\shaha\AppData\Local\osrm_portable\manhattan.osrm`
- **Safeguard:** Preserved completely **untouched**, neither stopped nor modified.

### 4.2 Kerala OSRM Service (Port 5001)
- **Port 5001:** No process is listening.
- **Filesystem Audit:** Scanned `AppData\Local\osrm_portable`, `Downloads`, and `pool engine`; no Kerala `.osm.pbf` or `.osrm` files exist.
- **Silent Fallback Protection:** `.env.staging` explicitly targets `OSRM_BASE_URL=http://127.0.0.1:5001`. Connection failures to port 5001 fail fast and do not silently fall back to port 5000.
- **NYC Cross-Contamination Test:** Querying port 5000 with Kerala coordinates snaps 15,678 km away to Catalpa Avenue, New York, demonstrating why port isolation is strictly required.
- **Status:** **BLOCKED** pending approval to download and contract Kerala map data.

---

## 5. Area 4: Firebase Authentication Verification

### 5.1 Project ID Consistency
- Frontend (`src/config/firebase.ts`): `waymate-v3`
- Backend (`.env.staging`): `FIREBASE_PROJECT_ID=waymate-v3`
- Verified exact match across frontend and backend configurations.

### 5.2 Cryptographic Verification & Rejection Tests
- 9 / 9 tests in `tests/unit/test_firebase_auth.py` passed.
- Live `FirebaseAuthProvider` tests verified:
  - Missing `Authorization` header: `authenticated = False`
  - Garbage Bearer token: `authenticated = False`
  - Forged JWT token: `authenticated = False`
- **Requirements for Live Browser Verification:**
  - A real Firebase ID token minted from a browser Google sign-in session.
  - Optional service account JSON key for local token revocation checks.

---

## 6. Area 5: Frontend Integration & Safety Verification

### 6.1 Test Suites & Production Build
- **Vitest Suites:** 85 / 85 tests passed in 816ms:
  - `tests/google-auth.test.ts` (14 passed)
  - `tests/pool-engine-client.test.ts` (22 passed)
  - `tests/pool-engine-adapter.test.ts` (18 passed)
  - `tests/pool-engine-workflow.test.ts` (5 passed)
  - `tests/dev-mock-security.test.ts` (13 passed)
  - `tests/phone-auth.test.ts` (6 passed)
  - `tests/mfa-service.test.ts` (7 passed)
- **Production Build:** `npm run build` completed with exit code 0 in 4.46s.

### 6.2 Feature Flag & Fallback Safeguards
- `VITE_USE_POOL_ENGINE=false` remains strictly the default in code (`poolEngineConfig.ts`) and environment files.
- In `src/services/ride/rideService.ts`: When Pool Engine is active, API errors propagate immediately without falling back to Firestore.
- Firestore ride queries are never mixed with PostgreSQL ride data.

---

## 7. Area 6: End-to-End Staging Lifecycle Flow

Executed against `pool_engine_staging`:

```
[Step 1] Health & Readiness Check
  - Liveness: HTTP 200 OK
  - Storage Component: healthy

[Step 2] Host Ride Creation
  - Created Ride ID: ride-host-1793116061-usr-stag
  - Persisted in PostgreSQL 'rides' table (status: SCHEDULED)

[Step 3] Passenger Ride Request & Proposal
  - Created Request ID: req-9cdebe36-fbb4-464b-a40a-02508faec50d
  - Created Proposal ID: prop-053202fd42b5
  - Persisted in PostgreSQL 'seat_holds' table (seat_count: 1)

[Step 4] Bilateral Mutual Acceptance
  - Host Accepts: status=200, host_accepted=True, is_confirmed=False
  - Traveller Accepts: status=200, traveller_accepted=True, is_confirmed=True
  - Mutual confirmation triggered: 4 stops added to 'route_stops' table
    (Origin Waypoint -> Pickup -> Dropoff -> Destination Waypoint)

[Step 5] Proposal Decline & Seat Release
  - Created 2nd proposal and verified hold
  - Declined proposal: status=DECLINED
  - Verified seat hold was immediately released from PostgreSQL (0 holds remaining)

[Step 6] Persistence Across Fresh Connection
  - Storage connection terminated and reconnected from scratch
  - Reloaded Ride ID and confirmed 4 stops, driver, and seats survived intact

[Step 7] Cleanup
  - Staging verification records cleaned up cleanly respecting foreign keys
```

---

## 8. Remaining Blockers & Single Recommended Next Action

### Remaining Blockers:
1. **Kerala Road Network Routing (Port 5001):**
   - The Kerala OpenStreetMap dataset (`.osm.pbf`) is not present on disk.
   - Port 5001 OSRM service is offline.
   - Required before real driving distance/duration calculations can be verified in staging.

### Single Recommended Next Action:
**Authorize downloading the official Kerala OSM extract (`kerala-latest.osm.pbf`, ~120 MB) from Geofabrik and processing it with the existing portable OSRM binaries (`osrm-extract.exe` and `osrm-contract.exe`) to launch the isolated Kerala routing service on port 5001.**
