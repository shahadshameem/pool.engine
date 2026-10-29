# Pool Engine — Phase 4: Routing Guardrail Audit and Regression Benchmark Report

**Repository:** `C:\Users\shaha\pool engine`
**Phase:** Phase 4 — Routing Guardrail Audit and Regression Benchmark
**Date:** October 29, 2026
**Status:** COMPLETE (Kerala Live Routing Verification: BLOCKED pending dataset provision)

---

## 1. Executive Summary

Phase 4 audited the Phase 3 regional boundary validation and routing guardrails implementation across all routing, dispatch, corridor matching, and API call paths. The audit systematically verified:
1. **Configuration Integrity:** Handling of valid, missing, partial, and inverted `BoundingBox` settings, ensuring deployments do not silently default to Manhattan in a Kerala environment.
2. **Call-Path Traversal:** Tracing coordinate and waypoint validation across direct route lookups, distance matrices, batched prefetching, LRU caching, candidate generation, vehicle registration, and en-route join.
3. **Confirmed Defects & Surgical Hardening:** Identified and resolved 4 critical validation bypasses (pre-supplied distance/duration bypass, unvalidated vehicle coordinates, unhandled malformed/NaN OSRM waypoint data, and direct `ServiceConfig` instantiation).
4. **Validation Overhead Measurement:** Measured the exact empirical microsecond overhead of coordinate invariants, bounding box evaluation, and snapping distance checks using a reproducible benchmark script (`scripts/benchmark_phase4_validation_overhead.py`).
5. **Full Regression Health:** The entire test suite passed with **513 passed, 1 skipped in 26.66s** (100% green; zero failures or regressions).

---

## 2. Configuration & Call-Path Audit Findings

### 2.1 Regional Configuration & BoundingBox Guardrails

| Setting / Property | Audit Expectation | Implementation Verification | Status |
| :--- | :--- | :--- | :--- |
| **Missing Bounding Box** | System operates without geographical clipping, relying strictly on snapping distance tolerance. | If `ROUTING_REGION_*` env vars are absent, `BoundingBox.from_env()` returns `None`. `OsrmRoutingAdapter` sets `self.bounding_box = None`. | **VERIFIED** |
| **Partial Bounding Box** | Incomplete configurations must fail fast rather than silently guessing missing bounds. | If 1, 2, or 3 bounding box variables are set, `BoundingBox.from_env()` raises `ValueError("Incomplete regional bounding box configuration...")`. `ServiceConfig` model validator raises `ValueError`. | **VERIFIED** |
| **Inverted Bounds** | Inverted latitudes (`min_lat > max_lat`) or longitudes (`min_lon > max_lon`) must be rejected. | `BoundingBox.__post_init__` enforces `min_lat <= max_lat` and `min_lon <= max_lon`, raising `InvalidCoordinateError`. | **VERIFIED** |
| **Provider Independence** | Configuration must never silently default to Manhattan in a Kerala deployment. | No hardcoded Manhattan fallback exists in `BoundingBox` or `ServiceConfig`. In a Kerala deployment (`ROUTING_REGION_MIN_LAT=8.18`, `ROUTING_REGION_MAX_LAT=12.80`), Manhattan coordinates are rejected. | **VERIFIED** |
| **Boundary Coordinates** | Points directly on the min/max boundary edges must behave consistently. | `BoundingBox.contains` uses inclusive inequalities (`self.min_lat <= coord.latitude <= self.max_lat`). Both `Coordinate` and `BoundingBox` round to 6 decimal places, preventing floating-point precision mismatches. | **VERIFIED** |
| **Strict Mode Routing** | Prohibits silent fallback to `MockRoutingProvider`. | When `REQUIRE_REAL_ROUTING=true`, missing `OSRM_BASE_URL` raises `ValueError`, and an unhealthy backend raises `RoutingProviderError`. Silent fallback is physically impossible. | **VERIFIED** |

### 2.2 Call-Path Traversal Matrix

