"""Provider-neutral spatial indexing coordinator with safe multi-ring expansion and BBox fallback."""

import logging
from collections.abc import Callable
from typing import Sequence

from engine.contracts.routing import Coordinate
from engine.contracts.spatial import SpatialCandidate, SpatialIndexProvider
from engine.spatial.lower_bounds import (
    compute_derived_bounding_box,
    haversine_distance_meters,
    is_in_bounding_box,
)

logger = logging.getLogger(__name__)


class SpatialIndexCoordinator:
    """
    Provider-neutral spatial candidate discovery coordinator.
    Orchestrates discrete cell indexing, conservative metric lower bounds,
    and automatic fallback to derived bounding-box search upon boundary distortions or exceptions.
    """

    def __init__(self, spatial_provider: SpatialIndexProvider) -> None:
        self.spatial_provider = spatial_provider
        self._all_entities: list[tuple[str, Coordinate]] = []

    def index_entities(self, entities: Sequence[tuple[str, Coordinate]]) -> None:
        """Indexes entities in both the underlying spatial provider and local coordinator cache."""
        self._all_entities = list(entities)
        self.spatial_provider.index_entities(entities)

    def exhaustive_search(
        self,
        target: Coordinate,
        max_radius_meters: float,
        entity_filter: Callable[[str], bool] | None = None,
    ) -> Sequence[SpatialCandidate]:
        """
        Exhaustive brute-force all-pairs candidate discovery using derived bounding box.
        Guarantees 100% complete recall of all physically feasible candidate entities.
        """
        bbox = compute_derived_bounding_box(center=target, radius_meters=max_radius_meters)
        candidates: list[SpatialCandidate] = []

        for entity_id, loc in self._all_entities:
            if entity_filter is not None and not entity_filter(entity_id):
                continue
            # 1. Bounding-box pre-filtering
            if is_in_bounding_box(loc, bbox):
                # 2. Exact great-circle Haversine verification
                d = haversine_distance_meters(target, loc)
                if d <= max_radius_meters:
                    cell_id = self.spatial_provider.get_cell_id(loc)
                    candidates.append(
                        SpatialCandidate(
                            entity_id=entity_id,
                            location=loc,
                            haversine_distance_meters=d,
                            cell_id=cell_id,
                        )
                    )

        candidates.sort(key=lambda c: c.haversine_distance_meters)
        return candidates

    def find_candidates_within_radius(
        self,
        target: Coordinate,
        max_radius_meters: float,
        min_candidates: int = 5,
        max_candidates: int | None = None,
        entity_filter: Callable[[str], bool] | None = None,
    ) -> Sequence[SpatialCandidate]:
        """
        Discovers candidates within max_radius_meters.
        Attempts discrete spatial provider expansion first; automatically falls back
        to exhaustive bounding-box search if boundary distortions, exceptions,
        or under-recall conditions occur.
        """
        # Derived Search Geometry & Spherical Boundary Condition Check:
        bbox = compute_derived_bounding_box(center=target, radius_meters=max_radius_meters)
        min_lat, min_lon, max_lat, max_lon = bbox

        # 1. Antimeridian wrap: search geometry crosses +/-180 deg longitude line
        spans_antimeridian = (
            min_lon < -180.0
            or max_lon > 180.0
            or (max_lon - min_lon) >= 360.0
            or abs(abs(target.longitude) - 180.0) < 0.5
        )
        # 2. Polar distortion: target latitude or search geometry enters polar cap (|lat| > 85 deg)
        is_polar = abs(target.latitude) > 85.0 or min_lat <= -85.0 or max_lat >= 85.0

        if is_polar or spans_antimeridian:
            logger.info("Search geometry spans spherical boundary; executing safe exhaustive BBox fallback.")
            res = self.exhaustive_search(
                target=target,
                max_radius_meters=max_radius_meters,
                entity_filter=entity_filter,
            )
            return res[:max_candidates] if max_candidates is not None else res

        try:
            candidates = self.spatial_provider.find_nearest_candidates(
                target=target,
                max_radius_meters=max_radius_meters,
                min_candidates=min_candidates,
                max_candidates=max_candidates,
                entity_filter=entity_filter,
            )

            # Safe Fallback Check:
            # If discrete indexing returned fewer than min_candidates but we have enough total entities
            if len(candidates) < min_candidates and len(self._all_entities) >= min_candidates:
                # Check whether exhaustive search yields more valid candidates
                exhaustive = self.exhaustive_search(
                    target=target,
                    max_radius_meters=max_radius_meters,
                    entity_filter=entity_filter,
                )
                if len(exhaustive) > len(candidates):
                    return exhaustive[:max_candidates] if max_candidates is not None else exhaustive

            return candidates

        except Exception as exc:
            logger.warning(
                f"Spatial provider error ({exc}); triggering automatic exhaustive BBox fallback."
            )
            res = self.exhaustive_search(
                target=target,
                max_radius_meters=max_radius_meters,
                entity_filter=entity_filter,
            )
            return res[:max_candidates] if max_candidates is not None else res
