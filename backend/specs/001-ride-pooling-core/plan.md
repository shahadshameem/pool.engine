# Implementation Plan: Core Provider-Independent Ride-Pooling and Dispatch Engine

**Branch**: `001-ride-pooling-core` | **Date**: 2026-10-24 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-ride-pooling-core/spec.md`

---

## Summary

This plan defines the architecture, module layout, algorithmic pipeline, and verification strategy for a high-performance, real-time, provider-independent ride-pooling engine. 

The engine solves the dynamic multi-vehicle dial-a-ride problem (DARP) for individual and multi-passenger group requests by executing a **Two-Tier Optimization Framework**:
1. **Tier 1 (Candidate Generation & Feasible Route Insertion)**:
   - Provider-neutral spatial indexing (`SpatialIndexProvider`) queries candidate neighborhoods using adaptive multi-ring expansion and conservative metric lower-bound pruning ($d_{\text{haversine}} \le d_{\text{road}}$).
   - Generates admissible `CandidateAssignment` bundles for (a) single-request insertion into active rides and (b) multi-request group formation for available vehicles.
   - Stage 1 invariant gating strictly prunes capacity overages, pickup/dropoff order inversions, detour breaches, and pickup delay exceedances before objective evaluation.
2. **Tier 2 (Fleet-Wide Conflict-Free Assignment)**:
   - Formulates batch dispatch as a **Set Packing Problem / Maximum Weight Independent Set** over candidate bundles, maximizing total composite utility $J$.
   - Enforces disjoint request constraints ($\sum_{T \ni r} x_{v, T} \le 1$) and fleet limits ($\sum_T x_{v, T} \le 1$) via Primal-Dual Auction / Greedy with Regret-K.
   - Enforces an anytime deadline with a hard interrupt at $450\text{ms}$ to guarantee final verification and serialization complete within the $\le 500\text{ms}$ SLA.

The core engine is completely decoupled from external mapping vendors, telematics protocols, and database engines via four canonical abstraction contracts: `RoadNetworkRoutingProvider`, `RideStorageProvider`, `DispatchPolicyProvider`, and `SpatialIndexProvider`.

---

## Technical Context

- **Language & Runtime**: Python 3.13+ with strict type annotations (`mypy --strict`).
- **Primary Dependencies**:
  - `numpy`: Vectorized matrix operations and numeric evaluations.
  - `h3` (H3-py C-extension) / pluggable spatial providers: Fast $O(1)$ discrete spatial lookups.
  - `pydantic` (v2.x) / `dataclasses`: Canonical domain model validation and immutable schemas.
- **Storage Layer**: Decoupled via `RideStorageProvider` (supports in-memory snapshots for tests/benchmarks and PostgreSQL/Redis for production).
- **Testing Tools**: `pytest`, `hypothesis` (property-based invariant testing), `pytest-benchmark`.
- **Target Platform**: Windows PowerShell 5.1 (`powershell.exe`) and Linux container runtimes.
- **Project Type**: Standalone computational engine and reusable dispatch library.
- **Performance Goals**: Batch dispatch optimization solving cycle $\le 500\text{ms}$ under a regional cluster workload of 1,000 active requests and 200 vehicles (treated as an empirically measured acceptance target).
- **Constraints**:
  - Zero invariant violations (no dropoff before pickup, never exceed vehicle capacity, never exceed detour caps).
  - Bit-for-bit deterministic reproducibility for identical inputs and PRNG seeds.
  - Zero vendor SDK assumptions in core modules.

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-evaluated post-design.*

| Principle | Constitution Mandate | Proposed Implementation Alignment | Gate Status |
| :--- | :--- | :--- | :--- |
| **I. Correctness & Physical Invariants** | Zero illegal passenger states, capacity conservation, detour bounds. | Enforced as non-negotiable hard gates in Stage 1 pruning prior to objective scoring. Invariant validator checks every route leg. | **PASS** |
| **II. Provider Neutrality** | Zero vendor coupling; canonical domain models; isolated adapters. | Abstract base classes (`RoadNetworkRoutingProvider`, `RideStorageProvider`, `DispatchPolicyProvider`, `SpatialIndexProvider`) isolate all external infrastructure. | **PASS** |
| **III. Multi-Objective Optimization** | Explicit objective balancing VMT, detour, wait, and idle time; transparent scoring. | Mathematically formulated utility maximization $J$; itemized score breakdown output with every match result. | **PASS** |
| **IV. Modular Architecture** | Unidirectional layers: Spatial Index $\to$ Candidate Gen $\to$ Solver $\to$ State. | Strict module separation under `src/engine/` preventing cyclic dependencies or downstream leaks. | **PASS** |
| **V. Test-First Development** | Mandatory TDD; unit, scenario, property, and benchmark tests. | Test architecture defined with red-green-refactor workflow across unit, concurrency, property, and simulation tiers. | **PASS** |
| **VI. Concurrency & Determinism** | Stateless solver; bit-for-bit determinism; thread-safe state mutations. | Pure, stateless solver over immutable snapshots; deterministic tie-breaking hierarchy; optimistic CAS seat locking. | **PASS** |
| **VII. Sub-Second Latency SLAs** | Batch solving $\le 500\text{ms}$ for regional clusters; bounded memory. | Monotonic wall-clock deadline ($450\text{ms}$ cutoff, $50\text{ms}$ reserved Stage 6 headroom); 100% fixture candidate recall; safe timeout fallback; in-memory routing cache. | **PASS** |
| **VIII. Security & Privacy** | Location sanitization; input validation; structured audit logging. | Bounded schema validation on all inputs; coordinates obfuscated in non-operational logs; audit metadata emitted. | **PASS** |

---

## Project Structure

### Documentation & Spec Kit Artifacts
```text
specs/001-ride-pooling-core/
├── spec.md                  # Ratified feature specification
├── plan.md                  # This implementation plan
├── research.md              # Phase 0: Technology evaluation, group matching & latency budget
├── data-model.md            # Phase 1: Canonical domain model & state machines
├── quickstart.md            # Phase 1: End-to-end executable validation guide
├── checklists/
│   └── requirements.md      # Specification quality checklist (100% verified)
└── contracts/
    ├── routing-provider.md  # RoadNetworkRoutingProvider contract
    ├── storage-provider.md  # RideStorageProvider contract
    ├── policy-provider.md   # DispatchPolicyProvider contract
    └── spatial-provider.md  # SpatialIndexProvider contract
