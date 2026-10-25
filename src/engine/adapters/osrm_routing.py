"""Production road-network routing adapter for OSRM (Open Source Routing Machine)."""

from abc import ABC, abstractmethod
from collections import OrderedDict
import concurrent.futures
import http.client
import json
import math
import queue
import threading
import time
from typing import Any, Mapping, Sequence
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
    Standard HTTP transport for OSRM with bounded Keep-Alive connection pooling
    and automatic reconnection.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:5000",
        max_connections: int = 8,
    ) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        self.scheme = parsed.scheme.lower() if parsed.scheme else "http"
        host = parsed.hostname or "localhost"
        # Windows IPv6 resolution for "localhost" introduces a 2-second connection delay
        # when daemon binds to IPv4. Normalize to 127.0.0.1 for instant loopback connections.
        self.host = "127.0.0.1" if host == "localhost" else host
        self.port = parsed.port or (443 if self.scheme == "https" else 80)
        self.path_prefix = parsed.path.rstrip("/")
        self.max_connections = max(1, max_connections)
        self._pool: queue.LifoQueue[http.client.HTTPConnection | http.client.HTTPSConnection] = queue.LifoQueue(
            maxsize=self.max_connections
        )
        self._total_created = 0
        self._pool_lock = threading.Lock()
        self._closed = False

    def _create_raw_connection(self, timeout: float) -> http.client.HTTPConnection | http.client.HTTPSConnection:
        if self.scheme == "https":
            return http.client.HTTPSConnection(self.host, self.port, timeout=timeout)
        return http.client.HTTPConnection(self.host, self.port, timeout=timeout)

    def _get_connection(self, timeout: float) -> http.client.HTTPConnection | http.client.HTTPSConnection:
        if self._closed:
            raise ConnectionError("DefaultOsrmTransport is closed")
        try:
            conn = self._pool.get_nowait()
            conn.timeout = timeout
            return conn
        except queue.Empty:
            with self._pool_lock:
                if self._closed:
                    raise ConnectionError("DefaultOsrmTransport is closed")
                if self._total_created < self.max_connections:
                    self._total_created += 1
                    return self._create_raw_connection(timeout)
            try:
                conn = self._pool.get(timeout=timeout)
                conn.timeout = timeout
                return conn
            except queue.Empty:
                raise TimeoutError(f"Connection pool exhausted (max={self.max_connections}) after {timeout}s")

    def _put_connection(
        self,
        conn: http.client.HTTPConnection | http.client.HTTPSConnection,
        healthy: bool = True,
    ) -> None:
        if self._closed or not healthy:
            try:
                conn.close()
            except Exception:
                pass
            with self._pool_lock:
                self._total_created = max(0, self._total_created - 1)
            return

        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            try:
                conn.close()
            except Exception:
                pass
            with self._pool_lock:
                self._total_created = max(0, self._total_created - 1)

    def get(self, path_and_query: str, timeout: float) -> tuple[int, bytes]:
        full_path = self.path_prefix + (path_and_query if path_and_query.startswith("/") else "/" + path_and_query)
        headers = {"Accept": "application/json", "User-Agent": "PoolEngine-OSRM/1.0"}

        for attempt in range(2):
            conn = self._get_connection(timeout)
            healthy = False
            try:
                conn.request("GET", full_path, headers=headers)
                resp = conn.getresponse()
                body = resp.read()
                healthy = True
                return resp.status, body
            except (
                http.client.RemoteDisconnected,
                http.client.CannotSendRequest,
                BrokenPipeError,
                ConnectionResetError,
            ):
                healthy = False
                if attempt == 0:
                    continue
                raise
            finally:
                self._put_connection(conn, healthy=healthy)

        raise RuntimeError("Unexpected transport loop termination")

    def close(self) -> None:
        with self._pool_lock:
            self._closed = True
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except Exception:
                pass
        with self._pool_lock:
            self._total_created = 0


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

    def get_missing(
        self, keys: Sequence[tuple[float, float, float, float]]
    ) -> list[tuple[float, float, float, float]]:
        """Returns the sublist of keys that are not present in the cache."""
        with self._lock:
            return [k for k in keys if k not in self._data]

    def set_many(
        self, items: Mapping[tuple[float, float, float, float], tuple[int, int] | None]
    ) -> None:
        """Batch inserts items into the cache under a single lock acquisition."""
        with self._lock:
            for key, value in items.items():
                self._data[key] = value
                self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
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
        max_workers: int = 8,
        transport: OsrmHttpTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.profile = profile
        self.timeout_seconds = max(0.01, timeout_seconds)
        self.max_retries = max(0, max_retries)
        self.max_table_size = max(2, max_table_size)
        self.coord_precision = coord_precision
        self.max_workers = max(1, max_workers)
        self._cache = LruLegCache(maxsize=cache_maxsize)
        self.transport = (
            transport
            if transport is not None
            else DefaultOsrmTransport(base_url=self.base_url, max_connections=self.max_workers)
        )
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._executor_lock = threading.Lock()

    def _get_executor(self) -> concurrent.futures.ThreadPoolExecutor:
        with self._executor_lock:
            if self._executor is None:
                self._executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=self.max_workers,
                    thread_name_prefix="poolengine-osrm-prefetch",
                )
            return self._executor

    def close(self) -> None:
        """Closes thread pool and transport connections."""
        with self._executor_lock:
            if self._executor is not None:
                self._executor.shutdown(wait=False, cancel_futures=True)
                self._executor = None
        self.transport.close()

    def __enter__(self) -> "OsrmRoutingAdapter":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

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

    def check_health(self) -> bool:
        """
        Lightweight connectivity probe verifying OSRM routing backend is reachable.
        Returns True if backend is healthy, False if unreachable or timed out.
        """
        try:
            status, _ = self.transport.get(
                f"/nearest/v1/{self.profile}/-73.985130,40.758896?number=1",
                self.timeout_seconds,
            )
            return status in (200, 400)
        except Exception:
            return False

    def _cache_key(self, origin: Coordinate, destination: Coordinate) -> tuple[float, float, float, float]:
        if self.coord_precision == 6:
            return (
                origin.latitude,
                origin.longitude,
                destination.latitude,
                destination.longitude,
            )
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
        unresolved_pairs: list[tuple[Coordinate, Coordinate]] = []

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
                        key = self._cache_key(orig, dest)

                        if raw_dist is None or raw_dur is None:
                            self._cache.set(key, None)
                            unresolved_pairs.append((orig, dest))
                            continue

                        try:
                            validated = validate_route_leg(orig, dest, (raw_dist, raw_dur))
                            res_dist[o_start + r][d_start + c] = validated[0]
                            res_dur[o_start + r][d_start + c] = validated[1]
                            self._cache.set(key, validated)
                        except InvalidRouteDataError:
                            self._cache.set(key, None)
                            unresolved_pairs.append((orig, dest))

        if unresolved_pairs:
            first_orig, first_dest = unresolved_pairs[0]
            raise RouteLookupError(
                f"OSRM could not resolve route from ({first_orig.latitude}, {first_orig.longitude}) "
                f"to ({first_dest.latitude}, {first_dest.longitude})"
            )

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

    def prefetch_matrix(
        self,
        origins: Sequence[Coordinate],
        destinations: Sequence[Coordinate] | None = None,
        deadline: float | None = None,
        reserved_headroom: float = 0.050,
    ) -> int:
        """
        Prefetches pairwise distance and duration matrix from OSRM table service
        and populates the internal cache. Handles chunking, deduplication, and
        never raises if individual cells cannot be routed.
        Returns the count of new valid legs cached.
        """
        same_endpoints = (destinations is None or destinations is origins or destinations == origins)
        if destinations is None:
            destinations = origins
        m = len(origins)
        n = len(destinations)
        if m == 0 or n == 0:
            return 0

        if deadline is not None and time.monotonic() > deadline - reserved_headroom:
            return 0

        max_origins_per_chunk = max(1, self.max_table_size // (1 if same_endpoints else 2))
        max_dest_per_chunk = (
            max_origins_per_chunk if same_endpoints else max(1, self.max_table_size - max_origins_per_chunk)
        )
        cached_count = 0

        for o_start in range(0, m, max_origins_per_chunk):
            if deadline is not None and time.monotonic() > deadline - reserved_headroom:
                break
            o_end = min(m, o_start + max_origins_per_chunk)
            chunk_origins = origins[o_start:o_end]

            for d_start in range(0, n, max_dest_per_chunk):
                if deadline is not None and time.monotonic() > deadline - reserved_headroom:
                    break
                d_end = min(n, d_start + max_dest_per_chunk)
                chunk_destinations = destinations[d_start:d_end]

                chunk_same = (same_endpoints and o_start == d_start and o_end == d_end)
                keys = [
                    self._cache_key(o, d)
                    for o in chunk_origins
                    for d in chunk_destinations
                    if (o.latitude, o.longitude) != (d.latitude, d.longitude)
                ]
                missing = self._cache.get_missing(keys)
                if not missing:
                    continue

                if chunk_same:
                    coords_str = ";".join(
                        f"{c.longitude:.{self.coord_precision}f},{c.latitude:.{self.coord_precision}f}"
                        for c in chunk_origins
                    )
                    path = f"/table/v1/{self.profile}/{coords_str}?annotations=duration,distance"
                else:
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

                try:
                    data = self._execute_get(path)
                except Exception:
                    continue

                distances = data.get("distances")
                durations = data.get("durations")
                if not isinstance(distances, list) or not isinstance(durations, list):
                    continue

                batch_to_set: dict[tuple[float, float, float, float], tuple[int, int] | None] = {}
                for r, orig in enumerate(chunk_origins):
                    if r >= len(distances) or not isinstance(distances[r], list):
                        continue
                    row_dist = distances[r]
                    row_dur = durations[r]
                    for c, dest in enumerate(chunk_destinations):
                        if c >= len(row_dist):
                            continue
                        raw_dist = row_dist[c]
                        raw_dur = row_dur[c]
                        key = self._cache_key(orig, dest)
                        if raw_dist is None or raw_dur is None:
                            batch_to_set[key] = None
                            continue
                        try:
                            val = validate_route_leg(orig, dest, (raw_dist, raw_dur))
                            batch_to_set[key] = val
                            cached_count += 1
                        except InvalidRouteDataError:
                            batch_to_set[key] = None

                if batch_to_set:
                    self._cache.set_many(batch_to_set)

        return cached_count

    def prefetch_matrices(
        self,
        groups: Sequence[Sequence[Coordinate]],
        deadline: float | None = None,
        reserved_headroom: float = 0.050,
    ) -> int:
        """
        Prefetches pairwise distance and duration matrices for multiple waypoint groups
        concurrently using bounded worker threads and pooled HTTP connections.
        Handles deduplication, missing key detection, and negative caching.
        Returns the count of new valid legs cached.
        """
        if not groups:
            return 0
        if deadline is not None and time.monotonic() > deadline - reserved_headroom:
            return 0

        # Filter and deduplicate groups that actually have missing keys
        needed_groups: list[Sequence[Coordinate]] = []
        seen_group_coords: set[tuple[tuple[float, float], ...]] = set()

        for group in groups:
            if len(group) < 2:
                continue
            # Deduplicate groups with identical coordinate sets (prevent duplicate in-flight requests)
            group_key = tuple(sorted(set((c.latitude, c.longitude) for c in group)))
            if group_key in seen_group_coords:
                continue
            seen_group_coords.add(group_key)

            # Check if all legs in this group are already in cache (excluding self-to-self)
            keys = [
                self._cache_key(o, d)
                for o in group
                for d in group
                if (o.latitude, o.longitude) != (d.latitude, d.longitude)
            ]
            missing = self._cache.get_missing(keys)
            if missing:
                needed_groups.append(group)

        if not needed_groups:
            return 0

        # If only 1 group or max_workers <= 1, execute sequentially
        if len(needed_groups) == 1 or self.max_workers <= 1:
            total = 0
            for g in needed_groups:
                if deadline is not None and time.monotonic() > deadline - reserved_headroom:
                    break
                total += self.prefetch_matrix(
                    origins=g,
                    destinations=g,
                    deadline=deadline,
                    reserved_headroom=reserved_headroom,
                )
            return total

        # Concurrent execution with bounded worker pool
        executor = self._get_executor()

        def _fetch_group(grp: Sequence[Coordinate]) -> int:
            if deadline is not None and time.monotonic() > deadline - reserved_headroom:
                return 0
            return self.prefetch_matrix(
                origins=grp,
                destinations=grp,
                deadline=deadline,
                reserved_headroom=reserved_headroom,
            )

        timeout = (
            max(0.001, (deadline - reserved_headroom) - time.monotonic())
            if deadline is not None
            else None
        )

        futures = [executor.submit(_fetch_group, g) for g in needed_groups]
        done, not_done = concurrent.futures.wait(
            futures,
            timeout=timeout,
            return_when=concurrent.futures.ALL_COMPLETED,
        )

        total_cached = 0
        for f in done:
            try:
                total_cached += f.result()
            except Exception:
                pass

        # Cancel any pending futures that did not complete within the deadline
        for f in not_done:
            f.cancel()

        return total_cached

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
