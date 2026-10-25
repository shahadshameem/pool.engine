"""Uber H3 spatial index adapter with graceful pure-Python discrete cell fallback."""

import math
from collections.abc import Callable
from typing import Any, Sequence

from engine.contracts.routing import Coordinate
from engine.contracts.spatial import SpatialCandidate, SpatialIndexProvider
from engine.spatial.lower_bounds import DEFAULT_EARTH_RADIUS_METERS, haversine_distance_meters

# Attempt to load native H3 C-extension; if blocked by OS policy, use pure-Python discrete grid
_H3_MODULE: Any = None
try:
    import h3 as _h3_import  # type: ignore[import-untyped]
    # Test if basic functions run without DLL error
    _test_cell = _h3_import.latlng_to_cell(40.7128, -74.0060, 8) if hasattr(_h3_import, "latlng_to_cell") else _h3_import.geo_to_h3(40.7128, -74.0060, 8)
    _H3_MODULE = _h3_import
except Exception:
    _H3_MODULE = None

_GLOBAL_H3_RING_CACHE: dict[tuple[str, int], set[str]] = {}


class H3SpatialIndexAdapter(SpatialIndexProvider):
    """
    SpatialIndexProvider implementation using Uber H3 discrete hexagonal partitioning
    when native libraries are available, with an exact discrete cell-grid fallback.
    """

    def __init__(self, resolution: int = 8) -> None:
        self.resolution = resolution
        # Grid step in degrees roughly corresponding to H3 resolution 8 (~460m)
        self._lat_step = 0.0045 * (2 ** (8 - self.resolution))
        self._lon_step = 0.0055 * (2 ** (8 - self.resolution))
        # Internal indexed storage: cell_id -> list of (entity_id, Coordinate, lat_rad, lon_rad, cos_lat)
        self._cells: dict[str, list[tuple[str, Coordinate, float, float, float]]] = {}
        self._all_entities: list[tuple[str, Coordinate]] = []
        self._ring_cache: dict[tuple[str, int], set[str]] = _GLOBAL_H3_RING_CACHE

    def _grid_cell_id(self, coord: Coordinate) -> str:
        """Pure-Python discrete cell index generator."""
        r_i = int(math.floor(coord.latitude / self._lat_step))
        c_j = int(math.floor(coord.longitude / self._lon_step))
        return f"grid_r{self.resolution}_{r_i}_{c_j}"

    def get_cell_id(self, coordinate: Coordinate) -> str:
        """Returns the canonical string representation of the spatial cell."""
        if _H3_MODULE is not None:
            try:
                if hasattr(_H3_MODULE, "latlng_to_cell"):
                    return str(_H3_MODULE.latlng_to_cell(coordinate.latitude, coordinate.longitude, self.resolution))
                return str(_H3_MODULE.geo_to_h3(coordinate.latitude, coordinate.longitude, self.resolution))
            except Exception:
                pass
        return self._grid_cell_id(coordinate)

    def index_entities(self, entities: Sequence[tuple[str, Coordinate]]) -> None:
        """Indexes entities into spatial cells."""
        self._cells.clear()
        self._all_entities = list(entities)

        for entity_id, location in entities:
            cell_id = self.get_cell_id(location)
            if cell_id not in self._cells:
                self._cells[cell_id] = []
            lat_rad = math.radians(location.latitude)
            lon_rad = math.radians(location.longitude)
            cos_lat = math.cos(lat_rad)
            self._cells[cell_id].append((entity_id, location, lat_rad, lon_rad, cos_lat))

    def _get_h3_k_ring_cells(self, origin_cell: str, k: int) -> set[str]:
        """Queries concentric cell rings using H3."""
        cache_key = (origin_cell, k)
        if cache_key in self._ring_cache:
            return self._ring_cache[cache_key]

        if _H3_MODULE is not None:
            try:
                if hasattr(_H3_MODULE, "grid_ring"):
                    res = set(_H3_MODULE.grid_ring(origin_cell, k))
                    self._ring_cache[cache_key] = res
                    return res
                if hasattr(_H3_MODULE, "grid_disk"):
                    res = set(_H3_MODULE.grid_disk(origin_cell, k))
                    self._ring_cache[cache_key] = res
                    return res
                res = set(_H3_MODULE.k_ring(origin_cell, k))
                self._ring_cache[cache_key] = res
                return res
            except Exception as ring_exc:
                try:
                    if hasattr(_H3_MODULE, "grid_disk"):
                        res = set(_H3_MODULE.grid_disk(origin_cell, k))
                        self._ring_cache[cache_key] = res
                        return res
                    if hasattr(_H3_MODULE, "k_ring"):
                        res = set(_H3_MODULE.k_ring(origin_cell, k))
                        self._ring_cache[cache_key] = res
                        return res
                    raise ring_exc
                except Exception as disk_exc:
                    raise RuntimeError(
                        f"H3 traversal failed for cell {origin_cell} at ring {k}: {disk_exc}"
                    ) from disk_exc
        return set()

    def _get_grid_k_ring_cells(self, coord: Coordinate, k: int) -> set[str]:
        """Queries concentric cell rings using discrete grid."""
        r_i = int(math.floor(coord.latitude / self._lat_step))
        c_j = int(math.floor(coord.longitude / self._lon_step))
        ring_cells: set[str] = set()

        if k == 0:
            ring_cells.add(f"grid_r{self.resolution}_{r_i}_{c_j}")
        else:
            for di in range(-k, k + 1):
                ring_cells.add(f"grid_r{self.resolution}_{r_i + di}_{c_j - k}")
                ring_cells.add(f"grid_r{self.resolution}_{r_i + di}_{c_j + k}")
            for dj in range(-k + 1, k):
                ring_cells.add(f"grid_r{self.resolution}_{r_i - k}_{c_j + dj}")
                ring_cells.add(f"grid_r{self.resolution}_{r_i + k}_{c_j + dj}")
        return ring_cells

    def find_nearest_candidates(
        self,
        target: Coordinate,
        max_radius_meters: float,
        min_candidates: int = 5,
        max_candidates: int | None = None,
        entity_filter: Callable[[str], bool] | None = None,
    ) -> Sequence[SpatialCandidate]:
        """
        Queries nearest candidate entities within max_radius_meters using multi-ring expansion.
        If max_candidates is None, does not truncate and returns all candidates within radius.
        If entity_filter is specified, only entities passing the predicate are considered
        towards the candidate limit.
        """
        center_cell = self.get_cell_id(target)
        candidates_found: dict[str, SpatialCandidate] = {}

        target_lat_rad = math.radians(target.latitude)
        target_lon_rad = math.radians(target.longitude)
        cos_target_lat = math.cos(target_lat_rad)

        # Minimum physical distance step per ring
        cos_lat = max(0.01, cos_target_lat)
        lat_step_m = self._lat_step * 111000.0
        lon_step_m = self._lon_step * 111000.0 * cos_lat
        min_cell_step_meters = max(50.0, min(lat_step_m, lon_step_m))

        max_k = max(2, int(math.ceil(max_radius_meters / min_cell_step_meters)) + 2)

        for k in range(max_k + 1):
            if _H3_MODULE is not None and not center_cell.startswith("grid_"):
                cell_ring = self._get_h3_k_ring_cells(center_cell, k)
            else:
                cell_ring = self._get_grid_k_ring_cells(target, k)

            for cell_id in cell_ring:
                if cell_id in self._cells:
                    for ent_id, ent_loc, ent_lat_rad, ent_lon_rad, ent_cos_lat in self._cells[cell_id]:
                        if entity_filter is not None and not entity_filter(ent_id):
                            continue
                        if ent_id not in candidates_found:
                            dlat = ent_lat_rad - target_lat_rad
                            dlon = ent_lon_rad - target_lon_rad
                            sin_half_dlat = math.sin(dlat * 0.5)
                            sin_half_dlon = math.sin(dlon * 0.5)
                            a = (
                                sin_half_dlat * sin_half_dlat
                                + cos_target_lat * ent_cos_lat * sin_half_dlon * sin_half_dlon
                            )
                            c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
                            d = DEFAULT_EARTH_RADIUS_METERS * c
                            if d <= max_radius_meters:
                                candidates_found[ent_id] = SpatialCandidate(
                                    entity_id=ent_id,
                                    location=ent_loc,
                                    haversine_distance_meters=d,
                                    cell_id=cell_id,
                                )

            # Termination condition 1: full physical radius covered
            min_inner_radius = max(0.0, (k - 1) * min_cell_step_meters)
            if min_inner_radius >= max_radius_meters:
                break

            # Termination condition 2: candidate count saturated AND full ring finished (if bounded)
            if max_candidates is not None and len(candidates_found) >= max_candidates:
                break

        # Sort ascending by distance
        sorted_candidates = sorted(candidates_found.values(), key=lambda c: c.haversine_distance_meters)
        if max_candidates is not None:
            return sorted_candidates[:max_candidates]
        return sorted_candidates
