# Pool Engine — Phase 5: Multi-Region Routing Architecture and Production Readiness Audit

**Repository:** `C:\Users\shaha\pool engine`
**Phase:** Phase 5 — Multi-Region Routing Architecture and Production Readiness
**Date:** October 29, 2026
**Status:** AUDIT COMPLETE — Awaiting Architectural Alignment

---

## 1. Executive Summary

Phase 5 audits and plans the evolution of Pool Engine from a single-region validated routing engine into an explicitly configured, multi-region-capable dispatch and routing architecture.

This audit:
1. **Verifies the Baseline:** Confirms clean Git state, 513 passed / 1 skipped tests, and verified uncommitted Phase 1–4 working tree modifications.
2. **Pinpoints Single-Region & Manhattan Assumptions:** Identifies hardcoded probe coordinates in `OsrmRoutingAdapter.check_health()`, monolithic single-bounding-box environment parsing in `ServiceConfig`, single-router construction in `service.py`, and lack of cross-region journey rejection.
3. **Evaluates Cache Isolation:** Identifies that `LruLegCache` key tuples lack dataset/profile namespacing, presenting a cache contamination risk if multiple regions or road networks were to share a cache instance.
4. **Designs the Multi-Region Architecture:** Formulates `RegionConfig`, `RegionalRoutingRouter` (composite routing provider), per-region health telemetry, and disjoint boundary enforcement.
5. **Identifies Architectural Decisions:** Outlines 3 explicit design choices regarding region overlap policy, dispatch batch partitioning, and API backward-compatibility before modifying production code.

---

## 2. Baseline Verification & Git Status

### 2.1 Git Repository State
- **Branch:** `master` (up to date with `origin/master`).
- **Head Commit:** `76b514ed9181d39226c6ee3a36b425e2d25a6bf8` (*"perf: tune OSRM routing batch defaults to reduce cold-cache latency"*).
- **Working Tree:** Contains verified uncommitted changes from Phases 1–4 across 22 files (connection pooling, FastAPI concurrency lifecycle, 4-tier spatial boundary validation, and audit hardening).
- **Protected Directories:** `.agents/` and sub-repositories `ECC/` and `spec-kit/` remain completely untouched and untracked.

### 2.2 Test Suite Execution Baseline
Executing the full regression suite against live PostgreSQL (port 5433) and Manhattan OSRM (port 5000):
```powershell
$env:TEST_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5433/pool_engine_test"
python -m pytest -ra
```
- **Passed:** **513 passed**
- **Skipped:** **1 skipped** (`test_kerala_osrm_port_5001_status_is_blocked` in `tests/integration/test_osrm_regional_boundaries.py:67`)
- **Total Duration:** 22.23s (0 failed, 100% green across all unit, integration, and concurrency tests).
- **Kerala OSRM Status:** Port 5001 has no active listener; real Kerala routing verification remains safely marked `BLOCKED` pending user approval of an external dataset (no external downloads triggered).

---

## 3. Confirmed Issues & Single-Region Limitations

Our audit of `src/` identified five concrete single-region limitations and assumptions:

### Issue 1: Hardcoded Manhattan Coordinates in `OsrmRoutingAdapter.check_health()`
- **Location:** `src/engine/adapters/osrm_routing.py:463-464`
- **Current Code:**
  ```python
  if self.bounding_box is not None:
      probe_lat = (self.bounding_box.min_lat + self.bounding_box.max_lat) / 2.0
      probe_lon = (self.bounding_box.min_lon + self.bounding_box.max_lon) / 2.0
  else:
      probe_lat = 40.758896
      probe_lon = -73.985130
  ```
- **Risk:** If an `OsrmRoutingAdapter` is instantiated without an explicit bounding box for an international region (e.g., Kerala or Tokyo), the health probe queries Times Square (`40.758896, -73.985130`). Against a non-Manhattan OSRM graph, this probe either fails or snaps tens of thousands of kilometers away, resulting in false unhealthy states or invalid connectivity reporting.
- **Proposed Fix:** Eliminate hardcoded coordinate fallbacks. Require an explicit `probe_coordinate` or derive from `bounding_box`. If neither is configured, query a provider-neutral ping or require explicit probe configuration.

