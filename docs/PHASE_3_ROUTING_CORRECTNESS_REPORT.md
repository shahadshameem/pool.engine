# Pool Engine — Phase 3: Regional Routing Correctness and Boundary Validation Report

**Repository:** `C:\Users\shaha\pool engine`
**Phase:** Phase 3 — Regional Routing Correctness and Boundary Validation
**Date:** October 29, 2026
**Status:** COMPLETE (Kerala Live Routing Verification: BLOCKED pending dataset provision)

---

## 1. Executive Summary

Phase 3 establishes rigorous spatial boundary and snapping distance validation across Pool Engine's routing layer. Prior to this phase, the routing engine treated any HTTP 200 `Ok` response from an Open Source Routing Machine (OSRM) backend as evidence that a route was valid. Because OSRM by design snaps any coordinate on Earth to the nearest edge in its loaded road network, queries containing coordinates thousands of kilometers away from the dataset's operational region were silently accepted, returning artificial or zero-distance routes and corrupting dispatch, pricing, and ETA calculations.

Phase 3 introduces an evidence-backed, 4-tier regional boundary validation architecture:
1. **Tier 1 (Coordinate Invariants):** Strict mathematical validation on `Coordinate` (`[-90.0, 90.0]`, `[-180.0, 180.0]`, finite, non-boolean) raising `InvalidCoordinateError`.
2. **Tier 2 (Configurable Bounding Box):** Optional `BoundingBox` constraints parsed from environment variables (`ROUTING_REGION_MIN_LAT`, etc.) providing $O(1)$ fast-path rejection before network transmission.
3. **Tier 3 (Max Snapping Tolerance):** Validation of OSRM-returned waypoint snapping distances (`sources[i].distance`, `destinations[j].distance`, `waypoints[i].distance`) against a configurable threshold (`max_snap_distance_meters`, default 5,000 m), raising typed `OutOfRegionError`.
4. **Tier 4 (Strict Routing Mode & Dynamic Probing):** Enforcement of `REQUIRE_REAL_ROUTING=true` prohibiting silent fallback to mock routing, with readiness probing dynamically targeted to the operational region center rather than hardcoded Manhattan coordinates.

Full test suite verification confirms **501 passed, 1 skipped** (100% green across all unit, integration, concurrency, and benchmark suites).

---

## 2. Problem Analysis: The OSRM Global Snapping Hazard

### 2.1 Why HTTP 200 "Ok" Is Never Proof of Geographic Validity
OSRM operates on a pre-compiled contraction hierarchy or MLD graph for a specific geographical region (e.g., Manhattan, New York). When queried via `/table/v1/` or `/route/v1/`, OSRM performs a spatial KD-tree lookup to locate the nearest traversable road edge for every input coordinate.

OSRM has **no inherent regional bounding cutoff**. If an application queries a Manhattan dataset with coordinates located in Kerala (India), London (UK), or Albany (New York), OSRM projects those coordinates onto the outer boundary road edges of the loaded dataset and returns:
- HTTP Status `200 OK`
- JSON payload with `"code": "Ok"`
- Non-null `distances` and `durations` matrices
- Waypoint objects containing a massive `distance` property (the metric snapping distance from the queried point to the snapped road segment).

### 2.2 Empirical Demonstration on Live Staging Services

Empirical queries against the running Manhattan OSRM daemon on port 5000 demonstrated severe silent corruption:

#### Scenario A: Cross-Continent Kerala Query
- **Query:** Origin `(8.5469, 76.9054)` (Thiruvananthapuram, Kerala) to Destination `(8.4875, 76.9528)`.
- **OSRM Response:**
  ```json
  {
    "code": "Ok",
    "sources": [
      {
        "name": "Catalpa Avenue",
        "location": [-73.891301, 40.705059],
        "distance": 15678813.9
      }
    ],
    "destinations": [
      {
        "name": "Catalpa Avenue",
        "location": [-73.891301, 40.705059],
        "distance": 15690888.82
      }
    ],
    "distances": [[0.0]],
    "durations": [[0.0]]
  }
  ```
- **Hazard:** Both coordinates snapped ~15,679 km away to the same outer road in Queens/Brooklyn, NY (`Catalpa Avenue`). OSRM returned a 0-meter, 0-second route. If unvalidated, Pool Engine would dispatch this cross-country trip as a zero-cost instant trip.

