"""Unit tests for OsrmRoutingAdapter and HTTP transport handling."""

import json
from typing import Any
import pytest

from engine.contracts.routing import (
    Coordinate,
    InvalidRouteDataError,
    MatrixResult,
    RoadNetworkRoutingProvider,
    RouteGeometry,
    RouteLookupError,
    RouteTimeoutError,
)
from engine.adapters.osrm_routing import (
    DefaultOsrmTransport,
    LruLegCache,
    OsrmHttpTransport,
    OsrmRoutingAdapter,
)


class FakeOsrmTransport(OsrmHttpTransport):
    """Controllable fake HTTP transport for unit testing."""

    def __init__(self) -> None:
        self.responses: dict[str, tuple[int, bytes]] = {}
        self.call_history: list[str] = []
        self.raise_on_calls: list[Exception | None] = []

    def set_response(self, path_and_query: str, status_code: int, data: dict[str, Any] | str | bytes) -> None:
        if isinstance(data, dict):
            body = json.dumps(data).encode("utf-8")
        elif isinstance(data, str):
            body = data.encode("utf-8")
        else:
            body = data
        self.responses[path_and_query] = (status_code, body)

    def get(self, path_and_query: str, timeout: float) -> tuple[int, bytes]:
        self.call_history.append(path_and_query)
        if self.raise_on_calls:
            exc = self.raise_on_calls.pop(0)
            if exc is not None:
                raise exc

        # Find matching response (exact or prefix)
        if path_and_query in self.responses:
            return self.responses[path_and_query]

        for pattern, resp in self.responses.items():
            if pattern in path_and_query:
                return resp

        # Default fallback: 404
        return 404, json.dumps({"code": "InvalidQuery", "message": "Not found in fake"}).encode("utf-8")


# Sample coordinates
C_PHL = Coordinate(latitude=39.9526, longitude=-75.1652)  # Philadelphia Center City
C_UPENN = Coordinate(latitude=39.9522, longitude=-75.1932)  # UPenn
C_TEMPLE = Coordinate(latitude=39.9800, longitude=-75.1575)  # Temple University
C_AIRPORT = Coordinate(latitude=39.8744, longitude=-75.2424)  # PHL Airport


def test_osrm_adapter_implements_provider_contract() -> None:
    transport = FakeOsrmTransport()
    adapter = OsrmRoutingAdapter(base_url="http://localhost:5000", transport=transport)
    assert isinstance(adapter, RoadNetworkRoutingProvider)


def test_get_direct_leg_same_coordinate_zero_cost_no_network() -> None:
    transport = FakeOsrmTransport()
    adapter = OsrmRoutingAdapter(transport=transport)
    dist, dur = adapter.get_direct_leg(C_PHL, C_PHL)
    assert dist == 0
    assert dur == 0
    assert len(transport.call_history) == 0


def test_get_direct_leg_cache_hit_and_miss() -> None:
    transport = FakeOsrmTransport()
    # Table response for single pair
    transport.set_response(
        "/table/v1/driving/",
        200,
        {
            "code": "Ok",
            "distances": [[2500.0]],
            "durations": [[320.0]],
        },
    )
    adapter = OsrmRoutingAdapter(transport=transport)

    # First call -> cache miss, network query
    dist1, dur1 = adapter.get_direct_leg(C_PHL, C_UPENN)
    assert dist1 == 2500
    assert dur1 == 320
    assert len(transport.call_history) == 1
    assert adapter.cache_hits == 0
    assert adapter.cache_misses == 1

    # Second call -> cache hit, no network query
    dist2, dur2 = adapter.get_direct_leg(C_PHL, C_UPENN)
    assert dist2 == 2500
    assert dur2 == 320
    assert len(transport.call_history) == 1
    assert adapter.cache_hits == 1
    assert adapter.cache_misses == 1


def test_get_direct_leg_asymmetry_preserved() -> None:
    transport = FakeOsrmTransport()
    adapter = OsrmRoutingAdapter(transport=transport)

    # Responses differ in forward vs backward direction
    transport.set_response(
        f"{C_PHL.longitude:.6f},{C_PHL.latitude:.6f};{C_UPENN.longitude:.6f},{C_UPENN.latitude:.6f}",
        200,
        {"code": "Ok", "distances": [[2500.0]], "durations": [[320.0]]},
    )
    transport.set_response(
        f"{C_UPENN.longitude:.6f},{C_UPENN.latitude:.6f};{C_PHL.longitude:.6f},{C_PHL.latitude:.6f}",
        200,
        {"code": "Ok", "distances": [[2750.0]], "durations": [[360.0]]},
    )

    d_fwd, t_fwd = adapter.get_direct_leg(C_PHL, C_UPENN)
    d_rev, t_rev = adapter.get_direct_leg(C_UPENN, C_PHL)

    assert (d_fwd, t_fwd) == (2500, 320)
    assert (d_rev, t_rev) == (2750, 360)
    assert len(transport.call_history) == 2


