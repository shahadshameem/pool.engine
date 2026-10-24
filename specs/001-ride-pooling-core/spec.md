# Feature Specification: Core Provider-Independent Ride-Pooling and Dispatch Engine

**Feature Branch**: `001-ride-pooling-core`

**Created**: 2026-10-24

**Last Updated**: 2026-10-24

**Status**: Specification Complete (Clarifications Resolved & Mathematically Audited)

**Input**: User description: "Core Provider-Independent Ride-Pooling and Dispatch Engine: Define a production-oriented, optimized, reusable ride-pooling engine that matches individual passengers and groups to compatible rides while minimizing additional road distance, travel time, pickup delay, and passenger inconvenience."

---

## Clarifications

### Session 2026-10-24

- **Q: How should the maximum allowable passenger detour and pickup promise window be formulated?**  
  **A**: **Option A Approved (Relative ratio multiplier with absolute cap)**. Maximum allowable in-vehicle travel time is bounded by $T_{\text{total}} \le \min(\alpha \cdot T_{\text{direct}}, T_{\text{direct}} + C)$, where additional travel time (detour) is $\Delta T = T_{\text{total}} - T_{\text{direct}} \le \min((\alpha - 1) \cdot T_{\text{direct}}, C)$. Initial configurable defaults are relative multiplier $\alpha = 1.30$ and absolute cap $C = 900\text{ seconds}$ ($15\text{ minutes}$). Detour strictly measures *additional in-vehicle travel time* in seconds relative to the direct road route. Pickup delay ($\Delta T_{\text{pickup}} = T_{\text{actual\_pickup}} - T_{\text{requested\_earliest}}$) and scheduled pickup windows are separately configurable constraints governed by `DispatchPolicyProvider`.
- **Q: What relative prioritization should govern the optimization solver when evaluating candidate trade-offs?**  
  **A**: **Option A Approved (Balanced Efficiency & Rider Experience)**. Initial default objective weights are: Vehicle-Distance (VMT) Reduction 40% ($w_{\text{vmt}} = 0.40$), Passenger Detour Minimization 30% ($w_{\text{detour}} = 0.30$), Passenger Waiting-Time Minimization 20% ($w_{\text{wait}} = 0.20$), Driver Idle-Time Minimization 10% ($w_{\text{idle}} = 0.10$). All weights are configurable through `DispatchPolicyProvider`, validated, and normalized to sum to $1.0$ (or rejected if invalid). Hard feasibility constraints (capacity, precedence, detour caps, promise windows) are strictly evaluated in Stage 1 and can NEVER be traded off for an improved objective score.
- **Q: What default time windows should govern boarding grace periods, join request expiration, and scheduled ride activation?**  
  **A**: **Option A Approved (Standard Transit Policy)**. Initial configurable defaults: Boarding grace period = $180\text{ seconds}$ ($3\text{ minutes}$), Join request approval expiration = $300\text{ seconds}$ ($5\text{ minutes}$), Scheduled ride activation lead time = $1800\text{ seconds}$ ($30\text{ minutes}$ prior to departure). Exact boundary behaviors are defined ($t \le t_{\text{threshold}}$ is active/valid; $t > t_{\text{threshold}}$ triggers transition). Boarding grace period (driver waiting at stop for passenger to board) is strictly decoupled from scheduled-ride departure grace period (grace window for driver to initiate trip departure). GPS movement alone is NOT definitive proof of ride/stop commencement; explicit confirmation or geofence dwell + driver action is required.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Real-Time Individual & Multi-Passenger Group Match Request (Priority: P1)

As a passenger or group organizer, I want to submit a ride request specifying pickup/drop-off locations, passenger seat count, and desired departure/arrival time windows, so that the engine matches me with a compatible shared vehicle journey or provisions a new pooled ride that minimizes detour and travel time.

**Why this priority**: Core matching is the foundational value proposition of the engine. Without individual and group request matching under physical and temporal constraints, no ride-pooling operations can function.

**Independent Test**: Can be verified by submitting single-passenger and multi-passenger requests against a simulated fleet of vehicles at known spatial coordinates, verifying that the engine assigns passengers to vehicles with sufficient seats, sequences pickups before dropoffs, and returns valid match results.

**Acceptance Scenarios**:

1. **Given** an active ride in a vehicle with 4 total seats currently transporting 1 passenger, **When** an individual passenger submits a ride request for 1 seat whose pickup and drop-off align with the vehicle's road trajectory, and no other vehicle yields a higher composite score, **Then** the engine returns a match result inserting the pickup and drop-off stops into the vehicle's itinerary while respecting vehicle capacity and detour limits.
2. **Given** an active ride with 2 available seats, **When** a passenger group submits a request for 3 seats, **Then** the engine rejects insertion into this vehicle due to capacity constraints and either evaluates alternate vehicles or designates the request for a new ride.
3. **Given** an incoming request whose insertion into an existing ride would cause any existing passenger's detour or delay to exceed configured tolerance thresholds, **When** evaluated, **Then** the candidate match is marked inadmissible in Stage 1 and excluded from solver scoring.
4. *(Short Trip Detour - Relative Multiplier Binds)* **Given** an active policy with $\alpha = 1.30$ and $C = 900\text{ s}$ ($15\text{ min}$), **When** evaluating an insertion for a passenger with direct travel time $T_{\text{direct}} = 600\text{ s}$ ($10\text{ min}$), **Then** the maximum allowable travel time is $\min(1.30 \times 600, 600 + 900) = \min(780, 1500) = 780\text{ s}$ ($\Delta T \le 180\text{ s}$). A candidate route yielding total travel time $T_{\text{total}} = 840\text{ s}$ ($14\text{ min}$, $\Delta T = 240\text{ s}$) is rejected because it exceeds the $780\text{ s}$ bound.
5. *(Long Trip Detour - Absolute Cap Binds)* **Given** the same active policy ($\alpha = 1.30$, $C = 900\text{ s}$), **When** evaluating an insertion for a passenger with direct travel time $T_{\text{direct}} = 3600\text{ s}$ ($60\text{ min}$), **Then** the maximum allowable travel time is $\min(1.30 \times 3600, 3600 + 900) = \min(4680, 4500) = 4500\text{ s}$ ($75\text{ min}$, $\Delta T \le 900\text{ s}$). A candidate route yielding total travel time $T_{\text{total}} = 4560\text{ s}$ ($76\text{ min}$, $\Delta T = 960\text{ s}$) is rejected because it exceeds the $4500\text{ s}$ absolute cap, even though its relative multiplier ($4560 / 3600 = 1.267 \le 1.30$) would have passed.
6. *(Pickup Delay Exceeded)* **Given** a passenger request specifying earliest departure $T_{\text{requested}} = \text{08:00:00}$ with an active policy setting `max_pickup_delay_seconds` $= 600\text{ s}$ ($10\text{ min}$, latest acceptable pickup $\text{08:10:00}$), **When** a candidate vehicle's earliest arrival at the pickup stop is $\text{08:12:00}$ ($720\text{ s}$ delay), **Then** the candidate is rejected in Stage 1 for pickup delay violation, regardless of available seats or subsequent route efficiency.

---

### User Story 2 - Join Requests, Creator Acceptance, and Atomic Seat Reservation (Priority: P2)

As a ride creator or dispatch coordinator, I want prospective co-passengers to submit join requests for open ride opportunities, allow creators/dispatchers to accept or decline them, and have the engine revalidate the route and atomically reserve seats upon confirmation, so that overbooking and stale matches are prevented.

**Why this priority**: Pooled rides often operate on collaborative or coordinator-governed models where ride creators or dispatch systems must explicitly review match candidates before route modification, requiring strict concurrency isolation.

**Independent Test**: Can be tested by creating an open ride, generating concurrent join requests from multiple simulated passengers, confirming acceptance on one, and verifying that the engine atomically updates available capacity, revalidates the route, and rejects conflicting requests once capacity is exhausted.

**Acceptance Scenarios**:

1. **Given** an open shared ride with available capacity, **When** a passenger submits a join request, **Then** the engine transitions the request to a pending state, initiates an approval expiration countdown of $300\text{ seconds}$ (`join_request_expiry_seconds`), and places a temporary seat hold.
2. **Given** a pending join request and a temporary seat hold, **When** the ride creator accepts the request before the expiration window, **Then** the engine revalidates the complete route itinerary against current road conditions, atomically reserves the seats, and updates the scheduled route stops.
3. **Given** two concurrent join requests competing for the single remaining seat on an active ride, **When** both requests attempt confirmation simultaneously, **Then** exactly one request successfully reserves the seat, while the second request is safely rejected with an over-capacity notification.
4. **Given** a pending join request created at $T_0$, **When** the creator explicitly declines, or the wall-clock time reaches $T > T_0 + 300\text{ seconds}$, **Then** the join request transitions to rejected/expired and the temporary seat hold is immediately released.
5. *(Policy Update During Active Join)* **Given** an active join request created under Policy Version 1, **When** a global policy update (Policy Version 2) is deployed prior to creator acceptance, **Then** the engine revalidates the join candidate against Policy Version 2 upon the acceptance call, rejecting the join if it violates the newly configured constraints.

---

### User Story 3 - Road-Network Routing & Stop Insertion via Pluggable Interfaces (Priority: P3)

As a fleet operations engineer, I want the engine to compute realistic travel durations, road distances, and stop insertions using pluggable road-network routing providers, so that the engine remains vendor-independent and operates accurately with any mapping backend.

**Why this priority**: Euclidean approximations produce infeasible matches in real urban geography. Pluggable road-network interfaces ensure algorithmic accuracy while upholding the project's non-negotiable provider-independence requirement.

**Independent Test**: Can be tested by injecting a mock road-network routing provider that returns deterministic distance/time matrices and turn-by-turn costs, verifying that stop insertion permutations evaluate actual road costs rather than straight-line distance.

**Acceptance Scenarios**:

1. **Given** a vehicle traveling between stop A and stop B, **When** evaluating the insertion of pickup stop P and drop-off stop D, **Then** the engine queries the pluggable routing provider for road travel times and distances for candidate permutations `[A, P, D, B]` and `[A, P, B, D]`.
2. **Given** candidate insertion permutations, **When** evaluated by the insertion engine, **Then** any sequence that places drop-off D before pickup P is strictly pruned in Stage 1 without invoking external routing APIs.
3. **Given** a change or failure in an external routing backend, **When** a secondary routing provider adapter is configured, **Then** the engine switches routing computation without requiring modifications to core matching or optimization logic.

---

### User Story 4 - Ride Lifecycle, In-Progress Updates, and Grace Periods (Priority: P4)

As a passenger and driver, I want the engine to maintain ride lifecycle states (scheduled, active/in-progress, arrived, passenger grace period, cancelled, completed), handle en-route cancellations, and manage boarding grace periods, so that system state remains consistent during disruptions.

**Why this priority**: Real-world operations involve driver delays, passenger no-shows, and mid-journey cancellations. The engine must maintain physical consistency through all lifecycle events.

