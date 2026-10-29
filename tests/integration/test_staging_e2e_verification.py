"""
Phase 8C: Staging End-to-End Correctness Tests.

Validates multi-region routing, failure isolation, boundary validation,
and concurrent dispatch against real OSRM and PostgreSQL backends.
"""

from __future__ import annotations

import concurrent.futures
import socket
import time
from typing import Any
import pytest
import urllib.request
import json

from engine.contracts.routing import (
    BoundingBox,
    Coordinate,
    OutOfRegionError,
    RouteLookupError,
    RouteTimeoutError,
)
from engine.adapters.osrm_routing import OsrmRoutingAdapter, DefaultOsrmTransport
from engine.adapters.regional_router import RegionalRoutingRouter
from engine.service.app import create_app
from engine.service.client import AsgiTestClient
from engine.service.service import build_service_from_env


def _is_port_open(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)
    try:
        sock.connect((host, port))
        sock.close()
        return True
    except (OSError, TimeoutError):
        return False


# Coordinates for E2E scenarios
NYC_TIMES_SQUARE = {"latitude": 40.7580, "longitude": -73.9855}
NYC_WALL_STREET = {"latitude": 40.7070, "longitude": -74.0090}
KL_SECRETARIAT = {"latitude": 8.5030, "longitude": 76.9530}
KL_CENTRAL_STN = {"latitude": 8.4875, "longitude": 76.9528}
KL_KOVALAM = {"latitude": 8.4000, "longitude": 76.9780}
KL_TECHNOPARK = {"latitude": 8.5560, "longitude": 76.8820}
OUTSIDE_ALBANY = {"latitude": 42.6526, "longitude": -73.7562}
OUTSIDE_TOKYO = {"latitude": 35.6762, "longitude": 139.6503}


@pytest.fixture(scope="module")
def staging_client() -> AsgiTestClient:
    """Creates an ASGI test client bound to the staging multi-region environment."""
    env = {
        "ROUTING_REGIONS_FILE": "config/regions.json",
        "REQUIRE_REAL_ROUTING": "true",
        "STRICT_ROUTING_READINESS": "false",
        "DATABASE_URL": "postgresql://postgres:postgres@127.0.0.1:5433/pool_engine_test",
        "REQUIRE_PERSISTENT_STORAGE": "true",
        "AUTH_ENABLED": "false",
    }
    service = build_service_from_env(env)
    app = create_app(service)
    client = AsgiTestClient(app)
    yield client
    service.close()


# ---------------------------------------------------------------------------
# Scenario 1: Manhattan request routes to Manhattan backend
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _is_port_open("127.0.0.1", 5000), reason="OSRM Manhattan port 5000 required")
def test_scenario_01_manhattan_routes_to_manhattan_backend(staging_client: AsgiTestClient) -> None:
    resp = staging_client.post(
        "/v1/requests",
        json={
            "request_id": "req-e2e-nyc-01",
            "user_id": "rider-nyc-01",
            "pickup_location": NYC_TIMES_SQUARE,
            "dropoff_location": NYC_WALL_STREET,
            "seat_count": 1,
            "earliest_pickup_time": 1700000000,
            "latest_dropoff_time": 1700003600,
        },
    )
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert 7000 < data["direct_distance_meters"] < 12000
    assert 500 < data["direct_duration_seconds"] < 1800
    assert data["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Scenario 2: Kerala request routes to Kerala backend
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _is_port_open("127.0.0.1", 5001), reason="OSRM Kerala port 5001 required")
def test_scenario_02_kerala_routes_to_kerala_backend(staging_client: AsgiTestClient) -> None:
    resp = staging_client.post(
        "/v1/requests",
        json={
            "request_id": "req-e2e-kl-01",
            "user_id": "rider-kl-01",
            "pickup_location": KL_KOVALAM,
            "dropoff_location": KL_CENTRAL_STN,
            "seat_count": 1,
            "earliest_pickup_time": 1700000000,
            "latest_dropoff_time": 1700003600,
        },
    )
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert 10000 < data["direct_distance_meters"] < 16000  # ~12.2 km
    assert 600 < data["direct_duration_seconds"] < 1500     # ~15 min
    assert data["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Scenario 3: Out of region coordinates rejected
# ---------------------------------------------------------------------------
def test_scenario_03_out_of_region_rejected(staging_client: AsgiTestClient) -> None:
    resp = staging_client.post(
        "/v1/requests",
        json={
            "request_id": "req-e2e-out-01",
            "user_id": "rider-out-01",
            "pickup_location": OUTSIDE_ALBANY,
            "dropoff_location": NYC_TIMES_SQUARE,
            "seat_count": 1,
            "earliest_pickup_time": 1700000000,
            "latest_dropoff_time": 1700003600,
        },
    )
    assert resp.status_code == 400
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "OUT_OF_REGION"


# ---------------------------------------------------------------------------
# Scenario 4: Cross-region request rejected
# ---------------------------------------------------------------------------
def test_scenario_04_cross_region_rejected(staging_client: AsgiTestClient) -> None:
    resp = staging_client.post(
        "/v1/requests",
        json={
            "request_id": "req-e2e-cross-01",
            "user_id": "rider-cross-01",
            "pickup_location": NYC_TIMES_SQUARE,
            "dropoff_location": KL_CENTRAL_STN,
            "seat_count": 1,
            "earliest_pickup_time": 1700000000,
            "latest_dropoff_time": 1700003600,
        },
    )
    assert resp.status_code == 400
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "OUT_OF_REGION"


# ---------------------------------------------------------------------------
# Scenario 5: Region-specific cache isolation preserved
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not (_is_port_open("127.0.0.1", 5000) and _is_port_open("127.0.0.1", 5001)),
    reason="Both Manhattan and Kerala OSRM required",
)
def test_scenario_05_region_cache_isolation() -> None:
    nyc_adapter = OsrmRoutingAdapter(base_url="http://127.0.0.1:5000")
    kl_adapter = OsrmRoutingAdapter(base_url="http://127.0.0.1:5001")

    # NYC query caches under nyc_adapter
    c1 = Coordinate(latitude=40.7580, longitude=-73.9855)
    c2 = Coordinate(latitude=40.7070, longitude=-74.0090)
    nyc_adapter.get_direct_leg(c1, c2)
    assert len(nyc_adapter.cache) > 0

    # Kerala adapter cache remains 0
    assert len(kl_adapter.cache) == 0

    # Querying Kerala does not hit NYC cache
    k1 = Coordinate(latitude=8.5030, longitude=76.9530)
    k2 = Coordinate(latitude=8.4875, longitude=76.9528)
    kl_adapter.get_direct_leg(k1, k2)
    assert len(kl_adapter.cache) > 0

    nyc_adapter.close()
    kl_adapter.close()


