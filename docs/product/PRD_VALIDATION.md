# PRD Validation & Audit Report (Phase 10B)

**Document Version:** 1.0.0
**Audit Date:** 2026-10-26
**Auditor:** Engine Architecture & Quality Team
**Governing Documents:** `.specify/memory/constitution.md`, `specs/001-ride-pooling-core/spec.md`
**Target Document Under Audit:** `docs/product/PRD.md`

---

## Executive Summary of Validation Findings

This audit reviewed `docs/product/PRD.md` against the actual codebase (`src/engine/`, `tests/`), historical git commits, Spec Kit artifacts, and project planning documents.

### Key Validation Outcomes:
1. **Source Checklist Availability (Task 1 & 2):**
   An exhaustive automated scan across `pool engine`, parent directories, user downloads, desktop, documents, and git history confirmed that **the original 112-scenario checklist was never provided as a file** in this workspace. Consequently, the 112 scenarios in `PRD.md` v1.0.0 were newly synthesized during architectural planning rather than mapped from an authentic source document. **Complete source-to-PRD traceability remains UNVERIFIED.**
2. **Codebase Discrepancies & Path Corrections (Task 3):**
   PRD v1.0.0 cited non-existent or mislocated file paths (e.g., `src/engine/domain/invariants.py` instead of `src/engine/routing/invariants.py`, `src/engine/api/routes.py` instead of `src/engine/service/app.py`, `src/engine/solvers/darp_solver.py` instead of `src/engine/orchestration/dispatch_orchestrator.py` + `src/engine/optimization/set_packing.py`). These citations have been corrected to ground truth.
3. **Discovery of Existing Seat Reservation Domain Logic (Task 3 & 4):**
   PRD v1.0.0 marked atomic seat holds as "Missing (0% Implemented)". In reality, `src/engine/lifecycle/reservations.py` already contains a robust domain implementation (`submit_join_request`, `confirm_join_request`, `reject_join_request`, `expire_stale_holds`), thoroughly tested under concurrent race conditions in `tests/concurrency/test_atomic_reservation.py`. The actual gap is that these domain methods are not yet exposed via HTTP in `src/engine/service/app.py`.
4. **Separation of Fleet Dispatch vs. Marketplace (Task 4):**
   The current API (`POST /v1/dispatch`) is an auto-committing commercial fleet solver. It does not generate ephemeral proposals or await mutual acceptance. The marketplace proposal lifecycle must sit in front of the vehicle state.
5. **Radical MVP Reduction (Task 5 & 6):**
   The MVP scope has been reduced strictly to the smallest end-to-end vertical slice (Host trip offer $\to$ Rider request $\to$ Proposal generation $\to$ Atomic seat hold $\to$ Mutual acceptance $\to$ En-route ahead-of-vehicle join). All auxiliary features (live GPS telemetry, notifications, payments, ratings, fleet dashboards) are explicitly deferred.
6. **SLA Reconciliation (Task 8):**
   Reconciled the 500 ms external wall-clock SLA with the 450 ms internal solver cutoff (reserving 50 ms headroom for set packing, tie breaking, persistence, and serialization) based on exact code in `src/engine/orchestration/dispatch_orchestrator.py`.
7. **Legal Flags (Task 9):**
   All references to the Motor Vehicles Act (Section 66), DPDP Act 2023, and tax laws have been explicitly flagged as **[LEGAL REVIEW REQUIRED]** hypotheses rather than verified legal facts.

---

## 1. Source Checklist Coverage & Discrepancies (Tasks 1 & 2)

### 1.1 Checklist Search Audit
The following search procedures were executed across the filesystem:
- **Repository Search:** Recursively walked `C:\Users\shaha\pool engine` for filenames containing `112`, `scenario`, `checklist`, `case`, `test`. Only Spec Kit templates, `requirements.md` (a Spec Kit quality gate), and unit/scenario test files were found.
- **Git History Search:** Inspected all commit messages and historical file paths (`git log --all --name-only`). No checklist file ever existed in git history.
- **User Directories:** Recursively scanned `Downloads`, `Desktop`, `Documents`, `P1`, `.gemini`, and system `TEMP`. Found related PDFs (`Cab Pooling Algorithm Zero-Cost Implementation Suggestions.pdf`, `WayMate Implementation Plan.pdf`, `WayMate Zero-Cost Open-Source Architecture (Kerala).pdf`) and Word documents (`Cab_Pooling_Algorithm_Plan_Revised.docx`). None contained a 112-scenario checklist.