**Independent Test**: Can be tested by walking a ride through its complete lifecycle: scheduled -> active -> stop arrival -> grace period countdown -> passenger onboard -> en-route passenger cancellation -> route re-optimization -> completion.

**Acceptance Scenarios**:

1. **Given** a scheduled ride with departure time $T_0$, **When** the wall-clock time reaches $T \ge T_0 - 1800\text{ s}$ (`scheduled_activation_lead_seconds`), **Then** the ride transitions from `Scheduled` to `Active`, notifying assigned drivers and opening telematics tracking.
2. **Given** a vehicle arriving within a pickup stop geofence at timestamp $T_{\text{arr}}$, **When** the vehicle dwells continuously for at least $15\text{ seconds}$ (`stop_arrival_dwell_seconds`) or the driver affirmatively confirms arrival, **Then** the engine transitions the stop to `Arrived` and initiates the boarding grace period timer ($180\text{ seconds}$). At timestamp $t \le T_{\text{arr}} + 180\text{s}$, the passenger remains eligible to board.
3. *(Exact Boarding Grace Boundary)* **Given** an active boarding grace period where arrival was registered at $T_{\text{arr}} = \text{09:00:00}$, **When** passenger boarding is confirmed at $\text{09:03:00}$ ($t = 180\text{ s}$ elapsed), the confirmation is accepted; **When** no boarding confirmation is received by $\text{09:03:01}$ ($t = 181\text{ s}$ elapsed), **Then** the stop immediately transitions to `NoShow`, the passenger's reserved seats are freed for downstream matching, and the remaining vehicle itinerary is re-optimized.
4. *(Scheduled Departure Grace Boundary)* **Given** a scheduled ride with departure time $T_0 = \text{08:00:00}$ and `scheduled_departure_grace_seconds` $= 600\text{ s}$ ($10\text{ min}$), **When** the vehicle/driver has not initiated the route or arrived at the first pickup by $\text{08:10:01}$ ($t > T_0 + 600\text{ s}$), **Then** the ride transitions to `DriverNoShow` / `StaleScheduledRide` and booked passengers receive cancellation/re-dispatch events.
5. *(Telemetry Safety - Geofence Passthrough)* **Given** a vehicle in transit whose trajectory passes through a pickup stop's geofence at $45\text{ km/h}$ for only $3\text{ seconds}$ without dwelling or driver confirmation, **Then** the engine MUST NOT mark the stop as arrived or initiate passenger boarding timers.
6. **Given** an in-progress ride with two matched passengers onboard and a third passenger awaiting pickup downstream, **When** the downstream passenger cancels before vehicle arrival, **Then** the engine removes the downstream pickup and drop-off stops, updates the vehicle route, and notifies the remaining passengers of the updated ETA.

---

### User Story 5 - Deterministic Batch Matching & Auditable Scoring (Priority: P5)

As an operations auditor and optimization engineer, I want the dispatch engine to execute deterministic matching batches and output transparent, itemized score breakdowns, so that system decisions can be inspected, reproduced, and verified for fairness and efficiency.

**Why this priority**: Non-deterministic matching creates untraceable dispatch errors and hampers simulation replay. Auditable scoring is mandated by Principle III and Principle VI of the Constitution.

**Independent Test**: Can be tested by running the solver twice on identical snapshots of requests and vehicle states with identical random seeds, confirming bit-for-bit identical assignments and matching itemized scores.

**Acceptance Scenarios**:

1. **Given** a batch of 100 requests and 25 vehicles, **When** the batch optimization cycle is executed twice with the same inputs and seed, **Then** both runs output identical vehicle-to-passenger assignments, stop ordering, and calculated costs.
2. **Given** any candidate match generated by the engine, **When** the match result is produced, **Then** it includes an itemized score breakdown explicitly reporting additional road distance (VMT), passenger in-vehicle detour time, pickup wait delay, and driver idle time.
3. *(Policy Variance)* **Given** an identical demand batch input, **When** evaluated under a high-efficiency policy ($w_{\text{vmt}} = 0.60, w_{\text{detour}} = 0.20, w_{\text{wait}} = 0.10, w_{\text{idle}} = 0.10$), the engine selects a shared 3-passenger route that eliminates a vehicle; **When** evaluated under a rider-convenience policy ($w_{\text{vmt}} = 0.10, w_{\text{detour}} = 0.60, w_{\text{wait}} = 0.20, w_{\text{idle}} = 0.10$), the engine selects two separate low-detour rides.
4. *(Hard Constraint Immunity Over Objective Score)* **Given** a candidate route that would achieve an 85% VMT reduction and an exceptionally high utility score, **When** that candidate exceeds vehicle capacity by 1 seat or breaches a passenger's absolute detour cap by $1\text{ second}$, **Then** the engine prunes the candidate in Stage 1 and NEVER evaluates or selects it in Stage 2.
5. *(Deterministic Tie-Breaking)* **Given** two candidate vehicle assignments $A$ and $B$ that produce identical utility scores within float precision ($|J_A - J_B| \le 10^{-6}$), **Then** the engine applies the deterministic tie-breaking hierarchy (higher VMT reduction, lower detour, lower wait, lexical vehicle ID order) such that both runs select the exact same candidate.
6. *(Policy Weight Validation)* **Given** an invalid policy configuration submitted with negative weights ($w_{\text{vmt}} = -0.20$) or zero sum ($\sum w_i = 0$), **When** loaded into the policy provider, **Then** the system rejects the configuration with a validation error and preserves the active valid policy.

---

### Edge Cases