# ---------------------------------------------------------------------------
# Scenario 6: Backend timeout and connection failure handling
# ---------------------------------------------------------------------------
def test_scenario_06_backend_timeout_and_failure_handling() -> None:
    # Pointing to an unbound loopback port (5999)
    dead_adapter = OsrmRoutingAdapter(base_url="http://127.0.0.1:5999", timeout_seconds=0.1)
    c1 = Coordinate(latitude=40.7580, longitude=-73.9855)
    c2 = Coordinate(latitude=40.7070, longitude=-74.0090)
    with pytest.raises((RouteLookupError, RouteTimeoutError)):
        dead_adapter.get_direct_leg(c1, c2)
    dead_adapter.close()


# ---------------------------------------------------------------------------
# Scenario 7: Unhealthy regional backend does not take down healthy region
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _is_port_open("127.0.0.1", 5000), reason="OSRM Manhattan port 5000 required")
def test_scenario_07_unhealthy_backend_isolation() -> None:
    from engine.contracts.routing import RegionConfig

    # Configure one live region (Manhattan) and one offline region (dummy port 5999)
    regions = [
        RegionConfig(
            region_id="us-nyc-manhattan",
            bounding_box=BoundingBox(min_lat=40.69, min_lon=-74.05, max_lat=40.88, max_lon=-73.90),
            provider_type="osrm",
            endpoint_url="http://127.0.0.1:5000",
            probe_coordinate=Coordinate(latitude=40.7580, longitude=-73.9855),
        ),
        RegionConfig(
            region_id="in-kl-offline",
            bounding_box=BoundingBox(min_lat=8.18, min_lon=76.80, max_lat=8.65, max_lon=77.05),
            provider_type="osrm",
            endpoint_url="http://127.0.0.1:5999",
            probe_coordinate=Coordinate(latitude=8.5241, longitude=76.9366),
        ),
    ]
    router = RegionalRoutingRouter(regions=regions)

    # Health check for Manhattan is True
    assert router.get_provider("us-nyc-manhattan").check_health() is True
    # Health check for offline region is False
    assert router.get_provider("in-kl-offline").check_health() is False

    # Routing within Manhattan still works perfectly!
    dist, dur = router.get_direct_leg(
        Coordinate(latitude=40.7580, longitude=-73.9855),
        Coordinate(latitude=40.7070, longitude=-74.0090),
    )
    assert dist > 7000
    router.close()


# ---------------------------------------------------------------------------
# Scenario 8: API readiness represents dependencies accurately
# ---------------------------------------------------------------------------
def test_scenario_08_api_readiness_accuracy(staging_client: AsgiTestClient) -> None:
    resp = staging_client.get("/v1/health/readiness")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is True
    assert data["components"]["storage"] == "healthy"
    assert data["components"]["routing"] == "healthy"


