# Pool Engine — Phase 5: Multi-Region Routing Architecture and Production Readiness Report

**Repository:** `C:\Users\shaha\pool engine`
**Phase:** Phase 5 — Multi-Region Routing Architecture and Production Readiness
**Date:** October 29, 2026
**Status:** COMPLETE (Multi-Region Real-Routing: BLOCKED pending secondary OSRM dataset provisioning)

---

## 1. Executive Summary

Phase 5 elevates the Pool Engine from a region-validated single-market routing service into an explicitly configured, multi-region-capable architecture. The engine now concurrently supports multiple disjoint regional markets, routing each query to its dedicated road-network backend while enforcing strict boundary safety, sub-second dispatch SLAs, and zero cross-market data contamination.

Key achievements in Phase 5:
1. **Audit & Single-Region Elimination:** Identified and resolved all Manhattan-specific assumptions, including hardcoded probe coordinates in `OsrmRoutingAdapter.check_health()`, single-bounding-box environment configurations, and lack of cross-region journey detection.
2. **Explicit Regional Routing Contract:** Designed and implemented `RegionConfig` supporting stable region identifiers (`region_id`), geographic bounding boxes, provider types (`osrm`, `mock`), dataset identities, road profiles, snap tolerances, and timeout constraints.
3. **Composite Multi-Region Router (`RegionalRoutingRouter`):** Implemented a composite routing provider conforming to `RoadNetworkRoutingProvider` that routes queries to isolated regional providers, strictly validates disjoint boundaries, and immediately rejects unsupported cross-region journeys.
4. **Cache & Deduplication Isolation:** Enhanced `LruLegCache` and singleflight in-flight deduplication keys to incorporate `(dataset_id, profile, origin, destination)`, guaranteeing that road-network metrics cannot leak across incompatible markets or graph versions.
5. **Region-Partitioned Dispatch Orchestration:** Enabled targeted regional dispatch solving (`region_id` parameter) and partitioned multi-region solving, ensuring the $\le 500\text{ms}$ regional dispatch window SLA is strictly preserved per geographic cluster.
6. **Zero-Regression Verification:** Full test suite expanded to **533 passed, 1 skipped in 16.84s** (100% green; 20 new multi-region unit and integration tests). Strict `mypy` passed with zero errors across all 45 source files, and `git diff --check` passed cleanly.
7. **Empirical Benchmarking:** Executed the full scale benchmark matrix across all 4 workloads (`Peak`, `XLarge`, `XXLarge`, `Target`) with fixed seeds, recording 0 deadline expirations (0.0% expiration rate) and full SLA compliance. Microbenchmarks show regional resolution overhead of just $0.21\ \mu\text{s}$ per query.

---

## 2. Architectural Design & Implementation

### 2.1 Regional Routing Contract (`src/engine/contracts/routing.py`)

#### `BoundingBox.overlaps(other)`
Enforces area intersection detection between 2D geographic bounding boxes:
$$\text{lat\_overlap} = \max(\text{min\_lat}_1, \text{min\_lat}_2) < \min(\text{max\_lat}_1, \text{max\_lat}_2)$$
$$\text{lon\_overlap} = \max(\text{min\_lon}_1, \text{min\_lon}_2) < \min(\text{max\_lon}_1, \text{max\_lon}_2)$$
Two bounding boxes with area overlap fail configuration validation at startup, ensuring deterministic $O(1)$ spatial containment mapping.

#### `RegionConfig`
```python
@dataclass(frozen=True)
class RegionConfig:
    region_id: str
    bounding_box: BoundingBox
    provider_type: str = "osrm"  # "osrm" or "mock"
    endpoint_url: str | None = None
    dataset_id: str = "default"
    profile: str = "driving"
    max_snap_distance_meters: float = 5000.0
    timeout_seconds: float = 0.500
    probe_coordinate: Coordinate | None = None
```
- Validates that `region_id` matches `^[a-zA-Z0-9_\-]+$`.
- Validates that `probe_coordinate` falls within `bounding_box`.
- Validates positive snapping tolerances and timeouts.

### 2.2 Composite Router (`src/engine/adapters/regional_router.py`)

