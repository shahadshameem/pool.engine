"""Integration tests for multi-region API service and endpoints via ASGI client (Phase 5)."""

import json
import pytest

from engine.contracts.routing import BoundingBox, Coordinate, RegionConfig
from engine.adapters.mock_routing import MockRoutingProvider
from engine.adapters.regional_router import RegionalRoutingRouter
from engine.service.app import create_app
from engine.service.client import AsgiTestClient
from engine.service.config import ServiceConfig
from engine.service.service import PoolEngineService, build_service_from_env

NYC_BBOX = BoundingBox(min_lat=40.6900, min_lon=-74.0500, max_lat=40.8800, max_lon=-73.9000)
KERALA_BBOX = BoundingBox(min_lat=8.1800, min_lon=76.8000, max_lat=12.8000, max_lon=77.5000)

NYC_TIMES_SQUARE = {"latitude": 40.7580, "longitude": -73.9855}
NYC_WALL_STREET = {"latitude": 40.7070, "longitude": -74.0090}

KERALA_TVM_ORIGIN = {"latitude": 8.5469, "longitude": 76.9054}
KERALA_TVM_DEST = {"latitude": 8.4875, "longitude": 76.9528}

LONDON_COORD = {"latitude": 51.5074, "longitude": -0.1278}


def test_multi_region_app_readiness_and_routing() -> None:
    """Verifies that an ASGI app configured with multiple regions exposes per-region health."""
    env = {
        "ROUTING_REGIONS": json.dumps([
            {
                "region_id": "us-nyc-manhattan",
                "bounding_box": {
                    "min_lat": 40.6900,
                    "min_lon": -74.0500,
                    "max_lat": 40.8800,
                    "max_lon": -73.9000,
                },
                "provider_type": "mock",
                "dataset_id": "nyc-mock-v1",
            },
            {
                "region_id": "in-kl-tvm",
                "bounding_box": {
                    "min_lat": 8.1800,
                    "min_lon": 76.8000,
                    "max_lat": 12.8000,
                    "max_lon": 77.5000,
                },
                "provider_type": "mock",
                "dataset_id": "kl-mock-v1",
            },
        ])
    }

    config = ServiceConfig.from_env(env)
    assert len(config.regions) == 2

    service = build_service_from_env(env)
    assert isinstance(service.router, RegionalRoutingRouter)

    app = create_app(service=service, config=config)
    client = AsgiTestClient(app)

    # 1. Check readiness probe includes both regions
    resp = client.get("/v1/health/readiness")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is True
    assert "regions" in data["components"]
    regions_report = data["components"]["regions"]
    assert "us-nyc-manhattan" in regions_report
    assert regions_report["us-nyc-manhattan"]["healthy"] is True
    assert regions_report["us-nyc-manhattan"]["dataset_id"] == "nyc-mock-v1"
    assert "in-kl-tvm" in regions_report
    assert regions_report["in-kl-tvm"]["healthy"] is True
    assert regions_report["in-kl-tvm"]["dataset_id"] == "kl-mock-v1"

    # 2. Submit valid NYC ride request
    req_resp = client.post(
        "/v1/requests",
        json={
            "user_id": "user-nyc-api",
            "pickup_location": NYC_TIMES_SQUARE,
            "dropoff_location": NYC_WALL_STREET,
            "earliest_pickup_time": 1000,
            "latest_dropoff_time": 2500,
            "region_id": "us-nyc-manhattan",
        },
    )
    assert req_resp.status_code == 201
    assert req_resp.json()["status"] == "PENDING"

    # 3. Submit valid Kerala ride request
    req_resp2 = client.post(
        "/v1/requests",
        json={
            "user_id": "user-kl-api",
            "pickup_location": KERALA_TVM_ORIGIN,
            "dropoff_location": KERALA_TVM_DEST,
            "earliest_pickup_time": 1000,
            "latest_dropoff_time": 2500,
            "region_id": "in-kl-tvm",
        },
    )
    assert req_resp2.status_code == 201
    assert req_resp2.json()["status"] == "PENDING"

    # 4. Reject cross-region journey
    cross_resp = client.post(
        "/v1/requests",
        json={
            "user_id": "user-cross-api",
            "pickup_location": NYC_TIMES_SQUARE,
            "dropoff_location": KERALA_TVM_DEST,
            "earliest_pickup_time": 1000,
            "latest_dropoff_time": 2500,
        },
    )
    assert cross_resp.status_code == 400
    err_data = cross_resp.json()
    assert err_data["error"]["code"] == "OUT_OF_REGION"

    # 5. Reject out-of-region coordinate
    out_resp = client.post(
        "/v1/requests",
        json={
            "user_id": "user-london",
            "pickup_location": LONDON_COORD,
            "dropoff_location": NYC_WALL_STREET,
            "earliest_pickup_time": 1000,
            "latest_dropoff_time": 2500,
        },
    )
    assert out_resp.status_code == 400
    assert out_resp.json()["error"]["code"] == "OUT_OF_REGION"

    # 6. Reject mismatched region_id
    mismatch_resp = client.post(
        "/v1/requests",
        json={
            "user_id": "user-mismatch-api",
            "pickup_location": NYC_TIMES_SQUARE,
            "dropoff_location": NYC_WALL_STREET,
            "earliest_pickup_time": 1000,
            "latest_dropoff_time": 2500,
            "region_id": "in-kl-tvm",
        },
    )
    assert mismatch_resp.status_code == 400
    assert mismatch_resp.json()["error"]["code"] == "OUT_OF_REGION"