# ---------------------------------------------------------------------------
# Scenario 9: Invalid coordinates and malformed inputs handled safely
# ---------------------------------------------------------------------------
def test_scenario_09_invalid_coordinates_handled_safely(staging_client: AsgiTestClient) -> None:
    # Lat > 90
    resp = staging_client.post(
        "/v1/requests",
        json={
            "request_id": "req-invalid-lat",
            "user_id": "rider-01",
            "pickup_location": {"latitude": 95.0, "longitude": 76.9530},
            "dropoff_location": KL_CENTRAL_STN,
            "seat_count": 1,
            "earliest_pickup_time": 1700000000,
            "latest_dropoff_time": 1700003600,
        },
    )
    assert resp.status_code in (400, 422)

    # Malformed non-JSON
    resp_raw = staging_client.post(
        "/v1/requests",
        data=b"not a valid json payload",
        headers={"Content-Type": "application/json"},
    )
    assert resp_raw.status_code == 400


# ---------------------------------------------------------------------------
# Scenario 10: Service reconnection preserves routing state
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _is_port_open("127.0.0.1", 5001), reason="OSRM Kerala port 5001 required")
def test_scenario_10_reconnection_preserves_routing_state() -> None:
    adapter = OsrmRoutingAdapter(base_url="http://127.0.0.1:5001")
    c1 = Coordinate(latitude=8.5030, longitude=76.9530)
    c2 = Coordinate(latitude=8.4875, longitude=76.9528)

    # Initial query
    d1, t1 = adapter.get_direct_leg(c1, c2)

    # Force connection close to simulate connection drop/reconnection
    if isinstance(adapter.transport, DefaultOsrmTransport):
        adapter.transport.close()

    # Subsequent query succeeds and produces identical metric
    d2, t2 = adapter.get_direct_leg(c1, c2)
    assert d1 == d2
    assert t1 == t2
    adapter.close()


# ---------------------------------------------------------------------------
# Scenario 11: Concurrent requests do not leak cross-region configuration
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not (_is_port_open("127.0.0.1", 5000) and _is_port_open("127.0.0.1", 5001)),
    reason="Both Manhattan and Kerala OSRM required",
)
def test_scenario_11_concurrent_requests_no_leakage(staging_client: AsgiTestClient) -> None:
    def send_nyc(idx: int) -> dict[str, Any]:
        r = staging_client.post(
            "/v1/requests",
            json={
                "request_id": f"req-conc-nyc-{idx}",
                "user_id": f"user-nyc-{idx}",
                "pickup_location": NYC_TIMES_SQUARE,
                "dropoff_location": NYC_WALL_STREET,
                "seat_count": 1,
                "earliest_pickup_time": 1700000000,
                "latest_dropoff_time": 1700003600,
            },
        )
        return {"status": r.status_code, "data": r.json(), "region": "nyc"}

    def send_kl(idx: int) -> dict[str, Any]:
        r = staging_client.post(
            "/v1/requests",
            json={
                "request_id": f"req-conc-kl-{idx}",
                "user_id": f"user-kl-{idx}",
                "pickup_location": KL_KOVALAM,
                "dropoff_location": KL_CENTRAL_STN,
                "seat_count": 1,
                "earliest_pickup_time": 1700000000,
                "latest_dropoff_time": 1700003600,
            },
        )
        return {"status": r.status_code, "data": r.json(), "region": "kl"}

    tasks = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for i in range(15):
            tasks.append(pool.submit(send_nyc, i))
            tasks.append(pool.submit(send_kl, i))
        results = [t.result() for t in tasks]

    assert len(results) == 30
    for res in results:
        assert res["status"] in (200, 201)
        if res["region"] == "nyc":
            # NYC distance: 7km - 12km
            assert 7000 < res["data"]["direct_distance_meters"] < 12000
        else:
            # Kerala distance: 10km - 16km
            assert 10000 < res["data"]["direct_distance_meters"] < 16000


# ---------------------------------------------------------------------------
# Scenario 12: Existing request ingestion behavior and status codes
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _is_port_open("127.0.0.1", 5001), reason="OSRM Kerala port 5001 required")
def test_scenario_12_request_and_host_ride_compatibility(staging_client: AsgiTestClient) -> None:
    # 1. Ride Request
    req_resp = staging_client.post(
        "/v1/requests",
        json={
            "request_id": "req-compat-01",
            "user_id": "rider-compat-01",
            "pickup_location": KL_SECRETARIAT,
            "dropoff_location": KL_CENTRAL_STN,
            "seat_count": 2,
            "earliest_pickup_time": 1700000000,
            "latest_dropoff_time": 1700003600,
        },
    )
    assert req_resp.status_code in (200, 201)
    assert req_resp.json()["status"] == "PENDING"

    # 2. Host Ride
    host_resp = staging_client.post(
        "/v1/host-rides",
        json={
            "ride_id": "ride-compat-01",
            "driver_id": "driver-compat-01",
            "origin": KL_KOVALAM,
            "destination": KL_TECHNOPARK,
            "scheduled_departure_time": 1700000000,
            "available_seats": 4,
        },
    )
    assert host_resp.status_code == 201
    host_data = host_resp.json()
    assert host_data["status"] == "SCHEDULED"
    assert len(host_data["stops"]) == 2
    assert host_data["direct_distance_meters"] > 20000
