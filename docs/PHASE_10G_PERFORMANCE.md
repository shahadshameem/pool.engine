# Pool Engine — Phase 10G: Resource Allocation & Performance Plan

**Repository:** `C:\Users\shaha\pool engine`  
**Phase:** Phase 10G — Performance & Resource Management  
**Date:** October 29, 2026  
**Auditor:** Senior Performance Engineer / SRE Lead (Pair-Programming Agent)  
**Target Hardware:** Contabo VPS (4 vCPUs, ~7.8 GiB RAM, ~90 GiB free disk)  
**Status:** COMPLETE & DOCUMENTED  

---

## 1. Executive Summary

This document establishes the resource allocation budget, container limits, disk footprint projections, and progressive load-testing targets for deploying Pool Engine to the Contabo VPS.

Because OSRM Contraction Hierarchies (CH) compiles road networks into highly optimized hierarchical shortcut graphs, the entire Kerala pilot road network requires only **~42.3 MB on disk** and consumes **< 100 MB of RAM** at runtime. The entire multi-container stack fits comfortably within the VPS resources with over **40% RAM headroom reserved for the host OS and Coolify**.

---

## 2. Resource Allocation Budget (4 vCPUs, 7.8 GiB RAM)

| Service Container | Reserved vCPU | Max vCPU Limit | Reserved RAM | Max Memory Limit | Expected Actual RSS |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`postgres-production`** | 0.5 vCPU | 1.5 vCPU | 256 MiB | 1,536 MiB (1.5 GiB) | ~80–120 MiB |
| **`osrm-kerala`** | 0.5 vCPU | 2.0 vCPU | 128 MiB | 1,024 MiB (1.0 GiB) | ~85–95 MiB |
| **`pool-engine-api` (4 workers)** | 0.5 vCPU | 2.0 vCPU | 256 MiB | 2,048 MiB (2.0 GiB) | ~250–320 MiB |
| **Host OS, Docker & Coolify** | 0.5 vCPU | Uncapped | 512 MiB | Uncapped | ~1.5–2.0 GiB |
| **Total Allocation** | **2.0 vCPU** | **Dynamic** | **1,152 MiB** | **4.5 GiB Capped** | **~2.2 GiB Total** |

**Headroom Guarantee:** Even if all three containers reach their peak memory limits simultaneously (4.5 GiB), the host retains **~3.3 GiB of free physical RAM**, completely preventing out-of-memory (OOM) kernel panics.

---

## 3. Storage & Disk Consumption Projections

The VPS reported approximately 90 GiB of available disk space at initial inspection.

| Storage Category | Expected Size | Persistence Volume |
| :--- | :--- | :--- |
| **Kerala CH Graph Artifacts** | ~42.3 MB | `pool_engine_osrm_kerala_data` |
| **Extracted Kerala OSM Data** | ~154.8 MB | Staged temporarily during compilation |
| **PostgreSQL Data Volume** | ~100–500 MB (10,000 rides) | `pool_engine_pgdata_prod` |
| **Docker Base Images (`postgres`, `osrm`, `python`)** | ~770 MB | Docker root filesystem |
| **Pool Engine API Image** | ~220 MB | Docker root filesystem |
| **Total Stack Disk Footprint** | **~1.3 GiB** | **< 1.5% of available 90 GiB disk** |

---

## 4. Progressive Load Testing Schedule for Kerala Staging

To validate the deployment under realistic traffic without risking server instability, testing must be executed in three progressive tiers using `scripts/load_test_staging.py`:

### Tier 1: Smoke Test (Diagnostic Verification)
- **Concurrency:** 2 concurrent clients
- **Requests:** 20 requests
- **Purpose:** Verifies network round-trip, database transaction commits, and Kerala OSRM connectivity.
- **Pass Gate:** 0.00% error rate, p50 latency < 25 ms.

### Tier 2: Pilot Workload (Target Operating Baseline)
- **Concurrency:** 5–10 concurrent clients
- **Requests:** 100 requests
- **Workload:** 90% valid Kerala passenger trips, 10% controlled out-of-region coordinates.
- **Pass Gate:** 0.00% server errors (5xx), p95 latency < 75 ms.

### Tier 3: Burst Stress Test (Peak Surge Simulation)
- **Concurrency:** 20 concurrent clients
- **Requests:** 250 requests
- **Purpose:** Verifies connection pool checkout stability and multi-worker load balancing.
- **Pass Gate:** 0.00% server errors, p95 latency < 150 ms (well below 500 ms dispatch SLA).

---

## 5. Performance Safety Safeguards

1. **Automatic Test Abort:** If server CPU exceeds 85% sustained for >10 seconds or available RAM drops below 1.5 GiB, load tests must abort immediately.
2. **Cold vs Warm Cache Distinction:** Initial requests establish baseline cold CH graph lookup times (~5–15 ms); subsequent queries exercise the thread-safe `LruLegCache` (< 2 ms).