### 1.2 Scenario Synthesis Disclosure
> [!WARNING]
> **UNVERIFIED SOURCE TRACEABILITY:**
> Because the original 112-scenario checklist file was not provided, the 112 scenario IDs (`SCN-001` through `SCN-112`) appearing in `PRD.md` v1.0.0 were newly synthesized from general ride-pooling principles, constitution invariants, and the 10 use-cases in `Cab_Pooling_Algorithm_Plan_Revised.docx`.
>
> To maintain strict integrity, `PRD.md` has been amended to label these 112 scenarios as a **System-Synthesized Requirements & Test Catalog (112 Scenarios)** rather than an authentic source mapping. Complete source traceability cannot be certified until the original document is supplied.

### 1.3 Discrepancy Register
| Area | PRD v1.0.0 Claim | Codebase Reality / Audit Finding | Action Taken |
|---|---|---|---|
| **Scenario Provenance** | Claimed all 112 scenarios came from "the uploaded 112-scenario checklist". | No 112-scenario checklist was uploaded. Scenarios were synthesized by the assistant in Phase 10A. | Updated Section 6.1 and PRD header to explicitly disclose synthesis and mark source traceability `UNVERIFIED`. |
| **Seat Holds** | Claimed seat holds were "Missing (0%)". | `src/engine/lifecycle/reservations.py` already implements atomic seat holds and stale hold expiry. | Corrected status from `Missing` to `Partial (Domain Implemented; HTTP Missing)`. |
| **Model Names** | Cited `Request`, `Waypoint`. | Actual Pydantic models in `src/engine/domain/models.py` are `RideRequest` and `RouteStop`. | Updated all entity references throughout `PRD.md`. |
| **Module Paths** | Cited `src/engine/domain/invariants.py`, `src/engine/api/routes.py`, `src/engine/solvers/darp_solver.py`. | Actual paths are `src/engine/routing/invariants.py`, `src/engine/service/app.py`, `src/engine/orchestration/dispatch_orchestrator.py`. | Corrected all file path citations. |

---

## 2. Implementation Status Verification & Evidence (Task 3)

Every feature claimed in the PRD has been verified against actual files, functions, and tests.

