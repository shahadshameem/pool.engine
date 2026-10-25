"""Contract for road network routing providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import math
import time
from typing import Any, Sequence


@dataclass(frozen=True)
class Coordinate:
    """Geographical coordinate for routing queries."""
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "latitude", round(float(self.latitude), 6))
        object.__setattr__(self, "longitude", round(float(self.longitude), 6))


@dataclass(frozen=True)
class MatrixResult:
    """Pairwise distance and travel duration matrix."""
    distances_meters: list[list[int]]
    durations_seconds: list[list[int]]


@dataclass(frozen=True)
class RouteGeometry:
    """Turn-by-turn road route connecting waypoints."""
    points: list[Coordinate]
    total_distance_meters: int
    total_duration_seconds: int


class RoutingProviderError(Exception):
    """Base exception for routing backend errors and failures."""
    pass


class RouteLookupError(RoutingProviderError):
    """Raised when routing between specific coordinates fails or cannot be resolved."""
    pass


class RouteTimeoutError(RoutingProviderError):
    """Raised when the routing backend query times out."""
    pass


class InvalidRouteDataError(RoutingProviderError):
    """Raised when the routing backend returns physically invalid or corrupt data."""
    pass


def validate_route_leg(
    origin: Coordinate,
    destination: Coordinate,
    leg: Any,
) -> tuple[int, int]:
    """
    Validates that a direct leg result satisfies physical invariants:
    - leg must be a 2-tuple or 2-element sequence of numbers (distance_meters, duration_seconds).
    - distance_meters and duration_seconds must be valid, finite, non-negative numbers.
    - If origin and destination are distinct coordinates (haversine > 0), distance and duration
      must be strictly positive (> 0). A failed route lookup must never be treated as 0m or 0s.
    Returns the validated (distance_meters, duration_seconds) as integers.
    """
    if not isinstance(leg, (tuple, list)) or len(leg) != 2:
        raise InvalidRouteDataError(
            f"Routing provider returned invalid leg structure (expected 2-tuple): {leg!r}"
        )
    dist, dur = leg
    if (
        isinstance(dist, bool)
        or isinstance(dur, bool)
        or not isinstance(dist, (int, float))
        or not isinstance(dur, (int, float))
    ):
        raise InvalidRouteDataError(
            f"Routing provider returned non-numeric leg values: dist={dist!r}, dur={dur!r}"
        )
    if math.isnan(dist) or math.isnan(dur) or math.isinf(dist) or math.isinf(dur):
        raise InvalidRouteDataError(
            f"Routing provider returned NaN or infinite leg values: dist={dist!r}, dur={dur!r}"
        )
    if dist < 0 or dur < 0:
        raise InvalidRouteDataError(
            f"Routing provider returned negative leg values: dist={dist}, dur={dur}"
        )

    # Distinct coordinates must not have zero distance or zero duration
    if origin.latitude != destination.latitude or origin.longitude != destination.longitude:
        if dist <= 0 or dur <= 0:
            raise InvalidRouteDataError(
                f"Route leg between distinct coordinates ({origin.latitude}, {origin.longitude}) "
                f"and ({destination.latitude}, {destination.longitude}) returned zero distance or duration "
                f"({dist}m, {dur}s). Failed route lookups must never be treated as zero distance/time."
            )
        return max(1, int(round(dist))), max(1, int(round(dur)))

    return int(round(dist)), int(round(dur))


class RoadNetworkRoutingProvider(ABC):
    """
    Vendor-independent road network routing contract.
    Must be implemented by concrete adapters (e.g. OSRM, Valhalla, Mock).
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

    def prefetch_matrix(
        self,
        origins: Sequence[Coordinate],
        destinations: Sequence[Coordinate] | None = None,
        deadline: float | None = None,
        reserved_headroom: float = 0.050,
    ) -> int:
        """
        Optional performance hint to prefetch and memoize pairwise legs among waypoints.
        Default implementation is a no-op returning 0.
        Concrete adapters with batched matrix endpoints (e.g. OSRM /table)
        can query and populate their internal cache in bulk.
        Must never fail or raise if individual legs cannot be routed.
        Returns the count of new valid legs cached.
        """
        return 0

    def prefetch_matrices(
        self,
        groups: Sequence[Sequence[Coordinate]],
        deadline: float | None = None,
        reserved_headroom: float = 0.050,
    ) -> int:
        """
        Optional performance hint to prefetch and memoize pairwise legs for multiple waypoint groups.
        Default implementation sequentially iterates through groups calling prefetch_matrix.
        Concrete adapters with concurrent transports can execute requests concurrently.
        Must never fail or raise if individual legs cannot be routed.
        Returns the total count of new valid legs cached.
        """
        total = 0
        for group in groups:
            if deadline is not None and time.monotonic() > deadline - reserved_headroom:
                break
            total += self.prefetch_matrix(
                origins=group,
                destinations=group,
                deadline=deadline,
                reserved_headroom=reserved_headroom,
            )
        return total

    def check_health(self) -> bool:
        """
        Operational health check verifying connectivity to the routing backend.
        Default implementation returns True; concrete adapters can execute a lightweight query.
        """
        return True
