"""Production road-network routing adapter for OSRM (Open Source Routing Machine)."""

from abc import ABC, abstractmethod
from collections import OrderedDict
import http.client
import json
import math
import threading
from typing import Any, Sequence
import urllib.parse

from engine.contracts.routing import (
    Coordinate,
    InvalidRouteDataError,
    MatrixResult,
    RoadNetworkRoutingProvider,
    RouteGeometry,
    RouteLookupError,
    RouteTimeoutError,
    validate_route_leg,
)


class OsrmHttpTransport(ABC):
    """Abstract HTTP transport for OSRM routing requests."""

    @abstractmethod
    def get(self, path_and_query: str, timeout: float) -> tuple[int, bytes]:
        """
        Executes an HTTP GET request.
        Returns a tuple of (status_code, response_body_bytes).
        """
        pass

    def close(self) -> None:
        """Closes any underlying network connections."""
        pass


class DefaultOsrmTransport(OsrmHttpTransport):
    """
    Standard HTTP transport for OSRM with Keep-Alive connection pooling
    and automatic reconnection.
    """

    def __init__(self, base_url: str = "http://localhost:5000") -> None:
        parsed = urllib.parse.urlsplit(base_url)
        self.scheme = parsed.scheme.lower() if parsed.scheme else "http"
        self.host = parsed.hostname or "localhost"
        self.port = parsed.port or (443 if self.scheme == "https" else 80)
        self.path_prefix = parsed.path.rstrip("/")
        self._lock = threading.Lock()
        self._conn: http.client.HTTPConnection | http.client.HTTPSConnection | None = None

    def _get_connection(self, timeout: float) -> http.client.HTTPConnection:
        if self._conn is None:
            if self.scheme == "https":
                self._conn = http.client.HTTPSConnection(self.host, self.port, timeout=timeout)
            else:
                self._conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        else:
            self._conn.timeout = timeout
        return self._conn

    def get(self, path_and_query: str, timeout: float) -> tuple[int, bytes]:
        full_path = self.path_prefix + (path_and_query if path_and_query.startswith("/") else "/" + path_and_query)
        headers = {"Accept": "application/json", "User-Agent": "PoolEngine-OSRM/1.0"}

        with self._lock:
            conn = self._get_connection(timeout)
            try:
                conn.request("GET", full_path, headers=headers)
                resp = conn.getresponse()
                body = resp.read()
                return resp.status, body
            except (
                http.client.RemoteDisconnected,
                http.client.CannotSendRequest,
                BrokenPipeError,
                ConnectionResetError,
            ):
                # Connection was closed or stale; reconnect once
                self._close_locked()
                conn = self._get_connection(timeout)
                conn.request("GET", full_path, headers=headers)
                resp = conn.getresponse()
                body = resp.read()
                return resp.status, body

    def _close_locked(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def close(self) -> None:
        with self._lock:
            self._close_locked()


class LruLegCache:
    """Thread-safe LRU cache for road legs (with negative caching support)."""

    def __init__(self, maxsize: int = 50000) -> None:
        self.maxsize = max(1, maxsize)
        self._data: OrderedDict[tuple[float, float, float, float], tuple[int, int] | None] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def lookup(self, key: tuple[float, float, float, float]) -> tuple[bool, tuple[int, int] | None]:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self.hits += 1
                return True, self._data[key]
            self.misses += 1
            return False, None

    def get(self, key: tuple[float, float, float, float]) -> tuple[int, int] | None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self.hits += 1
                return self._data[key]
            self.misses += 1
            return None

    def set(self, key: tuple[float, float, float, float], value: tuple[int, int] | None) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self._data[key] = value
                return
            self._data[key] = value
            if len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.hits = 0
            self.misses = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


class OsrmRoutingAdapter(RoadNetworkRoutingProvider):
    """
    High-performance, provider-independent routing adapter backed by OSRM.
    Implements distance matrix batching, Keep-Alive transport, physical invariant
    validation, and in-memory LRU caching.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:5000",
        profile: str = "driving",
        timeout_seconds: float = 0.500,
        max_retries: int = 1,
        max_table_size: int = 100,
        cache_maxsize: int = 50000,
        coord_precision: int = 6,
        transport: OsrmHttpTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.profile = profile
        self.timeout_seconds = max(0.01, timeout_seconds)
        self.max_retries = max(0, max_retries)
        self.max_table_size = max(2, max_table_size)
        self.coord_precision = coord_precision
        self._cache = LruLegCache(maxsize=cache_maxsize)
        self.transport = transport if transport is not None else DefaultOsrmTransport(base_url=self.base_url)

    @property
    def cache(self) -> LruLegCache:
        return self._cache

    @property
    def cache_hits(self) -> int:
        return self._cache.hits

    @property
    def cache_misses(self) -> int:
        return self._cache.misses

    def clear_cache(self) -> None:
        self._cache.clear()

    def _cache_key(self, origin: Coordinate, destination: Coordinate) -> tuple[float, float, float, float]:
        return (
            round(origin.latitude, self.coord_precision),
            round(origin.longitude, self.coord_precision),
            round(destination.latitude, self.coord_precision),
            round(destination.longitude, self.coord_precision),
        )

    def _execute_get(self, path_and_query: str) -> dict[str, Any]:
        """Executes GET request with configured timeout and retry policy."""
        attempts = 0
        last_error: Exception | None = None

        while attempts <= self.max_retries:
            attempts += 1
            try:
                status, body = self.transport.get(path_and_query, self.timeout_seconds)
                break
            except TimeoutError as err:
                last_error = err
                if attempts > self.max_retries:
                    raise RouteTimeoutError(
                        f"OSRM request timed out after {self.timeout_seconds}s: {err}"
                    ) from err
            except (ConnectionError, OSError) as err:
                last_error = err
                if attempts > self.max_retries:
                    raise RouteLookupError(f"OSRM connection failed: {err}") from err
        else:
            if isinstance(last_error, TimeoutError):
                raise RouteTimeoutError(f"OSRM request timed out: {last_error}") from last_error
            raise RouteLookupError(f"OSRM request failed: {last_error}")

        try:
            data = json.loads(body.decode("utf-8"))
        except Exception as err:
            raise InvalidRouteDataError(
                f"Failed to parse OSRM JSON response (HTTP {status}): {err}"
            ) from err

        if not isinstance(data, dict):
            raise InvalidRouteDataError(f"OSRM response is not a JSON object: {data!r}")

        code = data.get("code")
        if status != 200:
            msg = data.get("message", f"HTTP {status}")
            raise RouteLookupError(f"OSRM error ({code}): {msg}")

        if code != "Ok":
            msg = data.get("message", f"Status code: {code}")
            raise RouteLookupError(f"OSRM returned non-OK code '{code}': {msg}")

        return data

    def get_direct_leg(
        self,
        origin: Coordinate,
        destination: Coordinate,
    ) -> tuple[int, int]:
        """
        Returns road network distance (meters) and travel duration (seconds)
        for a direct leg between origin and destination.
        """
        # Identical origin and destination: zero cost, zero duration
        if origin.latitude == destination.latitude and origin.longitude == destination.longitude:
            return 0, 0

        key = self._cache_key(origin, destination)
        found, cached = self._cache.lookup(key)
        if found:
            if cached is not None:
                return cached
            raise RouteLookupError(
                f"OSRM could not resolve route from ({origin.latitude}, {origin.longitude}) "
                f"to ({destination.latitude}, {destination.longitude}) [cached failure]"
            )

        # Query OSRM Table service for single pair
        orig_str = f"{origin.longitude:.{self.coord_precision}f},{origin.latitude:.{self.coord_precision}f}"
        dest_str = f"{destination.longitude:.{self.coord_precision}f},{destination.latitude:.{self.coord_precision}f}"
        path = (
            f"/table/v1/{self.profile}/{orig_str};{dest_str}"
            f"?sources=0&destinations=1&annotations=duration,distance"
        )

        data = self._execute_get(path)

        distances = data.get("distances")
        durations = data.get("durations")

        if (
            not isinstance(distances, list)
            or not isinstance(durations, list)
            or len(distances) == 0
            or len(durations) == 0
            or not isinstance(distances[0], list)
            or not isinstance(durations[0], list)
            or len(distances[0]) == 0
            or len(durations[0]) == 0
        ):
            raise InvalidRouteDataError(f"OSRM table response missing distance/duration matrices: {data!r}")

        raw_dist = distances[0][0]
        raw_dur = durations[0][0]

        if raw_dist is None or raw_dur is None:
            self._cache.set(key, None)
            raise RouteLookupError(
                f"OSRM could not resolve route from ({origin.latitude}, {origin.longitude}) "
                f"to ({destination.latitude}, {destination.longitude})"
            )

        try:
            validated = validate_route_leg(origin, destination, (raw_dist, raw_dur))
        except InvalidRouteDataError:
            self._cache.set(key, None)
            raise
        self._cache.set(key, validated)
        return validated

    def get_distance_matrix(
        self,
        origins: Sequence[Coordinate],
        destinations: Sequence[Coordinate],
    ) -> MatrixResult:
        """
        Computes pairwise road network distances and durations.
        Handles chunking when |origins| + |destinations| > max_table_size
        and leverages in-memory caching.
        """
        m = len(origins)
        n = len(destinations)

        if m == 0:
            return MatrixResult(distances_meters=[], durations_seconds=[])
        if n == 0:
            return MatrixResult(
                distances_meters=[[] for _ in origins],
                durations_seconds=[[] for _ in origins],
            )

        # Pre-allocate result matrices
        res_dist: list[list[int | None]] = [[None] * n for _ in range(m)]
        res_dur: list[list[int | None]] = [[None] * n for _ in range(m)]

        # Check cache and zero-cost diagonals first
        for i, orig in enumerate(origins):
            for j, dest in enumerate(destinations):
                if orig.latitude == dest.latitude and orig.longitude == dest.longitude:
                    res_dist[i][j] = 0
                    res_dur[i][j] = 0
                else:
                    found, cached = self._cache.lookup(self._cache_key(orig, dest))
                    if found:
                        if cached is None:
                            raise RouteLookupError(
                                f"OSRM could not resolve route from ({orig.latitude}, {orig.longitude}) "
                                f"to ({dest.latitude}, {dest.longitude}) [cached failure]"
                            )
                        res_dist[i][j] = cached[0]
                        res_dur[i][j] = cached[1]

        # Check if all pairs are resolved
        all_resolved = all(
            res_dist[i][j] is not None and res_dur[i][j] is not None
            for i in range(m)
            for j in range(n)
        )
        if all_resolved:
            return MatrixResult(
                distances_meters=[[int(val) for val in row if val is not None] for row in res_dist],
                durations_seconds=[[int(val) for val in row if val is not None] for row in res_dur],
            )

        # Chunk query if necessary to respect max_table_size
        # Total coordinates in table query = chunk_origins + chunk_destinations <= max_table_size
        max_origins_per_chunk = max(1, self.max_table_size // 2)
        max_dest_per_chunk = max(1, self.max_table_size - max_origins_per_chunk)

        for o_start in range(0, m, max_origins_per_chunk):
            o_end = min(m, o_start + max_origins_per_chunk)
            chunk_origins = origins[o_start:o_end]

            for d_start in range(0, n, max_dest_per_chunk):
                d_end = min(n, d_start + max_dest_per_chunk)
                chunk_destinations = destinations[d_start:d_end]

                # Check if all cells in this chunk are already filled
                chunk_needed = False
                for i in range(o_start, o_end):
                    for j in range(d_start, d_end):
                        if res_dist[i][j] is None or res_dur[i][j] is None:
                            chunk_needed = True
                            break
                    if chunk_needed:
                        break

                if not chunk_needed:
                    continue

                # Query this chunk
                all_coords = list(chunk_origins) + list(chunk_destinations)
                coords_str = ";".join(
                    f"{c.longitude:.{self.coord_precision}f},{c.latitude:.{self.coord_precision}f}"
                    for c in all_coords
                )
                sources_str = ";".join(str(i) for i in range(len(chunk_origins)))
                dests_str = ";".join(
                    str(len(chunk_origins) + j) for j in range(len(chunk_destinations))
                )

                path = (
                    f"/table/v1/{self.profile}/{coords_str}"
                    f"?sources={sources_str}&destinations={dests_str}&annotations=duration,distance"
                )

                data = self._execute_get(path)

                distances = data.get("distances")
                durations = data.get("durations")

                if (
                    not isinstance(distances, list)
                    or not isinstance(durations, list)
                    or len(distances) < len(chunk_origins)
                    or len(durations) < len(chunk_origins)
                ):
                    raise InvalidRouteDataError(f"OSRM returned invalid table matrix dimensions: {data!r}")

                for r, orig in enumerate(chunk_origins):
                    row_dist = distances[r]
                    row_dur = durations[r]
                    if (
                        not isinstance(row_dist, list)
                        or not isinstance(row_dur, list)
                        or len(row_dist) < len(chunk_destinations)
                        or len(row_dur) < len(chunk_destinations)
                    ):
                        raise InvalidRouteDataError(f"OSRM returned malformed row in matrix: {data!r}")

                    for c, dest in enumerate(chunk_destinations):
                        raw_dist = row_dist[c]
                        raw_dur = row_dur[c]

                        if raw_dist is None or raw_dur is None:
                            raise RouteLookupError(
                                f"OSRM could not resolve route from ({orig.latitude}, {orig.longitude}) "
                                f"to ({dest.latitude}, {dest.longitude})"
                            )

                        validated = validate_route_leg(orig, dest, (raw_dist, raw_dur))
                        res_dist[o_start + r][d_start + c] = validated[0]
                        res_dur[o_start + r][d_start + c] = validated[1]
                        self._cache.set(self._cache_key(orig, dest), validated)

        # Assemble final validated matrix
        final_dist: list[list[int]] = []
        final_dur: list[list[int]] = []
        for i in range(m):
            row_d: list[int] = []
            row_t: list[int] = []
            for j in range(n):
                val_d = res_dist[i][j]
                val_t = res_dur[i][j]
                if val_d is None or val_t is None:
                    raise InvalidRouteDataError(
                        f"Unresolved route leg between origin {i} and destination {j}"
                    )
                row_d.append(val_d)
                row_t.append(val_t)
            final_dist.append(row_d)
            final_dur.append(row_t)

        return MatrixResult(distances_meters=final_dist, durations_seconds=final_dur)

    def get_route(
        self,
        waypoints: Sequence[Coordinate],
    ) -> RouteGeometry:
        """
        Computes the turn-by-turn road route connecting ordered waypoints.
        """
        if len(waypoints) == 0:
            raise InvalidRouteDataError("get_route requires at least one waypoint")
        if len(waypoints) == 1:
            return RouteGeometry(
                points=list(waypoints),
                total_distance_meters=0,
                total_duration_seconds=0,
            )

        coords_str = ";".join(
            f"{c.longitude:.{self.coord_precision}f},{c.latitude:.{self.coord_precision}f}"
            for c in waypoints
        )
        path = f"/route/v1/{self.profile}/{coords_str}?overview=full&geometries=geojson"

        data = self._execute_get(path)

        routes = data.get("routes")
        if not isinstance(routes, list) or len(routes) == 0:
            raise RouteLookupError(f"OSRM returned no routes: {data!r}")

        primary_route = routes[0]
        if not isinstance(primary_route, dict):
            raise InvalidRouteDataError(f"OSRM route entry is invalid: {primary_route!r}")

        raw_distance = primary_route.get("distance")
        raw_duration = primary_route.get("duration")
        geometry = primary_route.get("geometry")

        if (
            not isinstance(raw_distance, (int, float))
            or not isinstance(raw_duration, (int, float))
            or not isinstance(geometry, dict)
        ):
            raise InvalidRouteDataError(f"OSRM route missing distance, duration, or geometry: {primary_route!r}")

        coordinates_list = geometry.get("coordinates")
        if not isinstance(coordinates_list, list):
            raise InvalidRouteDataError(f"OSRM route geometry missing coordinates list: {geometry!r}")

        points: list[Coordinate] = []
        for pt in coordinates_list:
            if not isinstance(pt, list) or len(pt) < 2:
                raise InvalidRouteDataError(f"OSRM geometry coordinate is malformed: {pt!r}")
            points.append(Coordinate(latitude=float(pt[1]), longitude=float(pt[0])))

        return RouteGeometry(
            points=points,
            total_distance_meters=int(round(raw_distance)),
            total_duration_seconds=int(round(raw_duration)),
        )
