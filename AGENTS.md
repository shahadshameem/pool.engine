# AGENTS.md — Provider-Independent Ride-Pooling Engine

## 1. Project Purpose & Mission
This repository implements a high-performance, real-time, **optimized, provider-independent ride-pooling and dispatch engine**. 

The engine pairs multiple passenger ride requests into shared vehicular journeys, solving vehicle routing and dial-a-ride problems (DARP) under strict spatial, temporal, capacity, and quality-of-service constraints.

### The Provider-Independence Requirement (Non-Negotiable)
The core engine must be completely decoupled from any single rideshare vendor, fleet operator, or dispatch network.
- **Canonical Domain Models**: All entities (Riders, Drivers, Vehicles, Waypoints, Trips, Batches, Constraints) use provider-neutral, internal domain contracts.
- **Decoupled Adapter Layer**: External integrations (e.g., proprietary ride-hailing APIs, open mobility data specs, municipal transit feeds) must reside in isolated adapter interfaces that translate to/from canonical schemas.
- **Agnostic Core Algorithms**: Matchers, objective functions, spatial indices, and routing solvers must never embed provider-specific business logic or vendor SDK assumptions.

---

## 2. Core Architectural Principles
All agents operating in this codebase must adhere to the principles ratified in [`.specify/memory/constitution.md`](.specify/memory/constitution.md):

1. **Algorithmic Correctness & Physical Invariants**:
   - Zero illegal passenger states: no pickup without prior booking, no dropoff before pickup, never exceed vehicle capacity.
   - Detour bounds: No matched passenger may experience detour time/distance exceeding configurable tolerance ratios (\(1 + \delta\)).
   - Hard time-window guarantees: Pickup and dropoff estimated time of arrivals (ETAs) must strictly satisfy contractual passenger promise windows.

2. **Measurable Multi-Objective Optimization**:
   - Explicit objective formulation balancing: Total Vehicle Miles Traveled (VMT), passenger wait time, passenger in-vehicle detour, fleet occupancy rate, and operating cost.
   - Fast, reproducible heuristics and exact/sub-gradient solvers with bounded compute budgets.

3. **Concurrency Safety & Determinism**:
   - Deterministic matching cycles: Given an identical input batch of requests, driver states, and seeded PRNG, solver output must be bit-for-bit identical.
   - Thread-safe state transitions with isolated execution contexts.

4. **Sub-Second Performance & Latency SLAs**:
   - Batch dispatch solving cycle must execute within strict latency targets (SLA: \(\le 500\text{ms}\) per dispatch window for regional spatial clusters).
   - Spatial indexing (e.g., H3 / S2 / R-tree) for \(O(1)\) or \(O(\log N)\) candidate neighbor lookups.

5. **Security & Privacy by Design**:
   - Geospatial obfuscation/sanitization for passenger location telemetry at rest and in logs.
   - Zero hardcoded credentials, vendor keys, or PII leaks in persistent data or logs.

---

## 3. Testing & TDD Expectations (Strictly Enforced)
Test-Driven Development (TDD) is mandatory across this codebase:
- **Red-Green-Refactor**: Tests MUST be written before writing production code. Confirm failure before writing the minimal implementation to pass.
- **Test Categories**:
  1. *Unit Tests*: Domain model invariants, capacity checks, distance/ETA estimators.
  2. *Solver Scenario Tests*: Multi-passenger grouping scenarios verifying detour limits, pickup/dropoff sequence ordering, and capacity conservation.
  3. *Simulation Benchmarks*: Large-scale scenario replays validating solver performance, memory bounds, and solution optimality under burst traffic.
  4. *Property-Based Tests*: Invariant testing across randomly generated demand/supply distributions (e.g., using `hypothesis`).
- Adhere strictly to the guidelines in [`.agents/rules/python-testing.md`](.agents/rules/python-testing.md) and [`.agents/rules/common-testing.md`](.agents/rules/common-testing.md).

---

## 4. Spec Kit & ECC Operating Model

This repository is governed by **Spec Kit** (Spec-Driven Development) and powered by **ECC (Everything Claude Code / Universal Agent OS)**:

```
Spec Kit (Specification & Governance)
  ├── 1. Constitution (.specify/memory/constitution.md) -> Invariants & Constraints
  ├── 2. /speckit-specify                              -> specs/<feature>/spec.md
  ├── 3. /speckit-clarify                              -> Interactive disambiguation
  ├── 4. /speckit-plan                                 -> specs/<feature>/plan.md
  ├── 5. /speckit-tasks                                -> specs/<feature>/tasks.md
  └── 6. /speckit-converge                             -> Cross-verification of built code

ECC (Autonomous Execution & Review)
  ├── Orchestration:  orch-add-feature, orch-build-mvp, continuous-agent-loop
  ├── Architecture:   architect, code-architect
  ├── Implementation: tdd-guide, python-patterns
  └── Quality Gates:  code-reviewer, python-reviewer, performance-optimizer, security-reviewer
```

### Specialized Roles & Workflow Integration
- **When Planning Features**: Invoke `speckit-plan` with the `architect` or `code-architect` agent to design clean modular boundaries.
- **When Implementing**: Invoke `speckit-implement` with `tdd-guide` to maintain 100% test-first discipline.
- **When Optimizing Hot Paths**: Involve `performance-optimizer` to profile spatial queries, route graphs, and solver bottlenecks.
- **When Reviewing PRs / Changes**: Apply `code-reviewer`, `python-reviewer`, and `security-reviewer` before approving any commit.

---

## 5. Environment & Execution Guidelines
- **Shell Compatibility**: This machine operates Windows PowerShell 5.1 (`powershell.exe`). Do **not** invoke `pwsh` directly in scripts or commands. Always execute PowerShell scripts with `powershell -File <path> ...`.
- **Runtimes Available**: Python 3.13+, Node.js 24+, Git 2.56+.
- **Sub-Repositories**: The cloned directories [`ECC/`](ECC/) and [`spec-kit/`](spec-kit/) contain reference tools and upstream sources. They are excluded from root tracking in [`.gitignore`](.gitignore) and must never be altered, relocated, or committed into project history.
