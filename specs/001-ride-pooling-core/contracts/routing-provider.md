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

---

## 3. Concrete Production Adapter: `OsrmRoutingAdapter`

### Overview & Architecture
`OsrmRoutingAdapter` (`engine.adapters.osrm_routing.OsrmRoutingAdapter`) implements `RoadNetworkRoutingProvider` for production deployments using the Open Source Routing Machine (OSRM).

Key architectural features:
1. **Persistent HTTP Keep-Alive Connection Pool**: Uses standard library `http.client.HTTPConnection` with connection reuse and thread safety, eliminating loopback TCP handshake overhead.
2. **Matrix Query Chunking**: Transparently breaks large matrix queries into sub-blocks respecting `max_table_size` (default 100 coordinates) to avoid HTTP URL length limits (RFC 7230).
3. **In-Memory Thread-Safe LRU Leg Cache**: Caches validated `(distance_meters, duration_seconds)` keyed by 6-decimal-place rounded coordinates (`~0.1m` precision). Warm dispatch cycles achieve $> 95\%$ cache hit rates and sub-millisecond route evaluations.
4. **Physical Invariant Enforcement**: All responses (direct legs and distance matrices) pass through `validate_route_leg`. Unreachable destinations (`null` values from OSRM) raise `RouteLookupError`. Distances and durations between distinct coordinates are guaranteed $\ge 1\text{m}$ and $\ge 1\text{s}$, preventing synthetic zero-cost detours.
5. **Configurable Timeout and Retries**: Automatically retries transient socket disconnects while enforcing strict monotonic query timeouts.

### Constructor Configuration

```python
from engine.adapters.osrm_routing import OsrmRoutingAdapter

adapter = OsrmRoutingAdapter(
    base_url="http://localhost:5000",   # OSRM backend endpoint
    profile="driving",                  # Routing profile
    timeout_seconds=0.500,              # Monotonic HTTP timeout per request
    max_retries=1,                      # Retries for transient network drops
    max_table_size=100,                 # Maximum coordinates per /table/v1/ query
    cache_maxsize=50000,                # In-memory LRU cache capacity
    coord_precision=6,                  # Coordinate rounding decimal places
)
```

### Reproducible OSRM Docker Setup

To run a local OSRM instance for real-road routing:

1. **Download OSM Region Extract** (e.g. New York or Delaware):
   ```bash
   curl -O https://download.geofabrik.de/north-america/us/new-york-latest.osm.pbf
   ```

2. **Extract Graph Hierarchy** (using car profile):
   ```bash
   docker run -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend \
     osrm-extract -p /opt/car.lua /data/new-york-latest.osm.pbf
   ```

3. **Partition & Customize (MLD) or Contract (CH)**:
   ```bash
   docker run -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend \
     osrm-partition /data/new-york-latest.osrm
   docker run -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend \
     osrm-customize /data/new-york-latest.osrm
   ```

4. **Launch OSRM Routed Daemon**:
   ```bash
   docker run -d -p 5000:5000 -v "${PWD}:/data" --name osrm-ny \
     ghcr.io/project-osrm/osrm-backend osrm-routed --algorithm mld /data/new-york-latest.osrm
   ```

5. **Execute Benchmark**:
   ```powershell
   $env:OSRM_BASE_URL = "http://localhost:5000"
   python -m pytest tests/benchmark/test_osrm_benchmark.py -v -s
   ```
