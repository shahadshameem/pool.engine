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

KERALA_BBOX = BoundingBox(
    min_lat=8.1800,
    min_lon=76.8000,
    max_lat=8.6500,
    max_lon=77.0500,
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

def test_kerala_osrm_port_5001_status_and_live_routing() -> None:
    """
    Verifies operational availability and routing correctness of the Kerala OSRM service on port 5001.
    When port 5001 is active, verifies real road-network routing within Thiruvananthapuram.
    """
    is_open = _is_port_open("127.0.0.1", 5001)
    if not is_open:
        pytest.skip(
            "Kerala OSRM service on port 5001 is unavailable. "
            "Real Kerala routing verification is safely marked BLOCKED pending dataset provision."
        )

    adapter = OsrmRoutingAdapter(
        base_url="http://127.0.0.1:5001",
        bounding_box=KERALA_BBOX,
        max_snap_distance_meters=5000.0,
    )

    # 1. Short Route: Secretariat area to Central Railway Station
    dist, dur = adapter.get_direct_leg(KERALA_TVM_ORIGIN, KERALA_TVM_DEST)
    assert 5000 < dist < 12000  # ~8.7 km
    assert 400 < dur < 1800     # ~10-15 min

    # 2. Long Route: Kovalam to Technopark
    kovalam = Coordinate(latitude=8.4000, longitude=76.9780)
    technopark = Coordinate(latitude=8.5560, longitude=76.8820)
    dist_long, dur_long = adapter.get_direct_leg(kovalam, technopark)
    assert 18000 < dist_long < 30000  # ~23.4 km
    assert 1000 < dur_long < 3000     # ~25-35 min

    # 3. Reject Manhattan coordinates on Kerala instance
    with pytest.raises(OutOfRegionError, match=r"outside regional bounding box"):
        adapter.get_direct_leg(MANHATTAN_TIMES_SQUARE, KERALA_TVM_DEST)

    adapter.close()


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


@pytest.mark.skipif(
    not (_is_port_open("127.0.0.1", 5000) and _is_port_open("127.0.0.1", 5001)),
    reason="Both Manhattan (port 5000) and Kerala (port 5001) live OSRM daemons required",
)
def test_live_multi_region_concurrent_routing_and_isolation() -> None:
    """
    Verifies multi-region routing isolation, concurrent dispatch handling,
    and cross-region rejection across simultaneously active Manhattan and Kerala OSRM instances.
    """
    env = {
        "ROUTING_REGIONS_FILE": "config/regions.json",
        "REQUIRE_REAL_ROUTING": "true",
    }
    service = build_service_from_env(env)
    app = create_app(service)
    client = AsgiTestClient(app)

    # 1. Readiness probe across all regions
    ready_resp = client.get("/v1/health/readiness")
    assert ready_resp.status_code == 200
    ready_data = ready_resp.json()
    assert ready_data["ready"] is True
    regions = ready_data["components"]["regions"]
    assert regions["us-nyc-manhattan"]["healthy"] is True
    assert regions["in-kl-tvm"]["healthy"] is True

    # 2. Targeted readiness probe for in-kl-tvm
    ready_kl = client.get("/v1/health/readiness?region=in-kl-tvm")
    assert ready_kl.status_code == 200
    assert ready_kl.json()["components"]["target_region"] == "in-kl-tvm"

    # 3. Targeted readiness probe for us-nyc-manhattan
    ready_nyc = client.get("/v1/health/readiness?region=us-nyc-manhattan")
    assert ready_nyc.status_code == 200
    assert ready_nyc.json()["components"]["target_region"] == "us-nyc-manhattan"

    # 4. In-region Manhattan request
    nyc_resp = client.post(
        "/v1/requests",
        json={
            "request_id": "req-live-nyc-001",
            "user_id": "rider-nyc-1",
            "pickup_location": {"latitude": 40.7580, "longitude": -73.9855},
            "dropoff_location": {"latitude": 40.7070, "longitude": -74.0090},
            "seat_count": 1,
            "earliest_pickup_time": 1700000000,
            "latest_dropoff_time": 1700003600,
        },
    )
    assert nyc_resp.status_code == 201
    assert nyc_resp.json()["direct_distance_meters"] > 7000

    # 5. In-region Kerala request
    kl_resp = client.post(
        "/v1/requests",
        json={
            "request_id": "req-live-kl-001",
            "user_id": "rider-kl-1",
            "pickup_location": {"latitude": 8.4000, "longitude": 76.9780},
            "dropoff_location": {"latitude": 8.4875, "longitude": 76.9528},
            "seat_count": 1,
            "earliest_pickup_time": 1700000000,
            "latest_dropoff_time": 1700003600,
        },
    )
    assert kl_resp.status_code == 201
    assert kl_resp.json()["direct_distance_meters"] > 10000

    # 6. Cross-region request (NYC pickup, Kerala dropoff)
    cross_resp = client.post(
        "/v1/requests",
        json={
            "request_id": "req-cross-region-001",
            "user_id": "rider-cross-1",
            "pickup_location": {"latitude": 40.7580, "longitude": -73.9855},
            "dropoff_location": {"latitude": 8.4875, "longitude": 76.9528},
            "seat_count": 1,
            "earliest_pickup_time": 1700000000,
            "latest_dropoff_time": 1700003600,
        },
    )
    assert cross_resp.status_code == 400
    assert cross_resp.json()["error"]["code"] == "OUT_OF_REGION"

    service.close()
