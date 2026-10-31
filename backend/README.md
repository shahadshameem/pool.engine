# Provider-Independent Ride-Pooling & Dispatch Engine

A high-performance, real-time, provider-independent ride-pooling and dispatch engine built with Python 3.13+.

The engine pairs multiple passenger ride requests into shared vehicular journeys, solving vehicle routing and dial-a-ride problems (DARP) under strict spatial, temporal, capacity, and quality-of-service constraints.

## Architecture & Principles

- **Canonical Domain Models**: All entities (Riders, Drivers, Vehicles, Waypoints, Trips, Batches, Constraints) use provider-neutral contracts.
- **Pluggable Adapter Layer**: Pluggable interfaces for spatial indexing (`SpatialIndexProvider`), road network routing (`RoadNetworkRoutingProvider`), dispatch policy (`DispatchPolicyProvider`), and ride storage (`RideStorageProvider`).
- **Two-Stage Feasibility Gate**: Hard physical invariants (pickup-before-dropoff precedence, vehicle seat capacity across all route legs, relative detour ratio $(1 + \delta)$, and pickup delay caps) are evaluated and enforced before scoring.
- **Deterministic Multi-Objective Scoring**: Fleet-wide Set Packing via Regret-K heuristic balancing Total Vehicle Miles Traveled (VMT), passenger wait time, passenger in-vehicle detour, fleet occupancy rate, and operating cost.
- **Deterministic 4-Tier Tie-Breaking**: Quantized utility total-order hierarchy with 4 tiers (VMT savings ratio $\to$ detour penalty $\to$ wait penalty $\to$ canonical lexical sort: vehicle ID $\to$ sorted request IDs $\to$ canonical ordered stop IDs $\to$ candidate ID) ensuring bit-for-bit repeatability and mathematical transitivity.
- **Explicit Operating Modes (Exact vs. Bounded)**:
  - **Exact Mode** (`CandidateGenerationConfig.exact()`): Exhaustive spatial reachability search over the full physical reachability radius ($R_{\text{reach}} = v_{\max} \times \Delta t_{\text{delay}}$) with zero spatial candidate or request count caps.
    - *Scope of Guarantees*: EXACT guarantees exhaustive spatial reachability only within the configured candidate-generation scope:
      1. Up to `max_bundle_size` (default 2) for idle vehicles; 3+ request bundles are not evaluated unless `max_bundle_size` is explicitly configured.
      2. Strictly single-request insertions for active rides; concurrent multi-request insertion into active rides in a single cycle is out of scope.
      3. Fixed relative order of existing stops in active rides.
      4. Physical speed ceiling of $v_{\max} = 120\text{ km/h}$ ($33.333\text{ m/s}$).
      5. Fleet set packing is solved via the Regret-K heuristic ($k=2$), not exact Branch-and-Cut ILP; global mathematical optimality is not guaranteed.
      6. Does **not** guarantee the 500 ms SLA for large batches ($N=1,000$ requires $> 10\text{ seconds}$). If the wall-clock deadline expires before completion, the result is explicitly flagged with `search_status=SearchStatus.INCOMPLETE_DEADLINE_EXPIRED` and `is_approximated=True`.
  - **Bounded Mode** (`CandidateGenerationConfig.bounded()`): High-throughput production mode with explicit, user-configured approximation limits (default 5 km search radius, max 8 vehicles per request, max 3 requests per vehicle, max bundle size 2). Solves 1,000 requests and 200 vehicles in sub-500 ms while strictly preserving all hard physical invariants and reporting `SearchStatus.APPROXIMATED` and `is_approximated=True`.
- **Sub-Second Latency SLA (Bounded Mode Only)**: Solves batches of 1,000 active requests and 200 vehicles in under 500 ms **strictly in BOUNDED mode** under a single monotonic wall-clock deadline with 50 ms reserved Stage 6 serialization headroom. The 500 ms SLA target does not apply to EXACT mode.

## Installation

### Prerequisites
- Python 3.13+
- Windows PowerShell 5.1 (`powershell.exe`) or POSIX shell