- **Concurrent Seat Contention**: Multiple passengers attempting to join the same ride when only one seat remains; requires atomic reservation with database row locking or compare-and-swap semantics to guarantee zero overbooking.
- **Mid-Route Driver Disruption**: Vehicle breakdowns or emergency stops while passengers are onboard; requires isolating stranded passengers and generating recovery dispatch requests.
- **Severe Traffic Delay During Active Ride**: Unexpected road closures causing active passengers to breach detour caps; requires graceful notification and route re-optimization without invalidating active onboard states.
- **Co-located Stops**: Distinct passengers sharing the exact same pickup or drop-off coordinates; stop aggregation must group arrivals without duplicate stop stops or premature passenger dropoffs.
- **Zero Viable Matches**: High demand in underserved regions where no vehicle satisfies time or capacity constraints; engine must safely classify requests as unassigned and schedule for subsequent batch windows.
- **Early Driver Arrival**: Driver arrives at pickup prior to the promised window; the boarding grace period timer MUST NOT elapse before the scheduled pickup window officially opens.
- **Routing Backend Outage**: Pluggable routing interface encounters timeouts or errors; engine must fall back to conservative geometric estimations with safety margins or flag the batch for graceful degradation.
- **Driver GPS Drift & False Departures**: Vehicle stops briefly at red lights near a pickup geofence; engine must require minimum dwell time (`stop_arrival_dwell_seconds`, default: $15\text{ s}$) or explicit driver confirmation before initiating boarding state transitions.

---

## Configuration & Policy Specification

### 1. Architectural Role & Provider Contract
All operational rules, constraint thresholds, and optimization objective weights are decoupled from the algorithmic core and supplied via the pluggable `DispatchPolicyProvider` interface:

```
[DispatchPolicyProvider]
        │
        ├── Invariant Thresholds (Detour caps, Delay limits, Windows)
        ├── Lifecycle Timers (Grace periods, Expiry timers, Lead times)
        └── Objective Weights (VMT, Detour, Wait, Idle)
        │
        ▼
[Optimization Core (Pure / Stateless)]
```

### 2. Parameter Definitions & Constraints Matrix

All internal time calculations use **integer seconds** as their canonical unit.

| Parameter Name | Canonical Unit | Default Value | Valid Range | Invalid Value Behavior |
| :--- | :--- | :--- | :--- | :--- |
| `detour_relative_multiplier` ($\alpha$) | Float (dimensionless) | `1.30` | $[1.00, 3.00]$ | Reject on load; retain previous active policy. |
| `detour_absolute_cap_seconds` ($C$) | Integer (seconds) | `900` ($15\text{ min}$) | $[60, 7200]$ ($1\text{m} - 2\text{h}$) | Reject on load; retain previous active policy. |
| `max_pickup_delay_seconds` | Integer (seconds) | `600` ($10\text{ min}$) | $[0, 3600]$ ($0 - 1\text{h}$) | Reject on load; retain previous active policy. |
| `boarding_grace_period_seconds` | Integer (seconds) | `180` ($3\text{ min}$) | $[30, 900]$ ($30\text{s} - 15\text{m}$) | Reject on load; retain previous active policy. |
| `scheduled_departure_grace_seconds` | Integer (seconds) | `600` ($10\text{ min}$) | $[60, 1800]$ ($1\text{m} - 30\text{m}$) | Reject on load; retain previous active policy. |
| `join_request_expiry_seconds` | Integer (seconds) | `300` ($5\text{ min}$) | $[30, 1800]$ ($30\text{s} - 30\text{m}$) | Reject on load; retain previous active policy. |
| `scheduled_activation_lead_seconds` | Integer (seconds) | `1800` ($30\text{ min}$) | $[300, 7200]$ ($5\text{m} - 2\text{h}$) | Reject on load; retain previous active policy. |
| `stop_arrival_dwell_seconds` | Integer (seconds) | `15` | $[0, 120]$ ($0 - 2\text{m}$) | Reject on load; retain previous active policy. |
| `weight_vmt_reduction` ($w_{\text{vmt}}$) | Float (ratio) | `0.40` | $[0.0, 1.0]$ | Reject if any $w < 0$ or $\sum w_i \le 0$; normalize if sum $\ne 1.0$. |
| `weight_passenger_detour` ($w_{\text{detour}}$) | Float (ratio) | `0.30` | $[0.0, 1.0]$ | Reject if any $w < 0$ or $\sum w_i \le 0$; normalize if sum $\ne 1.0$. |
| `weight_passenger_wait` ($w_{\text{wait}}$) | Float (ratio) | `0.20` | $[0.0, 1.0]$ | Reject if any $w < 0$ or $\sum w_i \le 0$; normalize if sum $\ne 1.0$. |
| `weight_driver_idle` ($w_{\text{idle}}$) | Float (ratio) | `0.10` | $[0.0, 1.0]$ | Reject if any $w < 0$ or $\sum w_i \le 0$; normalize if sum $\ne 1.0$. |

### 3. Invariants vs. Configurable Policies

To guarantee algorithmic correctness and prevent illegal passenger states, constraints are strictly partitioned into two categories:

1. **Mandatory Algorithmic Invariants (Non-Negotiable)**:
   - *Precedence Invariant*: Drop-off stop index must be strictly greater than pickup stop index for every passenger ($idx_{\text{drop}} > idx_{\text{pickup}}$).
   - *Capacity Conservation*: Concurrent passenger count $\le$ vehicle seat capacity across every route leg ($\forall \text{ leg } l, Occupancy(l) \le Capacity_{\text{vehicle}}$).
   - *Temporal Monotonicity*: Estimated stop arrival times along a vehicle route must be strictly non-decreasing ($ETA_{k+1} \ge ETA_k + Duration(k, k+1)$).
   - *Physical Feasibility*: Vehicle cannot traverse closed roads or exceed physical road speed limits.
   - *Stage 1 Gate*: Invariants are hard gates in Stage 1 pruning; violation results in immediate candidate rejection regardless of score.