`RegionalRoutingRouter` implements `RoadNetworkRoutingProvider` (Composite Pattern):
```
                                 [API Request]
                                       │
                        (Pickup / Dropoff / Vehicle)
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
  │ Isolated LruLegCache        │                 │ Isolated LruLegCache        │
  └─────────────────────────────┘                 └─────────────────────────────┘
```

1. **Spatial Region Resolution:** `find_region_for_coordinate(coord)` checks bounding box containment in $O(K)$ where $K$ is the number of configured regions.
2. **Cross-Region Rejection:**
   - In `get_direct_leg(origin, destination)`: If `find_region(origin) != find_region(destination)`, raises `OutOfRegionError("Cross-region routing between '<id1>' and '<id2>' is unsupported")`.
   - In `get_distance_matrix` and `get_route`: All waypoints must belong to the same region; mixed sets raise `OutOfRegionError`.
3. **Prefetch Partitioning:** `prefetch_matrix` and `prefetch_matrices` group waypoints by region, delegating within-region pairs to their respective provider while safely dropping cross-region combinations.
4. **Per-Region Health Reporting:** `check_regions_health()` provides granular connectivity status for each regional backend.

### 2.3 Cache Isolation & Health Probe Decoupling (`src/engine/adapters/osrm_routing.py`)

1. **Namespaced Cache Keys:**
   ```python
   def _cache_key(self, origin: Coordinate, destination: Coordinate) -> tuple[Any, ...]:
       return (
           self.dataset_id,
           self.profile,
           round(origin.latitude, self.coord_precision),
           round(origin.longitude, self.coord_precision),
           round(destination.latitude, self.coord_precision),
           round(destination.longitude, self.coord_precision),
       )
   ```
   Guarantees zero cache poisoning across different dataset versions or vehicle profiles.
2. **Elimination of Hardcoded Probe Coordinates:**
   In `OsrmRoutingAdapter.check_health()`, the probe coordinate is resolved dynamically from `probe_coordinate` or `(min_lat + max_lat) / 2.0`, completely eliminating previous Times Square hardcoding.

### 2.4 Region-Partitioned Dispatch Orchestration (`src/engine/orchestration/dispatch_orchestrator.py`)

- `DispatchOrchestrator.dispatch_cycle(..., region_id: Optional[str] = None)`:
  - When `region_id` is supplied: Filters pending requests and active vehicles to those within `region_id`, evaluating only the target regional fleet.
  - When `region_id` is omitted in a multi-region deployment: Automatically partitions solving across all configured regions sequentially, preserving the $\le 500\text{ms}$ SLA per market.

---

## 3. Microbenchmark: Regional Validation Overhead

