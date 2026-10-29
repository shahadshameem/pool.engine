"""Integration tests for regional boundary validation against live OSRM and dispatch service (Phase 3)."""

import os
import socket
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.osrm_routing import DefaultOsrmTransport, OsrmRoutingAdapter
from engine.contracts.routing import (
    BoundingBox,
    Coordinate,
    OutOfRegionError,
    RouteLookupError,
)
from engine.domain.enums import RequestStatus
from engine.domain.models import GeoCoordinate, RideRequest
from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator, OrchestrationConfig
from engine.service.app import create_app
from engine.service.client import AsgiTestClient
from engine.service.config import ServiceConfig
from engine.service.schemas import CreateHostRideInput, CreateRideRequestInput
from engine.service.service import PoolEngineService, build_service_from_env


# Regional coordinates
MANHATTAN_TIMES_SQUARE = Coordinate(latitude=40.7580, longitude=-73.9855)
MANHATTAN_WALL_STREET = Coordinate(latitude=40.7070, longitude=-74.0090)
KERALA_TVM_ORIGIN = Coordinate(latitude=8.5469, longitude=76.9054)
KERALA_TVM_DEST = Coordinate(latitude=8.4875, longitude=76.9528)
ALBANY_NY = Coordinate(latitude=42.6526, longitude=-73.7562)

MANHATTAN_BBOX = BoundingBox(
    min_lat=40.6900,
    min_lon=-74.0500,
    max_lat=40.8800,
    max_lon=-73.9000,
)


def _is_port_open(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)
    try:
        sock.connect((host, port))
        sock.close()
        return True
    except (OSError, TimeoutError):
        return False


# ===========================================================================
# 1. Kerala OSRM Availability Verification
# ===========================================================================

def test_kerala_osrm_port_5001_status_is_blocked() -> None:
    """
    Verifies the operational availability of the Kerala OSRM service on port 5001.
    Per Phase 3 specifications, if port 5001 is inactive or dataset is absent,
    real Kerala routing verification must be formally documented as BLOCKED
    without downloading external map data.
    """
    is_open = _is_port_open("127.0.0.1", 5001)
    if not is_open:
        # Expected: port 5001 is offline in this environment
        pytest.skip(
            "Kerala OSRM service on port 5001 is unavailable. "
            "Real Kerala routing verification is safely marked BLOCKED pending dataset provision."
        )


# ===========================================================================
# 2. Live Manhattan OSRM (Port 5000) Boundary Validation
# ===========================================================================

@pytest.mark.skipif(
    not _is_port_open("127.0.0.1", 5000),
    reason="Live Manhattan OSRM service on port 5000 is unavailable",
)
def test_live_manhattan_osrm_in_region_routing() -> None:
    """Confirms in-region Manhattan coordinates route accurately via live OSRM."""
    adapter = OsrmRoutingAdapter(
        base_url="http://127.0.0.1:5000",
        bounding_box=MANHATTAN_BBOX,
        max_snap_distance_meters=5000.0,
    )
    dist, dur = adapter.get_direct_leg(MANHATTAN_TIMES_SQUARE, MANHATTAN_WALL_STREET)
    assert 7000 < dist < 12000  # ~9.4 km
    assert 500 < dur < 1800     # ~15 min
    adapter.close()


@pytest.mark.skipif(
    not _is_port_open("127.0.0.1", 5000),
    reason="Live Manhattan OSRM service on port 5000 is unavailable",
)
def test_live_manhattan_osrm_rejects_kerala_due_to_bounding_box() -> None:
    """Confirms Kerala coordinates are rejected by bounding box prior to network call."""
    adapter = OsrmRoutingAdapter(
        base_url="http://127.0.0.1:5000",
        bounding_box=MANHATTAN_BBOX,
        max_snap_distance_meters=5000.0,
    )
    with pytest.raises(OutOfRegionError, match=r"outside regional bounding box"):
        adapter.get_direct_leg(KERALA_TVM_ORIGIN, KERALA_TVM_DEST)
    adapter.close()