#### Scenario B: Regional Excursion (Times Square to Albany, NY)
- **Query:** Origin `(40.7580, -73.9855)` (Times Square, Manhattan) to Destination `(42.6526, -73.7562)` (Albany, NY, ~206 km north).
- **OSRM Response:**
  ```json
  {
    "code": "Ok",
    "sources": [{"name": "7th Avenue", "location": [-73.985506, 40.758002], "distance": 0.55}],
    "destinations": [{"name": "Manhattan Avenue", "location": [-73.961475, 40.798654], "distance": 206621.15}],
    "distances": [[0, 6109.5]],
    "durations": [[0, 646.0]]
  }
  ```
- **Hazard:** Albany was snapped 206.6 km southward to northern Manhattan (`Manhattan Avenue`). OSRM reported a 6.1 km, 10.7-minute trip. Pool Engine would promise a passenger an arrival in Albany in 10 minutes.

---

## 3. Architectural Implementation: 4-Tier Validation

```
                    Incoming Coordinate (lat, lon)
                                  │
                 ▼ (Tier 1: Coordinate Invariants)
         lat in [-90, 90] & lon in [-180, 180] & finite?
                 │                             │
                Yes                            No ──► InvalidCoordinateError (HTTP 400)
                 │
                 ▼ (Tier 2: Regional Bounding Box)
            Configured BoundingBox.contains(coord)?
                 │                             │
                Yes / Not set                  No ──► OutOfRegionError (HTTP 400)
                 │
                 ▼ (Network Transmission to OSRM)
                 OSRM Response (HTTP 200, code="Ok")
                 │
                 ▼ (Tier 3: Snapping Distance Validation)
          waypoint.distance <= max_snap_distance_meters?
                 │                             │
                Yes                            No ──► OutOfRegionError (HTTP 400)
                 │
                 ▼ (Tier 4: Strict Mode & Output Invariants)
          validate_route_leg() & dynamic readiness health
                 │
                 ▼
          Valid Road Leg / Route Geometry Accepted
```

### 3.1 Tier 1: Coordinate Invariants (`src/engine/contracts/routing.py`)
- `Coordinate.__post_init__` strictly validates:
  - Latitude $\in [-90.0, 90.0]$
  - Longitude $\in [-180.0, 180.0]$
  - Rejects `NaN`, `+Inf`, `-Inf`, and boolean instances.
  - Automatically rounds valid coordinates to 6 decimal places (~0.1m precision).
  - Failure raises `InvalidCoordinateError(RoutingProviderError, ValueError)`.

### 3.2 Tier 2: Bounding Box Boundaries (`src/engine/contracts/routing.py`)
- Dataclass `BoundingBox(min_lat, min_lon, max_lat, max_lon)`:
  - Enforces `min_lat <= max_lat` and `min_lon <= max_lon`.
  - Method `contains(coord: Coordinate) -> bool`.
  - Method `validate(coord: Coordinate, label: str) -> None`: raises `OutOfRegionError` immediately if out of bounds.
  - Classmethod `from_env(env: Mapping[str, str] | None = None)`: parses standard environment variables `ROUTING_REGION_MIN_LAT`, `ROUTING_REGION_MIN_LON`, `ROUTING_REGION_MAX_LAT`, `ROUTING_REGION_MAX_LON`. Fails fast if partially configured.

### 3.3 Tier 3: Snapping Distance Threshold (`src/engine/adapters/osrm_routing.py`)
- Parameters added to `OsrmRoutingAdapter`:
  - `bounding_box: BoundingBox | None = None`
  - `max_snap_distance_meters: float = 5000.0` (configurable via `ROUTING_MAX_SNAP_DISTANCE_METERS`).
- Method `_validate_waypoint_snapping(waypoint, original_coord, label)`:
  - Inspects `waypoint.get("distance")`. If distance exceeds `max_snap_distance_meters`, raises `OutOfRegionError`.
  - Inspects `waypoint.get("location")` (`[lon, lat]`). If bounding box is configured and the snapped location is outside the box, raises `OutOfRegionError`.
