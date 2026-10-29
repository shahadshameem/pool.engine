# Pool Engine — Phase 9C: Clean-Environment Reproducibility Audit

**Repository:** `C:\Users\shaha\pool engine`  
**Phase:** Phase 9C — Clean-Environment Reproducibility  
**Date:** October 29, 2026  
**Auditor:** Senior Backend Architect / SRE Auditor (Pair-Programming Agent)  
**Status:** COMPLETE (4 Confirmed Defects Identified, Remediations Formulated)  

---

## 1. Executive Summary

This audit assesses whether a developer on a clean workstation (Linux, macOS, or Windows) can clone this repository and spin up an operational multi-region staging environment without relying on undocumented local state, hidden binaries, or tribal knowledge.

The audit evaluated both deployment paths:
1. **Containerized Staging** (`deploy/docker/docker-compose.staging.yml` and `deploy/docker/Dockerfile`).
2. **Native Windows Staging** (`scripts/run_staging_server.py`).

### Key Findings:
- **Containerized Staging:** **BLOCKED FROM FIRST-TIME SUCCESS** due to:
  1. Missing `COPY config/ /app/config/` in `deploy/docker/Dockerfile` causing `/app/config/regions.staging.json` to be absent at runtime.
  2. Missing `./osrm-data/` directory structure and lack of documentation on how to mount precompiled `.osrm` graphs into containers.
  3. Potential dependency on `nc` in OSRM container health checks where minimal images may lack `netcat`.
- **Native Windows Staging:** **OPERATIONAL BUT FRAGILE** due to:
  1. Inflexible database pre-flight string matching in `scripts/run_staging_server.py` (`"127.0.0.1:5433" in db_url`), which silently bypasses TCP checks if standard port `5432` or `localhost` is provided.

---

## 2. Containerized Staging Audit (Docker / Compose)

### 2.1 Dockerfile Review (`deploy/docker/Dockerfile`)
The multi-stage build pattern is clean:
- **Stage 1 (`builder`):** `python:3.13-slim` compiles wheels for `.[postgres,service]`.
- **Stage 2 (`runtime`):** Non-root user `appuser:appgroup` (UID 10001:10001), pip installs wheels, and cleans wheel caches.
- **Defect Identified (HIGH):**
  Lines 37-38 copy only `src/` and `scripts/`:
  ```dockerfile
  COPY src/ /app/src/
  COPY scripts/ /app/scripts/
  ```
  However, `docker-compose.staging.yml` specifies:
  ```yaml
  ROUTING_REGIONS_FILE: "config/regions.staging.json"
  ```
  When `pool-engine-api` boots up, `config/regions.staging.json` does *not* exist in `/app`, causing `build_service_from_env()` to fail during container startup.
  - **Remediation:** Add `COPY config/ /app/config/` to Stage 2 of `Dockerfile`.

### 2.2 Docker Compose Service Review (`deploy/docker/docker-compose.staging.yml`)

1. **Service Topology & Network Isolation:**
   - 4 services declared: `postgres-staging` (5432), `osrm-manhattan` (5000), `osrm-kerala` (5001), and `pool-engine-api` (8000).
   - Port binding is restricted to `127.0.0.1`, which prevents accidental external interface exposure.
2. **Health Checks & Startup Sequencing:**
   - `pool-engine-api` has `depends_on` with `condition: service_healthy` for postgres, osrm-manhattan, and osrm-kerala.
   - Prevents race conditions during engine initialization.
3. **OSRM Graph Volume Provisioning Defect (HIGH):**
   - In `osrm-manhattan`:
     ```yaml
     volumes:
       - ./osrm-data/manhattan:/data:ro
     ```
   - In `osrm-kerala`:
     ```yaml
     volumes:
       - ./osrm-data/kerala:/data:ro
     ```
   - *Observation:* The folder `./deploy/docker/osrm-data` does not exist in the repository. A clean clone will fail immediately when starting the OSRM containers because the graph files `/data/manhattan.osrm` and `/data/kerala.osrm` are missing.
   - *Remediation:* Create a `.gitkeep` directory structure `deploy/docker/osrm-data/{manhattan,kerala}` and provide a setup guide / script to place or link compiled graphs into these mount points.
4. **Non-Root Execution & Read-Only Volumes:**
   - OSRM mounts use `:ro` (read-only), protecting graph artifacts from container tampering.
   - API executes as unprivileged UID 10001.

---

## 3. Native Windows Staging Audit (`scripts/run_staging_server.py`)

### 3.1 Preflight & Dependency Health Checks
- **Mechanism:** Probes `check_tcp_port()` for PostgreSQL and `check_http_endpoint()` (`/nearest/v1/driving/...`) for each regional OSRM backend defined in `config/regions.json`.
- **Defect Identified (MEDIUM):**
  Line 86 contains:
  ```python
  if db_url and "127.0.0.1:5433" in db_url:
      pg_ok = check_tcp_port("127.0.0.1", 5433)
  ```
  If a developer configures `DATABASE_URL` with `localhost:5433`, or runs PostgreSQL on the standard port `5432`, the condition evaluates to `False`. The script reports no PostgreSQL status and launches Uvicorn blindly.
  - **Remediation:** Parse `db_url` with `urllib.parse.urlsplit` to dynamically extract host and port (defaulting to port 5432 if unspecified), then probe the extracted host and port.

### 3.2 Process Lifecycle & Safety Checks
- **Termination Scope:** The script launches Uvicorn in-process via Python (`uvicorn.run(app, ...)`). It does not kill external PIDs or spawn detached background daemons, ensuring it cannot terminate existing unrelated processes.
- **Path Portability:** Uses relative paths (`config/regions.json`), which work from any cloned repository root.
- **Graceful Shutdown:** Catches `KeyboardInterrupt` and relies on ASGI lifecycle `shutdown` events to drain connection pools cleanly.

---

## 4. Summary of Reproducibility Defect Ledger

| Defect ID | Component | Severity | Description | Remediation Plan |
| :--- | :--- | :--- | :--- | :--- |
| **REP-01** | `deploy/docker/Dockerfile` | **HIGH** | `config/` directory omitted from runtime image; container cannot load `config/regions.staging.json`. | Add `COPY config/ /app/config/` in Stage 2. |
| **REP-02** | `deploy/docker/docker-compose.staging.yml` | **HIGH** | `./osrm-data` volume directories missing; fresh clone cannot run OSRM containers. | Create directory structure with `.gitkeep` and document mount instructions. |
| **REP-03** | `scripts/run_staging_server.py` | **MEDIUM** | Hardcoded `"127.0.0.1:5433"` string match skips PostgreSQL TCP preflight check for other hosts/ports. | Use `urllib.parse.urlsplit` to parse arbitrary database URLs dynamically. |
| **REP-04** | `deploy/docker/docker-compose.staging.yml` | **LOW** | OSRM health checks rely on `nc` which may not be present in minimal OSRM images. | Use `sh -c 'cat < /dev/null > /dev/tcp/127.0.0.1/5000' || exit 1` or HTTP `/nearest` probe. |

---

## 5. Audit Conclusion

Native Windows staging is currently functional for local iteration on this machine. Containerized staging requires the two high-priority Docker packaging fixes (**REP-01** and **REP-02**) to be reproducible on clean Linux/CI workstations. Both fixes are non-destructive and will be applied in Phase 9G.