@pytest.mark.skipif(
    not _is_port_open("127.0.0.1", 5000),
    reason="Live Manhattan OSRM service on port 5000 is unavailable",
)
def test_live_manhattan_osrm_rejects_kerala_snapping_without_bbox() -> None:
    """
    Confirms that even without a pre-configured bounding box, Kerala coordinates
    are rejected when queried against Manhattan OSRM because the returned snapping
    distance (~15,678 km) exceeds max_snap_distance_meters.
    """
    adapter = OsrmRoutingAdapter(
        base_url="http://127.0.0.1:5000",
        bounding_box=None,  # No bounding box
        max_snap_distance_meters=5000.0,
    )
    with pytest.raises(OutOfRegionError, match=r"snapped.*exceeding maximum allowed snapping distance"):
        adapter.get_direct_leg(KERALA_TVM_ORIGIN, KERALA_TVM_DEST)
    adapter.close()


@pytest.mark.skipif(
    not _is_port_open("127.0.0.1", 5000),
    reason="Live Manhattan OSRM service on port 5000 is unavailable",
)
def test_live_manhattan_osrm_rejects_albany_snapping() -> None:
    """Confirms Albany (206km away) is rejected by snapping distance against Manhattan OSRM."""
    adapter = OsrmRoutingAdapter(
        base_url="http://127.0.0.1:5000",
        bounding_box=None,
        max_snap_distance_meters=5000.0,
    )
    with pytest.raises(OutOfRegionError, match=r"snapped.*exceeding maximum allowed snapping distance"):
        adapter.get_direct_leg(MANHATTAN_TIMES_SQUARE, ALBANY_NY)
    adapter.close()


# ===========================================================================
# 3. API Failure Propagation & Error Codes
# ===========================================================================

@pytest.mark.skipif(
    not _is_port_open("127.0.0.1", 5000),
    reason="Live Manhattan OSRM service on port 5000 is unavailable",
)
def test_api_rejects_out_of_region_request_with_rfc7807_error() -> None:
    storage = InMemoryRideStorage()
    router = OsrmRoutingAdapter(
        base_url="http://127.0.0.1:5000",
        bounding_box=MANHATTAN_BBOX,
        max_snap_distance_meters=5000.0,
    )
    spatial = H3SpatialIndexAdapter()
    policy = DefaultPolicyProvider()
    orchestrator = DispatchOrchestrator(
        storage=storage,
        policy_provider=policy,
        routing_provider=router,
        spatial_index=spatial,
        config=OrchestrationConfig(deadline_seconds=0.500),
    )
    service = PoolEngineService(storage=storage, orchestrator=orchestrator, router=router)
    app = create_app(service)
    client = AsgiTestClient(app)

    # Submitting Kerala request to Manhattan service
    resp = client.post(
        "/v1/requests",
        json={
            "request_id": "req-kerala-001",
            "user_id": "user-kerala-1",
            "pickup_location": {"latitude": 8.5469, "longitude": 76.9054},
            "dropoff_location": {"latitude": 8.4875, "longitude": 76.9528},
            "seat_count": 1,
            "earliest_pickup_time": 1700000000,
            "latest_dropoff_time": 1700003600,
        },
    )
    assert resp.status_code == 400
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "OUT_OF_REGION"
    assert "outside" in data["error"]["message"].lower()

    # Submitting Kerala host ride to Manhattan service
    host_resp = client.post(
        "/v1/host-rides",
        json={
            "ride_id": "ride-kerala-host-001",
            "driver_id": "driver-kerala-1",
            "origin": {"latitude": 8.5469, "longitude": 76.9054},
            "destination": {"latitude": 8.4875, "longitude": 76.9528},
            "scheduled_departure_time": 1700000000,
            "available_seats": 3,
        },
    )
    assert host_resp.status_code == 400
    host_data = host_resp.json()
    assert "error" in host_data
    assert host_data["error"]["code"] == "OUT_OF_REGION"

    router.close()
