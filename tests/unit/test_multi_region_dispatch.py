"""Unit tests for multi-region dispatch orchestration, API consistency, and concurrency (Phase 5)."""

import concurrent.futures
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.mock_routing import MockRoutingProvider
from engine.adapters.regional_router import RegionalRoutingRouter
from engine.contracts.routing import BoundingBox, Coordinate, RegionConfig
from engine.domain.enums import RequestStatus, SearchStatus
from engine.domain.models import GeoCoordinate, RideRequest, Vehicle
from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator
from engine.service.config import ServiceConfig
from engine.service.errors import OutOfRegionServiceError
from engine.service.schemas import (
    CreateRideRequestInput,
    DispatchRunInput,
    RegisterVehicleInput,
)
from engine.service.service import PoolEngineService
from engine.service.telemetry import StructuredLoggerTelemetry

NYC_BBOX = BoundingBox(min_lat=40.6900, min_lon=-74.0500, max_lat=40.8800, max_lon=-73.9000)
KERALA_BBOX = BoundingBox(min_lat=8.1800, min_lon=76.8000, max_lat=12.8000, max_lon=77.5000)

NYC_TIMES_SQUARE = GeoCoordinate(latitude=40.7580, longitude=-73.9855)
NYC_WALL_STREET = GeoCoordinate(latitude=40.7070, longitude=-74.0090)
NYC_CENTRAL_PARK = GeoCoordinate(latitude=40.7850, longitude=-73.9680)

KERALA_TVM_ORIGIN = GeoCoordinate(latitude=8.5469, longitude=76.9054)
KERALA_TVM_DEST = GeoCoordinate(latitude=8.4875, longitude=76.9528)
KERALA_TVM_MID = GeoCoordinate(latitude=8.5000, longitude=76.9200)


def build_multi_region_service() -> PoolEngineService:
    """Builds a test PoolEngineService with isolated NYC and Kerala mock regions."""
    cfg_nyc = RegionConfig(
        region_id="us-nyc-manhattan",
        bounding_box=NYC_BBOX,
        provider_type="mock",
        dataset_id="nyc-mock",
    )
    cfg_kl = RegionConfig(
        region_id="in-kl-tvm",
        bounding_box=KERALA_BBOX,
        provider_type="mock",
        dataset_id="kl-mock",
    )
    p_nyc = MockRoutingProvider(average_speed_kmh=30.0, bounding_box=NYC_BBOX)
    p_kl = MockRoutingProvider(average_speed_kmh=50.0, bounding_box=KERALA_BBOX)

    router = RegionalRoutingRouter(
        regions=[cfg_nyc, cfg_kl],
        providers={"us-nyc-manhattan": p_nyc, "in-kl-tvm": p_kl},
    )
    storage = InMemoryRideStorage()
    spatial = H3SpatialIndexAdapter()
    policy = DefaultPolicyProvider()
    orchestrator = DispatchOrchestrator(
        storage=storage,
        policy_provider=policy,
        routing_provider=router,
        spatial_index=spatial,
    )
    telemetry = StructuredLoggerTelemetry()

    return PoolEngineService(
        storage=storage,
        orchestrator=orchestrator,
        router=router,
        telemetry=telemetry,
    )


def test_service_create_request_region_id_consistency() -> None:
    """Service accepts valid matching region_id, auto-resolves if omitted, rejects mismatch."""
    svc = build_multi_region_service()

    # 1. Matching region_id explicitly supplied
    req1 = svc.create_request(
        CreateRideRequestInput(
            user_id="user-nyc-1",
            pickup_location=NYC_TIMES_SQUARE,
            dropoff_location=NYC_WALL_STREET,
            earliest_pickup_time=1000,
            latest_dropoff_time=2500,
            region_id="us-nyc-manhattan",
        )
    )
    assert req1.status == RequestStatus.PENDING

    # 2. Omitted region_id is automatically accepted
    req2 = svc.create_request(
        CreateRideRequestInput(
            user_id="user-kl-1",
            pickup_location=KERALA_TVM_ORIGIN,
            dropoff_location=KERALA_TVM_DEST,
            earliest_pickup_time=1000,
            latest_dropoff_time=2500,
        )
    )
    assert req2.status == RequestStatus.PENDING

    # 3. Mismatched region_id is rejected with OutOfRegionServiceError
    with pytest.raises(OutOfRegionServiceError, match="does not match declared region 'in-kl-tvm'"):
        svc.create_request(
            CreateRideRequestInput(
                user_id="user-mismatch",
                pickup_location=NYC_TIMES_SQUARE,
                dropoff_location=NYC_WALL_STREET,
                earliest_pickup_time=1000,
                latest_dropoff_time=2500,
                region_id="in-kl-tvm",
            )
        )


def test_service_register_vehicle_region_id_consistency() -> None:
    """Vehicle registration enforces region_id consistency when provided."""
    svc = build_multi_region_service()

    # 1. Valid vehicle in NYC
    v1 = svc.register_vehicle(
        RegisterVehicleInput(
            vehicle_id="veh-nyc-1",
            driver_id="drv-nyc-1",
            total_seat_capacity=4,
            current_location=NYC_TIMES_SQUARE,
            region_id="us-nyc-manhattan",
        )
    )
    assert v1.is_active is True

    # 2. Mismatched vehicle location vs declared region
    with pytest.raises(OutOfRegionServiceError, match="does not match declared region 'us-nyc-manhattan'"):
        svc.register_vehicle(
            RegisterVehicleInput(
                vehicle_id="veh-kl-mismatch",
                driver_id="drv-kl-1",
                total_seat_capacity=4,
                current_location=KERALA_TVM_ORIGIN,
                region_id="us-nyc-manhattan",
            )
        )