```
+-------------------------------------------------------------------------------------------------------------------------+
|                                              CODEBASE VERIFICATION EVIDENCE MATRIX                                      |
+------------------------------+------------------------------------+------------------------------------+----------------+
| Capability / Invariant       | Production Implementation Path     | Test Suite Verification            | Status         |
+------------------------------+------------------------------------+------------------------------------+----------------+
| Precedence Check             | src/engine/routing/invariants.py   | tests/unit/test_invariants.py      | IMPLEMENTED    |
|                              | fn: check_precedence()             | tests/property/test_matching_*.py  |                |
+------------------------------+------------------------------------+------------------------------------+----------------+
| Cumulative Capacity Profile  | src/engine/routing/invariants.py   | tests/unit/test_invariants.py      | IMPLEMENTED    |
|                              | fn: check_capacity_profile()       | tests/concurrency/test_atomic_*.py |                |
+------------------------------+------------------------------------+------------------------------------+----------------+
| Detour Ratio Bound           | src/engine/routing/invariants.py   | tests/unit/test_invariants.py      | IMPLEMENTED    |
|                              | fn: check_detour_bound()           | tests/unit/test_dispatch.py        |                |
+------------------------------+------------------------------------+------------------------------------+----------------+
| Pickup Delay / Time Windows  | src/engine/routing/invariants.py   | tests/unit/test_invariants.py      | IMPLEMENTED    |
|                              | fn: check_pickup_delay()           | tests/scenario/test_candidate_*.py |                |
+------------------------------+------------------------------------+------------------------------------+----------------+
| Road Routing Adapter         | src/engine/adapters/osrm_routing.py| tests/unit/test_osrm_routing.py    | IMPLEMENTED    |
| (OSRM & Matrix Coalescing)   | class: OsrmRoutingAdapter          | tests/integration/test_osrm_*.py   |                |
+------------------------------+------------------------------------+------------------------------------+----------------+
| Mock Routing Provider        | src/engine/adapters/mock_routing.py| tests/unit/test_dispatch.py        | IMPLEMENTED    |
|                              | class: MockRoutingProvider         | tests/benchmark/test_solver_*.py   |                |
+------------------------------+------------------------------------+------------------------------------+----------------+
| Spatial Indexing (H3)        | src/engine/adapters/h3_spatial.py  | tests/unit/test_spatial_index.py   | IMPLEMENTED    |
|                              | class: H3SpatialIndex              | tests/property/test_spatial_*.py   |                |
+------------------------------+------------------------------------+------------------------------------+----------------+
| Multi-Objective Optimization | src/engine/optimization/           | tests/unit/test_dispatch.py        | IMPLEMENTED    |
| & Set Packing Solver         | set_packing.py, objective.py       | tests/scenario/test_group_*.py     |                |
+------------------------------+------------------------------------+------------------------------------+----------------+
| PostgreSQL Persistence & OCC | src/engine/adapters/postgres_*.py  | tests/unit/test_postgres_storage.py| IMPLEMENTED    |
| Row Locks & Idempotency      | class: PostgresStorageProvider     | tests/integration/test_postgres_*.py|               |
+------------------------------+------------------------------------+------------------------------------+----------------+
| Seat Reservation & Holds     | src/engine/lifecycle/              | tests/concurrency/                 | PARTIAL        |
|                              | reservations.py                    | test_atomic_reservation.py         | (Domain only;  |
|                              | fn: submit_join_request()          | fn: test_concurrent_seat_race()    | no HTTP route) |
+------------------------------+------------------------------------+------------------------------------+----------------+
| En-Route Cancellation        | src/engine/lifecycle/              | tests/integration/                 | PARTIAL        |
|                              | transitions.py                     | test_cancellation_postgres.py      | (Domain only;  |
|                              | fn: cancel_en_route_request()      | tests/scenario/test_active_*.py    | no HTTP route) |
+------------------------------+------------------------------------+------------------------------------+----------------+
| HTTP REST Service            | src/engine/service/app.py          | tests/unit/test_api_service.py     | IMPLEMENTED    |
| (Vehicles, Requests, Dispatch| fn: handle_create_request(), etc.  | tests/integration/test_api_asgi.py | (Fleet dispatch|
|                              |                                    | tests/integration/test_api_pg.py   | only)          |
+------------------------------+------------------------------------+------------------------------------+----------------+
| MatchProposal State Machine  | Not implemented                    | No tests                           | MISSING        |
| (Mutual accept / decline)    |                                    |                                    |                |
+------------------------------+------------------------------------+------------------------------------+----------------+
| Ahead-of-Vehicle Spatial Gate| Not implemented                    | No tests                           | MISSING        |
| (Downstream projection)      |                                    |                                    |                |
+------------------------------+------------------------------------+------------------------------------+----------------+
| Host Corridor Anchoring      | Not implemented                    | No tests                           | MISSING        |
| (Fixed origin/dest route)    |                                    |                                    |                |
+------------------------------+------------------------------------+------------------------------------+----------------+
```

---

## 3. Fleet Dispatch vs. Marketplace Separation (Task 4)

A fundamental distinction must be maintained between the existing engine behavior and the requested marketplace product:

### Current Behavior: Fleet-Wide Auto-Commit Dispatch
- **Endpoint:** `POST /v1/dispatch`
- **Execution Path:** `DispatchOrchestrator.dispatch_cycle()` $\to$ `solve_dispatch()` $\to$ `storage.save_ride()`.
- **Characteristics:**
  - Evaluates all pending `RideRequest` records against active `Vehicle` assets.
  - Automatically commits winning candidate bundles to the database as confirmed `Ride` instances.
  - Transitions `RideRequest.status` directly from `PENDING` to `MATCHED`.
  - Appropriate for a commercial fleet (taxis, corporate vans) with paid drivers under central dispatch.

### New Requirement: Two-Sided Marketplace Proposal Flow
- **Interaction Model:** Mutual consent required. Neither party is unilaterally forced into a ride.
- **Workflow:**
  1. The solver identifies a compatible group.
  2. Instead of writing a confirmed `Ride`, the engine emits a `MatchProposal` record.
  3. A temporary `JoinRequest` (seat hold) is created with status `PENDING` and an expiration timestamp (`expires_at`).
  4. Both the Host and the Rider receive proposal notices and must independently call:
     - `POST /v1/proposals/{id}/accept`
  5. Only when **both** have accepted does the proposal transition to `CONFIRMED`, at which point the confirmed `Ride` is created.
  6. If either party declines (`POST /v1/proposals/{id}/decline`) or if `expires_at` is reached, `expire_stale_holds()` releases the reserved seats back into inventory.