2. **Configurable Operational Policies**:
   - Detour tolerances ($\alpha, C$), maximum pickup delays, timer durations, and objective scoring weights.
   - Supplied via `DispatchPolicyProvider` and customizable per deployment zone, fleet tier, or time of day.

### 4. Distinct Lifecycle Concepts & Exact Boundary Semantics

The engine strictly decouples four distinct temporal lifecycle concepts to prevent state conflation:

1. **Boarding Grace Period (`boarding_grace_period_seconds`, default: 180s)**:
   - *Scope*: Individual passenger boarding at a specific pickup stop.
   - *Start Trigger*: Triggered only when the vehicle is verified present at the stop geofence (satisfying `stop_arrival_dwell_seconds` or driver manual confirmation).
   - *Boundary Semantics*: For arrival timestamp $T_{\text{arr}}$, boarding remains valid while current time $t \le T_{\text{arr}} + \text{boarding\_grace\_period\_seconds}$. At $t > T_{\text{arr}} + \text{boarding\_grace\_period\_seconds}$, the passenger is declared a no-show (`NoShow`), seats are freed, and route is re-optimized.
2. **Scheduled Departure Grace Period (`scheduled_departure_grace_seconds`, default: 600s)**:
   - *Scope*: Vehicle-level trip departure for pre-booked scheduled rides.
   - *Start Trigger*: Initiated at the scheduled route departure timestamp $T_0$.
   - *Boundary Semantics*: The assigned driver must initiate the trip or arrive at the initial stop while $t \le T_0 + \text{scheduled\_departure\_grace\_seconds}$. At $t > T_0 + \text{scheduled\_departure\_grace\_seconds}$ without start confirmation, the ride transitions to `DriverNoShow` / `StaleScheduledRide`, triggering passenger reassignment.
3. **Scheduled Activation Lead Time (`scheduled_activation_lead_seconds`, default: 1800s)**:
   - *Scope*: Lifecycle state transition from dormant `Scheduled` to active dispatch `Active`.
   - *Boundary Semantics*: At $t \ge T_0 - \text{scheduled\_activation\_lead\_seconds}$, the ride transitions to `Active`, alerting drivers and opening real-time telemetry streaming.
4. **Join-Request Expiry (`join_request_expiry_seconds`, default: 300s)**:
   - *Scope*: Prospective co-passenger seat reservation hold.
   - *Boundary Semantics*: Initiated upon join request submission ($T_{\text{sub}}$). The seat hold and approval window remain active while $t \le T_{\text{sub}} + \text{join\_request\_expiry\_seconds}$. At $t > T_{\text{sub}} + \text{join\_request\_expiry\_seconds}$, unconfirmed join requests transition to `Expired` and the temporary seat hold is immediately freed.

### 5. Justification of the GPS Dwell Rule
The `stop_arrival_dwell_seconds` parameter (default: $15\text{ seconds}$) is a spatial-temporal noise filter designed to prevent premature stop state transitions:
- *Justification*: Urban vehicles frequently pause at red lights, pedestrian crossings, or traffic bottlenecks directly adjacent to a passenger's pickup geofence without having arrived for pickup. Immediate geofence-entry triggers lead to premature grace-period countdowns, passenger confusion, and false no-shows.
- *Configurability*: Fully configurable within $[0, 120\text{ seconds}]$ via `DispatchPolicyProvider`.
- *Explicit Boundary*: Continuous dwell within the geofence establishes **vehicle presence at stop** (`Arrived` stop state). It does **NOT** establish passenger boarding, and does **NOT** establish ride trip departure. Passenger boarding requires affirmative passenger/driver confirmation or physical boarding verification.

### 6. Objective Function Calculation & Normalization
The matching solver operates as a **Utility Maximization** problem (higher score = superior assignment). Candidate solutions are ranked by comparing the net social and operational utility generated by serving requests in shared pools versus serving them via unpooled single-occupancy direct trips.

#### Two-Stage Evaluation Pipeline
1. **Stage 1: Hard Invariant Feasibility Gate**:
   Every candidate itinerary is evaluated against all mandatory invariants (precedence, vehicle capacity) and contractual thresholds ($\Delta T \le \min((\alpha - 1) T_{\text{direct}}, C)$ and $\Delta T_{\text{pickup}} \le \text{max\_pickup\_delay}$). Any candidate violating any invariant is immediately pruned and receives no score.
2. **Stage 2: Utility Maximization**:
   Admissible candidates surviving Stage 1 are scored using normalized dimensionless metrics $\in [0.0, 1.0]$.

#### Mathematical Component Definitions
1. **Baseline Formulation ($VMT_{\text{baseline}}$)**:
   For a matched candidate set of requests $R_{\text{matched}}$, the baseline represents unshared single-occupancy transport:
   $$VMT_{\text{baseline}} = \sum_{r \in R_{\text{matched}}} DirectDistance(r)$$
   If $VMT_{\text{baseline}} = 0$, $S_{\text{vmt}} = 0.0$.
2. **VMT Reduction Benefit ($S_{\text{vmt}}$)** (Benefit term to maximize $\in [0.0, 1.0]$):
   $$S_{\text{vmt}} = \max\left(0.0, \frac{VMT_{\text{baseline}} - VMT_{\text{pooled}}}{VMT_{\text{baseline}}}\right)$$