### Issue 2: Monolithic Single-Region Configuration in `ServiceConfig`
- **Location:** `src/engine/service/config.py:38-53`
- **Current Fields:**
  - `routing_region_min_lat`, `routing_region_min_lon`, `routing_region_max_lat`, `routing_region_max_lon`
  - `routing_max_snap_distance_meters`
- **Risk:** Only one bounding box and one OSRM backend URL (`OSRM_BASE_URL`) can be configured at a time. The system cannot concurrently route requests in both Manhattan and Kerala.
- **Proposed Fix:** Introduce `RegionConfig` supporting multiple named regions with independent endpoints, bounding boxes, datasets, and provider types, while preserving single-region environment variables for backward compatibility.

### Issue 3: Single Router in Service and Dispatch Orchestrator
- **Location:** `src/engine/service/service.py:68` and `src/engine/orchestration/dispatch_orchestrator.py:75`
- **Current Design:** `PoolEngineService` and `DispatchOrchestrator` take a single `router: RoadNetworkRoutingProvider`.
- **Risk:** Without an architectural routing router, the engine cannot dispatch routing queries to different regional endpoints or datasets.
- **Proposed Fix:** Implement `RegionalRoutingRouter` conforming to `RoadNetworkRoutingProvider` (Composite Pattern). It maintains a registry of `RegionConfig -> RoadNetworkRoutingProvider` instances and dispatches queries to the appropriate provider based on coordinate containment.

### Issue 4: Absence of Cross-Region Journey Rejection
- **Current Behavior:** `validate_coordinate(coord)` checks if a coordinate falls inside the single configured bounding box.
- **Risk:** In a multi-region environment, a rider could submit a journey with pickup in Manhattan (`40.7580, -73.9855`) and dropoff in Thiruvananthapuram (`8.4875, 76.9528`). If both regions are configured in the engine, each point is individually "in a region", but the journey spans across regions.
- **Proposed Fix:** `RegionalRoutingRouter` and `service.create_request()` must verify that both pickup and dropoff belong to the **exact same region ID**. Cross-region trips must be explicitly rejected with a typed `OutOfRegionError` (`HTTP 400 OutOfRegionServiceError`).

### Issue 5: Routing Cache Isolation Across Datasets and Profiles
- **Location:** `src/engine/adapters/osrm_routing.py:170, 475-485`
- **Current Cache Key:** `(origin.latitude, origin.longitude, destination.latitude, destination.longitude)`
- **Risk:** If multiple regions share a cache or if dataset versions/profiles are swapped dynamically, coordinates could collide or return incorrect cached distances.
- **Proposed Fix:**
  1. Each region in `RegionalRoutingRouter` has its own isolated `RoadNetworkRoutingProvider` instance and dedicated `LruLegCache`.
  2. Cache keys incorporate dataset identity and profile: `(dataset_id, profile, lat1, lon1, lat2, lon2)`.

---

## 4. Proposed Multi-Region Architecture

```
                                  [API Request]
                                        │
                         (Pickup / Dropoff / Vehicle Coord)
                                        │
                                        ▼
                         ┌─────────────────────────────┐
                         │    RegionalRoutingRouter    │
                         │ (RoadNetworkRoutingProvider)│
                         └──────────────┬──────────────┘
                                        │
                ┌───────────────────────┴───────────────────────┐
                ▼                                               ▼
      Region: us-nyc-manhattan                        Region: in-kl-tvm
   ┌─────────────────────────────┐                 ┌─────────────────────────────┐
   │ BBox: [40.69, -74.05, ...]  │                 │ BBox: [8.18, 76.80, ...]    │
   │ Provider: OsrmRoutingAdapter│                 │ Provider: MockRoutingProvider│
   │ Endpoint: :5000             │                 │ (or live OSRM on :5001)     │
   │ Dataset: "manhattan-car-ch" │                 │ Dataset: "kerala-car-ch"    │
   │ Dedicated LruLegCache       │                 │ Dedicated LruLegCache       │
   └─────────────────────────────┘                 └─────────────────────────────┘
```