def test_get_direct_leg_unreachable_route_raises_lookup_error() -> None:
    transport = FakeOsrmTransport()
    # OSRM returns null when route cannot be found
    transport.set_response(
        "/table/v1/driving/",
        200,
        {
            "code": "Ok",
            "distances": [[None]],
            "durations": [[None]],
        },
    )
    adapter = OsrmRoutingAdapter(transport=transport)

    with pytest.raises(RouteLookupError, match="could not resolve route"):
        adapter.get_direct_leg(C_PHL, C_UPENN)

    assert len(transport.call_history) == 1

    # Second call should hit the negative cache and raise without issuing an HTTP query!
    with pytest.raises(RouteLookupError, match="cached failure"):
        adapter.get_direct_leg(C_PHL, C_UPENN)

    assert len(transport.call_history) == 1
    assert adapter.cache_hits == 1


def test_get_direct_leg_distinct_coords_zero_cost_raises_invalid_route_data() -> None:
    transport = FakeOsrmTransport()
    # OSRM returns 0 for distinct coordinates
    transport.set_response(
        "/table/v1/driving/",
        200,
        {
            "code": "Ok",
            "distances": [[0.0]],
            "durations": [[0.0]],
        },
    )
    adapter = OsrmRoutingAdapter(transport=transport)

    with pytest.raises(InvalidRouteDataError, match="zero distance or duration"):
        adapter.get_direct_leg(C_PHL, C_UPENN)


def test_get_direct_leg_timeout_raises_timeout_error() -> None:
    transport = FakeOsrmTransport()
    transport.raise_on_calls = [TimeoutError("Gateway timeout")]
    adapter = OsrmRoutingAdapter(transport=transport, max_retries=0)

    with pytest.raises(RouteTimeoutError, match="Gateway timeout"):
        adapter.get_direct_leg(C_PHL, C_UPENN)


def test_get_direct_leg_connection_error_raises_lookup_error() -> None:
    transport = FakeOsrmTransport()
    transport.raise_on_calls = [ConnectionRefusedError("Connection refused")]
    adapter = OsrmRoutingAdapter(transport=transport, max_retries=0)

    with pytest.raises(RouteLookupError, match="Connection refused"):
        adapter.get_direct_leg(C_PHL, C_UPENN)


def test_get_direct_leg_http_400_raises_lookup_error() -> None:
    transport = FakeOsrmTransport()
    transport.set_response(
        "/table/v1/driving/",
        400,
        {"code": "InvalidQuery", "message": "Coordinates are out of bounds"},
    )
    adapter = OsrmRoutingAdapter(transport=transport)

    with pytest.raises(RouteLookupError, match="InvalidQuery"):
        adapter.get_direct_leg(C_PHL, C_UPENN)


def test_get_direct_leg_malformed_json_raises_invalid_route_data() -> None:
    transport = FakeOsrmTransport()
    transport.set_response(
        "/table/v1/driving/",
        200,
        b"<html>Bad Gateway</html>",
    )
    adapter = OsrmRoutingAdapter(transport=transport)

    with pytest.raises(InvalidRouteDataError, match="Failed to parse OSRM JSON"):
        adapter.get_direct_leg(C_PHL, C_UPENN)


def test_get_direct_leg_retry_on_transient_failure() -> None:
    transport = FakeOsrmTransport()
    # First attempt raises ConnectionResetError, second succeeds
    transport.raise_on_calls = [
        ConnectionResetError("Socket reset"),
        None,
    ]
    transport.set_response(
        "/table/v1/driving/",
        200,
        {"code": "Ok", "distances": [[2500.0]], "durations": [[320.0]]},
    )
    adapter = OsrmRoutingAdapter(transport=transport, max_retries=1)

    dist, dur = adapter.get_direct_leg(C_PHL, C_UPENN)
    assert dist == 2500
    assert dur == 320
    assert len(transport.call_history) == 2