---

## 4. Minimum Viable Vertical Slice Scope (Tasks 5 & 6)

To ensure rapid, reliable, and testable delivery, the MVP is strictly scoped to the smallest end-to-end slice:

```
+----------------------------------------------------------------------------------------------------+
|                                    MINIMUM VIABLE VERTICAL SLICE (MVP)                             |
+----+-----------------------+-----------------------------------------------------------------------+
| Step| Action                | Description                                                           |
+----+-----------------------+-----------------------------------------------------------------------+
| 1  | Host Trip Offer       | Private-car host registers a ride with fixed origin, destination,     |
|    |                       | departure time, offered seats (e.g. 3), and max detour tolerance.     |
| 2  | Rider Request         | Compatible traveller submits request (pickup, dropoff, ready window). |
| 3  | Proposal Generation   | Matcher detects spatial corridor alignment; creates MatchProposal.    |
| 4  | Ephemeral Seat Hold   | Engine calls submit_join_request() to acquire an atomic seat hold.   |
| 5  | Mutual Acceptance     | Both Host and Rider accept via API before proposal TTL expires.       |
| 6  | Automatic Expiry      | If either declines or TTL elapses, seat hold is cleanly released.     |
| 7  | En-Route Join Gate    | Active ride evaluates new rider: accepted ONLY if pickup is ahead of  |
|    |                       | vehicle and existing passenger detour/arrival bounds remain valid.    |
+----+-----------------------+-----------------------------------------------------------------------+
```

### Explicit Deferrals (Post-MVP):
- **Live GPS Telemetry Ingestion:** Use mocked or simulated vehicle positions for MVP tests. Real-world cellular GPS ping smoothing is deferred to P1.
- **Push / WebSocket Alerts:** Proposal inspection will use REST polling (`GET /v1/proposals/{id}`) in MVP. WebSockets/FCM deferred to P1.
- **Payments & Escrow:** No financial transactions on-platform. Fuel-sharing amounts are calculated as advice only. In-app gateway deferred to P2.
- **Ratings & Reviews:** Bilateral feedback systems deferred to P1.
- **Identity & Verification Badges:** Email/college gating deferred to P1.
- **Commercial Fleet Portal:** Driver shift management and telematics dashboards deferred to P2.

---

## 5. Concrete Acceptance Tests (Task 7)

The PRD has been updated to require the following 7 deterministic acceptance tests:

1. **AT-01: Compatible vs. Incompatible Route Requests**
   - *Scenario:* Host H travels Times Square $\to$ Wall Street. Rider A requests Flatiron $\to$ City Hall (compatible, +4m detour). Rider B requests Upper West Side $\to$ Queens (incompatible, opposite direction and river crossing).
   - *Assertion:* Proposal generated for Rider A; Rider B rejected due to detour violation.
2. **AT-02: En-Route Pickup Ahead vs. Behind Vehicle**
   - *Scenario:* Host H is en route at SoHo heading south to Wall Street. Rider C requests pickup at Canal St (downstream/ahead). Rider D requests pickup at Midtown (upstream/behind).
   - *Assertion:* Rider C generates proposal; Rider D is rejected by ahead-of-vehicle spatial filter without route computation.
3. **AT-03: Host Acceptance Without Traveller Acceptance (Timeout)**
   - *Scenario:* Host accepts proposal. Traveller does not respond within TTL (180s).
   - *Assertion:* Proposal transitions to `EXPIRED`. Seat hold released back to vehicle. Trip is not confirmed.
4. **AT-04: Traveller Acceptance Without Host Acceptance (Timeout)**
   - *Scenario:* Traveller accepts proposal. Host does not respond within TTL.
   - *Assertion:* Proposal transitions to `EXPIRED`. Seat hold released. Trip is not confirmed.
5. **AT-05: Explicit Proposal Decline**
   - *Scenario:* Proposal created with seat hold. Host explicitly calls `/decline`.
   - *Assertion:* Proposal transitions to `DECLINED`. Seat hold status transitions to `RELEASED`. Capacity immediately restored for next matching cycle.
