<!--
Sync Impact Report
- Version change: [CONSTITUTION_VERSION] (Template) -> 1.0.0 (Initial Ratification)
- Modified Principles:
  * [PRINCIPLE_1_NAME] -> I. Algorithmic Correctness & Physical Invariants
  * [PRINCIPLE_2_NAME] -> II. Provider Neutrality & Interface Abstraction
  * [PRINCIPLE_3_NAME] -> III. Measurable Multi-Objective Optimization
  * [PRINCIPLE_4_NAME] -> IV. Modular & Layered Architecture
  * [PRINCIPLE_5_NAME] -> V. Test-First Development (NON-NEGOTIABLE)
  * Added -> VI. Concurrency Safety & Deterministic Replay
  * Added -> VII. Sub-Second Latency & Measurable Performance SLAs
  * Added -> VIII. Security, Data Privacy & Telemetry Integrity
- Added Sections:
  * Technical Constraints & Standards
  * Development Workflow & Quality Gates
- Removed Sections:
  * Placeholder example comments and unpopulated tokens
- Deferred TODOs: None
-->

# Ride-Pooling Engine Constitution

## Core Principles

### I. Algorithmic Correctness & Physical Invariants
The engine MUST guarantee physical, spatial, and temporal feasibility across all generated matches and routes:
- **Precedence Invariant**: A passenger's pickup must strictly precede their dropoff in any vehicle itinerary.
- **Capacity Conservation**: The instantaneous passenger count (and volume/weight limits) must never exceed vehicle capacity at any point along a route.
- **Detour & Delay Bounds**: No passenger route may exceed the configured maximum detour ratio (\(1 + \delta\)) relative to their direct journey, nor violate promised pickup time windows.
- **Feasibility Verification**: All proposed itineraries must undergo strict invariant validation prior to candidate evaluation. Illegal assignments are strictly prohibited.

### II. Provider Neutrality & Interface Abstraction
The core ride-pooling engine MUST remain completely decoupled from any specific fleet operator, rideshare company, or external telematics vendor:
- **Canonical Domain Models**: All entities (Riders, Drivers, Vehicles, Requests, Waypoints, Trips, Batches) MUST use vendor-neutral internal domain models.
- **Decoupled Adapter Layer**: External integrations (e.g., proprietary rideshare APIs, open transit data, municipal vehicle telemetry) MUST be implemented exclusively through isolated provider adapters.
- **Zero Vendor Logic in Core**: Matchers, objective functions, spatial indices, and routing graphs must never import vendor SDKs or depend on provider-specific assumptions.

### III. Measurable Multi-Objective Optimization
Dispatch and pooling decisions MUST be driven by an explicit, mathematically rigorous multi-objective optimization framework:
- **Objective Balance**: The objective function must explicitly balance total vehicle miles traveled (VMT), passenger wait times, passenger in-vehicle delay/detour, and fleet utilization.
- **Transparent Scoring**: Solvers MUST output decomposed, itemized cost scores alongside matches to ensure complete auditability of algorithmic decisions.
- **Bounded Computation**: Optimization algorithms must support anytime-heuristic execution or bounded search budgets, guaranteeing valid feasible assignments within real-time dispatch windows even under traffic surges.

### IV. Modular & Layered Architecture
The engine MUST maintain strict architectural boundaries with unidirectional dependencies across distinct functional subsystems:
- **Spatial & Temporal Indexing**: Geohash, H3, or S2 spatial indexing for localized candidate search and distance estimation.
- **Candidate Generation**: Pruning and admissible pair/group generation separating feasible combinations from combinatorial state space.
- **Optimization & Assignment Solver**: Mathematical solvers (e.g., bipartite matching, ILP, or meta-heuristics) decoupled from state persistence.
- **State & Lifecycle Management**: Immutable representation of vehicle states, active trips, and incoming request queues.
- **Provider Adapters**: Ingress/egress boundaries translating external platform events to canonical internal representations.

### V. Test-First Development (NON-NEGOTIABLE)
Test-Driven Development (TDD) is mandatory for all engine logic, routing calculations, and spatial algorithms:
- **Red-Green-Refactor Cycle**: Comprehensive tests MUST be authored, verified to fail, and approved before production code is written.
- **Required Test Tiers**:
  1. *Unit Tests*: Invariant validation, capacity limits, waypoint sequence logic, and geometric calculation edge cases.
  2. *Scenario Tests*: Dial-a-ride problem (DARP) instances validating detour bounds, shared-ride feasibility, and cancellation handling.
  3. *Simulation Benchmarks*: Scaled scenario replays validating solver performance, memory bounds, and solution quality under burst demand.
  4. *Property-Based Testing*: Randomized invariant testing (e.g., via Hypothesis) to verify stability against adversarial coordinate/time inputs.