def test_get_distance_matrix_success_and_populates_cache() -> None:
    transport = FakeOsrmTransport()
    origins = [C_PHL, C_UPENN]
    destinations = [C_TEMPLE, C_AIRPORT]

    transport.set_response(
        "/table/v1/driving/",
        200,
        {
            "code": "Ok",
            "distances": [
                [3500.0, 14000.0],
                [4200.0, 13000.0],
            ],
            "durations": [
                [500.0, 1100.0],
                [650.0, 1000.0],
            ],
        },
    )
    adapter = OsrmRoutingAdapter(transport=transport)

    matrix = adapter.get_distance_matrix(origins, destinations)
    assert isinstance(matrix, MatrixResult)
    assert matrix.distances_meters == [
        [3500, 14000],
        [4200, 13000],
    ]
    assert matrix.durations_seconds == [
        [500, 1100],
        [650, 1000],
    ]
    assert len(transport.call_history) == 1

    # Calling get_direct_leg for (C_PHL, C_TEMPLE) should now hit the cache!
    dist, dur = adapter.get_direct_leg(C_PHL, C_TEMPLE)
    assert (dist, dur) == (3500, 500)
    assert len(transport.call_history) == 1  # No additional network call!
    assert adapter.cache_hits == 1


def test_get_distance_matrix_all_cached_no_network_call() -> None:
    transport = FakeOsrmTransport()
    adapter = OsrmRoutingAdapter(transport=transport)

    # Pre-populate cache via direct legs or earlier matrix
    transport.set_response(
        "/table/v1/driving/",
        200,
        {"code": "Ok", "distances": [[1000.0]], "durations": [[100.0]]},
    )
    adapter.get_direct_leg(C_PHL, C_UPENN)
    assert len(transport.call_history) == 1

    # Query matrix with just that pair
    matrix = adapter.get_distance_matrix([C_PHL], [C_UPENN])
    assert matrix.distances_meters == [[1000]]
    assert matrix.durations_seconds == [[100]]
    # Zero extra network calls!
    assert len(transport.call_history) == 1


def test_get_distance_matrix_chunking_when_exceeding_max_table_size() -> None:
    transport = FakeOsrmTransport()
    # Set max_table_size to 3 coordinates total
    # If 2 origins and 2 destinations (total 4 coordinates > 3), must chunk!
    origins = [C_PHL, C_UPENN]
    destinations = [C_TEMPLE, C_AIRPORT]

    adapter = OsrmRoutingAdapter(transport=transport, max_table_size=3)

    # Set responses for each sub-chunk
    # Origin 0 to destinations
    transport.set_response(
        f"{C_PHL.longitude:.6f},{C_PHL.latitude:.6f};{C_TEMPLE.longitude:.6f},{C_TEMPLE.latitude:.6f};{C_AIRPORT.longitude:.6f},{C_AIRPORT.latitude:.6f}",
        200,
        {"code": "Ok", "distances": [[3500.0, 14000.0]], "durations": [[500.0, 1100.0]]},
    )
    # Origin 1 to destinations
    transport.set_response(
        f"{C_UPENN.longitude:.6f},{C_UPENN.latitude:.6f};{C_TEMPLE.longitude:.6f},{C_TEMPLE.latitude:.6f};{C_AIRPORT.longitude:.6f},{C_AIRPORT.latitude:.6f}",
        200,
        {"code": "Ok", "distances": [[4200.0, 13000.0]], "durations": [[650.0, 1000.0]]},
    )

    matrix = adapter.get_distance_matrix(origins, destinations)
    assert matrix.distances_meters == [
        [3500, 14000],
        [4200, 13000],
    ]
    assert matrix.durations_seconds == [
        [500, 1100],
        [650, 1000],
    ]
    # Multiple calls were made due to chunking
    assert len(transport.call_history) >= 2


def test_get_distance_matrix_empty_origins_or_destinations() -> None:
    transport = FakeOsrmTransport()
    adapter = OsrmRoutingAdapter(transport=transport)

    assert adapter.get_distance_matrix([], [C_PHL]).distances_meters == []
    assert adapter.get_distance_matrix([C_PHL], []).distances_meters == [[]]
    assert len(transport.call_history) == 0