```

### Source Code Layout
```text
src/
└── engine/
    ├── __init__.py
    ├── domain/                    # Canonical domain schemas (immutable)
    │   ├── __init__.py
    │   ├── models.py              # User, Driver, Vehicle, RouteStop, Ride, RideRequest, MatchResult
    │   ├── candidate.py           # CandidateAssignment (hyperedge bundle representation)
    │   └── enums.py               # RideStatus, StopStatus, JoinStatus, DriverStatus
    ├── contracts/                 # Abstract provider interfaces
    │   ├── __init__.py
    │   ├── routing.py             # RoadNetworkRoutingProvider ABC
    │   ├── storage.py             # RideStorageProvider ABC
    │   ├── policy.py              # DispatchPolicyProvider ABC & DispatchPolicy schema
    │   └── spatial.py             # SpatialIndexProvider ABC & SpatialCandidate schema
    ├── spatial/                   # Spatial indexing & candidate discovery
    │   ├── __init__.py
    │   ├── index.py               # Provider-neutral spatial indexing coordinator
    │   └── lower_bounds.py        # Conservative Haversine metric lower-bound pruning
    ├── routing/                   # Route insertion & group trip generation
    │   ├── __init__.py
    │   ├── insertion.py           # Stop insertion permutations (idx_P < idx_D)
    │   ├── bundle_generator.py    # Multi-request group trip generation
    │   └── invariants.py          # Stage 1 hard invariant checks (precedence, capacity, detour)
    ├── optimization/              # Batch matching solver & objective scoring
    │   ├── __init__.py
    │   ├── objective.py           # Multi-objective utility scoring (VMT, detour, wait, idle)
    │   ├── tie_breaking.py        # 4-tier deterministic tie-breaking hierarchy
    │   └── set_packing.py         # Fleet-wide Set Packing solver with anytime deadline
    ├── lifecycle/                 # Ride & stop state transitions
    │   ├── __init__.py
    │   ├── transitions.py         # Lifecycle event dispatcher & boundary timer logic
    │   └── reservations.py        # Join request handling, double revalidation & atomic seat holds
    └── adapters/                  # Default / Mock provider implementations
        ├── __init__.py
        ├── mock_routing.py        # In-memory deterministic matrix routing provider
        ├── in_memory_storage.py   # Thread-safe in-memory storage provider with CAS locking
        ├── default_policy.py      # Default policy provider with A/A/A configuration
        └── h3_spatial.py          # Uber H3 adapter implementing SpatialIndexProvider

tests/
├── unit/                          # Invariant & domain model tests
│   ├── test_invariants.py         # Precedence, capacity, detour boundary tests
│   ├── test_models.py             # Schema validation and bounds checking
│   ├── test_spatial_index.py      # Candidate recall vs. exhaustive search (100% on fixtures)
│   └── test_lifecycle_timers.py   # Exact second-level timer boundaries
├── scenario/                      # Dial-a-ride pooling scenarios
│   ├── test_insertion_matching.py # Short vs long trip detour, pickup delay exceedance
│   └── test_group_matching.py     # Multi-passenger group bundling & capacity constraints
├── concurrency/                   # Thread safety & race condition tests
│   └── test_atomic_reservation.py # Concurrent seat contention, idempotency & rollback
├── property/                      # Hypothesis randomized invariant testing
│   └── test_spatial_invariants.py # Randomized coordinate distributions & capacity fuzzing
└── benchmark/                     # Latency & scale benchmark suite
    ├── test_solver_performance.py # 1,000 req / 200 veh benchmark under 500ms SLA
    └── test_solver_optimality.py  # Optimality gap vs. exact reference ILP solver (N <= 50)