def test_multi_region_dispatch_via_api() -> None:
    """Verifies targeted regional dispatch execution via POST /v1/dispatch."""
    env = {
        "ROUTING_REGIONS": json.dumps([
            {
                "region_id": "us-nyc-manhattan",
                "bounding_box": {
                    "min_lat": 40.6900,
                    "min_lon": -74.0500,
                    "max_lat": 40.8800,
                    "max_lon": -73.9000,
                },
                "provider_type": "mock",
            },
            {
                "region_id": "in-kl-tvm",
                "bounding_box": {
                    "min_lat": 8.1800,
                    "min_lon": 76.8000,
                    "max_lat": 12.8000,
                    "max_lon": 77.5000,
                },
                "provider_type": "mock",
            },
        ])
    }

    config = ServiceConfig.from_env(env)
    service = build_service_from_env(env)
    app = create_app(service=service, config=config)
    client = AsgiTestClient(app)

    # Register NYC supply + demand
    client.post(
        "/v1/vehicles",
        json={
            "vehicle_id": "veh-nyc-api",
            "driver_id": "drv-nyc-api",
            "total_seat_capacity": 4,
            "current_location": NYC_TIMES_SQUARE,
        },
    )
    req1 = client.post(
        "/v1/requests",
        json={
            "user_id": "rider-nyc-1",
            "pickup_location": NYC_TIMES_SQUARE,
            "dropoff_location": NYC_WALL_STREET,
            "earliest_pickup_time": 1000,
            "latest_dropoff_time": 2500,
        },
    ).json()

    # Register Kerala supply + demand
    client.post(
        "/v1/vehicles",
        json={
            "vehicle_id": "veh-kl-api",
            "driver_id": "drv-kl-api",
            "total_seat_capacity": 4,
            "current_location": KERALA_TVM_ORIGIN,
        },
    )
    req2 = client.post(
        "/v1/requests",
        json={
            "user_id": "rider-kl-1",
            "pickup_location": KERALA_TVM_ORIGIN,
            "dropoff_location": KERALA_TVM_DEST,
            "earliest_pickup_time": 1000,
            "latest_dropoff_time": 2500,
        },
    ).json()

    # Execute dispatch for NYC region only
    disp_resp = client.post(
        "/v1/dispatch",
        json={
            "current_time": 1000,
            "region_id": "us-nyc-manhattan",
        },
    )
    assert disp_resp.status_code == 200
    data = disp_resp.json()
    assert len(data["committed_assignments"]) == 1
    assignment = data["committed_assignments"][0]
    assert assignment["vehicle_id"] == "veh-nyc-api"
    assert req1["request_id"] in assignment["request_ids"]

    # Verify Kerala request was untouched by NYC dispatch
    status_resp = client.get(f"/v1/requests/{req2['request_id']}")
    assert status_resp.json()["status"] == "PENDING"