def test_get_distance_matrix_unreachable_cell_raises_lookup_error() -> None:
    transport = FakeOsrmTransport()
    transport.set_response(
        "/table/v1/driving/",
        200,
        {
            "code": "Ok",
            "distances": [[3500.0, None]],
            "durations": [[500.0, None]],
        },
    )
    adapter = OsrmRoutingAdapter(transport=transport)

    with pytest.raises(RouteLookupError, match="could not resolve route"):
        adapter.get_distance_matrix([C_PHL], [C_TEMPLE, C_AIRPORT])


def test_get_route_success() -> None:
    transport = FakeOsrmTransport()
    waypoints = [C_PHL, C_UPENN, C_AIRPORT]

    transport.set_response(
        "/route/v1/driving/",
        200,
        {
            "code": "Ok",
            "routes": [
                {
                    "distance": 16500.4,
                    "duration": 1420.8,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [-75.1652, 39.9526],
                            [-75.1700, 39.9530],
                            [-75.1932, 39.9522],
                            [-75.2424, 39.8744],
                        ],
                    },
                }
            ],
            "waypoints": [],
        },
    )
    adapter = OsrmRoutingAdapter(transport=transport)

    route = adapter.get_route(waypoints)
    assert isinstance(route, RouteGeometry)
    assert route.total_distance_meters == 16500
    assert route.total_duration_seconds == 1421
    assert len(route.points) == 4
    assert route.points[0] == Coordinate(latitude=39.9526, longitude=-75.1652)
    assert route.points[-1] == Coordinate(latitude=39.8744, longitude=-75.2424)


def test_get_route_empty_or_single_waypoint() -> None:
    transport = FakeOsrmTransport()
    adapter = OsrmRoutingAdapter(transport=transport)

    with pytest.raises(InvalidRouteDataError, match="requires at least one"):
        adapter.get_route([])

    single = adapter.get_route([C_PHL])
    assert single.total_distance_meters == 0
    assert single.total_duration_seconds == 0
    assert single.points == [C_PHL]
    assert len(transport.call_history) == 0


def test_get_route_no_route_raises_lookup_error() -> None:
    transport = FakeOsrmTransport()
    transport.set_response(
        "/route/v1/driving/",
        200,
        {
            "code": "NoRoute",
            "message": "Impossible route",
        },
    )
    adapter = OsrmRoutingAdapter(transport=transport)

    with pytest.raises(RouteLookupError, match="NoRoute"):
        adapter.get_route([C_PHL, C_AIRPORT])


def test_lru_cache_eviction_when_exceeding_maxsize() -> None:
    transport = FakeOsrmTransport()
    transport.set_response(
        "/table/v1/driving/",
        200,
        {"code": "Ok", "distances": [[1000.0]], "durations": [[100.0]]},
    )
    # Cache maxsize = 2
    adapter = OsrmRoutingAdapter(transport=transport, cache_maxsize=2)

    # Insert 1: (C_PHL, C_UPENN)
    adapter.get_direct_leg(C_PHL, C_UPENN)
    # Insert 2: (C_PHL, C_TEMPLE)
    adapter.get_direct_leg(C_PHL, C_TEMPLE)
    assert len(adapter.cache) == 2

    # Insert 3: (C_PHL, C_AIRPORT) -> evicts oldest (C_PHL, C_UPENN)
    adapter.get_direct_leg(C_PHL, C_AIRPORT)
    assert len(adapter.cache) == 2

    # (C_PHL, C_TEMPLE) should still be in cache
    adapter.get_direct_leg(C_PHL, C_TEMPLE)
    # (C_PHL, C_UPENN) was evicted, so accessing it causes a new network call
    history_len_before = len(transport.call_history)
    adapter.get_direct_leg(C_PHL, C_UPENN)
    assert len(transport.call_history) == history_len_before + 1


