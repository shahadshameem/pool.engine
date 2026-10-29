"""Unit tests for Phase 6 multi-region routing hardening, configuration validation, and isolation."""

import json
import pytest

from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.routing import (
    BoundingBox,
    Coordinate,
    OutOfRegionError,
    RegionConfig,
)
from engine.domain.enums import RequestStatus, RideStatus
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, StopStatus, StopType, Vehicle
from engine.service.config import ServiceConfig
from engine.service.errors import OutOfRegionServiceError
from engine.service.schemas import CreateHostRideInput
from engine.service.service import PoolEngineService, build_service_from_env


NYC_BBOX = BoundingBox(
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

NYC_TIMES_SQUARE = Coordinate(latitude=40.7580, longitude=-73.9855)
NYC_WALL_STREET = Coordinate(latitude=40.7070, longitude=-74.0090)
KERALA_TVM_ORIGIN = Coordinate(latitude=8.5469, longitude=76.9054)
KERALA_TVM_DEST = Coordinate(latitude=8.4875, longitude=76.9528)


# ===========================================================================
# 1. Configuration Validation: ROUTING_REGIONS_FILE
# ===========================================================================

def test_missing_routing_regions_file_raises_error() -> None:
    """Configuring a non-existent ROUTING_REGIONS_FILE must fail fast rather than silently defaulting."""
    with pytest.raises(ValueError, match="does not exist"):
        ServiceConfig.from_env({"ROUTING_REGIONS_FILE": "non_existent_regions_file.json"})


def test_valid_routing_regions_file_loads(tmp_path: pytest.TempPathFactory) -> None:
    """Configured ROUTING_REGIONS_FILE successfully parses valid regions."""
    regions_file = tmp_path / "valid_regions.json"  # type: ignore[operator]
    regions_content = [
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
                "max_lat": 8.6500,
                "max_lon": 77.0500,
            },
            "provider_type": "mock",
        },
    ]
    regions_file.write_text(json.dumps(regions_content), encoding="utf-8")

    cfg = ServiceConfig.from_env({"ROUTING_REGIONS_FILE": str(regions_file)})
    assert len(cfg.regions) == 2
    assert cfg.regions[0].region_id == "us-nyc-manhattan"
    assert cfg.regions[1].region_id == "in-kl-tvm"


# ===========================================================================
# 2. Multi-Region Real Routing Without Redundant OSRM_BASE_URL
# ===========================================================================

def test_build_service_from_env_with_regions_does_not_require_osrm_base_url() -> None:
    """
    When multi-region ROUTING_REGIONS is provided, build_service_from_env should not
    require the legacy single-region OSRM_BASE_URL variable.
    """
    regions_json = json.dumps([
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
    ])
    env = {
        "REQUIRE_REAL_ROUTING": "false",
        "ROUTING_REGIONS": regions_json,
    }
    svc = build_service_from_env(env)
    assert hasattr(svc.router, "regions")
    assert "us-nyc-manhattan" in svc.router.regions  # type: ignore[attr-defined]


# ===========================================================================
# 3. Host Ride Declared region_id Validation
# ===========================================================================

def test_register_host_ride_declared_region_mismatch_raises() -> None:
    """register_host_ride raises OutOfRegionServiceError if coordinates do not match declared region_id."""
    from engine.adapters.regional_router import RegionalRoutingRouter

    cfg_nyc = RegionConfig(region_id="us-nyc-manhattan", bounding_box=NYC_BBOX, provider_type="mock")
    cfg_kl = RegionConfig(region_id="in-kl-tvm", bounding_box=KERALA_BBOX, provider_type="mock")
    router = RegionalRoutingRouter(
        regions=[cfg_nyc, cfg_kl],
        providers={
            "us-nyc-manhattan": MockRoutingProvider(bounding_box=NYC_BBOX),
            "in-kl-tvm": MockRoutingProvider(bounding_box=KERALA_BBOX),
        },
    )
    storage = InMemoryRideStorage()
    svc = PoolEngineService(
        storage=storage,
        orchestrator=None,  # type: ignore[arg-type]
        router=router,
    )

    # Submitting Manhattan coordinates with declared region_id="in-kl-tvm"
    host_input = CreateHostRideInput(
        driver_id="driver-123",
        origin=GeoCoordinate(latitude=40.7580, longitude=-73.9855),  # Manhattan
        destination=GeoCoordinate(latitude=40.7070, longitude=-74.0090),  # Manhattan
        available_seats=3,
        scheduled_departure_time=1000,
        region_id="in-kl-tvm",  # Mismatch!
    )
    with pytest.raises(OutOfRegionServiceError, match="does not match declared region 'in-kl-tvm'"):
        svc.register_host_ride(host_input)


# ===========================================================================
# 4. Host Ride Proposal Generation Pre-Filtering by Region
# ===========================================================================