3. **Normalized Detour Penalty ($P_{\text{detour}}$)** (Cost term to minimize $\in [0.0, 1.0]$):
   $$P_{\text{detour}} = \frac{1}{|R_{\text{matched}}|} \sum_{r \in R_{\text{matched}}} \frac{\Delta T_r}{\min((\alpha - 1) \cdot T_{\text{direct}, r}, C)}$$
4. **Normalized Wait Penalty ($P_{\text{wait}}$)** (Cost term to minimize $\in [0.0, 1.0]$):
   $$P_{\text{wait}} = \frac{1}{|R_{\text{matched}}|} \sum_{r \in R_{\text{matched}}} \frac{\Delta T_{\text{pickup}, r}}{\text{max\_pickup\_delay\_seconds}}$$
5. **Normalized Driver Idle Penalty ($P_{\text{idle}}$)** (Cost term to minimize $\in [0.0, 1.0]$):
   $$P_{\text{idle}} = \frac{\sum_{v \in V_{\text{active}}} IdleTime(v)}{\sum_{v \in V_{\text{active}}} ShiftTime(v)}$$

#### Composite Utility Score ($J$)
$$J = w_{\text{vmt}} \cdot S_{\text{vmt}} - w_{\text{detour}} \cdot P_{\text{detour}} - w_{\text{wait}} \cdot P_{\text{wait}} - w_{\text{idle}} \cdot P_{\text{idle}}$$
Where $\sum w_i = 1.0$ and $w_i \ge 0$.

#### Deterministic Tie-Breaking Rule
If two distinct candidate assignments $A$ and $B$ produce identical utility scores within floating-point tolerance ($|J_A - J_B| \le 10^{-6}$), the solver selects the winner using the following deterministic hierarchy:
1. Higher raw vehicle-distance savings ($VMT_{\text{baseline}} - VMT_{\text{pooled}}$ in meters).
2. Lower total passenger detour ($\sum \Delta T$ in seconds).
3. Lower total passenger pickup delay ($\sum \Delta T_{\text{pickup}}$ in seconds).
4. Lexicographical comparison: vehicle ID string, followed by sorted request ID strings, followed by canonical ordered stop ID strings (`tuple(s.stop_id for s in c.ordered_stops)`), followed by candidate ID string.

#### Explicit Operating Modes: EXACT vs. BOUNDED
- **BOUNDED Mode** (`DispatchMode.BOUNDED`): High-throughput production dispatch mode. Prunes candidate search space using explicit, configurable limits (default 5,000m probe radius, max 8 vehicles per request, max 3 requests per vehicle, max bundle size 2). Solves 1,000 requests and 200 vehicles in $\le 500\text{ ms}$ under the monotonic deadline. Flags results with `search_status=SearchStatus.APPROXIMATED` and `is_approximated=True`.
- **EXACT Mode** (`DispatchMode.EXACT`): Candidate discovery evaluates the full physical reachability radius ($R_{\text{reach}} = v_{\max} \times \text{max\_pickup\_delay\_seconds}$) without arbitrary vehicle-count or request-count caps.
  - *Scope of Guarantees*: EXACT guarantees exhaustive spatial candidate reachability only within the configured candidate-generation scope:
    1. Up to `max_bundle_size` (default 2) for idle vehicles; feasible bundles of 3+ requests are not evaluated unless `max_bundle_size` is explicitly configured.
    2. Strictly single-request insertions for active rides; concurrent multi-request insertion into an active ride in a single dispatch cycle is out of scope.
    3. Fixed relative order of existing stops in active rides.
    4. Physical speed ceiling of $v_{\max} = 120\text{ km/h}$ ($33.333\text{ m/s}$).
    5. Fleet-wide set packing is solved via the Regret-K heuristic ($k=2$), not exact Branch-and-Cut ILP; global mathematical optimality is not guaranteed.
    6. Does **not** guarantee the 500 ms SLA for large batches ($N=1,000$ requires $> 10\text{ seconds}$). If the wall-clock deadline expires before completion, the result is explicitly flagged with `search_status=SearchStatus.INCOMPLETE_DEADLINE_EXPIRED` and `is_approximated=True`.

> [!IMPORTANT]
> **Operational Clarification & Specification Change Record: Unified Quantized Total-Order Policy**
> - **Original Literal Requirement**: Pairwise continuous tolerance $|J_A - J_B| \le 10^{-6}$.
> - **Mathematical Analysis**: In order theory, a pairwise tolerance relation $|x - y| \le \epsilon$ is a *semiorder* and is fundamentally **intransitive** ($A \sim B \land B \sim C \centernot\implies A \sim C$). When chained across 3 or more candidates, pairwise tolerance introduces preference cycles ($A \succ B \succ C \succ A$). Consequently, any collection sorting (such as Python Timsort or priority queue operations) using pairwise tolerance becomes input-order dependent, violating Constitution Principle 3 (Determinism) and Requirement FR-018.
> - **Ratified Operational Policy**: To guarantee a strict weak ordering with mathematical transitivity, bit-for-bit solver determinism, and candidate input-order independence across the entire solver pipeline, the utility tolerance is operationalized as **uniform grid quantization into $10^{-6}$ equivalence classes**:
>   $$Q(J) = \text{round}(J \times 10^6) = \text{round}(J, 6)$$
>   Two candidates are tied on utility if and only if they share the same quantized equivalence class ($Q(J_A) == Q(J_B)$). Ties within the same class are resolved by exact, unrounded continuous secondary tiers ($S_{\text{vmt}} \to P_{\text{detour}} \to P_{\text{wait}} \to \text{lexical ID}$).
> - **Explicit Non-Equivalence Notice**: Grid quantization `round(J, 6)` is **not mathematically equivalent** to the pairwise rule $|J_A - J_B| \le 10^{-6}$. Candidates with difference $< 10^{-6}$ that straddle a rounding boundary fall into adjacent classes, while candidates within the same bin are tied. This trade-off is mathematically necessary to provide input-order invariant sorting without cycles.