```

---

## 1. Functional Requirements to Module Mapping

| Requirement ID | Requirement Scope | Target Module / Interface |
| :--- | :--- | :--- |
| **FR-001** | Canonical domain models | `src/engine/domain/models.py` & `candidate.py` |
| **FR-002** | Pluggable road network routing contract | `src/engine/contracts/routing.py` |
| **FR-003** | Pluggable state persistence & atomic locking | `src/engine/contracts/storage.py` |
| **FR-004** | Pluggable operational policy & configuration | `src/engine/contracts/policy.py` |
| **FR-005, FR-006** | Spatial & temporal candidate filtering | `src/engine/spatial/index.py` & `lower_bounds.py` |
| **FR-007** | Individual & multi-passenger group requests | `src/engine/routing/bundle_generator.py` |
| **FR-008** | Precedence invariant ($idx_{\text{pickup}} < idx_{\text{drop}}$) | `src/engine/routing/invariants.py` |
| **FR-009** | Capacity conservation ($Occupancy(l) \le Capacity$) | `src/engine/routing/invariants.py` |
| **FR-010** | Maximum detour bounds ($\Delta T \le \min((\alpha - 1) T_{\text{direct}}, C)$) | `src/engine/routing/invariants.py` |
| **FR-011** | Pickup delay bounds ($\Delta T_{\text{pickup}} \le \text{max\_delay}$) | `src/engine/routing/invariants.py` |
| **FR-012, FR-016** | Ride lifecycle states & cancellation updates | `src/engine/lifecycle/transitions.py` |
| **FR-013, FR-024** | Boarding grace period & GPS arrival dwell verification | `src/engine/lifecycle/transitions.py` |
| **FR-014, FR-015** | Join requests, double revalidation & atomic seat holds | `src/engine/lifecycle/reservations.py` |
| **FR-017, FR-019** | Multi-objective scoring & itemized audit breakdown | `src/engine/optimization/objective.py` |
| **FR-018, FR-023** | Deterministic matching & 4-tier tie-breaking hierarchy | `src/engine/optimization/tie_breaking.py` |
| **FR-020** | Policy validation & invalid parameter rejection | `src/engine/contracts/policy.py` |
| **FR-021** | In-flight ride promise window immutability | `src/engine/contracts/policy.py` |
| **FR-022** | Strict Two-Stage evaluation pipeline (Gate $\to$ Score) | `src/engine/optimization/set_packing.py` |
| **FR-025** | Scheduled departure grace period monitoring | `src/engine/lifecycle/transitions.py` |

---

## 2. Canonical Domain Model & Provider Contracts

### Domain Schemas & Candidate Representation
Detailed schemas are defined in [`data-model.md`](data-model.md). Key entities include:
- **`CandidateAssignment`**: The core hyperedge data structure representing a candidate assignment:
  - `candidate_id`: `str`
  - `vehicle_id`: `str`
  - `existing_ride_id`: `str | None`
  - `request_ids`: `tuple[str, ...]` (the set of bundled requests $\{r_1, r_2, \dots, r_k\}$)
  - `ordered_stops`: `tuple[RouteStop, ...]` (feasible sequenced itinerary)
  - `peak_seat_load`: `int` (instantaneous peak load $\le Capacity$)
  - `vmt_meters`: `int` (total planned route road distance)
  - `objective_value`: `float` (raw composite utility $J \in [-0.60, +0.40]$)
  - `normalized_score`: `float` ($J_{\text{display}} \in [0.0, 1.0]$)
  - `score_breakdown`: `ScoreBreakdown`

### Provider Contracts
Detailed contracts are defined in [`contracts/`](contracts/):
1. **`RoadNetworkRoutingProvider`** ([`routing-provider.md`](contracts/routing-provider.md)): Query road distance/time matrices and turn-by-turn routes in integer meters/seconds.
2. **`RideStorageProvider`** ([`storage-provider.md`](contracts/storage-provider.md)): Transactional snapshot retrieval, optimistic version check, atomic seat holds with unified $T_{\text{expires}}$, and serializable race resolution.
3. **`DispatchPolicyProvider`** ([`policy-provider.md`](contracts/policy-provider.md)): Policy validation, A/A/A defaults, and dynamic update safety.
4. **`SpatialIndexProvider`** ([`spatial-provider.md`](contracts/spatial-provider.md)): Provider-neutral spatial indexing with adaptive multi-ring expansion, safe metric lower bounds ($d_{\text{haversine}} \le d_{\text{road}}$), 100% fixture recall guarantee, and safe bounding-box fallback.

---

## 3. Algorithmic Formulation: Group Matching & Fleet Assignment

### 3.1 Resolving the Fallacy of Bipartite Matching: The Two-Tier Problem Formulation
Standard bipartite matching (1 request to 1 vehicle) cannot solve ride pooling. The engine formulates matching across a structured **Two-Tier Optimization Framework**, defining precisely which mathematical problem each tier solves:

#### Tier 1: Constrained Itinerary Permutation & Feasible Bundle Generation (Hyperedge Construction)
Tier 1 solves the local constrained Dial-a-Ride Problem (DARP) for individual vehicles to generate admissible candidate hyperedges:
1. **Sub-Problem 1 (Insertion into Active Shared Rides)**:
   - For an active vehicle with existing stops $S = [s_1, \dots, s_k]$, evaluates single-request insertion permutations maintaining $idx_P < idx_D$.
2. **Sub-Problem 2 (Multi-Request Group Bundling for Available Vehicles)**:
   - For available vehicles, bundles of 2, 3, or 4 compatible requests are formed by intersecting spatial/temporal candidate sets. Stop sequencing evaluates permutations that maintain capacity and detour bounds.
- **Stage 1 Invariant Gate**: Every generated sequence must strictly pass capacity conservation across all legs ($Occupancy(l) \le Capacity$), individual detour bounds ($\Delta T \le \min((\alpha - 1) T_{\text{direct}}, C)$), and pickup delay bounds ($\Delta T_{\text{pickup}} \le \text{max\_pickup\_delay}$). Violations are pruned before objective scoring.
- **Output**: Each surviving sequence forms a concrete `CandidateAssignment` hyperedge with pre-calculated utility score $J$.

#### Tier 2: Fleet-Wide Set Packing / Maximum Weight Independent Set (Hyperedge Selection)
Tier 2 solves the global fleet conflict-free assignment problem across all candidate hyperedges generated in Tier 1:
3. **Sub-Problem 3 (Fleet-Wide Set Packing / MWIS)**:
   - Given a collection of candidate bundles $\mathcal{C} = \{c_1, c_2, \dots, c_m\}$ where each candidate $c = (v, T_c, J_c)$ targets vehicle $v$ and covers requests $T_c \subseteq R$, find a subset of assignments $\mathcal{X} \subseteq \mathcal{C}$ that:
     $$\text{Maximize } \sum_{c \in \mathcal{X}} J_c$$
     $$\text{Subject to: } \sum_{c \in \mathcal{X} : v(c) = v} 1 \le 1, \quad \forall v \in V \quad \text{(Fleet Constraint: 1 bundle per vehicle)}$$
     $$\sum_{c \in \mathcal{X} : r \in T_c} 1 \le 1, \quad \forall r \in R \quad \text{(Request Disjointness Constraint: 1 vehicle per request)}$$

### 3.2 Invariant Violation Prevention
The solver strictly prevents invalid states by construction:
- **No Duplicate Assignments**: Enforced by the Request Disjointness Constraint in the Set Packing formulation. When candidate $c_1$ covering $\{r_1, r_2\}$ is selected, all other candidates containing $r_1$ or $r_2$ are disqualified.
- **No Capacity Overages**: During candidate stop sequence generation, cumulative load is evaluated across every leg: $Occupancy(l) = \sum_{i=1}^l \Delta \text{passengers}_i \le Capacity$. Any sequence violating capacity is discarded in Stage 1 before candidate formation.
- **No Route Inversions**: Permutations are generated only for $idx_P < idx_D$.
- **No Detour or Pickup Delay Violations**: Bounded by $\Delta T \le \min((\alpha - 1) T_{\text{direct}}, C)$ and $\Delta T_{\text{pickup}} \le \text{max\_pickup\_delay}$. Violations are pruned in Stage 1.

### 3.3 Solver Selection, Complexity Derivation & Trade-Off Analysis
- **Selected Algorithm**: **Greedy Set Packing with Regret-K Heuristic**:
  1. Initialize inverted request-to-candidate index ($r \mapsto \mathcal{C}_r$) and vehicle-to-candidate index ($v \mapsto \mathcal{C}_v$).
  2. For each request, maintain candidate bundles ordered by utility in a local candidate heap.
  3. Compute regret for each request ($\text{regret}_k(r) = J(c_{r, 1}) - J(c_{r, \min(k, |\mathcal{C}_r|)})$) and maintain requests in a global regret max-heap.
  4. Iteratively commit the assignment with the highest regret, instantly invalidating conflicting vehicle candidates ($\mathcal{C}_{v^*}$) and request candidates ($\mathcal{C}_{r'}$ for $r' \in T_{c^*}$).
  5. For affected requests whose top-$k$ candidates were invalidated, recompute regret and update their positions in the regret max-heap.
  6. Time-bounded: If elapsed time reaches $450\text{ms}$, the algorithm terminates immediately and returns the conflict-free assignment accumulated so far.
- **Asymptotic Complexity Derivation**:
  - *Initialization*: Building inverted indices and candidate heaps takes $\mathcal{O}(B \cdot |\mathcal{C}| \log k)$. Heapifying $N$ requests takes $\mathcal{O}(N)$.
  - *Conflict Invalidation*: Across all iterations, each candidate $c \in \mathcal{C}$ is invalidated at most once ($O(|\mathcal{C}|)$ total amortized across the entire run).
  - *Regret Updates*: At most $B \cdot |\mathcal{C}|$ total candidate removals occur across request pools. Each top-$k$ candidate replacement costs $O(\log d_{\max})$ in the request candidate heap and $O(\log N)$ in the global regret heap.
  - *Worst-Case Bound with Indexed Heaps*:
    $$\mathcal{O}\left(B \cdot |\mathcal{C}| \cdot (\log d_{\max} + \log N) + N \log N\right) \approx \mathcal{O}\left(|\mathcal{C}| \cdot (\log d_{\max} + \log N) + N \log N\right)$$
  - *Naive Linear Rescan Bound*: If implemented without auxiliary heaps (rescanning all candidates for affected requests in each iteration), the bound degrades to $\mathcal{O}(\min(N, M) \cdot |\mathcal{C}|)$.
  - *Trade-off & Benchmark Validation Requirement*: Unlike exact ILP solvers that exhibit exponential worst-case tail latency ($O(2^{|\mathcal{C}|})$), Regret-K guarantees polynomial execution. However, actual wall-clock execution depends directly on data structure implementation choices and graph density ($d_{\max}$). The reference solver mandates indexed binary heaps, and empirical benchmark suites ([`test_solver_performance.py`](tests/benchmark/test_solver_performance.py)) MUST validate that execution completes within the 140ms solver budget across both dense ($d_{\max} \gg 1$) and sparse ($d_{\max} \approx 1$) regimes.
- **Empirical Optimality Gap Protocol**:
  Rather than asserting an unverified theoretical optimality bound, the test suite implements an empirical evaluation harness (`test_solver_optimality.py`). The heuristic's solution quality is benchmarked against an exact Branch-and-Cut reference solver on small fixture instances ($N \le 50$ requests, $V \le 15$ vehicles) across dense, sparse, and constrained regimes, explicitly reporting the percentage gap:
  $$\text{Optimality Gap} = \frac{J^*_{\text{exact}} - J_{\text{heuristic}}}{J^*_{\text{exact}}} \times 100\%$$

---

## 4. End-to-End Latency Budget & Monotonic Wall-Clock Deadline

The 500 ms latency SLA is an **acceptance target to be empirically measured and verified**, not assumed by design alone.

### Monotonic Wall-Clock Deadline Architecture
Execution of the entire batch dispatch cycle is governed by a **single monotonic wall-clock deadline**:
$$\text{deadline} = \text{time.monotonic}() + 0.500$$

All intermediate stage budgets are subordinate to this deadline. Continuous monotonic checks prevent runaway stages from eroding downstream verification:

| Stage | Subordinate Budget | Monotonic Deadline Offset | Cutoff Behavior |
| :--- | :--- | :--- | :--- |
| **Stage 1**: Input Ingestion & Schema Validation | $30\text{ms}$ | $t_0 + 0.030\text{s}$ | Abort on malformed input |
| **Stage 2**: Spatial Candidate Discovery & Lower Bounds | $60\text{ms}$ | $t_0 + 0.090\text{s}$ | Fallback to bounding-box if spatial query fails |
| **Stage 3**: Feasible Route Insertion & Stage 1 Pruning | $150\text{ms}$ | $t_0 + 0.240\text{s}$ | Truncate remaining permutations; proceed with evaluated |
| **Stage 4**: Group Bundling & Metric Normalization | $70\text{ms}$ | $t_0 + 0.310\text{s}$ | Truncate higher-order bundles; proceed with evaluated |
| **Stage 5**: Fleet Assignment Solver | $140\text{ms}$ | $t_0 + 0.450\text{s}$ | **Hard Cutoff at $450\text{ms}$**: terminate loop, keep best feasible set |
| **Stage 6**: Final Verification, Tie-Breaking & Serialization | $50\text{ms}$ | $t_0 + 0.500\text{s}$ | **Reserved Headroom**: finalize and serialize `MatchResult` |

### Overrun, Timeout & Safe Fallback Behavior
- **Hard Interrupt at $450\text{ms}$ (`deadline - 0.050`)**: The solver monitors `time.monotonic()` at each assignment iteration. When elapsed time reaches $450\text{ms}$, active solver loops terminate immediately.
- **Reserved Headroom ($50\text{ms}$)**: Stage 6 is strictly guaranteed $50\text{ms}$ to perform post-solve conflict-free verification, apply deterministic tie-breaking, and serialize the canonical `MatchResult`.
- **Documented Safe Fallback Guarantee**: If a critical timeout or exception occurs before Stage 5 commits a valid assignment, the engine executes a stateless rollback:
  - All incoming requests remain unassigned (`status = PENDING`) in the demand queue for the subsequent cycle.
  - Active vehicle routes and seat allocations remain entirely untouched.
  - Partially constructed, conflicting, or invalid assignments are **never returned or persisted**.
- **Stateless Solver Execution**: Each dispatch cycle is completely pure and stateless. Solver state does not persist between cycles, preventing cascading failures across batches.

### Benchmark Metrics Captured
1. **Latency Distribution**: p50, p95, p99, and maximum observed latency.
2. **Timeout Rate**: Percentage of batch runs triggering the $450\text{ms}$ interrupt (target: $\le 0.1\%$).
3. **Feasible Solution Rate**: Percentage of batches yielding valid, zero-violation solutions (target: $100\%$).
4. **Candidate Recall**: Percentage of feasible matches discovered by spatial filtering relative to exhaustive search on benchmark fixtures (target: **100% on test fixtures**).

---

## 5. Spatial Candidate Discovery & Lower-Bound Filtering

### Provider-Neutral Architecture
Isolated behind `SpatialIndexProvider` ([`spatial-provider.md`](contracts/spatial-provider.md)).

### Mathematical Proof: Pruning Rules Cannot Eliminate Feasible Candidates
1. **Pickup Reachability Lower Bound**:
   - For vehicle $v$ and request pickup $p$, road travel time is strictly bounded below by Haversine distance divided by maximum network speed $v_{\max}$:
     $$\text{TravelTime}_{\text{road}}(v_{\text{loc}}, p_{\text{loc}}) \ge \frac{d_{\text{road}}(v_{\text{loc}}, p_{\text{loc}})}{v_{\max}} \ge \frac{d_{\text{haversine}}(v_{\text{loc}}, p_{\text{loc}})}{v_{\max}} \equiv t_{\text{min\_pickup}}$$
   - If $t_{\text{min\_pickup}} > \Delta T_{\text{available}}(v, r) = \max\left(0, t_{\text{earliest\_pickup}}(r) + \text{max\_pickup\_delay\_seconds} - t_{\text{earliest\_departure}}(v)\right)$, road arrival within the delay window is physically impossible on *any* conceivable road network.
   - Pruning this pairing eliminates **zero** feasible candidates. $\blacksquare$
2. **Active Itinerary Detour Lower Bound**:
   - For an active vehicle inserting stop $p$ between existing stops $A$ and $B$, the added travel time is bounded below by the metric triangle inequality:
     $$\Delta t_{\text{min\_insertion}} = \frac{\max\left(0, d_{\text{haversine}}(x_A, x_p) + d_{\text{haversine}}(x_p, x_B) - d_{\text{road}}(x_A, x_B)\right)}{v_{\max}}$$
   - If $\Delta t_{\text{min\_insertion}} > \min((\alpha - 1) T_{\text{direct}}, C) - \Delta T_{\text{accumulated}}$ for any onboard passenger, the insertion is provably infeasible.
   - Pruning this insertion eliminates **zero** feasible candidates. $\blacksquare$

### Adaptive Multi-Ring Neighborhood Expansion & Exact Termination
- **Maximum Feasible Physical Search Radius**:
  $$R_{\text{search\_max}} = v_{\max} \cdot \text{max\_pickup\_delay\_seconds}$$
  Any coordinate at $d_{\text{haversine}} > R_{\text{search\_max}}$ is provably unreachable within the pickup delay window.
- **Ring Expansion Protocol**: Search begins at initial cell $k=0$ and expands to concentric neighbor rings $k = 1, 2, \dots$
- **Exact Termination Criteria**:
  Let $r_{\text{inner\_min}}(k)$ be the minimum distance from the target cell to the outer perimeter of ring $k$. Ring expansion terminates if and only if either:
  1. *Guaranteed Radius Coverage*: $r_{\text{inner\_min}}(k) \ge R_{\text{search\_max}}$ (all coordinates within physical reach have been evaluated).
  2. *Candidate Count Saturation*: Discovered candidate count reaches `max_candidates` AND all contiguous cells in the current ring $k$ have been fully processed (preventing directional selection bias).

### Mandatory Exhaustive Fallback & Derived Bounding-Box Proof
- **When Fallback is Required**:
  A spatial provider MUST trigger exhaustive bounding-box fallback under any of the following conditions:
  1. An indexing fault, cell lookup exception, or unindexed coordinate occurs.
  2. Target coordinate is near a spherical discontinuity (antimeridian $\pm 180^\circ$ or polar latitudes $|\phi| > 85^\circ$).
  3. The provider hits its maximum configured ring expansion limit ($k_{\text{limit}}$) before achieving $r_{\text{inner\_min}}(k) \ge R_{\text{search\_max}}$, AND fewer than `min_candidates` are found.
- **Derived Bounding Box**:
  Given target coordinate $(\phi_0, \lambda_0)$ in radians, angular radius $\Delta \sigma = \frac{R_{\text{search\_max}}}{R_{\text{earth}}}$, and maximum absolute latitude $\phi_{\text{max\_abs}} = \min\left(\frac{\pi}{2} - 10^{-6}, \max(|\phi_0 - \Delta \sigma|, |\phi_0 + \Delta \sigma|)\right)$:
  $$\text{BBox}(x_0, R_{\text{search\_max}}) = [\phi_0 - \Delta \sigma, \lambda_0 - \Delta \lambda, \phi_0 + \Delta \sigma, \lambda_0 + \Delta \lambda]$$
  where $\Delta \lambda = \frac{\Delta \sigma}{\cos(\phi_{\text{max\_abs}})}$.
- **Proof of Bounding-Box Completeness**:
  By the Haversine formula, $\sin^2(\Delta \sigma / 2) \ge \sin^2((\phi - \phi_0)/2) + \cos(\phi_0)\cos(\phi)\sin^2((\lambda - \lambda_0)/2)$.
  Since each term is non-negative, $|\phi - \phi_0| \le \Delta \sigma$ and $|\lambda - \lambda_0| \le \frac{\Delta \sigma}{\cos(\phi_{\text{max\_abs}})} = \Delta \lambda$ strictly hold for all points with $d_{\text{haversine}} \le R_{\text{search\_max}}$.
  Therefore, every point within distance $R_{\text{search\_max}}$ is provably contained inside $\text{BBox}$.
  Filtering entities within this derived $\text{BBox}$ followed by exact Haversine verification mathematically guarantees **100% complete recall** of all physically feasible candidate entities. $\blacksquare$

### Recall Validation Against Exhaustive Baseline
- **100% Fixture Candidate Recall**: In all defined benchmark fixtures ($N = 50, 100, 200$ requests), spatial candidate filtering is evaluated against a brute-force all-pairs search and MUST achieve **100% candidate recall** of all physically feasible pooled pairings. Any dropped feasible candidate on test fixtures constitutes an immediate test failure.
- **Fixture Verification vs. Universal Networks**:
  - *Fixture Verification*: Strict 100% recall against exhaustive search verifies that spatial indexing does not drop feasible matches on cell edges within controlled test environments.
  - *Universal Open Networks*: On real-world arbitrary road networks, straight-line Haversine lower bounds ($d_{\text{haversine}} \le d_{\text{road}}$) are mathematically sound, but complex road topologies (e.g. bodies of water, detours, restricted turns) require safe fallbacks.

---

## 6. Reproducible Deterministic Benchmark Specification

To ensure benchmarks are completely reproducible across environments, the test suite defines fixed fixtures and runtime conditions:

### Workload & Service Area
- **Bounding Box**: $10\text{ km} \times 10\text{ km}$ urban bounding box (e.g., $[40.7000, -74.0200]$ to $[40.7900, -73.9000]$).
- **Request Volume**: 1,000 active requests generated with fixed PRNG seed `seed=42`.
  - Demand Distribution: 60% clustered around 3 urban hot-spots (e.g. downtown, airport, transit hub); 40% uniformly distributed.
  - Party Sizes: 70% 1-seat requests, 20% 2-seat requests, 10% 3-to-4 seat requests.
  - Trip Durations ($T_{\text{direct}}$): 40% short ($< 600\text{s}$), 40% medium ($600 - 1800\text{s}$), 20% long ($1800 - 3600\text{s}$).
- **Fleet Volume**: 200 active vehicles.
  - Capacities: 80% 4-passenger sedans, 20% 6-passenger vans/SUVs.
  - Status: 50% idle/available, 50% currently executing active trips with 1-2 passengers onboard.

### Routing Cache & In-Memory Assumptions
- In-memory distance/duration matrix pre-computed for operational zone centroids ($\le 0.5\text{ms}$ query latency).
- External network HTTP calls to third-party mapping APIs are excluded from the solver benchmark.

### Reference Hardware & Environment
- **Hardware**: 8 vCPUs ($\ge 2.5\text{ GHz}$, x86_64 or ARM64), 16 GB RAM.
- **Runtime**: Python 3.13, Windows PowerShell 5.1 / Linux container.

---

## 7. Concurrency Model, Atomic Reservation & Consistency

### Unified Seat-Hold Lifecycle & Synchronization
To prevent race conditions between reservation approval countdowns and resource locking:
- **Unified Timestamp**: Temporary seat holds and join request expiry share a single canonical expiration timestamp:
  $$T_{\text{expires}} = T_{\text{submitted}} + \text{join\_request\_expiry\_seconds}$$
- **Exact Second-Level Boundary Semantics**:
  - The seat hold and pending join request are valid and active while current wall-clock time $t \le T_{\text{expires}}$.
  - At $t > T_{\text{expires}}$, the join request transitions to `EXPIRED` and held seats are automatically released back to vehicle capacity.
- **Hold Ownership**: A seat hold is directly owned by `join_request_id` and associated with `request_id` for a specific `ride_id` and `seat_count`.
- **Automatic Release**: If the ride creator explicitly rejects the request, or if the request times out ($t > T_{\text{expires}}$), the hold is immediately released via `release_seats_atomic`.

### Consistency Protocol & Race Resolution for Join Approvals
When a ride creator or dispatch coordinator approves a `JoinRequest`:
1. **Idempotency Check**: Verify if `idempotency_token` was already committed. If found, return existing approved state without double-allocating seats.
2. **Transactional Lock Acquisition**: Acquire an atomic lock on the `Ride` entity via `RideStorageProvider` using version checking (`expected_version`).
3. **Double Revalidation**:
   - Verify `JoinRequest.status == PENDING` and current time $t \le T_{\text{expires}}$. If $t > T_{\text{expires}}$, the transaction aborts and marks the request `EXPIRED`.
   - Verify cumulative passenger occupancy across all route legs satisfies $Occupancy(l) + \text{seats} \le Capacity$.
   - Re-calculate road travel times with updated stops; verify that existing onboard passengers do not breach their contractual detour caps $\Delta T \le \min((\alpha - 1) T_{\text{direct}}, C)$ under the active policy.
4. **Atomic Commit**:
   - Promote temporary seat hold to permanent passenger assignment.
   - Append pickup and dropoff stops to `Ride.stops`.
   - Increment `Ride.version = expected_version + 1`.
   - Set `JoinRequest.status = APPROVED`.
   - Set `RideRequest.status = MATCHED`.
   - Commit transaction and release lock.
5. **Atomic Race Resolution & Rollback**:
   - If two concurrent join requests compete for the last available seat on a ride, transactional locking serializes their execution.
   - The first transaction commits successfully and increments `Ride.version`.
   - The second transaction detects either an optimistic version mismatch or a capacity violation ($Occupancy(l) + \text{seats} > Capacity$).
   - The second transaction aborts cleanly, releases its temporary hold, and sets `JoinRequest.status = REJECTED` with reason `OVER_CAPACITY` or `ROUTE_INVALIDATED`.
   - Zero overbooking occurs, and existing ride routes remain unmodified.

### Storage Independence
The consistency contract is enforced entirely through the abstract `RideStorageProvider` interface, allowing pluggable storage adapters (PostgreSQL serializable transactions, Redis atomic Lua scripts, or thread-safe in-memory mutex stores).

---

## 8. Objective Function Formulation & Mathematical Normalization Proof

### Raw Objective Formulation ($J$)
$$J = w_{\text{vmt}} \cdot S_{\text{vmt}} - w_{\text{detour}} \cdot P_{\text{detour}} - w_{\text{wait}} \cdot P_{\text{wait}} - w_{\text{idle}} \cdot P_{\text{idle}}$$

Where:
- $w_{\text{vmt}} + w_{\text{detour}} + w_{\text{wait}} + w_{\text{idle}} = 1.0$ and $w_i \ge 0$.
- Default Weights: $w_{\text{vmt}} = 0.40, w_{\text{detour}} = 0.30, w_{\text{wait}} = 0.20, w_{\text{idle}} = 0.10$.
- Normalized Components $\in [0.0, 1.0]$:
  - $S_{\text{vmt}} = \frac{VMT_{\text{baseline}} - VMT_{\text{pooled}}}{VMT_{\text{baseline}}}$ (VMT savings fraction)
  - $P_{\text{detour}} = \frac{\Delta T_{\text{detour}}}{\Delta T_{\text{max\_allowed}}}$ (Detour penalty fraction)
  - $P_{\text{wait}} = \frac{\Delta T_{\text{wait}}}{\text{max\_pickup\_delay}}$ (Wait penalty fraction)
  - $P_{\text{idle}} = \frac{T_{\text{idle}}}{T_{\text{cycle\_max}}}$ (Driver idle penalty fraction)

### Mathematical Proof of Bounded Display Score $J_{\text{display}} \in [0.0, 1.0]$

**Theorem**: For any valid policy weight vector satisfying $w_{\text{vmt}} + w_{\text{detour}} + w_{\text{wait}} + w_{\text{idle}} = 1.0$ with $w_i \ge 0$, and for all component scores $S_{\text{vmt}}, P_{\text{detour}}, P_{\text{wait}}, P_{\text{idle}} \in [0.0, 1.0]$, the display score defined by:
$$J_{\text{display}} = J + (1 - w_{\text{vmt}})$$
is strictly bounded within $[0.0, 1.0]$.

**Proof**:
1. *Upper Bound on $J$*:
   The maximum possible utility occurs when savings are maximized ($S_{\text{vmt}} = 1.0$) and all penalties are zero ($P_{\text{detour}} = P_{\text{wait}} = P_{\text{idle}} = 0.0$):
   $$J_{\max} = w_{\text{vmt}} \cdot (1.0) - 0 - 0 - 0 = w_{\text{vmt}}$$
2. *Lower Bound on $J$*:
   The minimum possible utility occurs when savings are zero ($S_{\text{vmt}} = 0.0$) and all penalties are at their worst permissible values ($P_{\text{detour}} = P_{\text{wait}} = P_{\text{idle}} = 1.0$):
   $$J_{\min} = 0 - w_{\text{detour}}(1.0) - w_{\text{wait}}(1.0) - w_{\text{idle}}(1.0) = -(w_{\text{detour}} + w_{\text{wait}} + w_{\text{idle}})$$
   Since the weights sum to 1.0, $w_{\text{detour}} + w_{\text{wait}} + w_{\text{idle}} = 1 - w_{\text{vmt}}$. Therefore:
   $$J_{\min} = -(1 - w_{\text{vmt}})$$
3. *Total Span of $J$*:
   $$\text{Span} = J_{\max} - J_{\min} = w_{\text{vmt}} - (-(1 - w_{\text{vmt}})) = w_{\text{vmt}} + 1 - w_{\text{vmt}} = 1.0$$
4. *Bounded Display Score*:
   Adding the constant $(1 - w_{\text{vmt}})$ shifts the interval $[- (1 - w_{\text{vmt}}), w_{\text{vmt}}]$ by $+(1 - w_{\text{vmt}})$:
   $$J_{\text{display},\min} = -(1 - w_{\text{vmt}}) + (1 - w_{\text{vmt}}) = 0.0$$
   $$J_{\text{display},\max} = w_{\text{vmt}} + (1 - w_{\text{vmt}}) = 1.0$$
   Thus, $J_{\text{display}} \in [0.0, 1.0]$ holds identically for **all** valid weight configurations. For the default weights ($w_{\text{vmt}} = 0.40$), $J \in [-0.60, +0.40]$ and $J_{\text{display}} = J + 0.60 \in [0.0, 1.0]$. $\quad \blacksquare$

### Deterministic 4-Tier Tie-Breaking Hierarchy
When two candidate assignments yield $|J_A - J_B| \le 10^{-6}$:
1. **Tier 1**: Higher raw VMT savings ($VMT_{\text{saved}} = VMT_{\text{baseline}} - VMT_{\text{pooled}}$ in meters).
2. **Tier 2**: Lower total passenger detour ($\sum \Delta T$ in seconds).
3. **Tier 3**: Lower total pickup delay ($\sum \Delta T_{\text{pickup}}$ in seconds).
4. **Tier 4**: Lexicographical comparison of `vehicle_id` ASCII string, followed by sorted `request_id` ASCII strings.

> [!NOTE]
> **Implementation Clarification (Unified Quantized Total-Order Policy)**:
> In collection sorting and candidate ranking, the utility tolerance is operationalized as quantization into $10^{-6}$ equivalence classes ($Q(J) = \text{round}(J, 6)$). Pairwise continuous tolerance $|J_A - J_B| \le 10^{-6}$ is a non-transitive semiorder that produces cyclic deadlocks and input-order dependence in Timsort. Note that `round(J, 6)` is **not mathematically equivalent** to pairwise $|J_A - J_B| \le 10^{-6}$, but is mathematically necessary to ensure a strict weak ordering with transitivity and deterministic input-order independence across the entire solver pipeline.

---

## 9. Policy & Lifecycle Requirements Preservation

All ratified parameters and boundary semantics from `spec.md` are strictly preserved:

| Parameter | Canonical Value | Boundary Behavior |
| :--- | :--- | :--- |
| `detour_relative_multiplier` ($\alpha$) | `1.30` | Valid while $\Delta T \le (\alpha - 1) T_{\text{direct}}$ |
| `detour_absolute_cap_seconds` ($C$) | `900s` ($15\text{ min}$) | Valid while $\Delta T \le C$; violated at $\Delta T > C$ |
| `max_pickup_delay_seconds` | `600s` ($10\text{ min}$) | Valid while $\Delta T_{\text{pickup}} \le 600\text{s}$; violated at $> 600\text{s}$ |
| `boarding_grace_period_seconds` | `180s` ($3\text{ min}$) | Boardable at $t \le T_{\text{arr}} + 180\text{s}$; transitions to `NoShow` at $t > T_{\text{arr}} + 180\text{s}$ |
| `scheduled_departure_grace_seconds` | `600s` ($10\text{ min}$) | Active while $t \le T_0 + 600\text{s}$; transitions to `DriverNoShow` at $t > T_0 + 600\text{s}$ |
| `scheduled_activation_lead_seconds` | `1800s` ($30\text{ min}$) | Activates from `Scheduled` to `Active` at $t \ge T_0 - 1800\text{s}$ |
| `join_request_expiry_seconds` | `300s` ($5\text{ min}$) | Hold active at $t \le T_{\text{sub}} + 300\text{s}$; expires at $t > T_{\text{sub}} + 300\text{s}$ |
| `stop_arrival_dwell_seconds` | `15s` ($0 - 120\text{s}$) | Dwell $\ge 15\text{s}$ establishes vehicle arrival at stop; does NOT establish boarding or departure |

### Deferred Future Scope
The following items remain explicitly deferred:
1. Dynamic surge pricing & fare-splitting formulas.
2. Monetary cancellation penalties and driver no-show compensation.
3. Multi-hop intermodal transit transfers.
4. Autonomous fleet door-unlock and low-level sensor telemetry protocols.

---

## 10. Complexity Tracking

*No Constitution violations detected. Architecture strictly adheres to all ratified principles.*
