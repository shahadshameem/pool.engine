# Pool Engine — Phase 6C: Multi-Region Deployment & Isolation Report

**Repository:** `C:\Users\shaha\pool engine`
**Phase:** Phase 6C — Multi-Region Deployment & Isolation
**Date:** October 29, 2026
**Baseline Commit:** `eac5db7f8e46f2ac29bce71143ed7504719c6aa3` (Phase 5)
**Status:** COMPLETE — Deployment Topology, Configuration Templates, Blast-Radius Isolation & Targeted Probes Verified

---

## 1. Executive Summary

Phase 6C establishes the operational deployment architecture for multi-region ride-pooling dispatch. It defines the multi-process port topology, implements configuration templates, hardens configuration fail-fast invariants, and decouples regional health monitoring so that degradation in one market does not disrupt operations in healthy markets.

### Key Deliverables in Phase 6C:
1. **Multi-Region Port & Process Topology:** Formally defined port allocations separating the application API, persistent storage, and independent regional OSRM routing backends.
2. **Canonical Multi-Region Configuration:** Created `config/regions.json` defining disjoint regions for Manhattan (`us-nyc-manhattan`) and Kerala (`in-kl-tvm`), alongside `.env.staging.example`.
3. **Fail-Fast Configuration Hardening:** Eliminated silent fallback vulnerabilities when `ROUTING_REGIONS_FILE` is missing, and eliminated redundant single-region variable requirements (`OSRM_BASE_URL`) under multi-region operation.
4. **Targeted Regional Readiness Probing:** Implemented `region_id` query parameter filtering on `/v1/health/readiness?region=<region_id>` allowing regional load balancers and ingress proxies to make isolated traffic routing decisions.
5. **Cross-Region Contamination Elimination:** Pre-filtered pending request evaluations in host corridor matching, preventing out-of-region routing queries from consuming compute or triggering unhandled exceptions.

---

## 2. Multi-Region Deployment Topology