### 7. Dynamic Policy Updates & Ride Mutability
- **In-Flight Rides**: Once a ride is `Active` and passengers are onboard, the contractual promise windows and detour caps agreed upon at booking remain immutable for those onboard passengers.
- **Pending Join Requests**: Revalidated against the newly active policy at the moment of creator confirmation. If the new policy reduces the detour cap and the candidate no longer complies, the join is rejected.
- **Subsequent Batch Cycles**: Future dispatch cycles immediately consume the updated policy from `DispatchPolicyProvider`.

---

## Requirements *(mandatory)*

### Functional Requirements

#### Domain Modeling & Provider Abstraction
- **FR-001**: System MUST represent all actors, resources, and state transitions using canonical, vendor-neutral domain models: `User`, `Driver`, `Vehicle`, `Ride`, `RideRequest`, `RouteStop`, `JoinRequest`, and `MatchResult`.
- **FR-002**: System MUST isolate all external mapping, navigation, and road network routing services behind a pluggable `RoadNetworkRoutingProvider` interface.
- **FR-003**: System MUST isolate all state persistence and transactional locking behind a pluggable `RideStorageProvider` interface.
- **FR-004**: System MUST isolate all operational tuning parameters, detour thresholds, timers, and cost weights behind a pluggable `DispatchPolicyProvider` interface.

#### Candidate Discovery & Filtering
- **FR-005**: System MUST perform spatial indexing and geographic bounding to filter candidate vehicles and requests prior to invoking road-network distance calculations.
- **FR-006**: System MUST perform temporal filtering based on request earliest departure time, latest arrival time, and driver service availability.
- **FR-007**: System MUST support individual ride requests (single passenger) and multi-passenger group requests (allocating \(N\) seats under atomic all-or-nothing group constraints).

#### Route Insertion & Physical Invariants
- **FR-008**: System MUST enforce the precedence invariant: a passenger's pickup stop MUST strictly precede their drop-off stop in any candidate itinerary.
- **FR-009**: System MUST enforce capacity conservation: instantaneous passenger occupancy MUST NOT exceed rated vehicle seating capacity at any point along the route.
- **FR-010**: System MUST enforce maximum detour limits: additional in-vehicle travel time $\Delta T$ must satisfy $\Delta T \le \min((\alpha - 1) \cdot T_{\text{direct}}, C)$ where $\alpha$ and $C$ are supplied by `DispatchPolicyProvider`.
- **FR-011**: System MUST enforce pickup delay limits: actual scheduled pickup must satisfy $T_{\text{pickup}} - T_{\text{requested}} \le \text{max\_pickup\_delay\_seconds}$.

#### Ride Lifecycle & Concurrency
- **FR-012**: System MUST manage the complete lifecycle states for rides: `Draft`, `Scheduled`, `Active`, `Arrived`, `InGracePeriod`, `Completed`, and `Cancelled`.
- **FR-013**: System MUST initiate an internal boarding grace period timer (default: $180\text{ seconds}$) upon verified driver arrival at a pickup stop; if unboarded at $t > 180\text{ seconds}$, stop transitions to `NoShow`.
- **FR-014**: System MUST support join requests with temporary seat holds and atomic confirmation upon creator or dispatch approval within `join_request_expiry_seconds` (default: $300\text{ seconds}$).
- **FR-015**: System MUST revalidate route feasibility and current capacity immediately prior to confirming any join request.
- **FR-016**: System MUST support passenger cancellations prior to pickup by dynamically removing stops and recalculating downstream ETAs.
- **FR-020**: System MUST validate all incoming policy configurations, rejecting negative weights or invalid numeric ranges and maintaining active valid policies without interruption.
- **FR-021**: System MUST decouple active onboard passenger promise windows from dynamic policy reconfigurations, while applying updated policies to pending and future requests.
- **FR-022**: System MUST implement a strict two-stage candidate evaluation pipeline: Stage 1 filters and prunes all invariant-violating candidates; Stage 2 scores and ranks only feasible candidates.
- **FR-023**: System MUST apply a deterministic tie-breaking hierarchy (VMT savings, detour sum, pickup delay sum, lexical identifier order) when candidate solutions yield identical objective scores within float tolerance.
- **FR-024**: System MUST enforce stop arrival dwell verification via `stop_arrival_dwell_seconds` prior to marking stop arrival, and MUST NOT treat GPS velocity or arrival dwell alone as passenger boarding or trip departure.
- **FR-025**: System MUST monitor scheduled trip departure against `scheduled_departure_grace_seconds`, transitioning unstarted rides to `DriverNoShow` / `StaleScheduledRide` when departure deadline is exceeded.

#### Optimization, Determinism & Scoring
- **FR-017**: System MUST optimize a multi-objective cost function balancing VMT reduction, passenger detour, passenger wait time, and driver idle time using validated weights from `DispatchPolicyProvider`.
- **FR-018**: System MUST guarantee bit-for-bit deterministic matching output for identical batch input snapshots and seeded PRNG states.
- **FR-019**: System MUST output an itemized, auditable score breakdown for every evaluated match candidate.