def test_osrm_adapter_dispatch_engine_integration() -> None:
    """Verifies that DispatchEngine successfully dispatches with OsrmRoutingAdapter."""
    from engine.adapters.default_policy import DefaultPolicyProvider
    from engine.adapters.h3_spatial import H3SpatialIndexAdapter
    from engine.dispatch import DispatchEngine
    from engine.domain.enums import RequestStatus
    from engine.domain.models import GeoCoordinate, RideRequest, Vehicle

    transport = FakeOsrmTransport()
    # Provide canned table responses for coordinates
    transport.set_response(
        "/table/v1/driving/",
        200,
        {
            "code": "Ok",
            "distances": [[1500.0]],
            "durations": [[200.0]],
        },
    )

    adapter = OsrmRoutingAdapter(transport=transport)
    engine = DispatchEngine(
        policy_provider=DefaultPolicyProvider(),
        routing_provider=adapter,
        spatial_index=H3SpatialIndexAdapter(),
    )

    req = RideRequest(
        request_id="req-1",
        user_id="user-1",
        pickup_location=GeoCoordinate(latitude=39.9526, longitude=-75.1652),
        dropoff_location=GeoCoordinate(latitude=39.9522, longitude=-75.1932),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=2500,
        direct_distance_meters=1500,
        direct_duration_seconds=200,
        status=RequestStatus.PENDING,
    )
    veh = Vehicle(
        vehicle_id="veh-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=39.9525, longitude=-75.1650),
        is_active=True,
    )

    result = engine.dispatch_batch(
        requests=[req],
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
        batch_id="osrm-batch-1",
    )

    assert result.batch_id == "osrm-batch-1"
    assert len(result.selected_assignments) == 1
    assert "req-1" in result.selected_assignments[0].request_ids
    assert len(result.unassigned_request_ids) == 0
    assert len(transport.call_history) > 0
    assert adapter.cache_hits > 0 or adapter.cache_misses > 0


def test_osrm_adapter_concurrent_access() -> None:
    """Verifies thread-safety of OsrmRoutingAdapter across concurrent threads."""
    import concurrent.futures

    transport = FakeOsrmTransport()
    transport.set_response(
        "/table/v1/driving/",
        200,
        {"code": "Ok", "distances": [[2000.0]], "durations": [[250.0]]},
    )
    adapter = OsrmRoutingAdapter(transport=transport)

    def query(worker_id: int) -> tuple[int, int]:
        c1 = Coordinate(latitude=39.9526 + worker_id * 0.0001, longitude=-75.1652)
        c2 = Coordinate(latitude=39.9522, longitude=-75.1932)
        return adapter.get_direct_leg(c1, c2)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(query, i % 5) for i in range(40)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 40
    assert all(r == (2000, 250) for r in results)
    assert len(adapter.cache) <= 5
    assert adapter.cache_hits > 0


def test_default_osrm_transport_url_parsing_and_close() -> None:
    """Verifies DefaultOsrmTransport parses endpoints properly and handles close."""
    transport = DefaultOsrmTransport(base_url="https://osrm.example.com:8443/v1")
    assert transport.scheme == "https"
    assert transport.host == "osrm.example.com"
    assert transport.port == 8443
    assert transport.path_prefix == "/v1"

    # Close should not raise even if connection was never opened
    transport.close()


def test_default_osrm_transport_normalizes_localhost_to_ipv4() -> None:
    """Verifies DefaultOsrmTransport converts 'localhost' to '127.0.0.1' to avoid Windows IPv6 probe lag."""
    transport = DefaultOsrmTransport(base_url="http://localhost:5000")
    assert transport.host == "127.0.0.1"
    assert transport.port == 5000

    transport_ip = DefaultOsrmTransport(base_url="http://127.0.0.1:5000")
    assert transport_ip.host == "127.0.0.1"


def test_osrm_adapter_prefetch_matrix_success() -> None:
    """Verifies prefetch_matrix populates cache with valid legs without raising."""
    transport = FakeOsrmTransport()
    transport.set_response(
        "/table/v1/driving/",
        200,
        {
            "code": "Ok",
            "distances": [[0.0, 1500.0], [1400.0, 0.0]],
            "durations": [[0.0, 180.0], [170.0, 0.0]],
        },
    )
    adapter = OsrmRoutingAdapter(transport=transport)
    assert len(adapter.cache) == 0

    cached = adapter.prefetch_matrix(origins=[C_PHL, C_UPENN])
    assert cached == 4  # All 4 pairwise combinations (including zero-cost diagonals)
    assert len(adapter.cache) == 4

    # Subsequent direct leg lookup hits cache without network call
    call_count_before = len(transport.call_history)
    dist, dur = adapter.get_direct_leg(C_PHL, C_UPENN)
    assert dist == 1500
    assert dur == 180
    assert len(transport.call_history) == call_count_before