Each routing entry point was traced and verified to ensure an invalid or out-of-region route cannot produce a successful match:

```
[Client / API Request]
   │
   ├── POST /v1/requests ──────────────► service.create_request()
   │                                        ├─► router.validate_coordinate(pickup) ──► OutOfRegionServiceError (HTTP 400)
   │                                        ├─► router.validate_coordinate(dropoff) ─► OutOfRegionServiceError (HTTP 400)
   │                                        └─► router.get_direct_leg(p, d) ─────────► [OSRM Table] ──► Snapping check
   │
   ├── POST /v1/vehicles ──────────────► service.register_vehicle()
   │                                        └─► router.validate_coordinate(location) ─► OutOfRegionServiceError (HTTP 400)
   │
   ├── PATCH /v1/vehicles/{id}/loc ────► service.update_vehicle_location()
   │                                        └─► router.validate_coordinate(location) ─► OutOfRegionServiceError (HTTP 400)
   │
   ├── POST /v1/host-rides ────────────► service.register_host_ride()
   │                                        └─► router.get_direct_leg(orig, dest) ───► OutOfRegionServiceError (HTTP 400)
   │
   ├── POST /v1/dispatch ──────────────► DispatchOrchestrator.dispatch_cycle()
   │                                        └─► DispatchEngine
   │                                              ├─► prefetch_matrices() ────────────► Filters out-of-region coords
   │                                              ├─► candidate insertion (insertion.py)
   │                                              │     └─► get_direct_leg() ─────────► OutOfRegionError caught ──► returns None (Pruned)
   │                                              └─► bundle generator
   │                                                    └─► get_direct_leg() ─────────► OutOfRegionError caught ──► returns None (Pruned)
   │
   └── POST /v1/rides/{id}/join ───────► service.evaluate_en_route_join()
                                            └─► evaluate_host_corridor_match()
                                                  ├─► check_ahead_of_vehicle() ───────► OutOfRegionError caught ──► rejection_reason="OUT_OF_REGION"
                                                  └─► leg_req_direct / stop legs ─────► OutOfRegionError caught ──► rejection_reason="REQUEST_OUT_OF_REGION"
```

---

## 3. Confirmed Defects and Narrowly Scoped Fixes

During the audit, 4 specific validation gaps were identified and resolved via strict test-driven development (TDD):