In multi-region staging and production, each regional road network is served by an independent OSRM Contraction Hierarchies (CH) process running on an isolated loopback or internal VPC port:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Local / Staging Host                            │
│                                                                        │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │               Pool Engine ASGI API Service                   │     │
│   │                      (Port 8000)                             │     │
│   └───────────────┬───────────────────────────────┬──────────────┘     │
│                   │ (SQL Connection Pool)         │                    │
│                   ▼                               ▼                    │
│   ┌──────────────────────────────┐ ┌─────────────────────────────┐     │
│   │    PostgreSQL 16 Storage     │ │    RegionalRoutingRouter    │     │
│   │         (Port 5433)          │ │  (In-Memory Composite Hub)  │     │
│   └──────────────────────────────┘ └───────┬─────────────┬───────┘     │
│                                            │             │             │
│                       HTTP Loopback Pool   │             │             │
│                                            ▼             ▼             │
│                      ┌───────────────────────┐ ┌───────────────────────┐│
│                      │ OSRM Manhattan Daemon │ │  OSRM Kerala Daemon   ││
│                      │      (Port 5000)      │ │      (Port 5001)      ││
│                      │  "manhattan-car-ch"   │ │    "kerala-car-ch"    ││
│                      └───────────────────────┘ └───────────────────────┘│
└────────────────────────────────────────────────────────────────────────┘
```

### Process & Port Matrix

| Service | Port | Protocol | Dataset / Database | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **Pool Engine API** | `8000` | HTTP/1.1 (ASGI) | Pure Python / ASGI Router | Ingestion, Dispatch, Proposals, Lifecycle |
| **OSRM Manhattan** | `5000` | HTTP/1.1 | `manhattan.osrm` (CH) | Real road-network routing for Manhattan |
| **OSRM Kerala** | `5001` | HTTP/1.1 | `kerala.osrm` (CH) | Real road-network routing for Kerala (TVM) |
| **PostgreSQL 16** | `5433` | TCP / Postgres Wire | `pool_engine_test` / `staging` | Atomic seat holds, trip states, requests |

---

## 3. Configuration & Template Architecture

### 3.1 Canonical Region Configuration (`config/regions.json`)

The multi-region setup is defined in `config/regions.json`:

```json
[
  {
    "region_id": "us-nyc-manhattan",
    "bounding_box": {
      "min_lat": 40.6900,
      "min_lon": -74.0500,
      "max_lat": 40.8800,
      "max_lon": -73.9000
    },
    "provider_type": "osrm",
    "endpoint_url": "http://127.0.0.1:5000",
    "dataset_id": "manhattan-car-ch",
    "profile": "driving",
    "max_snap_distance_meters": 5000.0,
    "timeout_seconds": 0.500,
    "probe_coordinate": {
      "latitude": 40.7580,
      "longitude": -73.9855
    }
  },
  {
    "region_id": "in-kl-tvm",
    "bounding_box": {
      "min_lat": 8.1800,
      "min_lon": 76.8000,
      "max_lat": 8.6500,
      "max_lon": 77.0500
    },
    "provider_type": "osrm",
    "endpoint_url": "http://127.0.0.1:5001",
    "dataset_id": "kerala-car-ch",
    "profile": "driving",
    "max_snap_distance_meters": 5000.0,
    "timeout_seconds": 0.500,
    "probe_coordinate": {
      "latitude": 8.5241,
      "longitude": 76.9366
    }
  }
]
```

### 3.2 Configuration Fail-Fast Guarantees
1. **Missing Configuration File:** If `ROUTING_REGIONS_FILE` points to a non-existent path, `ServiceConfig.from_env` immediately raises `ValueError: Configured ROUTING_REGIONS_FILE '<path>' does not exist`.
2. **Overlapping Geographic Boundaries:** If any two regions share non-zero area, `ServiceConfig.validate_regions` raises `ValueError: Regional bounding boxes for '<r1>' and '<r2>' overlap`.
3. **Invalid Coordinates / Inverted Latitudes:** Bounding boxes enforce $-90.0 \le \text{min\_lat} \le \text{max\_lat} \le 90.0$ and $-180.0 \le \text{min\_lon} \le \text{max\_lon} \le 180.0$.
4. **Decoupled OSRM Base URL:** In `build_service_from_env`, `OSRM_BASE_URL` is only required when running in legacy single-region mode without `ROUTING_REGIONS`.

---

## 4. Readiness vs. Liveness Operational Architecture

Kubernetes and ingress proxies require separate probes to manage pod restart vs. traffic routing:

### 4.1 Liveness Probe (`GET /v1/health/liveness`)
- **Semantics:** Confirms the Python runtime and ASGI event loop are responsive.
- **Behavior:** Returns HTTP 200 `{"status": "alive", "service": "pool-engine"}`. Never fails due to database or routing backend outages.

### 4.2 Aggregate Readiness Probe (`GET /v1/health/readiness`)
- **Semantics:** Assesses cluster-wide dependencies.
- **Behavior:**
  - Storage failure: returns HTTP 503 `{"ready": false, "components": {"storage": "unreachable"}}`.
  - Routing degradation under `STRICT_ROUTING_READINESS=false`: returns HTTP 200 with `"components": {"routing": "degraded", "regions": {...}}`.
  - Routing degradation under `STRICT_ROUTING_READINESS=true`: returns HTTP 503 if any configured region is unhealthy.

### 4.3 Targeted Regional Readiness Probe (`GET /v1/health/readiness?region=<region_id>`)
- **Semantics:** Allows regional traffic routers (e.g. AWS ALB / Cloudflare Worker / NGINX) to route traffic to the pool engine for Market A even if Market B is degraded.
- **Operational Verification (Phase 7):**
  With both Manhattan (port 5000) and Kerala (port 5001) active, probing either region returns HTTP 200:
  ```json
  {
    "ready": true,
    "status": "ready",
    "components": {
      "storage": "healthy",
      "routing": "healthy",
      "target_region": "in-kl-tvm",
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
  HTTP Status: **200 OK** (Verified via automated test suite `tests/integration/test_osrm_regional_boundaries.py`).

---

## 5. Blast-Radius & Fault Isolation Verification

Through tests in `tests/unit/test_phase6_multi_region_hardening.py` and `tests/unit/test_multi_region_routing.py`:

1. **Routing Fault Isolation:** When the Kerala provider (port 5001) is down or throwing errors, Manhattan routing queries execute with zero errors, zero latency penalty, and 100% cache hit consistency.
2. **Corridor Pre-Filtering:** Host ride matching in Manhattan pre-filters pending requests in storage, ignoring Kerala requests without executing redundant cross-region distance computations.
3. **Cache Key Partitioning:** Cache keys prepend `dataset_id` (`manhattan-car-ch` vs `kerala-car-ch`) and maintain independent in-memory LRU instances per region.

---

## 6. Conclusion

Phase 6C provides a hardened, reproducible multi-region deployment architecture with decoupled health probes, fail-fast configuration, and verified fault isolation.