def test_service_rejects_cross_region_journey() -> None:
    """Service rejects ride request with pickup in NYC and dropoff in Kerala."""
    svc = build_multi_region_service()

    with pytest.raises(OutOfRegionServiceError, match="Cross-region"):
        svc.create_request(
            CreateRideRequestInput(
                user_id="user-cross",
                pickup_location=NYC_TIMES_SQUARE,
                dropoff_location=KERALA_TVM_DEST,
                earliest_pickup_time=1000,
                latest_dropoff_time=3600,
            )
        )


def test_multi_region_isolated_dispatch() -> None:
    """Dispatching a specific region_id only evaluates entities in that region."""
    svc = build_multi_region_service()

    # Register NYC supply and demand
    svc.register_vehicle(
        RegisterVehicleInput(
            vehicle_id="veh-nyc",
            driver_id="drv-nyc",
            total_seat_capacity=4,
            current_location=NYC_TIMES_SQUARE,
        )
    )
    req_nyc = svc.create_request(
        CreateRideRequestInput(
            user_id="user-nyc",
            pickup_location=NYC_TIMES_SQUARE,
            dropoff_location=NYC_WALL_STREET,
            earliest_pickup_time=1000,
            latest_dropoff_time=2500,
        )
    )

    # Register Kerala supply and demand
    svc.register_vehicle(
        RegisterVehicleInput(
            vehicle_id="veh-kl",
            driver_id="drv-kl",
            total_seat_capacity=4,
            current_location=KERALA_TVM_ORIGIN,
        )
    )
    req_kl = svc.create_request(
        CreateRideRequestInput(
            user_id="user-kl",
            pickup_location=KERALA_TVM_ORIGIN,
            dropoff_location=KERALA_TVM_DEST,
            earliest_pickup_time=1000,
            latest_dropoff_time=2500,
        )
    )

    # Run dispatch targeting ONLY NYC
    res_nyc = svc.run_dispatch(
        DispatchRunInput(
            current_time=1000,
            region_id="us-nyc-manhattan",
        )
    )
    assert len(res_nyc.committed_assignments) == 1
    assert res_nyc.committed_assignments[0].vehicle_id == "veh-nyc"
    assert req_nyc.request_id in res_nyc.committed_assignments[0].request_ids

    # Kerala request must NOT be assigned by NYC dispatch
    req_kl_fresh = svc.get_request(req_kl.request_id)
    assert req_kl_fresh.status == RequestStatus.PENDING

    # Run dispatch targeting Kerala
    res_kl = svc.run_dispatch(
        DispatchRunInput(
            current_time=1000,
            region_id="in-kl-tvm",
        )
    )
    assert len(res_kl.committed_assignments) == 1
    assert res_kl.committed_assignments[0].vehicle_id == "veh-kl"
    assert req_kl.request_id in res_kl.committed_assignments[0].request_ids


def test_concurrent_dispatches_across_separate_regions() -> None:
    """Concurrent dispatches targeting different regions execute safely in parallel."""
    svc = build_multi_region_service()

    # Set up entities for both regions
    svc.register_vehicle(
        RegisterVehicleInput(
            vehicle_id="veh-nyc-c",
            driver_id="drv-nyc-c",
            total_seat_capacity=4,
            current_location=NYC_TIMES_SQUARE,
        )
    )
    svc.create_request(
        CreateRideRequestInput(
            user_id="user-nyc-c",
            pickup_location=NYC_TIMES_SQUARE,
            dropoff_location=NYC_WALL_STREET,
            earliest_pickup_time=1000,
            latest_dropoff_time=2500,
        )
    )

    svc.register_vehicle(
        RegisterVehicleInput(
            vehicle_id="veh-kl-c",
            driver_id="drv-kl-c",
            total_seat_capacity=4,
            current_location=KERALA_TVM_ORIGIN,
        )
    )
    svc.create_request(
        CreateRideRequestInput(
            user_id="user-kl-c",
            pickup_location=KERALA_TVM_ORIGIN,
            dropoff_location=KERALA_TVM_DEST,
            earliest_pickup_time=1000,
            latest_dropoff_time=2500,
        )
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_nyc = executor.submit(
            svc.run_dispatch,
            DispatchRunInput(current_time=1000, region_id="us-nyc-manhattan"),
        )
        f_kl = executor.submit(
            svc.run_dispatch,
            DispatchRunInput(current_time=1000, region_id="in-kl-tvm"),
        )

        res_nyc = f_nyc.result(timeout=5.0)
        res_kl = f_kl.result(timeout=5.0)

    assert len(res_nyc.committed_assignments) == 1
    assert res_nyc.committed_assignments[0].vehicle_id == "veh-nyc-c"
    assert len(res_kl.committed_assignments) == 1
    assert res_kl.committed_assignments[0].vehicle_id == "veh-kl-c"
