# Waymate + Pool Engine: Staging Verification Runbook

This runbook outlines the repeatable, local-first staging architecture and verification steps for **Waymate** (React) and **Pool Engine** (FastAPI/ASGI 3).

> [!IMPORTANT]
> **Safety Guardrails:**
> - Zero cost: uses local processes and free-tier infrastructure.
> - Never deploy to production hosting during staging verification.
> - `VITE_USE_POOL_ENGINE=false` remains the default in repository configuration.
> - Do not commit real passwords, credentials, service-account JSON files, or private keys.

---

## 1. Staging Architecture Topology

```
┌────────────────────────────────┐         ┌────────────────────────────────┐
│   Waymate React Frontend       │         │   Pool Engine Backend (ASGI 3) │
│   Origin: http://localhost:5173│         │   Port: 8000                   │
│   VITE_USE_POOL_ENGINE=true    │────────▶│   ENVIRONMENT=staging          │
│   Firebase Web SDK (Google IdP)│         │   Firebase Admin SDK Token Ver.│
└────────────────────────────────┘         └────────────────┬───────────────┘
                                                            │
                            ┌───────────────────────────────┴───────────────────────────────┐
                            ▼                                                               ▼
             ┌─────────────────────────────┐                                 ┌─────────────────────────────┐
             │ PostgreSQL Staging Database │                                 │ Kerala OSRM Road Router     │
             │ Port: 5432                  │                                 │ Port: 5001 (Isolated)       │
             │ DB: pool_engine_staging     │                                 │ Dataset: kerala-latest.osrm │
             └─────────────────────────────┘                                 └─────────────────────────────┘
```

---

## 2. Prerequisites Checklist

| Component | Minimum Version | Local Status / Path |
| :--- | :--- | :--- |
| **Python** | 3.11+ | Python 3.13.15 available (`python.exe`) |
| **Node.js / npm** | Node 18+, npm 9+ | Node 18+ available |
| **OSRM Toolchain** | v5.26+ | Available at `C:\Users\shaha\AppData\Local\osrm_portable\osrm-v26.10.0-win32-x64-Release` |
| **PostgreSQL** | 14+ | Required: Local instance or free-tier managed DB (port 5432) |
| **Firebase Project** | `waymate-v3` | Google Provider enabled in Firebase Console |

---

## 3. Step-by-Step Service Setup (Windows PowerShell)

### Step 3.1: Prepare & Start Kerala OSRM (Port 5001)

*Note: The existing Manhattan OSRM process runs on port 5000. Kerala OSRM runs on port 5001 to prevent conflicts.*

1. **Obtain Kerala OSM Extract** (Place in `C:\Users\shaha\AppData\Local\osrm_portable\kerala-latest.osm.pbf`):
   ```powershell
   # Direct download from Geofabrik (~80-120 MB):
   curl.exe -L -o "C:\Users\shaha\AppData\Local\osrm_portable\kerala-latest.osm.pbf" "https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf"
   ```

2. **Extract Road Network using Car Profile**:
   ```powershell
   cd "C:\Users\shaha\AppData\Local\osrm_portable"
   & ".\osrm-v26.10.0-win32-x64-Release\osrm-extract.exe" -p ".\osrm-v26.10.0-win32-x64-Release\profiles\car.lua" "kerala-latest.osm.pbf"
   ```

3. **Contract Graph for Fast Routing (CH algorithm)**:
   ```powershell
   & ".\osrm-v26.10.0-win32-x64-Release\osrm-contract.exe" "kerala-latest.osrm"
   ```

4. **Start OSRM Daemon on Port 5001**:
   ```powershell
   & ".\osrm-v26.10.0-win32-x64-Release\osrm-routed.exe" -a CH -p 5001 -t 4 "kerala-latest.osrm"
   ```

5. **Verify Kerala Route Probe (CET to TVM Central)**:
   ```powershell
   Invoke-RestMethod -Uri "http://127.0.0.1:5001/route/v1/driving/76.9054,8.5469;76.9528,8.4875?overview=false"
   # Expected: code == 'Ok', duration ~1200-1800s, distance ~11000-14000m
   ```

---

### Step 3.2: Initialize PostgreSQL Staging Database

1. **Create Staging and Test Databases**:
   ```sql
   -- Execute in psql as superuser:
   CREATE USER pool_staging_user WITH PASSWORD 'staging_password';
   CREATE DATABASE pool_engine_staging OWNER pool_staging_user;
   CREATE DATABASE pool_engine_test OWNER pool_staging_user;
   ```

2. **Apply Pool Engine Schema**:
   ```powershell
   cd "C:\Users\shaha\pool engine"
   python scripts/init_db.py --dsn "postgresql://pool_staging_user:staging_password@127.0.0.1:5432/pool_engine_staging"
   ```

