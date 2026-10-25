"""Contract for spatial indexing providers."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from engine.contracts.routing import Coordinate


@dataclass(frozen=True)
class SpatialCandidate:
    """Discovered spatial neighbor candidate."""
    entity_id: str
    location: Coordinate
    haversine_distance_meters: float
    cell_id: str


class SpatialIndexProvider(ABC):
    """
    Vendor-independent spatial indexing contract.
    Provides discrete O(1) or O(log N) neighbor candidate discovery.
    """

    @abstractmethod
    def index_entities(
        self,
        entities: Sequence[tuple[str, Coordinate]]
    ) -> None:
        """Indexes a batch of spatial entities (e.g. active vehicles or pickup stops)."""
        pass

    @abstractmethod
    def find_nearest_candidates(
        self,
        target: Coordinate,
        max_radius_meters: float,
        min_candidates: int = 5,
        max_candidates: int | None = None,
        entity_filter: Callable[[str], bool] | None = None,
    ) -> Sequence[SpatialCandidate]:
        """
        Queries nearest candidate entities within max_radius_meters.
        Adaptively expands search rings up to max_radius_meters.
        If max_candidates is None, returns all candidates discovered within max_radius_meters.
        """
        pass

    @abstractmethod
    def get_cell_id(self, coordinate: Coordinate) -> str:
        """Returns the canonical string representation of the spatial cell containing coordinate."""
        pass