6. **AT-06: Two Concurrent Attempts to Claim Last Seat**
   - *Scenario:* Vehicle with 1 remaining seat. Two competing travellers simultaneously call `/accept` on competing proposals.
   - *Assertion:* Exactly 1 transaction acquires row-level lock and receives `200 OK` (`CONFIRMED`). Competing transaction receives `409 Conflict` (`SeatUnavailableError`). Zero overbooking.
7. **AT-07: Cancellation Racing Against Confirmation**
   - *Scenario:* Traveller cancels request at the exact moment host confirms proposal.
   - *Assertion:* Database version check / transaction isolation detects state change; aborts confirmation cleanly without orphan ride creation.

---

## 6. Performance SLA Reconciliation (Task 8)

| Metric | PRD v1.0.0 Claim | Codebase Ground Truth | Reconciled Standard in PRD v1.1.0 |
|---|---|---|---|
| **Dispatch Window SLA** | Claimed $\le 500\text{ms}$ dispatch SLA. | `DispatchOrchestratorConfig.deadline_seconds = 0.500`. Code strictly enforces wall-clock deadline `time.monotonic() + 0.500`. | **$\le 500\text{ms}$ external wall-clock dispatch SLA** preserved as contractual standard. |
| **Internal Solver Cutoff** | Vaguely referenced "450ms budget". | `DispatchOrchestratorConfig.reserved_headroom_seconds = 0.050`. Hard solver interrupt fires at `deadline - 0.050 = 450\text{ms}`. | **450 ms internal heuristic search cutoff** explicitly distinguished from the 500 ms SLA. Reserves 50 ms for set packing, tie breaking, persistence, and serialization. |
| **Verification Status** | Claimed SLA achieved across all workloads. | Phase 6 experiment proved 500 ms SLA holds at $P_{99} = 405\text{ms}$ with batched OSRM defaults (`24/2`), but large unbatched matrices breach SLA under cold cache. | Stated clearly: SLA compliance is **validated under batched road-matrix defaults**, but unverified under unbounded cold-start cluster sizes without caching. |

---

## 7. Legal & Regulatory Statement Flags (Task 9)

The following claims in PRD v1.0.0 have been tagged with explicit legal review warnings:

1. **Motor Vehicles Act 1988 (India) Section 66:**
   - *Previous PRD Text:* Asserted that carpooling is legally permitted strictly if costs are shared without profit markup under Section 66.
   - *Validation Flag:* `[LEGAL REVIEW REQUIRED]` — Transport regulations in India, the US, and the EU vary significantly by state/municipality. Whether private carpooling constitutes "plying for hire or reward" depends on local judicial interpretation and state carpooling policies (e.g., Karnataka carpooling disputes). This is a legal hypothesis and product risk, not an established statutory exemption.
2. **Digital Personal Data Protection (DPDP) Act 2023 & GDPR:**
   - *Previous PRD Text:* Asserted system compliance through location fuzzing.
   - *Validation Flag:* `[LEGAL REVIEW REQUIRED]` — DPDP Act rules on notice, consent managers, and fiduciary duties require formal Data Protection Officer (DPO) and legal review. Fuzzing to 200m is an engineering privacy-by-design mitigation, not certified legal compliance.
3. **Third-Party Ride Aggregator Policies (Uber/Ola):**
   - *Validation Confirmation:* Confirmed as an accurate technical and contractual fact: third-party commercial platforms prohibit automated injection or unauthorized route modification under their standard developer terms of service.

---

## 8. Summary of Files Changed & Next Engineering Task

- **Files Changed:**
  1. `docs/product/PRD_VALIDATION.md` (Created): Complete audit findings, source coverage analysis, codebase ground truth, and acceptance test definitions.
  2. `docs/product/PRD.md` (Updated): Corrected paths, model names, implementation statuses, MVP scoping, SLA reconciliation, and legal disclaimers.
- **Recommended Next Engineering Task:**
  - **Task: Expose Proposal & Mutual Acceptance Service over HTTP (Building on Existing `reservations.py`)**
  - *Context:* Because `submit_join_request`, `confirm_join_request`, `reject_join_request`, and `expire_stale_holds` already exist and are tested in `src/engine/lifecycle/reservations.py`, the next step is to create the marketplace service layer and API routes (`POST /v1/proposals/{id}/accept`, `POST /v1/proposals/{id}/decline`, `GET /v1/proposals/{id}`) connecting incoming requests to these atomic methods.