def test_osrm_adapter_prefetch_matrix_skips_when_already_cached() -> None:
    """Verifies prefetch_matrix skips network calls when coordinates are already in cache."""
    transport = FakeOsrmTransport()
    transport.set_response(
        "/table/v1/driving/",
        200,
        {
            "code": "Ok",
            "distances": [[0.0, 1500.0], [1400.0, 0.0]],
            "durations": [[0.0, 180.0], [170.0, 0.0]],
        },
    )
    adapter = OsrmRoutingAdapter(transport=transport)
    adapter.prefetch_matrix(origins=[C_PHL, C_UPENN])
    initial_calls = len(transport.call_history)

    # Calling prefetch again with the same coordinates should not issue new network requests
    adapter.prefetch_matrix(origins=[C_PHL, C_UPENN])
    assert len(transport.call_history) == initial_calls


def test_osrm_adapter_prefetch_matrix_negative_caching_and_no_exception() -> None:
    """Verifies prefetch_matrix caches unroutable pairs as None without raising."""
    transport = FakeOsrmTransport()
    transport.set_response(
        "/table/v1/driving/",
        200,
        {
            "code": "Ok",
            "distances": [[0.0, None]],
            "durations": [[0.0, None]],
        },
    )
    adapter = OsrmRoutingAdapter(transport=transport)
    cached = adapter.prefetch_matrix(origins=[C_PHL], destinations=[C_UPENN])
    assert cached == 0

    # The unroutable pair should be in cache as None (negative cached)
    hit, val = adapter._cache.lookup(adapter._cache_key(C_PHL, C_UPENN))
    assert hit is True
    assert val is None


def test_osrm_adapter_prefetch_matrix_respects_deadline() -> None:
    """Verifies prefetch_matrix exits early when deadline is exceeded."""
    import time

    transport = FakeOsrmTransport()
    adapter = OsrmRoutingAdapter(transport=transport)

    # Expired deadline
    cached = adapter.prefetch_matrix(
        origins=[C_PHL, C_UPENN],
        deadline=time.monotonic() - 1.0,
    )
    assert cached == 0
    assert len(transport.call_history) == 0


def test_osrm_adapter_get_distance_matrix_caches_valid_legs_before_raising() -> None:
    """Verifies get_distance_matrix caches all valid legs even when unroutable pairs cause RouteLookupError."""
    transport = FakeOsrmTransport()
    transport.set_response(
        "/table/v1/driving/",
        200,
        {
            "code": "Ok",
            "distances": [[0.0, 1200.0], [None, 0.0]],
            "durations": [[0.0, 150.0], [None, 0.0]],
        },
    )
    adapter = OsrmRoutingAdapter(transport=transport)
    with pytest.raises(RouteLookupError) as exc_info:
        adapter.get_distance_matrix(origins=[C_PHL, C_UPENN], destinations=[C_PHL, C_UPENN])

    assert "OSRM could not resolve route" in str(exc_info.value)
    # Valid leg (C_PHL -> C_UPENN) should be cached despite the error on (C_UPENN -> C_PHL)
    hit, val = adapter._cache.lookup(adapter._cache_key(C_PHL, C_UPENN))
    assert hit is True
    assert val == (1200, 150)


def test_lru_cache_get_missing_and_set_many() -> None:
    """Verifies get_missing and set_many on LruLegCache operate correctly under lock."""
    cache = LruLegCache(maxsize=5)
    k1 = (40.1, -74.1, 40.2, -74.2)
    k2 = (40.2, -74.2, 40.3, -74.3)
    k3 = (40.3, -74.3, 40.4, -74.4)

    # Initially all missing
    missing = cache.get_missing([k1, k2, k3])
    assert missing == [k1, k2, k3]

    # set_many inserts atomically
    cache.set_many({k1: (1000, 100), k2: (2000, 200)})
    assert len(cache) == 2

    missing_after = cache.get_missing([k1, k2, k3])
    assert missing_after == [k3]

    hit1, val1 = cache.lookup(k1)
    assert hit1 is True
    assert val1 == (1000, 100)


def test_prefetch_matrix_chunking_across_max_table_size() -> None:
    """Verifies prefetch_matrix correctly chunks requests when origins exceed max_table_size."""
    transport = FakeOsrmTransport()
    # 6 coordinates with max_table_size = 4 -> chunks of 4 and 2
    coords = [
        Coordinate(latitude=40.7100 + i * 0.01, longitude=-74.0000)
        for i in range(6)
    ]

    transport.set_response(
        "/table/v1/driving/",
        200,
        {
            "code": "Ok",
            "distances": [[1000.0] * 4 for _ in range(4)],
            "durations": [[100.0] * 4 for _ in range(4)],
        },
    )

    adapter = OsrmRoutingAdapter(transport=transport, max_table_size=4)
    cached = adapter.prefetch_matrix(origins=coords)

    # 6x6 = 36 pairwise legs, chunked across 4 subqueries
    assert cached > 0
    assert len(transport.call_history) > 1

    # Verify legs are cached
    key = adapter._cache_key(coords[0], coords[1])
    hit, val = adapter._cache.lookup(key)
    assert hit is True
    assert val == (1000, 100)


