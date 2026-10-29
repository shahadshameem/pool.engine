# Pool Engine — Phase 8B: Staging Deployment & Reproducibility Setup

**Repository:** `C:\Users\shaha\pool engine`  
**Phase:** Phase 8B — Reproducible Staging Environment  
**Date:** October 29, 2026  
**Status:** COMPLETE & OPERATIONAL (Live Multi-Region Staging Stack Active on Port 8000)  

---

## 1. Executive Summary

Phase 8B establishes a reproducible staging deployment architecture for the Pool Engine multi-region dispatch and routing system. It delivers:
1. **Containerized Staging Architecture (`deploy/docker/docker-compose.staging.yml`):** Multi-container Docker Compose specification defining isolated services for PostgreSQL 16, Manhattan OSRM (port 5000), Kerala OSRM (port 5001), and the Pool Engine ASGI service (port 8000).
2. **Platform Compatibility & Host Architecture:** Because Docker CLI and WSL are not installed on the current Windows 11 host, a native Python/PowerShell staging orchestration utility (`scripts/run_staging_server.py`) reproduces the exact staging configuration, dependency checks, and port topology natively without requiring external virtualization.
3. **Graph Persistence & Zero Recompilation:** All OSRM Contraction Hierarchies (CH) graphs (`manhattan.osrm*`, `kerala.osrm*`) remain mounted from persistent local storage (`C:\Users\shaha\AppData\Local\osrm_portable`), ensuring server reloads and container restarts never trigger repeated 533 MB extract processing or graph compilation.
4. **Environment Isolation:** Configuration is fully decoupled from production and local developer state via `config/regions.staging.json`, `deploy/docker/.dockerignore`, and `.env.staging`.

---

## 2. Multi-Region Staging Process & Port Topology

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Host Staging Environment (127.0.0.1)               │
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │            Pool Engine Staging API (Port 8000)                  │   │
│   │       (Uvicorn ASGI Engine, RegionalRoutingRouter Hub)          │   │
│   └────────────────┬───────────────────────────────┬────────────────┘   │
│                    │ SQL Connection Pool           │ HTTP Loopback      │
│                    ▼ (psycopg_pool)                ▼ (Keep-Alive)       │
│   ┌───────────────────────────────┐ ┌───────────────────────────────┐   │
│   │     PostgreSQL 16 Storage     │ │  Regional Routing Dispatcher  │   │
│   │          (Port 5433)          │ │  (config/regions.staging.json)│   │
│   │      "pool_engine_test"       │ └───────┬───────────────┬───────┘   │
│   └───────────────────────────────┘         │               │           │
│                                             ▼               ▼           │
│                           ┌───────────────────────┐ ┌───────────────────┐
│                           │ OSRM Manhattan Daemon │ │OSRM Kerala Daemon │
│                           │      (Port 5000)      │ │   (Port 5001)     │
│                           │  "manhattan-car-ch"   │ │ "kerala-car-ch"   │
│                           └───────────────────────┘ └───────────────────┘
└─────────────────────────────────────────────────────────────────────────┘
```

### Port Allocations

| Service | Host Port | Protocol | Dataset / Database | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **Pool Engine API** | `8000` | HTTP/1.1 (ASGI) | Uvicorn ASGI Server | Public staging endpoints (health, requests, rides, dispatch) |
| **OSRM Manhattan** | `5000` | HTTP/1.1 | `manhattan.osrm` (CH) | Real road-network routing for `us-nyc-manhattan` |
| **OSRM Kerala** | `5001` | HTTP/1.1 | `kerala.osrm` (CH) | Real road-network routing for `in-kl-tvm` (TVM pilot) |
| **PostgreSQL 16** | `5433` | TCP / Postgres Wire | `pool_engine_test` | State persistence, atomic seat holds, connection pool |

---

## 3. Configuration & Artifact Management

### 3.1 Regional Routing Configurations
- **Standard Local/Staging:** [`config/regions.json`](file:///C:/Users/shaha/pool%20engine/config/regions.json) (targets `http://127.0.0.1:5000` and `http://127.0.0.1:5001`).
- **Container Network Staging:** [`config/regions.staging.json`](file:///C:/Users/shaha/pool%20engine/config/regions.staging.json) (targets `http://osrm-manhattan:5000` and `http://osrm-kerala:5001`).

### 3.2 Graph Storage & Mounting
- **Physical Directory:** `C:\Users\shaha\AppData\Local\osrm_portable`
- **Manhattan Graph:** `manhattan.osrm` (81.9 MB source, 18.2 MB contracted hierarchy)
- **Kerala Graph:** `kerala.osrm` (162.3 MB source, 42.3 MB contracted hierarchy, 730,770 edges)
- **Mount Policy:** Read-only (`:ro`) mounts. Graph generation is strictly decoupled from runtime execution.

### 3.3 Container Ignore Rules (`.dockerignore`)
- Prevents bloat by excluding `.git/`, `.venv/`, `.hypothesis/`, test caches, `.osm`, `.pbf`, and temporary files from build contexts.

---

## 4. Staging Orchestration & Operational Playbook

### 4.1 Native Windows Staging Execution
To launch the staging API service natively:

```powershell
# 1. Run pre-flight dependency check
uv run python scripts/run_staging_server.py --check-only

# 2. Start Staging API on port 8000
uv run python scripts/run_staging_server.py --port 8000
```

### 4.2 Linux / Containerized CI Execution
For environments with Docker Compose installed:

```bash
docker compose -f deploy/docker/docker-compose.staging.yml up -d
docker compose -f deploy/docker/docker-compose.staging.yml ps
```

### 4.3 Service Health Verification
```powershell
# Liveness probe
Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/health/liveness"

# Global readiness probe
Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/health/readiness"

# Targeted regional probes
Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/health/readiness?region=us-nyc-manhattan"
Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/health/readiness?region=in-kl-tvm"
```
