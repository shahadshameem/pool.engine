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
- **Non-Negative Values**: All returned distances and durations must be non-negative integers ($\ge 0$).
- **Deterministic Matrix Ordering**: Matrix entries must strictly map to input origin and destination indices: `distances[i][j]` corresponds to `origins[i]` $\to$ `destinations[j]`.
- **Timeout & Failure Policy**: In the event of backend network timeouts or unreachable GIS services, the adapter must raise `RoutingProviderError`. The engine catches this error and gracefully flags affected candidates as unrouteable without terminating the dispatch loop.
- **In-Memory Caching Expectation**: For production solvers meeting the $\le 500\text{ms}$ SLA, concrete implementations must query pre-warmed in-memory matrix lookups (e.g., local OSRM instance, pre-calculated lookup tables, or contraction hierarchies) with $< 1\text{ms}$ query latency.