def test_prefetch_matrix_compact_url_when_same_endpoints() -> None:
    """Verifies prefetch_matrix generates compact URL without duplicate coordinates when origins == destinations."""
    transport = FakeOsrmTransport()
    transport.set_response(
        "/table/v1/driving/",
        200,
        {
            "code": "Ok",
            "distances": [[0.0, 1200.0], [1200.0, 0.0]],
            "durations": [[0.0, 150.0], [150.0, 0.0]],
        },
    )
    adapter = OsrmRoutingAdapter(transport=transport)
    adapter.prefetch_matrix(origins=[C_PHL, C_UPENN])

    assert len(transport.call_history) == 1
    url = transport.call_history[0]
    # Should NOT have sources or destinations parameter
    assert "sources=" not in url
    assert "destinations=" not in url
    # Should only list each coordinate once
    assert url.count("-75.165200,39.952600") == 1
    assert url.count("-75.193200,39.952200") == 1


def test_default_osrm_transport_pool_checkout_reuse_and_close(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies connection reuse, pool tracking, and cleanup on close."""
    import http.client
    from unittest.mock import MagicMock

    mock_conns: list[MagicMock] = []

    def mock_create_conn(*args: Any, **kwargs: Any) -> MagicMock:
        conn = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"code":"Ok"}'
        conn.getresponse.return_value = mock_resp
        mock_conns.append(conn)
        return conn

    monkeypatch.setattr(http.client, "HTTPConnection", mock_create_conn)

    transport = DefaultOsrmTransport(base_url="http://127.0.0.1:5000", max_connections=2)
    assert transport._total_created == 0

    # First request creates connection 1
    status1, body1 = transport.get("/test", timeout=1.0)
    assert status1 == 200
    assert transport._total_created == 1
    assert len(mock_conns) == 1

    # Second request reuses connection 1 from pool
    status2, body2 = transport.get("/test", timeout=1.0)
    assert status2 == 200
    assert transport._total_created == 1
    assert len(mock_conns) == 1

    # Close transport closes all connections and sets closed state
    transport.close()
    assert transport._closed is True
    mock_conns[0].close.assert_called_once()

    # Further get calls raise ConnectionError
    with pytest.raises(ConnectionError, match="closed"):
        transport.get("/test", timeout=1.0)


def test_default_osrm_transport_reconnects_on_stale_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that stale or dropped connections are closed and retried with a fresh connection."""
    import http.client
    from unittest.mock import MagicMock

    stale_conn = MagicMock()
    stale_conn.request.side_effect = http.client.RemoteDisconnected("Connection closed by peer")

    fresh_conn = MagicMock()
    fresh_resp = MagicMock()
    fresh_resp.status = 200
    fresh_resp.read.return_value = b'{"code":"Ok"}'
    fresh_conn.getresponse.return_value = fresh_resp

    conns = [stale_conn, fresh_conn]

    def mock_create_conn(*args: Any, **kwargs: Any) -> MagicMock:
        return conns.pop(0)

    monkeypatch.setattr(http.client, "HTTPConnection", mock_create_conn)

    transport = DefaultOsrmTransport(base_url="http://127.0.0.1:5000", max_connections=2)
    status, body = transport.get("/retry-test", timeout=1.0)
    assert status == 200
    assert body == b'{"code":"Ok"}'
    stale_conn.close.assert_called_once()
    transport.close()


def test_prefetch_matrices_concurrent_and_deduplicated() -> None:
    """Verifies concurrent prefetching across multiple waypoint groups with deduplication."""
    import time
    transport = FakeOsrmTransport()

    # Coordinate groups
    c1 = Coordinate(latitude=40.71, longitude=-74.01)
    c2 = Coordinate(latitude=40.72, longitude=-74.02)
    c3 = Coordinate(latitude=40.73, longitude=-74.03)
    c4 = Coordinate(latitude=40.74, longitude=-74.04)

    group_a = [c1, c2]
    group_b = [c3, c4]
    group_a_dup = [c2, c1]  # Same coordinates, reversed order

    transport.set_response(
        "/table/v1/driving/",
        200,
        {
            "code": "Ok",
            "distances": [[0.0, 1500.0], [1500.0, 0.0]],
            "durations": [[0.0, 120.0], [120.0, 0.0]],
        },
    )

    adapter = OsrmRoutingAdapter(transport=transport, max_workers=4)
    cached = adapter.prefetch_matrices(groups=[group_a, group_b, group_a_dup])

    # Should have executed for group_a and group_b, but deduplicated group_a_dup
    assert cached > 0
    assert len(transport.call_history) == 2

    # Verify keys are in cache
    hit, val = adapter._cache.lookup(adapter._cache_key(c1, c2))
    assert hit is True
    assert val == (1500, 120)

    hit_b, val_b = adapter._cache.lookup(adapter._cache_key(c3, c4))
    assert hit_b is True
    assert val_b == (1500, 120)

    adapter.close()


def test_prefetch_matrices_skips_fully_cached_groups() -> None:
    """Verifies that prefetch_matrices does not issue requests for groups already in cache."""
    transport = FakeOsrmTransport()
    c1 = Coordinate(latitude=40.71, longitude=-74.01)
    c2 = Coordinate(latitude=40.72, longitude=-74.02)

    adapter = OsrmRoutingAdapter(transport=transport, max_workers=2)
    # Pre-populate cache
    adapter._cache.set(adapter._cache_key(c1, c2), (1000, 100))
    adapter._cache.set(adapter._cache_key(c2, c1), (1000, 100))

    cached = adapter.prefetch_matrices(groups=[[c1, c2]])
    assert cached == 0
    assert len(transport.call_history) == 0
    adapter.close()


def test_prefetch_matrices_deadline_budget_respected() -> None:
    """Verifies that prefetch_matrices stops or cancels tasks if deadline is exceeded."""
    import time

    class SlowTransport(OsrmHttpTransport):
        def get(self, path_and_query: str, timeout: float) -> tuple[int, bytes]:
            time.sleep(0.1)
            return 200, b'{"code":"Ok","distances":[[0.0, 100.0],[100.0, 0.0]],"durations":[[0.0, 10.0],[10.0, 0.0]]}'

    adapter = OsrmRoutingAdapter(transport=SlowTransport(), max_workers=2)
    c1 = Coordinate(latitude=40.71, longitude=-74.01)
    c2 = Coordinate(latitude=40.72, longitude=-74.02)

    # Deadline already in the past
    cached = adapter.prefetch_matrices(
        groups=[[c1, c2]],
        deadline=time.monotonic() - 1.0,
        reserved_headroom=0.05,
    )
    assert cached == 0
    adapter.close()


def test_road_network_routing_provider_base_prefetch_matrices() -> None:
    """Verifies the base class contract implementation of prefetch_matrices."""
    from typing import Sequence
    from engine.contracts.routing import RoadNetworkRoutingProvider

    class MinimalRouter(RoadNetworkRoutingProvider):
        def __init__(self) -> None:
            self.prefetched_groups: list[Sequence[Coordinate]] = []

        def get_distance_matrix(self, origins: Sequence[Coordinate], destinations: Sequence[Coordinate]) -> MatrixResult:
            return MatrixResult(distances_meters=[], durations_seconds=[])

        def get_route(self, waypoints: Sequence[Coordinate]) -> RouteGeometry:
            return RouteGeometry(points=list(waypoints), total_distance_meters=0, total_duration_seconds=0)

        def get_direct_leg(self, origin: Coordinate, destination: Coordinate) -> tuple[int, int]:
            return (1000, 100)

        def prefetch_matrix(
            self,
            origins: Sequence[Coordinate],
            destinations: Sequence[Coordinate] | None = None,
            deadline: float | None = None,
            reserved_headroom: float = 0.050,
        ) -> int:
            self.prefetched_groups.append(origins)
            return len(origins)

    router = MinimalRouter()
    c1 = Coordinate(latitude=40.71, longitude=-74.01)
    c2 = Coordinate(latitude=40.72, longitude=-74.02)
    c3 = Coordinate(latitude=40.73, longitude=-74.03)

    count = router.prefetch_matrices(groups=[[c1, c2], [c2, c3]])
    assert count == 4
    assert len(router.prefetched_groups) == 2