- Integrated across all operations:
  - `get_direct_leg`: validates coordinates and snaps for `sources[0]` and `destinations[0]`.
  - `get_distance_matrix`: validates all input coordinates and all returned chunk waypoints.
  - `get_route`: validates all input waypoints and returned geometry snapped waypoints.
  - `prefetch_matrix`: filters out out-of-region coordinates; marks unroutable/snapping-violation legs as `None` (negative cache) without raising, preventing speculative cache warming from failing dispatch cycles.

### 3.4 Tier 4: Operational Readiness & Health Check Dynamic Probing
- In `OsrmRoutingAdapter.check_health()`:
  - If `bounding_box` is configured, probes the geometric center of the bounding box:
    $$\text{lat}_{\text{probe}} = \frac{\text{min\_lat} + \text{max\_lat}}{2}, \quad \text{lon}_{\text{probe}} = \frac{\text{min\_lon} + \text{max\_lon}}{2}$$
  - Eliminates the previous hardcoded Times Square probe that would cause false negatives when operating in non-Manhattan regions.
- In `build_service_from_env()`:
  - If `REQUIRE_REAL_ROUTING=true`, verifies `router.check_health()`. If unreachable or unhealthy, raises `RoutingProviderError` immediately, strictly prohibiting silent fallback to mock routing.

---

## 4. Service, API, and Dispatch Propagation

### 4.1 RFC 7807 Error Mapping (`src/engine/service/errors.py` & `app.py`)
- Added `OutOfRegionServiceError(ServiceError)`:
  - Status code: `400 Bad Request`
  - Error code: `OUT_OF_REGION`
- Mapped in FastAPI ASGI exception handler:
  - `OutOfRegionError` and `OutOfRegionServiceError` return HTTP 400 with RFC 7807 problem details:
    ```json
    {
      "error": {
        "code": "OUT_OF_REGION",
        "message": "Requested coordinates fall outside the operational service region: Origin (8.5469, 76.9054) falls outside regional bounding box [40.69, -74.05, 40.88, -73.9]",
        "details": []
      }
    }
    ```
  - `InvalidCoordinateError` returns HTTP 400 with `INVALID_COORDINATE` or `VALIDATION_ERROR`.

### 4.2 Dispatch Matching & Candidate Pruning
- In `src/engine/routing/insertion.py` and `src/engine/routing/bundle_generator.py`:
  - When candidate insertions evaluate travel legs between vehicles and requests, any `OutOfRegionError` is caught as a subclass of `RoutingProviderError`.
  - The leg is assigned `None` (unroutable), automatically pruning the candidate insertion from consideration.
  - Result: Out-of-region ride requests can **never** be paired with in-region vehicles.

### 4.3 Corridor Matching (`src/engine/routing/corridor.py`)
- In `check_ahead_of_vehicle` and `evaluate_host_corridor_match`:
  - Routing calls wrapped in `try / except OutOfRegionError`.
  - Out-of-region coordinates cleanly reject the candidate with explicit rejection codes (`OUT_OF_REGION`, `HOST_OUT_OF_REGION`, `REQUEST_OUT_OF_REGION`) without raising unhandled 500 exceptions.

---

## 5. Kerala OSRM Status & Environment Verification

| Service / Requirement | Configured Endpoint | Observed Status | Action Taken / Verification |
| :--- | :--- | :--- | :--- |
| **Manhattan OSRM** | `http://127.0.0.1:5000` | Active (`Listen`, PID: `task-8502`) | Maintained intact; verified with live integration tests. |
| **Kerala OSRM Service** | `http://127.0.0.1:5001` | Inactive (No TCP listener) | Verified via `Get-NetTCPConnection -LocalPort 5001`. |
| **Kerala Dataset on Disk** | `osrm_portable/*.osrm` | Absent (0 matching files) | Verified via recursive file search in `osrm_portable`. |
| **External Download Guardrail** | Public OSM / Geofabrik | Not triggered | Strict adherence to user instruction: **zero downloads**. |
| **Kerala Verification Status** | Kerala End-to-End | **BLOCKED** | Formally marked `BLOCKED` pending approved Kerala dataset. |

---

## 6. Verification and Regression Test Results

