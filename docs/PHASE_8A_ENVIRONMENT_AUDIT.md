# Pool Engine — Phase 8A: Repository & Runtime Audit

**Repository:** `C:\Users\shaha\pool engine`  
**Phase:** Phase 8A — Environment & Baseline Audit  
**Date:** October 29, 2026  
**Baseline Commit:** `f427fa6a4dbe70384e5a29c98fd39134d66d4a13`  
**Status:** VERIFIED BASELINE (542/542 Tests Passing, 0 Skipped, All Active Daemons Healthy)  

---

## 1. Executive Summary

Phase 8A performs a non-destructive audit of the Pool Engine codebase, runtime environment, running services, configuration templates, and testing infrastructure. It establishes an empirical baseline before implementing the staging deployment architecture and end-to-end load testing.

### Key Findings
1. **Verified Test & Type Baseline:** 542 passed tests (0 skipped, 0 failed) in 20.66s; `uv run mypy src` reported 0 issues across 45 source files.
2. **Active Runtime Topology:**
   - Manhattan OSRM: Port 5000 (`PID 19208`, `task-8502`) — HTTP 200 OK
   - Kerala OSRM: Port 5001 (`task-18285`) — HTTP 200 OK
   - PostgreSQL 16: Port 5433 (`task-7457`) — TCP Port Open, schema validated
3. **Host Runtime Constraints:**
   - Docker CLI / daemon is **not installed** on this Windows host (`CommandNotFoundException`).
   - WSL (Windows Subsystem for Linux) is **not installed** (`REGDB_E_CLASSNOTREG`).
   - The environment operates natively on Windows 11 using native portable binaries (`osrm-routed.exe`, `postgres.exe`, `uv`, Python 3.14).
4. **Staging Reproducibility Strategy:** Rather than attempting fragile nested containerization without a Docker daemon, Phase 8B will provide:
   - A fully containerized `deploy/docker/docker-compose.staging.yml` for Linux/CI/production container platforms.
   - A native Windows portable staging orchestration script (`scripts/run_staging_environment.ps1` / Python runner) that reproduces identical staging behavior, environment isolation, and health checking on this host.

---

## 2. Git & Working-Tree State

```
Branch: master (ahead of 'origin/master' by 3 commits)
Head Commit: f427fa6 feat(routing): acquire Kerala OSM extract, compile CH graph, and verify live routing (Phase 7)
Preceding Commit: 501e52c feat(routing): harden multi-region deployment, Kerala pipeline, and health probing (Phase 6)
Working Tree: Clean relative to tracked files.
Untracked Files:
  .agents/ (ECC tooling)
  playground/ (development scratchpad)
  STAGE_3_7_END_TO_END_VERIFICATION_REPORT.md
  uv.lock
```

---

## 3. Architecture & Service Framework Inspection

### 3.1 Application Framework
- **API Framework:** Custom ASGI application (`engine.service.app:create_app`) with a zero-dependency async URI regex router (`AsgiRouter`), asynchronous event-loop isolation (`asyncio.to_thread`), and RFC 7807 problem details error serialization.
- **ASGI Server:** `uvicorn` (version `0.30+`).
- **Entry Points:**
  - `GET /v1/health/liveness`: Process liveness probe.
  - `GET /v1/health/readiness`: Cluster readiness and targeted regional readiness probe (`?region=<region_id>`).
  - `POST /v1/requests`: Passenger ride request ingestion with road-network distance calculation.
  - `POST /v1/host-rides`: Host ride scheduling with stop insertion and detour bounds.
  - `POST /v1/proposals`: Atomic seat reservation and match acceptance.
  - `POST /v1/dispatch/run`: Dynamic batch matching and vehicle routing solver.