def test_generate_proposals_for_host_ride_prefilters_by_region() -> None:
    """generate_proposals_for_host_ride ignores pending requests from other regions without routing them."""
    from engine.adapters.regional_router import RegionalRoutingRouter
    from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator
    from engine.adapters.default_policy import DefaultPolicyProvider
    from engine.adapters.h3_spatial import H3SpatialIndexAdapter

    cfg_nyc = RegionConfig(region_id="us-nyc-manhattan", bounding_box=NYC_BBOX, provider_type="mock")
    cfg_kl = RegionConfig(region_id="in-kl-tvm", bounding_box=KERALA_BBOX, provider_type="mock")
    router = RegionalRoutingRouter(
        regions=[cfg_nyc, cfg_kl],
        providers={
            "us-nyc-manhattan": MockRoutingProvider(bounding_box=NYC_BBOX),
            "in-kl-tvm": MockRoutingProvider(bounding_box=KERALA_BBOX),
        },
    )
    storage = InMemoryRideStorage()
    orchestrator = DispatchOrchestrator(
        storage=storage,
        policy_provider=DefaultPolicyProvider(),
        routing_provider=router,
        spatial_index=H3SpatialIndexAdapter(),
    )
    svc = PoolEngineService(
        storage=storage,
        orchestrator=orchestrator,
        router=router,
    )

    # Seed Manhattan host ride
    host_input = CreateHostRideInput(
        driver_id="driver-nyc",
        origin=GeoCoordinate(latitude=40.7580, longitude=-73.9855),
        destination=GeoCoordinate(latitude=40.7070, longitude=-74.0090),
        available_seats=3,
        scheduled_departure_time=1000,
        region_id="us-nyc-manhattan",
    )
    host_ride_dto = svc.register_host_ride(host_input)

    # Seed a Kerala pending request in storage
    kerala_req = RideRequest(
        request_id="req-kerala-1",
        user_id="user-kerala",
        pickup_location=GeoCoordinate(latitude=8.5469, longitude=76.9054),
        dropoff_location=GeoCoordinate(latitude=8.4875, longitude=76.9528),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=2000,
        direct_distance_meters=8000,
        direct_duration_seconds=900,
        status=RequestStatus.PENDING,
    )
    storage.save_request(kerala_req)

    # Evaluating proposals for Manhattan host ride should NOT crash and should return 0 proposals
    proposals = svc.match_host_ride(host_ride_dto.ride_id)
    assert len(proposals) == 0


# ===========================================================================
# 5. Targeted Per-Region Readiness Probing
# ===========================================================================

def test_check_readiness_targeted_by_region() -> None:
    """check_readiness with region_id parameter assesses health specifically for that region."""
    from engine.adapters.regional_router import RegionalRoutingRouter

    class FailingProvider(MockRoutingProvider):
        def check_health(self) -> bool:
            return False

    cfg_nyc = RegionConfig(region_id="us-nyc-manhattan", bounding_box=NYC_BBOX, provider_type="mock")
    cfg_kl = RegionConfig(region_id="in-kl-tvm", bounding_box=KERALA_BBOX, provider_type="mock")
    router = RegionalRoutingRouter(
        regions=[cfg_nyc, cfg_kl],
        providers={
            "us-nyc-manhattan": MockRoutingProvider(bounding_box=NYC_BBOX),
            "in-kl-tvm": FailingProvider(bounding_box=KERALA_BBOX),
        },
    )
    storage = InMemoryRideStorage()
    svc = PoolEngineService(
        storage=storage,
        orchestrator=None,  # type: ignore[arg-type]
        router=router,
    )

    # General check: Kerala is failing, so routing is degraded
    general_readiness = svc.check_readiness(strict_routing=True)
    assert general_readiness["ready"] is False
    assert general_readiness["components"]["routing"] == "degraded"

    # Targeted check for Manhattan: Manhattan is healthy, so readiness is True even under strict_routing!
    nyc_readiness = svc.check_readiness(strict_routing=True, region_id="us-nyc-manhattan")
    assert nyc_readiness["ready"] is True
    assert nyc_readiness["components"]["routing"] == "healthy"
    assert nyc_readiness["components"]["target_region"] == "us-nyc-manhattan"

    # Targeted check for Kerala: Kerala is failing, so readiness is False
    kl_readiness = svc.check_readiness(strict_routing=True, region_id="in-kl-tvm")
    assert kl_readiness["ready"] is False
    assert kl_readiness["components"]["routing"] == "degraded"
    assert kl_readiness["components"]["target_region"] == "in-kl-tvm"


def test_asgi_readiness_endpoint_supports_targeted_region() -> None:
    """GET /v1/health/readiness?region=<region_id> passes target region to readiness evaluation."""
    from engine.adapters.regional_router import RegionalRoutingRouter
    from engine.service.app import create_app
    from engine.service.client import AsgiTestClient

    class FailingProvider(MockRoutingProvider):
        def check_health(self) -> bool:
            return False

    cfg_nyc = RegionConfig(region_id="us-nyc-manhattan", bounding_box=NYC_BBOX, provider_type="mock")
    cfg_kl = RegionConfig(region_id="in-kl-tvm", bounding_box=KERALA_BBOX, provider_type="mock")
    router = RegionalRoutingRouter(
        regions=[cfg_nyc, cfg_kl],
        providers={
            "us-nyc-manhattan": MockRoutingProvider(bounding_box=NYC_BBOX),
            "in-kl-tvm": FailingProvider(bounding_box=KERALA_BBOX),
        },
    )
    storage = InMemoryRideStorage()
    svc = PoolEngineService(
        storage=storage,
        orchestrator=None,  # type: ignore[arg-type]
        router=router,
    )
    app = create_app(service=svc, config=ServiceConfig(strict_routing_readiness=True))
    client = AsgiTestClient(app)

    # General endpoint returns 503 because Kerala is down under strict_routing_readiness
    res_general = client.get("/v1/health/readiness")
    assert res_general.status_code == 503

    # Targeted Manhattan probe returns 200 because Manhattan is healthy
    res_nyc = client.get("/v1/health/readiness?region=us-nyc-manhattan")
    assert res_nyc.status_code == 200
    assert res_nyc.json()["components"]["target_region"] == "us-nyc-manhattan"
    assert res_nyc.json()["components"]["routing"] == "healthy"

    # Targeted Kerala probe returns 503
    res_kl = client.get("/v1/health/readiness?region=in-kl-tvm")
    assert res_kl.status_code == 503
    assert res_kl.json()["components"]["target_region"] == "in-kl-tvm"