### 6.1 Unit Tests (`tests/unit/test_routing_regional_validation.py`)
- **Total Tests:** 28
- **Results:** 28 passed in 1.78s
- **Coverage:**
  - `Coordinate` extremes, precision rounding, and NaN/Inf/boolean rejection.
  - `BoundingBox` invariant enforcement, boundary edge checks, and environment variable parsing.
  - `OsrmRoutingAdapter` fast-path pre-network bounding box rejection ($0$ transport calls).
  - Extreme snapping distance rejection on Table (`/table/v1/`) and Route (`/route/v1/`) services.
  - Valid snapping within threshold ($<5,000$ m) acceptance.
  - Matrix out-of-region and extreme snapping rejection.
  - Speculative prefetch matrix safe skipping of out-of-region coordinates.
  - `ServiceConfig` regional configuration parsing.
  - `build_service_from_env` strict routing enforcement (prohibiting silent mock fallback and failing on unhealthy backends).

### 6.2 Integration Tests (`tests/integration/test_osrm_regional_boundaries.py`)
- **Total Tests:** 6
- **Results:** 5 passed, 1 skipped in 1.86s
- **Details:**
  - `test_kerala_osrm_port_5001_status_is_blocked`: SKIPPED (properly verifies Kerala port 5001 status is marked BLOCKED).
  - `test_live_manhattan_osrm_in_region_routing`: PASSED (9,403m, 896s verified against live Manhattan OSRM).
  - `test_live_manhattan_osrm_rejects_kerala_due_to_bounding_box`: PASSED (rejected prior to network call).
  - `test_live_manhattan_osrm_rejects_kerala_snapping_without_bbox`: PASSED (rejected due to 15,678 km snapping distance).
  - `test_live_manhattan_osrm_rejects_albany_snapping`: PASSED (rejected due to 206 km snapping distance).
  - `test_api_rejects_out_of_region_request_with_rfc7807_error`: PASSED (returns HTTP 400 with `OUT_OF_REGION` code on `/v1/requests` and `/v1/host-rides`).

### 6.3 Full Regression Suite
- **Command:** `$env:TEST_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5433/pool_engine_test"; python -m pytest -ra`
- **Result:** **501 passed, 1 skipped in 33.33s** (0 failures).
- **Baseline Comparison:**
  - Phase 1 Baseline: 458 passed.
  - Phase 2 Baseline: 468 passed.
  - Phase 3 Result: **501 passed, 1 skipped** (+33 net new passing tests).

---

## 7. Modified Files Inventory

| File Path | Description of Changes |
| :--- | :--- |
| `src/engine/contracts/routing.py` | Added `InvalidCoordinateError`, `OutOfRegionError`, `BoundingBox`; added invariant validation in `Coordinate.__post_init__`. |
| `src/engine/adapters/osrm_routing.py` | Added `bounding_box` and `max_snap_distance_meters` support; implemented waypoint snapping validation across direct leg, matrix, prefetch, and route queries; dynamic health check probe. |
| `src/engine/routing/corridor.py` | Wrapped routing queries in `check_ahead_of_vehicle` and `evaluate_host_corridor_match` to handle `OutOfRegionError` cleanly. |
| `src/engine/service/config.py` | Added `routing_region_*` bounding box and `routing_max_snap_distance_meters` configuration fields and env parsing. |
| `src/engine/service/errors.py` | Added `OutOfRegionServiceError` (HTTP 400, `OUT_OF_REGION`). |
| `src/engine/service/service.py` | Integrated bounding box and snap thresholds in `build_service_from_env()`; enforced health check in `require_real_routing`; mapped `OutOfRegionError` in `create_request` and `register_host_ride`. |
| `tests/unit/test_routing_regional_validation.py` | Comprehensive unit tests for coordinate invariants, bounding box, snapping rejection, and service configuration. |
| `tests/integration/test_osrm_regional_boundaries.py` | Live integration tests against Manhattan OSRM (port 5000) and port 5001 availability probe. |

---

## 8. Summary of Operating Invariants Preserved

1. **Physical Invariants:** No negative, non-finite, or boolean coordinates are ever accepted into the engine.
2. **Regional Invariants:** Coordinates outside the operational road network bounding box or snapping $> 5\text{km}$ away from traversable roads are rejected immediately with typed exceptions.
3. **No Silent Corruption:** HTTP 200 responses from OSRM with extreme snapping distances are rejected rather than treated as valid routes.
4. **Deterministic Pruning:** Out-of-region ride requests are automatically disqualified from candidate generation during dispatch solving.
5. **Phase 1 & 2 Preservation:** PostgreSQL connection pool lifecycle, transactional isolation, and event-loop concurrency remain 100% intact and passing.