### 3.2 Multi-Region Routing Architecture
- **Router:** `RegionalRoutingRouter` (`src/engine/adapters/regional_router.py`).
- **Configuration File:** `config/regions.json`.
- **Configured Regions:**
  1. `us-nyc-manhattan`: Bounding Box `[40.6900, -74.0500, 40.8800, -73.9000]`, OSRM Base URL: `http://127.0.0.1:5000`, Dataset ID: `manhattan-car-ch`.
  2. `in-kl-tvm`: Bounding Box `[8.1800, 76.8000, 8.6500, 77.0500]`, OSRM Base URL: `http://127.0.0.1:5001`, Dataset ID: `kerala-car-ch`.
- **Validation Rules:**
  - Non-overlapping bounding boxes enforced at router instantiation.
  - Out-of-region coordinates rejected prior to network dispatch (`OutOfRegionError`).
  - Cross-region origin/destination pairs rejected with HTTP 400 (`OUT_OF_REGION`).

### 3.3 Database & Storage Layer
- **Persistent Storage:** `PostgresRideStorage` (`src/engine/adapters/postgres_storage.py`).
- **Connection Pool:** Bounded `psycopg_pool.ConnectionPool` with configurable `min_size` (2), `max_size` (20), and timeout ($10\text{s}$).
- **Concurrency Safety:** `SELECT ... FOR UPDATE` row-level locks on vehicle seat holds and proposal acceptances.
- **Port:** 5433 (Portable PostgreSQL 16 on local loopback).

---

## 4. Graph Artifacts & Provenance Verification

All road network graphs reside in `C:\Users\shaha\AppData\Local\osrm_portable`:

| Region | Source Dataset | File Format | Disk Footprint | Algorithm | Integrity / Checksum |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Manhattan** | Overpass Highway Extract | `.osm` (XML) | 81.9 MB source, 18.2 MB graph | Contraction Hierarchies (CH) | Verified via port 5000 probe |
| **Kerala** | Geofabrik Southern India (`southern-zone-latest.osm.pbf`) | `.osm` (XML filtered via `osmconvert 0.8.10`) | 162.3 MB source, 42.3 MB graph | Contraction Hierarchies (CH) | SHA-256: `2c4d4368c8c227c535bef86a01c4794f84f29976e3a4940c599af11864c5577a` |

---

## 5. Non-Destructive Baseline Measurements

### 5.1 Automated Test Suite
- **Command:** `$env:TEST_DATABASE_URL = 'postgresql://postgres:postgres@127.0.0.1:5433/pool_engine_test'; uv run pytest`
- **Result:** **542 passed in 20.66 seconds** (0 failures, 0 warnings, 0 skipped).
- **Test Breakdown:**
  - Unit Tests: 393 passed
  - Scenario Tests: 70 passed
  - Integration Tests: 50 passed
  - Oracle Tests: 20 passed
  - Concurrency Tests: 17 passed
  - Benchmark Tests: 7 passed
  - Property Tests: 6 passed

### 5.2 Static Analysis & Typing
- **Command:** `uv run mypy src`
- **Result:** `Success: no issues found in 45 source files`

### 5.3 Live Health & Readiness Probes
- **Liveness:** `GET /v1/health/liveness` $\to$ HTTP 200 `{"status": "alive", "service": "pool-engine"}` (Latency: 0.8ms)
- **Global Readiness:** `GET /v1/health/readiness` $\to$ HTTP 200 `ready: true`, both regions `healthy: true` (Latency: 1.6ms)
- **Targeted Manhattan:** `GET /v1/health/readiness?region=us-nyc-manhattan` $\to$ HTTP 200 (Latency: 1.2ms)
- **Targeted Kerala:** `GET /v1/health/readiness?region=in-kl-tvm` $\to$ HTTP 200 (Latency: 1.3ms)

---

## 6. Audit Conclusion & Phase 8B Roadmap

The baseline is verified, stable, and reproducible. Phase 8B will proceed with:
1. Creating staging configuration profiles (`config/regions.staging.json`, `.env.staging`).
2. Defining containerized multi-region Compose architecture (`deploy/docker/docker-compose.staging.yml`) for standard CI/CD environments.
3. Providing native portable runner scripts (`scripts/run_staging_service.py` / `.ps1`) for local execution on this host.
4. Ensuring graph artifacts remain mounted and persistent without repeated graph compilation.
