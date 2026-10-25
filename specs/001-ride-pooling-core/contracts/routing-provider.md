# Contract: RoadNetworkRoutingProvider

**Interface**: `RoadNetworkRoutingProvider`  
**Namespace**: `engine.contracts.routing`  
**Purpose**: Decouple the matching engine from external road network routing, GIS services, and distance matrix engines.

---

## 1. Interface Definition (Python Abstract Base Class)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence

@dataclass(frozen=True)
class Coordinate:
    latitude: float
    longitude: float

@dataclass(frozen=True)
class MatrixResult:
    distances_meters: list[list[int]]   # Road distance matrix [source_idx][target_idx]
    durations_seconds: list[list[int]]  # Road travel time matrix [source_idx][target_idx]

@dataclass(frozen=True)
class RouteGeometry:
    points: list[Coordinate]
    total_distance_meters: int
    total_duration_seconds: int

class RoadNetworkRoutingProvider(ABC):
    """
    Vendor-independent routing contract.
    Must be implemented by concrete adapters (e.g., OSRM, Valhalla, Google Maps, Mock).
    """

    @abstractmethod
    def get_distance_matrix(
        self,
        origins: Sequence[Coordinate],
        destinations: Sequence[Coordinate]
    ) -> MatrixResult:
        """
        Computes pairwise road network distances and durations.
        Must return integer meters and integer seconds.
        """
        pass

    @abstractmethod
    def get_route(
        self,
        waypoints: Sequence[Coordinate]
    ) -> RouteGeometry:
        """
        Computes the turn-by-turn road route connecting ordered waypoints.
        """
        pass

    @abstractmethod
    def get_direct_leg(
        self,
        origin: Coordinate,
        destination: Coordinate
    ) -> tuple[int, int]:
        """
        Convenience query returning (distance_meters, duration_seconds) for a direct leg.
        """
        pass
```

## 2. Invariants & Error Handling Contract

### Typed Error Hierarchy
All routing provider errors derive from canonical, provider-independent exceptions in `engine.contracts.routing`:
- `RoutingProviderError`: Base exception for routing backend errors and network failures.
- `RouteLookupError(RoutingProviderError)`: Raised when a route between specific coordinates cannot be resolved or is unreachable (e.g. road closure, island, OSRM 400 NoRoute).
- `RouteTimeoutError(RoutingProviderError)`: Raised when the routing backend query exceeds its allotted network/socket timeout.
- `InvalidRouteDataError(RoutingProviderError)`: Raised when the routing backend returns malformed, non-numeric, negative, NaN/infinite, or physically contradictory leg data.

### Physical Leg Validation (`validate_route_leg`)
Every direct leg query is validated through `validate_route_leg(origin, destination, leg)` before being consumed by candidate search, route insertion, or lifecycle updates:
- **Structure**: Must be a 2-tuple or 2-element sequence `(distance_meters, duration_seconds)`.
- **Numeric & Finite**: Values must be real finite numbers (booleans, NaN, and Inf are strictly prohibited). Floats are rounded to integer meters/seconds.
- **Strictly Positive for Distinct Coordinates**: If $A \ne B$, both distance and duration must be strictly positive ($> 0$). **A failed route lookup must never be treated as 0 meters or 0 seconds**, as that would synthesize illegal zero-cost detours and falsify VMT savings.
- **Identical Coordinates**: Leg $(A, A)$ is permitted to be $(0, 0)$.

### Fault Isolation & Candidate Pruning
- **Shared Failure Memoization**: Failed route legs are cached as `None` within `shared_leg_cache`. This guarantees $O(1)$ fast rejection for unroutable coordinate pairs across subsequent permutations and vehicle evaluations, eliminating cascading backend timeouts.
- **Candidate Branch Pruning**: In group bundle search (`bundle_generator.py`) and active ride insertion (`insertion.py`), an unroutable leg isolates failure to the affected branch or candidate. Healthy candidates from other vehicles and unaffected requests continue to be generated and matched.
- **Active Ride Baseline Route Protection**: If an active ride's existing stops cannot be routed, baseline VMT cannot be established safely. `generate_active_ride_insertions` safely returns an empty candidate list (`[]`) rather than guessing baseline distance.
- **Error Propagation Toggle**: `CandidateGenerationConfig.propagate_routing_errors` (default `False`) allows callers to opt into immediate exception propagation if entire batch abort is required on backend failure.

### Dispatch Status & Completeness Guarantees
- **Completeness Semantics**:
  - In `EXACT` mode, if any routing errors occur during candidate generation and the deadline has not expired, the engine completes dispatch with healthy candidates and marks `MatchResult.search_status = SearchStatus.INCOMPLETE_ROUTING_ERROR` and `is_approximated = True`.
  - In `BOUNDED` mode, search status remains `SearchStatus.APPROXIMATED` (`is_approximated = True`).
- **Precedence Hierarchy**:
  - `SearchStatus.INCOMPLETE_DEADLINE_EXPIRED` strictly dominates `INCOMPLETE_ROUTING_ERROR`. If a dispatch cycle experiences both routing errors and deadline expiration, the deadline expiration status is reported.
- **Observability**: `MatchResult.routing_errors_count` and `CandidateList.routing_errors_count` record the total number of routing failures encountered during the dispatch cycle.

### Lifecycle Mutation Safety
- In `engine.lifecycle.transitions.cancel_en_route_request`, route leg recalculation wraps provider calls in error isolation guards. If the routing provider raises `RoutingProviderError`, `TimeoutError`, or `ConnectionError`, or returns invalid leg data, the function raises `LifecycleTransitionError` before persisting any updates to storage, ensuring active rides and requests in persistent storage are never corrupted.