- **Regression Immunity**: Every bug discovered in matching or dispatch must be accompanied by a reproducing regression test prior to resolution.

### VI. Concurrency Safety & Deterministic Replay
The engine MUST guarantee thread safety and bit-for-bit algorithmic determinism:
- **Stateless Matching Cycles**: The solver core must execute as a pure, stateless computation over an immutable batch snapshot of demand and supply.
- **Deterministic Replay**: Given an identical input snapshot, graph topology, and PRNG seed, the engine MUST produce bit-for-bit identical matching results.
- **Thread Safety**: Concurrent state transitions (driver locations, request arrivals, cancellations) must be managed through thread-safe event pipelines without data races.

### VII. Sub-Second Latency & Measurable Performance SLAs
Algorithmic performance MUST be measurable, continuously profiled, and satisfy real-time dispatch latency budgets:
- **Dispatch Solving SLA**: Batch optimization cycles for regional spatial clusters (up to 1,000 requests/vehicles) MUST complete within \(\le 500\text{ms}\).
- **Asymptotic Pruning**: Spatial candidate filtering must achieve \(O(1)\) or \(O(\log N)\) lookups to eliminate combinatorial explosion before solver invocation.
- **Bounded Memory Footprint**: Routing graphs, spatial indices, and distance caches must operate within strict, pre-allocated memory boundaries with zero memory leaks.

### VIII. Security, Data Privacy & Telemetry Integrity
The engine MUST treat user geospatial telemetry with the highest standards of data protection:
- **Location Sanitization**: Exact coordinate telemetry must be obfuscated or fuzz-indexed in logs and analytics storage to protect passenger and driver privacy.
- **Input Validation & Hardening**: All external data inputs (coordinates, timestamps, passenger counts) must be validated against strict schemas with bounds checking.
- **Audit Trails**: All dispatch assignments, price factor calculations, and routing decisions must be logged with tamper-evident, structured audit metadata.

---

## Technical Constraints & Standards

- **Core Runtime**: Python 3.13+ with strict type annotations (`mypy` / `pyright` compliance).
- **Domain Modeling**: Immutable data structures and Pydantic/dataclass schemas for all domain entities.
- **High-Performance Math**: Vectorized spatial operations and numeric computations using optimized libraries (e.g., NumPy, SciPy, H3).
- **Platform Compatibility**: All build, test, and Spec Kit scripts must operate seamlessly in Windows PowerShell 5.1 (`powershell.exe`) as well as cross-platform shell environments.

---

## Development Workflow & Quality Gates

1. **Spec-Driven Development (Spec Kit)**:
   - Every feature must proceed through the complete SDD cycle: `/speckit-specify` -> `/speckit-clarify` -> `/speckit-plan` -> `/speckit-tasks` -> `/speckit-implement` -> `/speckit-converge`.
2. **Quality Review Gates (ECC Agents)**:
   - Architecture review via `architect` / `code-architect`.
   - Implementation review via `code-reviewer` and `python-reviewer`.
   - Algorithmic latency verification via `performance-optimizer`.
   - Vulnerability and data leakage audit via `security-reviewer`.
3. **Commit & Merge Gates**:
   - Zero test failures, zero lint/type errors, and 100% invariant verification across all scenario tests.

---

## Governance

- **Supreme Authority**: This Constitution supersedes all informal practices, ad-hoc architecture decisions, and non-canonical conventions.
- **Amendment Procedure**: Amendments to core principles require documented rationale, impact analysis, and a formal version increment.
- **Versioning Policy**: Semantic versioning rules apply strictly:
  * **MAJOR** (e.g., 2.0.0): Incompatible principle redefinition, removal of invariant constraints, or structural governance overhaul.
  * **MINOR** (e.g., 1.1.0): Introduction of new principles, structural expansion, or substantial new architectural standards.
  * **PATCH** (e.g., 1.0.1): Clarifications, wording improvements, non-semantic refinements.
- **Compliance Enforcement**: All PRs, specifications, and code reviews must explicitly verify compliance with this Constitution.

**Version**: 1.0.0 | **Ratified**: 2026-10-24 | **Last Amended**: 2026-10-24