### Setup Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -U pip
pip install -e .[dev]
```

## Quickstart & Verification Scenarios

Run the end-to-end integration scenarios:

### 1. Multi-Passenger Group Bundling & Insertion
```powershell
pytest tests/scenario/test_group_matching.py -v -k "test_group_bundle_capacity"
```

### 2. Two-Stage Feasibility Gate & Invariant Protection
```powershell
pytest tests/unit/test_invariants.py -v -k "test_hard_invariant_gate"
```

### 3. Atomic Concurrency & Seat Holds
```powershell
pytest tests/concurrency/test_atomic_reservation.py -v -k "test_concurrent_seat_contention"
```

### 4. Exact Boundary Timer & Grace Period Transitions
```powershell
pytest tests/unit/test_lifecycle_timers.py -v -k "test_grace_period_boundaries"
```

### 5. Spatial Candidate Discovery & Recall
```powershell
pytest tests/unit/test_spatial_index.py -v -k "test_spatial_candidate_recall"
```

### 6. Solver Performance SLA & Optimality Gap
```powershell
pytest tests/benchmark/test_solver_performance.py -v
pytest tests/benchmark/test_solver_optimality.py -v -k "test_ilp_reference_gap"
```

### 7. Explicit Exact and Bounded Dispatch Modes
```powershell
pytest tests/scenario/test_dispatch_modes.py -v
```

### 8. PostgreSQL / PostGIS Persistent Storage & Integration
```powershell
# Unit tests (mocked & DDL validation):
pytest tests/unit/test_postgres_storage.py -v

# Live integration tests (requires PostgreSQL; set TEST_DATABASE_URL):
$env:TEST_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/pool_engine_test"
pytest tests/integration/test_postgres_integration.py -v
```

### 9. Routing Provider Fault Isolation & Leg Validation
```powershell
pytest tests/unit/test_routing_fault_isolation.py -v
```

### 10. Dispatch Orchestration & Atomic Commits
```powershell
# Unit tests (in-memory, OCC version conflicts, retry isolation, race prevention):
pytest tests/unit/test_dispatch_orchestrator.py -v

# Live PostgreSQL integration tests (transactional row locks, OCC rollback, persistence across instances):
$env:TEST_DATABASE_URL = "postgresql://postgres@localhost:5433/pool_engine_test"
pytest tests/integration/test_orchestrator_postgres.py -v
```

### 11. Production Road-Network Routing (OSRM Adapter)
```powershell
# Unit tests (offline, fake HTTP transport, matrix chunking, LRU cache):
pytest tests/unit/test_osrm_routing.py -v

# Real-road benchmark comparison (Mock vs. OSRM cold/warm cache):
python -m tests.benchmark.test_osrm_benchmark
pytest tests/benchmark/test_osrm_benchmark.py -v

# Live OSRM real-road test (requires running OSRM backend):
$env:OSRM_BASE_URL = "http://localhost:5000"
pytest tests/benchmark/test_osrm_benchmark.py -v -k "test_live_osrm"
```

## Static Analysis & Testing

Run all unit, scenario, property, concurrency, and benchmark tests:
```powershell
python -m pytest -v
```

Run strict type checking:
```powershell
python -m mypy --strict src/ tests/
```

## Package Layout

```text
src/engine/
  ├── domain/          # Canonical models (Ride, Vehicle, RideRequest, CandidateAssignment)
  ├── contracts/       # Provider ABCs (spatial, routing, policy, storage)
  ├── spatial/         # Haversine bounds, derived bounding-box, coordinate index
  ├── routing/         # Stop insertion permutations, group bundling, invariant gates
  ├── optimization/    # Multi-objective utility, quantized tie-breaking, Regret-K set packing
  ├── lifecycle/       # Reservation protocol, transitions, timers, dwell verification
  ├── adapters/        # H3 spatial, OSRM road router, mock router, in-memory & Postgres storage
  ├── orchestration/   # DispatchOrchestrator connecting persistent storage and dispatch
  └── dispatch.py      # Unified DispatchEngine facade
```