3. **Verify Schema Tables**:
   ```powershell
   python scripts/init_db.py --dsn "postgresql://pool_staging_user:staging_password@127.0.0.1:5432/pool_engine_staging" --check-only
   # Expected output: All 7 expected tables exist (vehicles, rides, route_stops, ride_requests, join_requests, seat_holds, idempotency_records).
   ```

4. **Run Isolated PostgreSQL Integration Tests**:
   ```powershell
   $env:TEST_DATABASE_URL = "postgresql://pool_staging_user:staging_password@127.0.0.1:5432/pool_engine_test"
   python -m pytest tests/integration/test_postgres_integration.py
   ```

---

### Step 3.3: Start Pool Engine Backend (Port 8000)

1. **Configure Environment**:
   ```powershell
   cd "C:\Users\shaha\pool engine"
   # Copy template without overwriting existing files
   Copy-Item .env.staging.example .env -Force
   # Edit .env with your local staging database credentials
   ```

2. **Launch ASGI Daemon**:
   ```powershell
   uvicorn "engine.service.app:create_app" --factory --host 127.0.0.1 --port 8000 --reload
   ```

3. **Verify Health and Operational Readiness**:
   ```powershell
   # General Liveness:
   Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/health"
   # Operational Readiness (checks PostgreSQL + OSRM):
   Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/health/readiness"
   # Expected: {"ready": true, "status": "ready", "components": {"storage": "healthy", "routing": "healthy"}}
   ```

---

### Step 3.4: Start Waymate Frontend (Port 5173)

1. **Configure Staging Environment**:
   ```powershell
   cd "C:\Users\shaha\Wmate V10"
   # Create .env.staging with VITE_USE_POOL_ENGINE=true and VITE_POOL_ENGINE_URL=http://127.0.0.1:8000
   ```

2. **Start Vite Development Server**:
   ```powershell
   npm run dev -- --port 5173
   ```

---

## 4. Staging Verification Test Scenarios

### Scenario 1: PostgreSQL Persistence Across Restart
1. Create a host ride via Pool Engine client or POST `/v1/rides/host`.
2. Stop the Pool Engine process (`Ctrl+C`).
3. Restart Pool Engine:
   ```powershell
   uvicorn "engine.service.app:create_app" --factory --host 127.0.0.1 --port 8000
   ```
4. Query the created ride by ID via GET `/v1/rides/host/{ride_id}`.
5. **Expected Result**: Ride is retrieved with full stop coordinates and seats, confirming persistent database storage across server restarts.

### Scenario 2: Kerala Road Network Routing Accuracy
1. Submit ride creation from CET (`8.5469, 76.9054`) to TVM Central (`8.4875, 76.9528`).
2. Verify route distance and duration returned by backend.
3. **Expected Result**: Duration reflects realistic road driving time (~20-30 mins), and straight-line approximation is NOT used.

### Scenario 3: Genuine Google Sign-In & Bearer Token Verification
1. In browser, navigate to `http://localhost:5173/login`.
2. Click **Continue with Google** and complete login with a test Google account.
3. Verify session restoration by reloading the browser (`F5`).
4. In DevTools Network tab, inspect outgoing requests to `http://127.0.0.1:8000/v1/*`.
5. **Expected Result**: Header contains `Authorization: Bearer <valid_firebase_id_token>`; backend responds with HTTP 200/201.

### Scenario 4: Cross-User Access Denial (403 Forbidden)
1. Using User A's token, attempt to modify or register a vehicle for User B:
   ```bash
   POST /v1/vehicles
   Header: Authorization: Bearer <user_a_token>
   Body: {"driver_id": "user_b_uid", ...}
   ```
2. **Expected Result**: HTTP 403 Forbidden (`Authenticated user 'user_a' cannot register vehicle for driver 'user_b'`).

### Scenario 5: Feature Flag Off Firestore Isolation
1. Set `VITE_USE_POOL_ENGINE=false` in frontend.
2. Create a ride in the UI.
3. **Expected Result**: Ride document is written directly to Firestore `rides/{rideId}`; no calls are dispatched to port 8000.

### Scenario 6: No Silent Fallback on Backend Failure
1. Set `VITE_USE_POOL_ENGINE=true`.
2. Stop Pool Engine backend (port 8000 offline).
3. Attempt to create a ride in Waymate.
4. **Expected Result**: UI displays clear error toast ("Failed to communicate with Pool Engine"); NO ride is written to Firestore.

---

## 5. Cleanup Instructions

1. **Stop OSRM Kerala Service**: Terminate the PowerShell process running on port 5001. *(Do not terminate port 5000 Manhattan process).*
2. **Stop Pool Engine**: Terminate the uvicorn process on port 8000.
3. **Clean Test Database**:
   ```sql
   DROP DATABASE pool_engine_test;
   ```
4. **Revert Frontend Feature Flag**: Ensure `VITE_USE_POOL_ENGINE=false` before finishing.