### Defect 1: Client Pre-Supplied Distance/Duration Bypass in `create_request`
- **Root Cause:** In [`src/engine/service/service.py`](file:///C:/Users/shaha/pool%20engine/src/engine/service/service.py), `self.router.get_direct_leg(coord_from, coord_to)` was enclosed inside `if direct_dist is None or direct_dur is None:`. If a client supplied both `direct_distance_meters` and `direct_duration_seconds` in the request payload, routing resolution was bypassed, allowing out-of-region coordinates (e.g. Kerala coordinates submitted to a Manhattan engine) to enter the system as `PENDING`.
- **Fix:** Added unconditional coordinate validation via `self.router.validate_coordinate(coord_from, "Pickup location")` and `self.router.validate_coordinate(coord_to, "Dropoff location")` prior to checking pre-supplied values. If either point is outside the operational region, `OutOfRegionServiceError` is raised immediately.

### Defect 2: Missing Regional Validation on Vehicle Registration and Telemetry
- **Root Cause:** In `service.register_vehicle` and `service.update_vehicle_location`, vehicle coordinates were stored directly without validating whether the vehicle was operating inside the service region.
- **Fix:** Added `self.router.validate_coordinate(veh_coord, "Vehicle location")` in both methods, rejecting vehicles outside the operational region with `OutOfRegionServiceError` (HTTP 400).

### Defect 3: Waypoint Snapping Vulnerability to Non-Dict, Boolean, and NaN Values
- **Root Cause:** In [`src/engine/adapters/osrm_routing.py`](file:///C:/Users/shaha/pool%20engine/src/engine/adapters/osrm_routing.py), `_validate_waypoint_snapping` assumed `waypoint` was a dictionary and that `waypoint.get("distance")` was numeric. If OSRM returned non-dict data, boolean values (`float(True) == 1.0`), NaN (`float("nan") > 5000` evaluates to `False`), or negative numbers, validation could be bypassed or raise unhandled `AttributeError`. Furthermore, if `waypoint["location"]` contained invalid coordinates, the exception was silently swallowed with `pass`.
- **Fix:** Hardened `_validate_waypoint_snapping` to:
  1. Reject non-dict waypoint items with `InvalidRouteDataError`.
  2. Reject boolean, non-numeric, NaN, infinite, or negative `distance` values with `InvalidRouteDataError`.
  3. Validate `waypoint["location"]` strictly, raising `InvalidRouteDataError` on corrupt coordinates and `OutOfRegionError` if snapped coordinates fall outside `bounding_box`.

### Defect 4: Unvalidated Partial Bounding Box on Direct `ServiceConfig` Instantiation
- **Root Cause:** [`ServiceConfig`](file:///C:/Users/shaha/pool%20engine/src/engine/service/config.py) only validated bounding box completeness when parsed through `from_env()`. Direct class instantiation (e.g., `ServiceConfig(routing_region_min_lat=40.0)`) permitted incomplete or inverted configurations.
- **Fix:** Added `@model_validator(mode="after")` `validate_regional_bounding_box` in `ServiceConfig` enforcing that all 4 bounding box fields are either all set with valid bounds (`min <= max`) or all `None`.

### Defect 5: `MockRoutingProvider` Regional Guardrail Support
- **Root Cause:** [`MockRoutingProvider`](file:///C:/Users/shaha/pool%20engine/src/engine/adapters/mock_routing.py) did not accept an optional `bounding_box` parameter or enforce `validate_coordinate`, preventing deterministic unit tests from verifying regional boundaries without OSRM.
- **Fix:** Added `bounding_box: BoundingBox | None = None` to `MockRoutingProvider` and implemented boundary checks in `validate_coordinate` and `get_direct_leg`.

---

## 4. Measured Validation Overhead (Microbenchmark)

A reproducible microbenchmark was executed via [`scripts/benchmark_phase4_validation_overhead.py`](file:///C:/Users/shaha/pool%20engine/scripts/benchmark_phase4_validation_overhead.py) to measure the exact computational cost of the added validation checks:

### 4.1 Benchmark Results

```
========================================================================
  POOL ENGINE — PHASE 4 ROUTING GUARDRAIL VALIDATION BENCHMARK
========================================================================

1. Coordinate Invariant Validation (100,000 ops):
   - Total time:       204.19 ms
   - Latency per op:   2,041.9 ns (2.0419 µs)

2. Bounding Box Boundary Checking (100,000 ops):
   - contains() in-bounds:     113.1 ns per check (0.1131 µs)
   - contains() out-of-bounds:  63.9 ns per check (0.0639 µs)
   - validate() (no raise):    145.1 ns per check (0.1451 µs)

3. Waypoint Snapping Validation (100,000 ops):
   - Total time:       257.08 ms
   - Latency per op:   2,570.8 ns (2.5708 µs)

4. End-to-End Direct Leg Query Comparison (10,000 queries):
   - Unbounded Router: mean = 0.2933 µs, p95 = 0.3000 µs, p99 = 0.4000 µs
   - Bounded Router:   mean = 0.7093 µs, p95 = 1.2000 µs, p99 = 1.6000 µs
   - Mean Added Overhead: +0.4160 µs (+141.85%)
========================================================================
```

### 4.2 Impact Analysis Against Dispatch SLA
- **Latency Budget:** The contractual SLA for regional batch dispatch solving is $\le 500\text{ms}$.
- **Net Overhead:** The measured net overhead for boundary checking is **$0.416\ \mu\text{s}$ per direct leg**.
- **Batch Evaluation Impact:** In a typical regional cluster dispatch cycle evaluating 200 candidate insertion legs:
  $$\text{Total Validation Overhead} = 200 \times 0.416\ \mu\text{s} \approx 0.0832\text{ ms} \quad (\approx 0.016\%\text{ of the 500ms budget})$$
- **Fast-Path Rejection Benefit:** For out-of-region coordinates, bounding-box validation rejects queries in **$63.9\text{ ns}$**, completely eliminating a $5\text{ms}\text{–}15\text{ms}$ network round-trip to OSRM.

---

## 5. Kerala OSRM Readiness Assessment

| Audit Parameter | Verification Command / Target | Result | Operational Status |
| :--- | :--- | :--- | :--- |
| **Kerala Port 5001** | `Get-NetTCPConnection -LocalPort 5001` | Inactive (No listener) | **BLOCKED** |
| **Kerala Graph File** | `Get-ChildItem ... -Filter "*kerala*"` | Absent (0 files) | **BLOCKED** |
| **Manhattan Port 5000** | `Get-NetTCPConnection -LocalPort 5000` | Active (`Listen`, PID: `task-8502`) | **ACTIVE** (Untouched) |
| **External Download Guardrail** | Public OSM / Geofabrik feeds | Zero requests emitted | **COMPLIANT** |

**Determination:** Real Kerala road-network routing remains **`BLOCKED`** pending provision of an approved Kerala `.osrm` dataset. Manhattan OSRM on port 5000 is preserved and active for geographically appropriate Manhattan tests.

---

## 6. Comprehensive Test Results

### 6.1 Focused Test Suites

1. **Routing Invariants & Validation Tests:**
   ```powershell
   python -m pytest tests/unit/test_osrm_routing.py tests/unit/test_routing_fault_isolation.py tests/unit/test_routing_regional_validation.py
   ```
   **Result:** **102 passed in 1.27s** (0 failed).

2. **Corridor Matching Tests:**
   ```powershell
   python -m pytest tests/unit/test_corridor_matching.py
   ```
   **Result:** **7 passed in 0.88s** (0 failed).

3. **Dispatch & Orchestration Tests:**
   ```powershell
   python -m pytest tests/unit/test_dispatch.py tests/unit/test_dispatch_audit.py tests/unit/test_dispatch_orchestrator.py
   ```
   **Result:** **37 passed in 0.60s** (0 failed).

4. **PostgreSQL & ASGI Integration Tests:**
   ```powershell
   $env:TEST_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5433/pool_engine_test"; python -m pytest tests/integration/
   ```
   **Result:** **59 passed, 1 skipped in 13.18s** (0 failed; 1 skipped verifying Kerala port 5001 status is marked `BLOCKED`).

### 6.2 Full Regression Suite

```powershell
$env:TEST_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5433/pool_engine_test"; python -m pytest -ra
```

**Result:** **513 passed, 1 skipped in 26.66s** (100% green; 0 failures).

```
=========================== short test summary info ===========================
SKIPPED [1] tests\integration\test_osrm_regional_boundaries.py:67: Kerala OSRM service on port 5001 is unavailable. Real Kerala routing verification is safely marked BLOCKED pending dataset provision.
513 passed, 1 skipped in 26.66s
```

---

## 7. Remaining Blockers & Next Steps

1. **Kerala Road Network Dataset:** Real routing verification for Kerala remains blocked until an approved Kerala `.osm.pbf` or pre-built `.osrm` graph is provisioned and started on port 5001.
2. **Production Bounding Box Provisioning:** When deploying to production environments, the 4 environment variables (`ROUTING_REGION_MIN_LAT`, `ROUTING_REGION_MIN_LON`, `ROUTING_REGION_MAX_LAT`, `ROUTING_REGION_MAX_LON`) must be configured to match the target operational market.
3. **No Unresolved Regressions:** All Phase 1 connection pooling, Phase 2 FastAPI lifecycle concurrency, Phase 3 regional boundary validation, and Phase 4 audit hardening are verified green.
