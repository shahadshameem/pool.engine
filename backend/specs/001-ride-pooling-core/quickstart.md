# Quickstart Validation Guide: Ride-Pooling Engine

**Feature**: `001-ride-pooling-core`  
**Phase**: Phase 1 (Validation Guide)  
**Date**: 2026-10-24  
**Status**: Revised & Mathematically Validated  

---

## 1. Overview & Purpose
This document provides executable verification scenarios to validate that the Core Provider-Independent Ride-Pooling Engine satisfies all functional requirements, invariants, group matching formulations, and performance targets specified in [`spec.md`](spec.md) and [`plan.md`](plan.md).

---

## 2. Prerequisites & Environment Setup

- **Python Runtime**: Python 3.13+ installed.
- **PowerShell**: Windows PowerShell 5.1 (`powershell.exe`).
- **Virtual Environment & Dependencies**:
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  pip install -U pip pytest hypothesis numpy
  ```

---

## 3. End-to-End Verification Scenarios

### Scenario 1: Multi-Passenger Group Bundling & Insertion
- **Objective**: Prove that the engine correctly forms multi-request bundles and assigns them without capacity violations or splitting group requests.
- **Input Fixture**:
  - Vehicle $V_1$: 4 seats, 1 existing passenger.
  - Request $R_1$: 1 seat, pickup $(10.02, 10.02)$, dropoff $(10.08, 10.08)$.
  - Request $R_2$: 3 seats, pickup $(10.01, 10.01)$, dropoff $(10.09, 10.09)$.
- **Execution Command**:
  ```powershell
  pytest tests/scenario/test_group_matching.py -v -k "test_group_bundle_capacity"
  ```
- **Expected Outcome**:
  - $R_1$ is merged into $V_1$ ($1 + 1 \le 4$ seats). $idx_{\text{pickup}} < idx_{\text{dropoff}}$.
  - $R_2$ is assigned to an empty vehicle ($V_2$) or separate trip ($3 + 1 > 4$ seats capacity violation on $V_1$).

### Scenario 2: Two-Stage Feasibility Gate & Invariant Protection
- **Objective**: Prove that candidates violating vehicle capacity or detour bounds are strictly pruned in Stage 1, regardless of theoretical VMT savings.
- **Execution Command**:
  ```powershell
  pytest tests/unit/test_invariants.py -v -k "test_hard_invariant_gate"
  ```
- **Expected Outcome**:
  - Candidate offering 90% VMT reduction but with $\Delta T > \min((\alpha - 1) T_{\text{direct}}, C)$ is pruned in Stage 1 and receives no score.

### Scenario 3: Atomic Concurrency, Seat Holds & Race Resolution
- **Objective**: Prove that concurrent join requests competing for the last seat on a ride never result in overbooking, adhere to the unified expiry timestamp $T_{\text{expires}} = T_{\text{submitted}} + \text{join\_request\_expiry\_seconds}$, and handle duplicate tokens idempotently.
- **Execution Command**:
  ```powershell
  pytest tests/concurrency/test_atomic_reservation.py -v -k "test_concurrent_seat_contention"
  ```
- **Expected Outcome**:
  - 10 concurrent join requests for 1 available seat result in exactly 1 `APPROVED` reservation and 9 clean `REJECTED` / `OVER_CAPACITY` responses.
  - Repeating the approval call with the identical `idempotency_token` returns `APPROVED` without consuming additional seats.
  - At $t \le T_{\text{expires}}$, the seat hold remains valid. At $t > T_{\text{expires}}$, unconfirmed holds expire and seats are automatically released back to capacity.

### Scenario 4: Exact Boundary Timer & Grace Period Transitions
- **Objective**: Prove exact second-level boundary transitions for boarding grace periods ($180\text{s}$) and scheduled departure grace periods ($600\text{s}$).
- **Execution Command**:
  ```powershell
  pytest tests/unit/test_lifecycle_timers.py -v -k "test_grace_period_boundaries"
  ```
- **Expected Outcome**:
  - At $t = 180\text{ s}$ elapsed from stop arrival, passenger boarding succeeds.
  - At $t = 181\text{ s}$, stop transitions to `NoShow`, releasing seats.
  - Dwell filter: A vehicle passing through a geofence for $< 15\text{ s}$ does NOT trigger `Arrived`.

### Scenario 5: Spatial Filtering Candidate Recall vs. Exhaustive Search
- **Objective**: Prove that spatial indexing achieves 100% recall of all feasible match candidates on defined test fixtures compared to exhaustive all-pairs brute-force search.
- **Workload**: Deterministic benchmark fixtures ($N = 50, 100, 200$ requests, $V = 10, 25, 50$ vehicles) evaluated against brute-force all-pairs search.
- **Execution Command**:
  ```powershell
  pytest tests/unit/test_spatial_index.py -v -k "test_spatial_candidate_recall"
  ```
- **Expected Outcome**:
  - Spatial candidate recall achieves **100% candidate recall** of all physically feasible pooled pairings identified by exhaustive search on the fixtures.
  - Adaptive ring expansion dynamically queries neighboring cells without dropping candidates on cell boundaries.
  - Distinguishes fixture verification (100% required) from universal open road networks (where conservative Haversine lower bounds and adaptive bounding-box fallbacks protect against geometry anomalies).

### Scenario 6: Deterministic Benchmark SLA ($\le 500\text{ms}$) & Heuristic Optimality Gap
- **Objective**: Measure batch dispatch solving latency against the documented regional workload under a single monotonic wall-clock deadline, and measure the empirical optimality gap against an exact reference solver on small instances.
- **Workload**:
  - Benchmark SLA: 1,000 active requests, 200 vehicles in a $10\text{ km} \times 10\text{ km}$ urban bounding box with fixed seed `seed=42`.
  - Exact Optimality Gap Suite: Small benchmark instances ($N \le 50$ requests, $V \le 15$ vehicles) across dense, sparse, and constrained regimes.
- **Execution Command**:
  ```powershell
  pytest tests/benchmark/test_solver_performance.py -v
  pytest tests/benchmark/test_solver_optimality.py -v -k "test_ilp_reference_gap"
  ```
- **Reported Metrics**:
  - Latency: p50, p95, p99, maximum observed latency (must complete $\le 500\text{ms}$ total wall-clock time with 450ms solver interrupt and 50ms Stage 6 reserved headroom).
  - Timeout rate: $\le 0.1\%$ timeout occurrences.
  - Feasible solution rate: $100\%$ valid assignments with zero invariant violations.
  - Safe fallback verification: Simulated timeout returns unassigned requests cleanly to queue with zero corrupt or partial state mutations.
  - Empirical Optimality Gap: Measures percentage gap $\frac{J^*_{\text{exact}} - J_{\text{heuristic}}}{J^*_{\text{exact}}} \times 100\%$ across test fixtures.
  - Reproducibility: Bit-for-bit identical assignments across consecutive runs with identical seed.