---

## Key Entities

- **User / Passenger**: An individual or group representative requesting transportation. Key attributes: identifier, contact profile, accessibility needs, trust/rating metrics.
- **Driver**: The vehicle operator responsible for executing the itinerary. Key attributes: identifier, active status, telematics stream, shift time bounds.
- **Vehicle**: The physical transport asset. Key attributes: identifier, total passenger seat capacity, luggage/cargo volume capacity, current geographic coordinates, active status.
- **Ride**: A scheduled or in-progress vehicle journey. Key attributes: ride identifier, assigned vehicle, assigned driver, ordered list of `RouteStop` entities, active lifecycle status, available capacity schedule.
- **RideRequest**: A passenger demand record. Key attributes: request identifier, requesting user, requested seat count, origin coordinate, destination coordinate, earliest pickup time, latest drop-off deadline, status (`Pending`, `Matched`, `Expired`, `Cancelled`).
- **RouteStop**: A specific waypoint on a vehicle's itinerary. Key attributes: stop identifier, coordinate, stop type (`Pickup`, `Dropoff`, `Waypoint`), associated passenger request identifier, passenger count delta, scheduled arrival window, actual arrival timestamp, completion status.
- **JoinRequest**: A prospective passenger's request to join an existing ride. Key attributes: request identifier, ride identifier, prospective passenger identifier, seat count, status (`Pending`, `Approved`, `Rejected`, `Expired`), temporary hold expiration timestamp.
- **MatchResult**: The output of an optimization cycle. Key attributes: match identifier, batch identifier, vehicle assignments, updated route itineraries, itemized score breakdown (VMT delta, detour time, wait time, idle time, total score), solver timestamp.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: **Batch Optimization Solving Latency Benchmark**:
  - *Target*: Batch optimization solving cycle MUST complete within **\(\le 500\text{ms}\)**.
  - *Operating Mode*: Applies strictly to **`DispatchMode.BOUNDED`** (configured approximation bounds for search radius, vehicles per request, and requests per vehicle). `DispatchMode.EXACT` (exhaustive physical reachability) is explicitly not guaranteed to complete within 500 ms at this scale.
  - *Standard Workload*: Regional cluster of 1,000 active ride requests and 200 active vehicles uniformly/normally distributed within a $10\text{ km} \times 10\text{ km}$ urban bounding box.
  - *Hardware Reference*: 8 physical or virtual cores ($\ge 2.5\text{ GHz}$, x86_64 or ARM64), 16 GB RAM, standard OS scheduling.
  - *Scope of Latency*: Measures **pure in-memory engine solving time**, including spatial indexing, candidate generation, Stage 1 pruning, and Stage 2 optimization. Assumes road distance/time queries are served from in-memory matrices or local cache ($\le 1\text{ ms}$ lookup). External network latency to third-party HTTP mapping services is strictly excluded.
  - *Cache State*: Evaluated under **warm cache** conditions (spatial index and centroid matrices pre-computed). Cold-start initialization has a separate budget of $\le 5.0\text{ seconds}$.
- **SC-002**: **Zero physical invariant violations**: 100% of validated matches must satisfy capacity conservation, pickup-before-dropoff precedence, and detour limits across all test suites.
- **SC-003**: **100% deterministic reproducibility**: Consecutive solver runs on identical input batch snapshots with identical seeds must yield identical vehicle assignments, stop sequences, and scores.
- **SC-004**: **Atomic seat integrity**: Zero overbooking occurrences or split group bookings across 10,000 simulated concurrent join and cancellation requests.
- **SC-005**: **Provider independence**: Core matching and routing logic must pass 100% of unit and integration test suites using mock provider interfaces without importing any commercial rideshare or mapping SDKs.
- **SC-006**: **Detour efficiency**: Shared rides must achieve at least a 25% reduction in total Vehicle Miles Traveled (VMT) compared to unshared single-passenger trips across standard benchmark scenario replays.

---

## Assumptions

- **Policy Initialization**: In the absence of an external configuration feed, the engine initializes with the validated default parameters specified in the Configuration & Policy Specification matrix.
- **Geographic Representation**: Coordinates are represented in standard WGS84 latitude/longitude format. Spatial filtering utilizes discrete spatial indexing (e.g., Uber H3 or Google S2) to provide \(O(1)\) candidate cell lookups.
- **Stateless Solvers**: Solvers operate on immutable point-in-time snapshots of requests, vehicle itineraries, and road distance matrices, isolating the optimization algorithm from concurrent mutations.
- **Network Reliability**: External routing and storage backends adhere to configured timeout thresholds; any failure gracefully marks the candidate as unrouteable without crashing the dispatch loop.

---

## Unresolved Domain Decisions & Future Scope

The following domain areas are explicitly excluded from this core specification and deferred to subsequent feature specifications:

1. **Fare Calculation & Cost-Sharing Formulas**: Financial models for splitting trip costs between passengers and calculating driver compensation are handled in billing layers and do not impact physical route feasibility.
2. **Cancellation Penalties & Passenger Compensation**: Monetary penalty policies for passenger no-shows or driver cancellations are deferred to billing/policy specs.
3. **Multi-Hop Intermodal Transfers**: Routing journeys that involve changing vehicles or transferring between rideshare and scheduled fixed-route transit are out of scope for Feature 001.
4. **Autonomous Fleet Communication Protocols**: Hardware-level protocols for vehicle telematics, remote door unlocking, and low-level sensor streams are decoupled behind adapter interfaces.
