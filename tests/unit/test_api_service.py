"""Unit tests for PoolEngineService domain service layer."""

import pytest
from unittest.mock import MagicMock

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.routing import (
    Coordinate,
    InvalidRouteDataError,
    RouteLookupError,
    RouteTimeoutError,
    RoutingProviderError,
)
from engine.domain.enums import RequestStatus, RideStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle
from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator, OrchestrationConfig
from engine.service.errors import (
    ConflictError,
    LifecycleError,
    ResourceNotFoundError,
    RoutingError,
    RoutingTimeoutError as ApiRoutingTimeoutError,
    ValidationError,
)
from engine.service.schemas import (
    CreateRideRequestInput,
    DispatchRunInput,
    RegisterVehicleInput,
)
from engine.service.service import PoolEngineService


@pytest.fixture
def service_env() -> tuple[PoolEngineService, InMemoryRideStorage, MockRoutingProvider, DispatchOrchestrator]:
    storage = InMemoryRideStorage()
    router = MockRoutingProvider()
    spatial = H3SpatialIndexAdapter()
    policy = DefaultPolicyProvider()
    orchestrator = DispatchOrchestrator(
        storage=storage,
        policy_provider=policy,
        routing_provider=router,
        spatial_index=spatial,
        config=OrchestrationConfig(deadline_seconds=0.500),
    )
    service = PoolEngineService(
        storage=storage,
        orchestrator=orchestrator,
        router=router,
    )
    return service, storage, router, orchestrator


def test_create_request_calculates_direct_leg_via_router(
    service_env: tuple[PoolEngineService, InMemoryRideStorage, MockRoutingProvider, DispatchOrchestrator],
) -> None:
    service, storage, router, _ = service_env
    dto = CreateRideRequestInput(
        user_id="usr-1",
        pickup_location=GeoCoordinate(latitude=40.75, longitude=-73.98),
        dropoff_location=GeoCoordinate(latitude=40.78, longitude=-73.96),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=3000,
    )
    req = service.create_request(dto)
    assert req.user_id == "usr-1"
    assert req.status == RequestStatus.PENDING
    assert req.direct_distance_meters > 0
    assert req.direct_duration_seconds > 0
    # Verified stored in persistent storage
    stored = storage.get_request(req.request_id)
    assert stored is not None
    assert stored.request_id == req.request_id


def test_create_request_preserves_explicit_direct_metrics(
    service_env: tuple[PoolEngineService, InMemoryRideStorage, MockRoutingProvider, DispatchOrchestrator],
) -> None:
    service, storage, router, _ = service_env
    dto = CreateRideRequestInput(
        user_id="usr-1",
        pickup_location=GeoCoordinate(latitude=40.75, longitude=-73.98),
        dropoff_location=GeoCoordinate(latitude=40.78, longitude=-73.96),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=3000,
        direct_distance_meters=4500,
        direct_duration_seconds=900,
    )
    req = service.create_request(dto)
    assert req.direct_distance_meters == 4500
    assert req.direct_duration_seconds == 900


def test_create_request_routing_failure_never_falls_back_to_haversine(
    service_env: tuple[PoolEngineService, InMemoryRideStorage, MockRoutingProvider, DispatchOrchestrator],
) -> None:
    service, storage, router, _ = service_env
    failing_router = MagicMock()
    failing_router.get_direct_leg.side_effect = RouteLookupError("No road route found")
    failing_service = PoolEngineService(
        storage=storage,
        orchestrator=service.orchestrator,
        router=failing_router,
    )

    dto = CreateRideRequestInput(
        user_id="usr-1",
        pickup_location=GeoCoordinate(latitude=40.75, longitude=-73.98),
        dropoff_location=GeoCoordinate(latitude=40.78, longitude=-73.96),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=3000,
    )

    with pytest.raises(RoutingError) as exc:
        failing_service.create_request(dto)
    assert exc.value.status_code == 502
    assert "Failed to resolve direct road route" in str(exc.value)


