# Specification Quality Checklist: Core Provider-Independent Ride-Pooling and Dispatch Engine

**Purpose**: Validate specification completeness, mathematical consistency, and testability before proceeding to planning
**Created**: 2026-10-24
**Last Updated**: 2026-10-24
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Architectural Revision & Quality Audit Notes

- **Group Matching Formulation (Resolved)**:
  * Replaced pure bipartite matching with a Two-Tier Framework: Tier 1 constructs feasible candidate trip bundles (`CandidateAssignment`), and Tier 2 solves a fleet-wide **Set Packing Problem / Maximum Weight Independent Set** enforcing request disjointness ($\sum_{T \ni r} x_{v, T} \le 1$) and fleet limits ($\sum_T x_{v, T} \le 1$).
  * Documented `CandidateAssignment` hyperedge representation with request IDs, vehicle ID, ordered stops, seat load, and score breakdown.
- **Monotonic Wall-Clock Deadline & 500 ms SLA Credibility (Resolved)**:
  * Governed by a single monotonic wall-clock deadline (`time.monotonic() + 0.500`) with subordinate stage budgets.
  * Hard interrupt at $450\text{ms}$ (`deadline - 0.050`) reserves $50\text{ms}$ for Stage 6 validation, tie-breaking, and serialization.
  * Documented safe fallback: if timeout occurs, return unassigned requests cleanly to queue; never return partial or invalid assignments. Stateless solver execution across cycles.
  * Specified required metrics: p50, p95, p99, maximum latency, timeout rate, and feasible solution rate.
- **Optimization Quality Claims, Complexity Derivation & Empirical Benchmark Evaluation (Resolved)**:
  * Removed unverified "$\ge 95\%$ ILP quality" and flat $\mathcal{O}(|\mathcal{C}| \log |\mathcal{C}|)$ claims.
  * Formally derived Regret-K complexity based on inverted indices, candidate heaps, conflict invalidation ($O(|\mathcal{C}|)$ total), and priority queue updates: $\mathcal{O}(B \cdot |\mathcal{C}| \cdot (\log d_{\max} + \log N) + N \log N)$ with indexed heaps (or $\mathcal{O}(\min(N, M) \cdot |\mathcal{C}|)$ with linear rescanning).
  * Documented implementation assumptions and required empirical benchmark validation on `test_solver_performance.py` across dense and sparse regimes.
  * Defined an empirical evaluation protocol (`test_solver_optimality.py`) benchmarking Regret-K heuristic solutions against an exact Branch-and-Cut ILP reference solver on small fixture instances ($N \le 50$) across dense, sparse, and constrained regimes, measuring the empirical optimality gap.
- **Spatial Filtering Validation, Pruning Proofs & 100% Fixture Candidate Recall (Resolved)**:
  * Isolated spatial indexing behind `SpatialIndexProvider`.
  * Candidate recall requirement enforced at **100% candidate recall against exhaustive all-pairs search on defined test fixtures**.
  * Formally proved that conservative Haversine lower bounds ($d_{\text{haversine}} \le d_{\text{road}}$) cannot eliminate any feasible candidate under maximum velocity $v_{\max}$.
  * Specified exact adaptive ring expansion termination criteria ($r_{\text{inner\_min}}(k) \ge R_{\text{search\_max}}$ or `max_candidates` with complete ring evaluation).
  * Defined mandatory triggers for exhaustive fallback and mathematically proved that derived bounding box $\text{BBox}(x_0, R_{\text{search\_max}})$ with $\Delta \phi = \Delta \sigma$ and $\Delta \lambda = \frac{\Delta \sigma}{\cos(\phi_{\text{max\_abs}})}$ contains 100% of all points within $R_{\text{search\_max}}$.
- **Unified Seat-Hold Lifecycle & Atomic Race Resolution (Resolved)**:
  * Synchronized temporary seat holds and join request expiry under a single unified timestamp: $T_{\text{expires}} = T_{\text{submitted}} + \text{join\_request\_expiry\_seconds}$.
  * Exact boundary semantics: valid while $t \le T_{\text{expires}}$; expired and freed when $t > T_{\text{expires}}$.
  * Hold ownership: directly owned by `join_request_id` and `request_id`.
  * Automatic release: freed immediately upon creator rejection, cancellation, or timer expiry.
  * Atomic race resolution: serialized locking on `Ride.version` guarantees that concurrent requests competing for the last available seat result in exactly one commit and clean rejection of contending requests without overbooking.
  * Idempotency token handling prevents duplicate allocations on retries.
- **Mathematical Normalization Proof (Resolved)**:
  * Formally proved that display score $J_{\text{display}} = J + (1 - w_{\text{vmt}})$ is strictly bounded within $[0.0, 1.0]$ for all valid normalized weight combinations ($\sum w_i = 1.0, w_i \ge 0$).
- **Reproducible Deterministic Benchmark (Resolved)**:
  * Specified exact $10\text{ km} \times 10\text{ km}$ service area, 1,000 requests (70% 1-seat, 20% 2-seat, 10% 3-4 seat), 200 vehicles (80% 4-seat, 20% 6-seat), short/medium/long trip mix, fixed seed `seed=42`, and reference hardware.
- **Preserved Governance & Lifecycle Boundaries**:
  * All A/A/A defaults and boundary semantics preserved ($\alpha = 1.30$, $C = 900\text{s}$, `max_pickup_delay` = $600\text{s}$, `boarding_grace` = $180\text{s}$, `scheduled_departure_grace` = $600\text{s}$, `scheduled_activation_lead` = $1800\text{s}$, `join_request_expiry` = $300\text{s}$, `stop_arrival_dwell` = $15\text{s}$).
  * GPS dwell verifies vehicle arrival, never passenger boarding or trip departure.
  * Deferred items (fare splitting, cancellation fees, multimodal transfers, autonomous telemetry) remain explicitly cataloged under Future Scope.
