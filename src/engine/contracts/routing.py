"""Contract for road network routing providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Coordinate:
    """Geographical coordinate for routing queries."""
    latitude: float
    longitude: float


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
    """Raised when routing backend experiences an error or timeout."""
    pass


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