def test_create_request_routing_timeout_raises_timeout_error(
    service_env: tuple[PoolEngineService, InMemoryRideStorage, MockRoutingProvider, DispatchOrchestrator],
) -> None:
    service, storage, router, _ = service_env
    failing_router = MagicMock()
    failing_router.get_direct_leg.side_effect = RouteTimeoutError("Routing provider timed out after 500ms")
    failing_service = PoolEngineService(
        storage=storage,
        orchestrator=service.orchestrator,
        router=failing_router,
    )

    dto = CreateRideRequestInput(
        user_id="usr-1",
        pickup_location=GeoCoordinate(latitude=40.75, longitude=-73.98),
        dropoff_location=GeoCoordinate(latitude=40.78, longitude=-73.96),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=3000,
    )

    with pytest.raises(ApiRoutingTimeoutError) as exc:
        failing_service.create_request(dto)
    assert exc.value.status_code == 504
    assert "Routing provider timed out" in str(exc.value)


def test_create_request_idempotency_and_conflict(
    service_env: tuple[PoolEngineService, InMemoryRideStorage, MockRoutingProvider, DispatchOrchestrator],
) -> None:
    service, storage, router, _ = service_env
    dto1 = CreateRideRequestInput(
        request_id="req-fixed-1",
        user_id="usr-1",
        pickup_location=GeoCoordinate(latitude=40.75, longitude=-73.98),
        dropoff_location=GeoCoordinate(latitude=40.78, longitude=-73.96),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=3000,
        direct_distance_meters=2000,
        direct_duration_seconds=400,
    )
    req1 = service.create_request(dto1)
    assert req1.request_id == "req-fixed-1"

    # Exact replay returns same request
    req2 = service.create_request(dto1)
    assert req2.request_id == req1.request_id

    # Conflict with differing parameters
    dto_diff = CreateRideRequestInput(
        request_id="req-fixed-1",
        user_id="usr-DIFFERENT",
        pickup_location=GeoCoordinate(latitude=40.75, longitude=-73.98),
        dropoff_location=GeoCoordinate(latitude=40.78, longitude=-73.96),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=3000,
        direct_distance_meters=2000,
        direct_duration_seconds=400,
    )
    with pytest.raises(ConflictError) as exc:
        service.create_request(dto_diff)
    assert exc.value.status_code == 409


def test_cancel_pending_request(
    service_env: tuple[PoolEngineService, InMemoryRideStorage, MockRoutingProvider, DispatchOrchestrator],
) -> None:
    service, storage, _, _ = service_env
    dto = CreateRideRequestInput(
        request_id="req-cancel-1",
        user_id="usr-1",
        pickup_location=GeoCoordinate(latitude=40.75, longitude=-73.98),
        dropoff_location=GeoCoordinate(latitude=40.78, longitude=-73.96),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=3000,
        direct_distance_meters=2000,
        direct_duration_seconds=400,
    )
    req = service.create_request(dto)
    assert req.status == RequestStatus.PENDING

    cancelled = service.cancel_request("req-cancel-1")
    assert cancelled.status == RequestStatus.CANCELLED

    # Idempotent re-cancellation
    cancelled_again = service.cancel_request("req-cancel-1")
    assert cancelled_again.status == RequestStatus.CANCELLED


def test_cancel_nonexistent_request(
    service_env: tuple[PoolEngineService, InMemoryRideStorage, MockRoutingProvider, DispatchOrchestrator],
) -> None:
    service, _, _, _ = service_env
    with pytest.raises(ResourceNotFoundError) as exc:
        service.cancel_request("non-existent")
    assert exc.value.status_code == 404


def test_cancel_completed_request_fails(
    service_env: tuple[PoolEngineService, InMemoryRideStorage, MockRoutingProvider, DispatchOrchestrator],
) -> None:
    service, storage, _, _ = service_env
    req = RideRequest(
        request_id="req-done",
        user_id="usr-1",
        pickup_location=GeoCoordinate(latitude=40.75, longitude=-73.98),
        dropoff_location=GeoCoordinate(latitude=40.78, longitude=-73.96),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=3000,
        direct_distance_meters=2000,
        direct_duration_seconds=400,
        status=RequestStatus.COMPLETED,
    )
    storage.save_request(req)

    with pytest.raises(LifecycleError) as exc:
        service.cancel_request("req-done")
    assert exc.value.status_code == 422


