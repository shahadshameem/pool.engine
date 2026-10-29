# Pool Engine — Phase 9A: Baseline Audit Report
## Independent Verification of Working-Tree, Runtime State & Test Baseline

**Repository:** `C:\Users\shaha\pool engine`  
**Phase:** Phase 9A — Independent Baseline Audit  
**Date:** October 29, 2026  
**Auditor:** Senior Backend Architect / SRE Auditor (Pair-Programming Agent)  
**Status:** COMPLETE & VERIFIED  

---

## 1. Actual Git Commit and Working-Tree State

- **Current Branch:** `master`
- **Current HEAD Commit:** `acef392` (`acef3921b04d4fadd4e0b117a324ec1d919fc4f1`)
- **Commit Message:** `feat(staging): implement staging topology, E2E tests, load testing, and resilience suite (Phase 8)`
- **Working Tree Cleanliness:**
  - `git diff`: Empty (no uncommitted modifications to tracked files).
  - Tracked Files in Working Tree: 100% clean.
  - Untracked Directories & Artifacts (Preserved as per safety rules):
    - `.agents/` (Preserved agent definitions and skills)
    - `playground/` (Local scratch directory)
    - `STAGE_3_7_END_TO_END_VERIFICATION_REPORT.md` (Historical untracked verification report from Phase 3/7)
    - `uv.lock` (Local lockfile)
- **VCS Integrity:**
  - Branch is 4 commits ahead of `origin/master`:
    1. `eac5db7` (Phase 5: Multi-region routing architecture)
    2. `501e52c` (Phase 6: Multi-region deployment hardening)
    3. `f427fa6` (Phase 7: Kerala live routing acquisition & CH graph)
    4. `acef392` (Phase 8: Staging deployment, reproducibility & load testing)

---

## 2. Detection of Active Runtime Services

The auditor probed local networking to detect active background services without restarting or disrupting them:

| Port | Bound Address | Service Identity | PID | Executable Path | Working Set RSS | Health Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **5000** | `0.0.0.0:5000` | Manhattan OSRM Backend | 19208 | `C:\Users\shaha\AppData\Local\osrm_portable\osrm-v26.10.0-win32-x64-Release\osrm-routed.exe` | ~75 MB | **Healthy** (Nearest query returns HTTP 200) |
| **5001** | `0.0.0.0:5001` | Kerala OSRM Backend | 42280 | `C:\Users\shaha\AppData\Local\osrm_portable\osrm-routed-kerala.exe` | ~74 MB | **Healthy** (Nearest query returns HTTP 200) |
| **5433** | `127.0.0.1:5433` | PostgreSQL 16 Portable | 40740 | `C:\Users\shaha\AppData\Local\pg_portable\pgsql\bin\postgres.exe` | ~89 MB | **Healthy** (`pool_engine_test` DB connected) |
| **8000** | `127.0.0.1:8000` | Pool Engine Staging API | 29428 | `C:\Users\shaha\AppData\Roaming\uv\python\cpython-3.14-windows-x86_64-none\python.exe` | ~91 MB | **Healthy** (`/v1/health/readiness` HTTP 200) |

### API Endpoint Health Verification Commands & Responses:
1. `GET http://127.0.0.1:8000/v1/health/liveness`
   - **Exit Code:** 0 (HTTP 200 OK)
   - **Payload:** `{"status": "alive", "service": "pool-engine"}`
2. `GET http://127.0.0.1:8000/v1/health/readiness`
   - **Exit Code:** 0 (HTTP 200 OK)
   - **Payload:**
     ```json
     {
       "ready": true,
       "status": "ready",
       "components": {
         "storage": "healthy",
         "routing": "healthy",
         "regions": {
           "us-nyc-manhattan": {
             "healthy": true,
             "provider_type": "osrm",
             "dataset_id": "manhattan-car-ch",
             "endpoint_url": "http://127.0.0.1:5000",
             "profile": "driving"
           },
           "in-kl-tvm": {
             "healthy": true,
             "provider_type": "osrm",
             "dataset_id": "kerala-car-ch",
             "endpoint_url": "http://127.0.0.1:5001",
             "profile": "driving"
           }
         }
       }
     }
     ```

---

## 3. Test Suite & Static Analysis Verification

The auditor independently executed the test suite and type checker:

### Command 1: Full Pytest Suite
```powershell
$env:TEST_DATABASE_URL = 'postgresql://postgres:postgres@127.0.0.1:5433/pool_engine_test'
uv run pytest -q
```
- **Exit Code:** 0
- **Duration:** 28.16 seconds
- **Collected Items:** 562
- **Result:** **562 passed, 0 failed, 0 skipped** (100% passing)

### Command 2: Mypy Static Type Verification
```powershell
uv run mypy src
```
- **Exit Code:** 0
- **Result:** `Success: no issues found in 45 source files`

---

## 4. Phase 8 Deliverable File Presence Audit

All files claimed in the Phase 8 report were inspected on disk:

| File Path | Verified Present | Size / Lines | Notes |
| :--- | :--- | :--- | :--- |
| `deploy/docker/docker-compose.staging.yml` | **Yes** | 132 lines | Staging topology config (Linux/CI) |
| `.dockerignore` | **Yes** | 22 lines | Prevents leaking dev/VCS files |
| `config/regions.staging.json` | **Yes** | 40 lines | Points to Docker service names |
| `config/regions.json` | **Yes** | 40 lines | Points to host loopback endpoints |
| `scripts/run_staging_server.py` | **Yes** | 156 lines | Windows staging runner |
| `scripts/load_test_staging.py` | **Yes** | 354 lines | Workload generator & metric collector |
| `tests/integration/test_staging_e2e_verification.py` | **Yes** | 403 lines | 12 E2E integration scenarios |
| `tests/integration/test_staging_resilience_and_faults.py` | **Yes** | 315 lines | 8 fault injection tests |
| `docs/PHASE_8A_ENVIRONMENT_AUDIT.md` | **Yes** | 85 lines | Pre-phase audit report |
| `docs/PHASE_8B_STAGING_SETUP.md` | **Yes** | 98 lines | Staging configuration spec |
| `docs/PHASE_8C_E2E_VERIFICATION.md` | **Yes** | 95 lines | E2E verification results |
| `docs/PHASE_8D_LOAD_TEST_RESULTS.md` | **Yes** | 76 lines | Load test report |
| `docs/PHASE_8E_RESILIENCE_TESTS.md` | **Yes** | 82 lines | Fault resilience report |
| `docs/PHASE_8F_OPERATIONAL_READINESS.md` | **Yes** | 92 lines | Operational readiness audit |
| `docs/PHASE_8_FINAL_REPORT.md` | **Yes** | 240 lines | Phase 8 comprehensive report |
| `docs/load_test_smoke.json` | **Yes** | 55 lines | Raw metrics Profile A (40 reqs) |
| `docs/load_test_normal.json` | **Yes** | 56 lines | Raw metrics Profile B (400 reqs) |
| `docs/load_test_burst.json` | **Yes** | 56 lines | Raw metrics Profile C (750 reqs) |
| `docs/load_test_diagnostic.json` | **Yes** | 56 lines | Raw metrics Profile D (1,000 reqs) |

---

## 5. Blocked Checks & Operational Limitations

1. **Docker Runtime Execution Blocked:**
   - **Reason:** Docker CLI (`docker.exe` / `docker compose`) is not installed on this Windows 11 host (`CommandNotFoundException`). WSL2 subsystem registered with `REGDB_E_CLASSNOTREG`.
   - **Auditor Action:** Containerized staging was audited statically by reviewing the Compose file, Dockerfile, build contexts, environment declarations, and network definitions. Native staging orchestration was audited dynamically using the active Windows binaries.
2. **Remote Deployment & Paid Cloud Infrastructure Blocked:**
   - **Reason:** Explicit safety constraint of Phase 9. No external cloud infrastructure created or billed.

---

## 6. Discrepancies Between Phase 8 Report and Current Repository

The auditor identified the following noteworthy observations between the Phase 8 documentation and the code implementation:

1. **Coordinate Masking Precision Claim vs Code:**
   - *Phase 8 Report Claim:* "Passenger coordinates are sanitized to 4 decimal places (~11m resolution) in non-debug logs".
   - *Actual Code (`src/engine/service/telemetry.py:12`):* `def mask_coordinate(lat, lon, precision: int = 2)` rounds to 2 decimal places (~1.1 km accuracy at equator). Furthermore, `app.py` does not log request coordinates at all.
2. **`MASK_COORDINATES_IN_LOGS` Configuration Usage:**
   - *Phase 8 Claim:* `MASK_COORDINATES_IN_LOGS` environment variable is loaded into `ServiceConfig.mask_coordinates_in_logs`.
   - *Actual Code:* `mask_coordinates_in_logs` is defined in `ServiceConfig`, but is not referenced inside `app.py` route handlers.
3. **Database URL Pre-flight Matching in `run_staging_server.py`:**
   - *Actual Code (`scripts/run_staging_server.py:86`):* `if db_url and "127.0.0.1:5433" in db_url:` checks only the hardcoded string `"127.0.0.1:5433"`. If a developer passes `localhost:5433` or standard port `5432`, the TCP pre-flight check is silently skipped.
4. **Graph Data Directory in Compose File:**
   - *Actual Code (`deploy/docker/docker-compose.staging.yml:47,70`):* Mounts `./osrm-data/manhattan:/data:ro` and `./osrm-data/kerala:/data:ro`. However, the `./osrm-data` folder does not exist in the repository (on this machine, graphs are stored in `AppData\Local\osrm_portable`). Without setup instructions, a clean `docker compose up` on Linux will fail with missing graph errors.

---

## 7. Baseline Conclusion

The working tree, test suite (562 passing tests), type safety (0 mypy issues), and runtime services are verified and operational. The identified discrepancies do not impair system operation but represent opportunities for targeted remediation in Phase 9G.