### 4.1 Data Models & Contracts
1. **`RegionConfig`:**
   - `region_id: str` (e.g., `"us-nyc-manhattan"`, `"in-kl-tvm"`)
   - `bounding_box: BoundingBox` (strict coordinate boundaries)
   - `provider_type: str` (`"osrm"` or `"mock"`)
   - `endpoint_url: Optional[str]`
   - `dataset_id: str` (e.g., `"manhattan-v1"`)
   - `profile: str` (default: `"driving"`)
   - `max_snap_distance_meters: float` (default: `5000.0`)
   - `timeout_seconds: float` (default: `0.500`)
   - `probe_coordinate: Optional[Coordinate]` (for dynamic readiness probe)

2. **`RegionalRoutingRouter` (implements `RoadNetworkRoutingProvider`):**
   - Registry mapping `region_id -> (RegionConfig, RoadNetworkRoutingProvider)`.
   - Method `find_region(coord: Coordinate) -> RegionConfig | None`.
   - Coordinate validation: Succeeds if coordinate is within any configured region; raises `OutOfRegionError` otherwise.
   - Leg routing: Origin and destination must resolve to the **same region**. If different or outside, raises `OutOfRegionError`.
   - Health check: Probes all configured regions; returns aggregate health and per-region status dictionary.

---

## 5. Architectural Decisions for Safe Implementation

Before implementing production changes in `src/engine/`, the following 3 design decisions are presented for alignment:

### Decision 1: Region Boundary Overlap Policy
- **Option A (Recommended — Strict Disjoint Boundaries):** Require configured regional bounding boxes to be strictly disjoint (`intersection is None`). If two regions overlap, configuration validation fails fast at startup with `ValueError`.
  - *Rationale:* Eliminates routing ambiguity. With disjoint regions, every coordinate maps deterministically to exactly one routing provider.
- **Option B (Priority Order):** Allow overlapping bounding boxes where the first configured region matching the coordinate takes precedence.
  - *Risk:* Border areas could silently switch routing backends depending on array ordering.

### Decision 2: Dispatch Batch Scope & Execution
- **Option A (Recommended — Explicit Region Partitioning):** When invoking `POST /v1/dispatch`, accept an optional `region_id: Optional[str] = None`.
  - If `region_id` is supplied: Dispatch runs strictly on entities in that region.
  - If `region_id` is omitted: Dispatch executes independent solving cycles per configured region, returning a combined or per-region result.
  - *Rationale:* Prevents cross-region entity contamination, respects the regional 500ms dispatch SLA per market, and avoids mixing vehicles in Manhattan with requests in Kerala.
- **Option B (Monolithic Solver Execution):** Pass all entities from all regions into a single `DispatchEngine` run, relying solely on spatial distance pruning to prevent cross-region matches.
  - *Risk:* Degrades solver performance and mixes regional prefetch queues.

### Decision 3: API Backward Compatibility for `region_id`
- **Option A (Recommended — Optional with Automatic Spatial Resolution):** Make `region_id` optional in `CreateRideRequestInput`, `RegisterVehicleInput`, and `CreateHostRideInput`.
  - If omitted: Region is resolved automatically by checking spatial containment of coordinates against configured regions.
  - If supplied: The service validates that coordinates strictly match the declared `region_id`. If they conflict, reject with `HTTP 400` (`RegionMismatchError`).
  - *Rationale:* 100% non-breaking for existing clients and the 513 existing tests, while enforcing strict guarantees when explicit region IDs are provided.
- **Option B (Strictly Mandatory `region_id`):** Require `region_id` in all API payloads whenever multi-region routing is enabled.
  - *Risk:* Breaks existing integration tests and client payloads that omit `region_id`.

---

## 6. Next Steps Upon Decision Confirmation
1. Implement `RegionConfig` and `RegionalRoutingRouter` in `src/engine/contracts/routing.py` and `src/engine/adapters/regional_router.py`.
2. Add multi-region configuration support to `ServiceConfig`.
3. Harden `OsrmRoutingAdapter` cache keys with dataset identity and remove hardcoded Times Square fallbacks.
4. Implement comprehensive multi-region unit and integration tests (mock multi-region and live Manhattan).
5. Run the full regression suite, strict type checking (`mypy`), and dispatch scale benchmarks.