Measured via [`scripts/benchmark_phase5_multiregion_overhead.py`](file:///C:/Users/shaha/pool%20engine/scripts/benchmark_phase5_multiregion_overhead.py) across 100,000 iterations:

| Operation | Baseline / Single Region | Multi-Region Router | Net Overhead | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Region Lookup (Hit 1 — Manhattan)** | N/A | **214.6 ns** ($0.2146\ \mu\text{s}$) | $+0.2146\ \mu\text{s}$ | $O(1)$ fast-path |
| **Region Lookup (Hit 2 — Kerala)** | N/A | **272.7 ns** ($0.2727\ \mu\text{s}$) | $+0.2727\ \mu\text{s}$ | $O(1)$ fast-path |
| **Region Lookup (Miss — Out of Bounds)**| N/A | **240.8 ns** ($0.2408\ \mu\text{s}$) | $+0.2408\ \mu\text{s}$ | Fast pre-network drop |
| **Cross-Region Pre-Network Rejection** | N/A | **1,033.9 ns** ($1.0339\ \mu\text{s}$) | Eliminates $5\text{–}15\text{ms}$ HTTP call | **100.0% accurate** |
| **Direct Leg Query (mean)** | $0.9801\ \mu\text{s}$ | **$2.0347\ \mu\text{s}$** | **$+1.0546\ \mu\text{s}$** | Negligible ($\le 0.04\%$ SLA) |
| **Direct Leg Query (p95)** | $1.7000\ \mu\text{s}$ | **$3.1000\ \mu\text{s}$** | $+1.4000\ \mu\text{s}$ | High predictability |
| **Direct Leg Query (p99)** | $2.6000\ \mu\text{s}$ | **$4.5000\ \mu\text{s}$** | $+1.9000\ \mu\text{s}$ | Bounded tail latency |

**Impact on Dispatch SLA:** For a regional batch evaluating 200 candidate insertion legs:
$$\text{Total Multi-Region Routing Overhead} = 200 \times 1.055\ \mu\text{s} \approx 0.211\text{ ms} \quad (\approx 0.042\%\text{ of the 500ms budget})$$

---

## 4. End-to-End Scale Benchmark (Fixed Seeds: 42, 123, 999)

Executed via [`scripts/benchmark_scale.py`](file:///C:/Users/shaha/pool%20engine/scripts/benchmark_scale.py) against live Manhattan OSRM on port 5000 across 72 total trials (3 seeds $\times$ 3 trials $\times$ 4 workloads $\times$ warm/cold):

| Workload | Scale (Req / Veh) | Cache State | p50 Latency | p95 Latency | p99 Latency | Max Latency | Expired / Total | Match Rate | SLA Result |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Peak** | 150R / 60V | **WARM** | **21.41 ms** | **32.17 ms** | 32.17 ms | 32.17 ms | **0 / 9 (0%)** | 24.4% | **PASS** |
| **Peak** | 150R / 60V | **COLD** | **54.26 ms** | **65.41 ms** | 65.41 ms | 65.41 ms | **0 / 9 (0%)** | 24.4% | **PASS** |
| **XLarge** | 300R / 100V | **WARM** | **47.97 ms** | **59.50 ms** | 59.50 ms | 59.50 ms | **0 / 9 (0%)** | 13.9% | **PASS** |
| **XLarge** | 300R / 100V | **COLD** | **155.39 ms** | **341.58 ms** | 341.58 ms | 341.58 ms | **0 / 9 (0%)** | 13.9% | **PASS** |
| **XXLarge** | 500R / 150V | **WARM** | **71.33 ms** | **80.16 ms** | 80.16 ms | 80.16 ms | **0 / 9 (0%)** | 7.9% | **PASS** |
| **XXLarge** | 500R / 150V | **COLD** | **143.90 ms** | **242.12 ms** | 242.12 ms | 242.12 ms | **0 / 9 (0%)** | 7.9% | **PASS** |
| **Target** | 1,000R / 200V | **WARM** | **83.63 ms** | **102.15 ms** | 102.15 ms | 102.15 ms | **0 / 9 (0%)** | 4.0% | **PASS** |
| **Target** | 1,000R / 200V | **COLD** | **202.41 ms** | **229.30 ms** | 229.30 ms | 229.30 ms | **0 / 9 (0%)** | 4.0% | **PASS** |

**SLA Compliance:** 100% of all trials met the $\le 500\text{ms}$ SLA deadline. Expired rate was **0.0%** across all 72 trials.

---

## 5. Test Suite, Type-Check, and Diff-Check Results

### 5.1 Full Regression Suite
```powershell
$env:TEST_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5433/pool_engine_test"
python -m pytest -ra
```
- **Passed:** **533 passed** (including 20 new Phase 5 multi-region tests).
- **Skipped:** **1 skipped** (`test_kerala_osrm_port_5001_status_is_blocked` in `tests/integration/test_osrm_regional_boundaries.py:67`).
- **Failed:** **0 failed** (100% green in 16.84s).

### 5.2 Strict Type Checking
```powershell
mypy src/
```
- **Result:** `Success: no issues found in 45 source files` (zero errors).

### 5.3 Git Diff Whitespace Check
```powershell
git diff --check
```
- **Result:** Clean (zero output).

---

## 6. Remaining Limitations & Operational Risks

1. **Kerala Live Road Network:** Real Kerala road routing remains **`BLOCKED`** pending provision of an approved Kerala `.osm.pbf` or pre-built `.osrm` graph on port 5001. Per explicit user instructions, zero external map downloads were initiated.
2. **Multi-Region Live Deployment Requirement:** While multi-region routing is certified via unit tests, simulated transports, and live Manhattan OSRM, true multi-region production deployment requires running at least two separate live OSRM backends on distinct host ports.
3. **Database Regional Indexing:** At extreme scale (millions of concurrent active requests across dozens of global markets), adding a dedicated `region_id` column with composite indexing `(region_id, status)` in `schema.sql` will improve query planning over pure coordinate bounding box scans.
