"""Contract for road network routing providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import math
import time
from typing import Any, Mapping, Sequence


class RoutingProviderError(Exception):
    """Base exception for routing backend errors and failures."""
    pass


class InvalidCoordinateError(RoutingProviderError, ValueError):
    """Raised when coordinates are non-numeric, non-finite, or outside physical boundaries."""
    pass


class RouteLookupError(RoutingProviderError):
    """Raised when routing between specific coordinates fails or cannot be resolved."""
    pass


class OutOfRegionError(RouteLookupError):
    """Raised when coordinates or snapped waypoints fall outside the supported road network region."""
    pass


class RouteTimeoutError(RoutingProviderError):
    """Raised when the routing backend query times out."""
    pass


class InvalidRouteDataError(RoutingProviderError):
    """Raised when the routing backend returns physically invalid or corrupt data."""
    pass


@dataclass(frozen=True)
class Coordinate:
    """Geographical coordinate for routing queries."""
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if isinstance(self.latitude, bool) or isinstance(self.longitude, bool):
            raise InvalidCoordinateError("Coordinate values cannot be boolean")
        if not isinstance(self.latitude, (int, float)) or not isinstance(self.longitude, (int, float)):
            raise InvalidCoordinateError(
                f"Coordinate values must be numbers: lat={self.latitude!r}, lon={self.longitude!r}"
            )
        if math.isnan(self.latitude) or math.isinf(self.latitude):
            raise InvalidCoordinateError(f"Coordinate latitude must be a finite number: {self.latitude!r}")
        if math.isnan(self.longitude) or math.isinf(self.longitude):
            raise InvalidCoordinateError(f"Coordinate longitude must be a finite number: {self.longitude!r}")
        if not (-90.0 <= self.latitude <= 90.0):
            raise InvalidCoordinateError(
                f"Latitude must be between -90.0 and 90.0 degrees: {self.latitude}"
            )
        if not (-180.0 <= self.longitude <= 180.0):
            raise InvalidCoordinateError(
                f"Longitude must be between -180.0 and 180.0 degrees: {self.longitude}"
            )

        object.__setattr__(self, "latitude", round(float(self.latitude), 6))
        object.__setattr__(self, "longitude", round(float(self.longitude), 6))


@dataclass(frozen=True)
class BoundingBox:
    """Geographic bounding box defining an operational road-network service region."""
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float

    def __post_init__(self) -> None:
        for val, name in (
            (self.min_lat, "min_lat"),
            (self.min_lon, "min_lon"),
            (self.max_lat, "max_lat"),
            (self.max_lon, "max_lon"),
        ):
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise InvalidCoordinateError(f"Bounding box {name} must be a number: {val!r}")
            if math.isnan(val) or math.isinf(val):
                raise InvalidCoordinateError(f"Bounding box {name} must be a finite number: {val!r}")

        if not (-90.0 <= self.min_lat <= 90.0 and -90.0 <= self.max_lat <= 90.0):
            raise InvalidCoordinateError(
                f"Bounding box latitudes must be between -90.0 and 90.0: [{self.min_lat}, {self.max_lat}]"
            )
        if not (-180.0 <= self.min_lon <= 180.0 and -180.0 <= self.max_lon <= 180.0):
            raise InvalidCoordinateError(
                f"Bounding box longitudes must be between -180.0 and 180.0: [{self.min_lon}, {self.max_lon}]"
            )
        if self.min_lat > self.max_lat:
            raise InvalidCoordinateError(
                f"Bounding box min_lat ({self.min_lat}) cannot exceed max_lat ({self.max_lat})"
            )
        if self.min_lon > self.max_lon:
            raise InvalidCoordinateError(
                f"Bounding box min_lon ({self.min_lon}) cannot exceed max_lon ({self.max_lon})"
            )

        object.__setattr__(self, "min_lat", round(float(self.min_lat), 6))
        object.__setattr__(self, "min_lon", round(float(self.min_lon), 6))
        object.__setattr__(self, "max_lat", round(float(self.max_lat), 6))
        object.__setattr__(self, "max_lon", round(float(self.max_lon), 6))

    def contains(self, coord: Coordinate) -> bool:
        """Returns True if the coordinate is within or on the bounding box boundary."""
        return (
            self.min_lat <= coord.latitude <= self.max_lat
            and self.min_lon <= coord.longitude <= self.max_lon
        )

    def overlaps(self, other: "BoundingBox") -> bool:
        """
        Returns True if this bounding box has area intersection with another bounding box.
        Boxes that only share an infinitesimally thin boundary line or corner point
        are considered non-overlapping.
        """
        lat_overlap = max(self.min_lat, other.min_lat) < min(self.max_lat, other.max_lat)
        lon_overlap = max(self.min_lon, other.min_lon) < min(self.max_lon, other.max_lon)
        return lat_overlap and lon_overlap

    def validate(self, coord: Coordinate, label: str = "Coordinate") -> None:
        """
        Validates that coord is contained within this bounding box.
        Raises OutOfRegionError if outside.
        """
        if not self.contains(coord):
            raise OutOfRegionError(
                f"{label} ({coord.latitude}, {coord.longitude}) falls outside regional bounding box "
                f"[{self.min_lat}, {self.min_lon}, {self.max_lat}, {self.max_lon}]"
            )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "BoundingBox | None":
        """
        Builds a BoundingBox by inspecting environment variables or provided mapping:
        - ROUTING_REGION_MIN_LAT
        - ROUTING_REGION_MIN_LON
        - ROUTING_REGION_MAX_LAT
        - ROUTING_REGION_MAX_LON
        Returns None if all are unset.
        Raises ValueError if partially configured.
        """
        import os
        source = os.environ if env is None else env
        keys = (
            "ROUTING_REGION_MIN_LAT",
            "ROUTING_REGION_MIN_LON",
            "ROUTING_REGION_MAX_LAT",
            "ROUTING_REGION_MAX_LON",
        )
        present = [k for k in keys if k in source and source[k].strip()]
        if not present:
            return None
        if len(present) != 4:
            missing = [k for k in keys if k not in present]
            raise ValueError(
                f"Incomplete regional bounding box configuration. Missing variables: {', '.join(missing)}"
            )
        try:
            return cls(
                min_lat=float(source["ROUTING_REGION_MIN_LAT"]),
                min_lon=float(source["ROUTING_REGION_MIN_LON"]),
                max_lat=float(source["ROUTING_REGION_MAX_LAT"]),
                max_lon=float(source["ROUTING_REGION_MAX_LON"]),
            )
        except ValueError as err:
            raise ValueError(f"Failed to parse regional bounding box coordinates from env: {err}") from err


import re

_REGION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")


@dataclass(frozen=True)
class RegionConfig:
    """Explicit configuration contract for a distinct operational geographic region."""
    region_id: str
    bounding_box: BoundingBox
    provider_type: str = "osrm"  # "osrm" or "mock"
    endpoint_url: str | None = None
    dataset_id: str = "default"
    profile: str = "driving"
    max_snap_distance_meters: float = 5000.0
    timeout_seconds: float = 0.500
    probe_coordinate: Coordinate | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.region_id, str) or not self.region_id.strip():
            raise ValueError(f"region_id must be a non-empty string: {self.region_id!r}")
        clean_id = self.region_id.strip()
        if not _REGION_ID_PATTERN.match(clean_id):
            raise ValueError(
                f"region_id must contain only alphanumeric characters, underscores, and hyphens: {self.region_id!r}"
            )
        object.__setattr__(self, "region_id", clean_id)

        if not isinstance(self.bounding_box, BoundingBox):
            raise ValueError(f"bounding_box must be an instance of BoundingBox: {self.bounding_box!r}")

        clean_type = str(self.provider_type).strip().lower()
        if clean_type not in ("osrm", "mock"):
            raise ValueError(f"provider_type must be 'osrm' or 'mock', got: {self.provider_type!r}")
        object.__setattr__(self, "provider_type", clean_type)

        if self.provider_type == "osrm" and self.endpoint_url is not None:
            if not str(self.endpoint_url).strip():
                raise ValueError("endpoint_url cannot be empty when provider_type is 'osrm'")

        if self.max_snap_distance_meters < 1.0:
            raise ValueError(
                f"max_snap_distance_meters must be at least 1.0m: {self.max_snap_distance_meters}"
            )
        if self.timeout_seconds <= 0.0:
            raise ValueError(f"timeout_seconds must be positive: {self.timeout_seconds}")

        if self.probe_coordinate is not None:
            if not isinstance(self.probe_coordinate, Coordinate):
                raise ValueError(f"probe_coordinate must be a Coordinate instance: {self.probe_coordinate!r}")
            if not self.bounding_box.contains(self.probe_coordinate):
                raise ValueError(
                    f"probe_coordinate ({self.probe_coordinate.latitude}, {self.probe_coordinate.longitude}) "
                    f"must fall within regional bounding box [{self.bounding_box.min_lat}, {self.bounding_box.min_lon}, "
                    f"{self.bounding_box.max_lat}, {self.bounding_box.max_lon}]"
                )



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


class RoutingPrefetchHandle(ABC):
    """Abstract handle for an in-flight or completed asynchronous prefetch session."""

    @abstractmethod
    def wait_group(self, group_index: int, timeout: float | None = None) -> bool:
        """
        Wait for group at group_index to finish prefetching and populating cache.
        Returns True if completed. Raises TimeoutError if timeout expires.
        """
        pass

    @abstractmethod
    def cancel(self) -> None:
        """Cancel any remaining in-flight prefetch queries."""
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

    def start_prefetch_matrices(
        self,
        groups: Sequence[Sequence[Coordinate]],
        deadline: float | None = None,
        reserved_headroom: float = 0.050,
    ) -> "RoutingPrefetchHandle | None":
        """
        Optional performance hint to initiate asynchronous prefetching of pairwise legs
        for multiple waypoint groups, allowing caller to overlap I/O with evaluation.
        Default implementation returns None (indicating synchronous or no prefetch).
        """
        return None

    def check_health(self) -> bool:
        """
        Operational health check verifying connectivity to the routing backend.
        Default implementation returns True; concrete adapters can execute a lightweight query.
        """
        return True

    def validate_coordinate(self, coord: Coordinate, label: str = "Coordinate") -> None:
        """
        Validates that a coordinate is geographically eligible for this routing provider.
        Default implementation is a no-op; concrete adapters with regional bounds enforce constraints.
        """
        pass
