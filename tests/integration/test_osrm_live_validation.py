"""Live OSRM integration tests against real road-network data."""

import os
import time
import urllib.parse
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.osrm_routing import DefaultOsrmTransport, OsrmRoutingAdapter
from engine.contracts.routing import Coordinate, RouteLookupError, RouteTimeoutError
from engine.dispatch import DispatchEngine
from engine.domain.enums import RequestStatus, SearchStatus
from engine.domain.models import GeoCoordinate, RideRequest, Vehicle


# Keep public endpoint correctness tests separate from local benchmark endpoint
LIVE_OSRM_URL = os.environ.get("OSRM_PUBLIC_URL", "http://router.project-osrm.org")


def _is_live_server_available(base_url: str) -> bool:
    try:
        transport = DefaultOsrmTransport(base_url=base_url)
        # Probe coordinates in NYC
        path = "/table/v1/driving/-74.0060,40.7128;-73.9855,40.7580?sources=0&destinations=1&annotations=duration,distance"
        status, body = transport.get(path, timeout=5.0)
        transport.close()
        return status == 200 and b'"code":"Ok"' in body
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _is_live_server_available(LIVE_OSRM_URL),
    reason=f"Live OSRM server not reachable at {LIVE_OSRM_URL}",
)


# Real Manhattan landmarks
C_EMPIRE_STATE = Coordinate(latitude=40.7484, longitude=-73.9857)  # 5th Ave & 34th St
C_NY_LIBRARY = Coordinate(latitude=40.7527, longitude=-73.9818)  # 5th Ave & 42nd St
C_TIMES_SQUARE = Coordinate(latitude=40.7580, longitude=-73.9855)  # Broadway & 45th St
C_DOWNTOWN = Coordinate(latitude=40.7128, longitude=-74.0060)  # Financial District
C_OCEAN = Coordinate(latitude=35.0000, longitude=-40.0000)  # Mid-Atlantic Ocean (no road route)


def test_live_nearby_road_route() -> None:
    """Verifies direct leg between nearby points on real road network."""
    adapter = OsrmRoutingAdapter(base_url=LIVE_OSRM_URL, timeout_seconds=10.0)
    dist, dur = adapter.get_direct_leg(C_EMPIRE_STATE, C_NY_LIBRARY)

    assert dist > 0
    assert dur > 0
    # Road distance from 34th to 42nd is between 500m and 3500m depending on one-way loops
    assert 500 <= dist <= 4000
    assert 30 <= dur <= 1200


def test_live_asymmetric_routes() -> None:
    """Verifies that directional one-way street asymmetry is preserved by real road network."""
    adapter = OsrmRoutingAdapter(base_url=LIVE_OSRM_URL, timeout_seconds=10.0)

    # 5th Ave runs southbound; travelling north requires looping onto Madison Ave or 6th Ave
    dist_north, dur_north = adapter.get_direct_leg(C_EMPIRE_STATE, C_NY_LIBRARY)
    dist_south, dur_south = adapter.get_direct_leg(C_NY_LIBRARY, C_EMPIRE_STATE)

    assert dist_north > 0
    assert dist_south > 0
    # Because of one-way streets, forward and reverse paths are physically different
    assert (dist_north, dur_north) != (dist_south, dur_south)


def test_live_barrier_unreachable_route() -> None:
    """Verifies that disconnected / ocean coordinates raise RouteLookupError."""
    adapter = OsrmRoutingAdapter(base_url=LIVE_OSRM_URL, timeout_seconds=10.0)

    with pytest.raises(RouteLookupError):
        adapter.get_direct_leg(C_EMPIRE_STATE, C_OCEAN)


def test_live_matrix_requests_and_chunking() -> None:
    """Verifies batched matrix queries with max_table_size chunking against live OSRM."""
    adapter = OsrmRoutingAdapter(base_url=LIVE_OSRM_URL, timeout_seconds=10.0, max_table_size=4)
    origins = [C_DOWNTOWN, C_EMPIRE_STATE]
    destinations = [C_NY_LIBRARY, C_TIMES_SQUARE]

    matrix = adapter.get_distance_matrix(origins, destinations)

    assert len(matrix.distances_meters) == 2
    assert len(matrix.durations_seconds) == 2
    assert len(matrix.distances_meters[0]) == 2
    assert len(matrix.durations_seconds[0]) == 2

    # All values must be valid positive integers
    for r in range(2):
        for c in range(2):
            assert matrix.distances_meters[r][c] > 0
            assert matrix.durations_seconds[r][c] > 0

    # Cache should now have 4 entries
    assert len(adapter.cache) == 4

    # Second call should be 100% cache hits
    matrix2 = adapter.get_distance_matrix(origins, destinations)
    assert matrix2.distances_meters == matrix.distances_meters
    assert adapter.cache_hits == 4


def test_live_timeout_handling() -> None:
    """Verifies that an unrealistically tight timeout triggers RouteTimeoutError."""
    # 0.0001s (0.1ms) cannot complete over a live network connection
    adapter = OsrmRoutingAdapter(base_url=LIVE_OSRM_URL, timeout_seconds=0.0001, max_retries=0)

    with pytest.raises(RouteTimeoutError):
        adapter.get_direct_leg(C_EMPIRE_STATE, C_NY_LIBRARY)


def test_live_dispatch_with_failure_isolation() -> None:
    """
    Verifies that DispatchEngine successfully dispatches using live OSRM,
    isolating failed/unroutable requests while matching valid ones.
    """
    adapter = OsrmRoutingAdapter(base_url=LIVE_OSRM_URL, timeout_seconds=10.0)
    policy_provider = DefaultPolicyProvider()
    spatial_index = H3SpatialIndexAdapter()
    engine = DispatchEngine(policy_provider, adapter, spatial_index)

    # Valid request in Manhattan (NYPL to ESB)
    valid_req = RideRequest(
        request_id="req-valid",
        user_id="user-valid",
        pickup_location=GeoCoordinate(latitude=40.7527, longitude=-73.9818),
        dropoff_location=GeoCoordinate(latitude=40.7484, longitude=-73.9857),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=3600,
        direct_distance_meters=1000,
        direct_duration_seconds=200,
        status=RequestStatus.PENDING,
    )

    # Request with unroutable dropoff in the ocean
    unroutable_req = RideRequest(
        request_id="req-unroutable",
        user_id="user-ocean",
        pickup_location=GeoCoordinate(latitude=40.7527, longitude=-73.9818),
        dropoff_location=GeoCoordinate(latitude=35.0000, longitude=-40.0000),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=3600,
        direct_distance_meters=1000000,
        direct_duration_seconds=50000,
        status=RequestStatus.PENDING,
    )

    # Vehicle in Manhattan near the valid request (Times Square)
    veh = Vehicle(
        vehicle_id="veh-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=40.7580, longitude=-73.9855),
        is_active=True,
    )

    # Dispatch with sufficient deadline for live network calls
    result = engine.dispatch_batch(
        requests=[valid_req, unroutable_req],
        vehicles=[veh],
        active_rides=[],
        current_time=1000,
        batch_id="live-isolation-batch",
        deadline=time.monotonic() + 15.0,  # Generous deadline for WAN calls
    )

    assert result.batch_id == "live-isolation-batch"
    # Unroutable request should not be assigned
    assert "req-unroutable" in result.unassigned_request_ids
    # The valid request should be assigned
    assert len(result.selected_assignments) == 1
    assert "req-valid" in result.selected_assignments[0].request_ids
    # Routing errors from unroutable request legs should be tracked
    assert result.routing_errors_count >= 1
    assert len(adapter.cache) > 0