def test_cancel_matched_request_calls_en_route_cancellation(
    service_env: tuple[PoolEngineService, InMemoryRideStorage, MockRoutingProvider, DispatchOrchestrator],
) -> None:
    service, storage, router, _ = service_env
    # Create vehicle and ride
    veh = Vehicle(
        vehicle_id="veh-1",
        driver_id="drv-1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=40.75, longitude=-73.98),
        is_active=True,
    )
    storage.save_vehicle(veh)

    pickup_stop = RouteStop(
        stop_id="stop-p1",
        ride_id="ride-1",
        request_id="req-matched-1",
        stop_type=StopType.PICKUP,
        location=GeoCoordinate(latitude=40.755, longitude=-73.975),
        passenger_delta=1,
        scheduled_arrival_time=1200,
        promised_window_start=1150,
        promised_window_end=1250,
        status=StopStatus.SCHEDULED,
    )
    dropoff_stop = RouteStop(
        stop_id="stop-d1",
        ride_id="ride-1",
        request_id="req-matched-1",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=40.78, longitude=-73.96),
        passenger_delta=-1,
        scheduled_arrival_time=1600,
        promised_window_start=1550,
        promised_window_end=1650,
        status=StopStatus.SCHEDULED,
    )

    ride = Ride(
        ride_id="ride-1",
        vehicle_id="veh-1",
        driver_id="drv-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(pickup_stop, dropoff_stop),
        scheduled_departure_time=1000,
        active_passenger_count=0,
        total_vmt_meters=5000,
        version=1,
    )
    storage.save_ride(ride)

    req = RideRequest(
        request_id="req-matched-1",
        user_id="usr-1",
        pickup_location=GeoCoordinate(latitude=40.755, longitude=-73.975),
        dropoff_location=GeoCoordinate(latitude=40.78, longitude=-73.96),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=3000,
        direct_distance_meters=2000,
        direct_duration_seconds=400,
        status=RequestStatus.MATCHED,
        matched_ride_id="ride-1",
    )
    storage.save_request(req)

    # Cancel the request
    cancelled = service.cancel_request("req-matched-1", current_time=1100)
    assert cancelled.status == RequestStatus.CANCELLED

    # Verify stops removed from ride
    updated_ride = storage.get_ride("ride-1")
    assert updated_ride is not None
    assert len(updated_ride.stops) == 0
    assert updated_ride.version == 2


def test_vehicle_registration_and_updates(
    service_env: tuple[PoolEngineService, InMemoryRideStorage, MockRoutingProvider, DispatchOrchestrator],
) -> None:
    service, storage, _, _ = service_env
    dto = RegisterVehicleInput(
        vehicle_id="veh-test",
        driver_id="drv-test",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=40.75, longitude=-73.98),
        is_active=True,
    )
    veh = service.register_vehicle(dto)
    assert veh.vehicle_id == "veh-test"

    # Idempotent registration
    veh_same = service.register_vehicle(dto)
    assert veh_same.vehicle_id == "veh-test"

    # Conflicting registration
    dto_conflict = RegisterVehicleInput(
        vehicle_id="veh-test",
        driver_id="drv-DIFFERENT",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=40.75, longitude=-73.98),
        is_active=True,
    )
    with pytest.raises(ConflictError) as exc:
        service.register_vehicle(dto_conflict)
    assert exc.value.status_code == 409

    # Update location
    new_loc = GeoCoordinate(latitude=40.76, longitude=-73.97)
    updated_loc = service.update_vehicle_location("veh-test", new_loc)
    assert updated_loc.current_location.latitude == 40.76

    # Update status
    updated_status = service.update_vehicle_status("veh-test", False)
    assert updated_status.is_active is False


def test_dispatch_idempotency_handling(
    service_env: tuple[PoolEngineService, InMemoryRideStorage, MockRoutingProvider, DispatchOrchestrator],
) -> None:
    service, _, _, _ = service_env
    # Mismatched header and body idempotency keys
    run_input = DispatchRunInput(
        current_time=1000,
        idempotency_token="token-A",
    )
    with pytest.raises(ValidationError) as exc:
        service.run_dispatch(run_input, header_idempotency_key="token-B")
    assert exc.value.status_code == 400
    assert "does not match" in str(exc.value)

    # Valid dispatch run
    run_valid = DispatchRunInput(
        current_time=1000,
        idempotency_token="token-A",
    )
    res1 = service.run_dispatch(run_valid, header_idempotency_key="token-A")
    assert res1.timestamp == 1000

    # Idempotent replay: returns cached result
    res2 = service.run_dispatch(run_valid, header_idempotency_key="token-A")
    assert res2.cycle_id == res1.cycle_id
