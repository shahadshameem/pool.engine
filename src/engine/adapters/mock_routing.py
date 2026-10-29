"""Deterministic mock routing provider for testing and benchmarks."""

import math
from typing import Sequence

from engine.contracts.routing import (
    BoundingBox,
    Coordinate,
    MatrixResult,
    RoadNetworkRoutingProvider,
    RouteGeometry,
)


class MockRoutingProvider(RoadNetworkRoutingProvider):
    """
    Deterministic mock routing provider based on great-circle distance,
    road circuity factor, and configured average speed.
    """

    def __init__(
        self,
        average_speed_kmh: float = 40.0,
        circuity_factor: float = 1.25,
        earth_radius_meters: float = 6371000.0,
        bounding_box: BoundingBox | None = None,
    ) -> None:
        self.average_speed_kmh = max(1.0, average_speed_kmh)
        self.circuity_factor = max(1.0, circuity_factor)
        self.earth_radius_meters = earth_radius_meters
        self.bounding_box = bounding_box
        self._speed_mps = (self.average_speed_kmh * 1000.0) / 3600.0
        self._cache: dict[tuple[float, float, float, float], tuple[int, int]] = {}

    def validate_coordinate(self, coord: Coordinate, label: str = "Coordinate") -> None:
        """Validates that coordinate is within the configured bounding box if present."""
        if self.bounding_box is not None:
            self.bounding_box.validate(coord, label)

    def _haversine_distance(self, c1: Coordinate, c2: Coordinate) -> float:
        """Computes great-circle distance in meters between two coordinates."""
        lat1, lon1 = math.radians(c1.latitude), math.radians(c1.longitude)
        lat2, lon2 = math.radians(c2.latitude), math.radians(c2.longitude)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = (
            math.sin(dlat / 2.0) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
        )
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
        return self.earth_radius_meters * c

    def get_direct_leg(
        self,
        origin: Coordinate,
        destination: Coordinate
    ) -> tuple[int, int]:
        """Returns deterministic road distance (meters) and duration (seconds)."""
        if self.bounding_box is not None:
            self.bounding_box.validate(origin, "Origin")
            self.bounding_box.validate(destination, "Destination")

        key = (origin.latitude, origin.longitude, destination.latitude, destination.longitude)
        if key in self._cache:
            return self._cache[key]

        haversine = self._haversine_distance(origin, destination)
        if haversine <= 0.0:
            return 0, 0

        # Road distance is bounded below by great-circle distance: d_road >= d_haversine
        road_distance = max(int(math.ceil(haversine)), int(round(haversine * self.circuity_factor)))
        road_duration = max(1, int(round(road_distance / self._speed_mps)))

        self._cache[key] = (road_distance, road_duration)
        return road_distance, road_duration

    def get_distance_matrix(
        self,
        origins: Sequence[Coordinate],
        destinations: Sequence[Coordinate]
    ) -> MatrixResult:
        """Computes pairwise road network distances and durations."""
        distances: list[list[int]] = []
        durations: list[list[int]] = []

        for orig in origins:
            row_dist: list[int] = []
            row_dur: list[int] = []
            for dest in destinations:
                dist, dur = self.get_direct_leg(orig, dest)
                row_dist.append(dist)
                row_dur.append(dur)
            distances.append(row_dist)
            durations.append(row_dur)

        return MatrixResult(distances_meters=distances, durations_seconds=durations)

    def get_route(
        self,
        waypoints: Sequence[Coordinate]
    ) -> RouteGeometry:
        """Computes route connecting ordered waypoints."""
        if len(waypoints) < 2:
            return RouteGeometry(
                points=list(waypoints),
                total_distance_meters=0,
                total_duration_seconds=0
            )

        total_distance = 0
        total_duration = 0
        for i in range(len(waypoints) - 1):
            dist, dur = self.get_direct_leg(waypoints[i], waypoints[i + 1])
            total_distance += dist
            total_duration += dur

        return RouteGeometry(
            points=list(waypoints),
            total_distance_meters=total_distance,
            total_duration_seconds=total_duration
        )
