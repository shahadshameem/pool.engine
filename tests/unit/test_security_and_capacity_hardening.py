"""Tests for security, capacity synchronization outbox, and server-side circuit breaker hardening."""

import time
import pytest
from pydantic import ValidationError

from engine.adapters.osrm_routing import DefaultOsrmTransport, ServerCircuitBreaker, ServerCircuitState
from engine.contracts.routing import Coordinate, RouteTimeoutError
from engine.domain.enums import RideStatus
from engine.domain.models import GeoCoordinate, Ride, Vehicle
from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.service.config import ServiceConfig
from engine.service.schemas import SyncRideCapacityInput
from engine.service.security import (
    ApiKeyAuthProvider,
    AuthContext,
    NoOpAuthProvider,
    build_auth_provider_from_env,
)
from engine.service.service import PoolEngineService


def test_staging_and_production_require_explicit_credentials_and_prohibit_dev_keys():
    """Verifies Priority 1: Staging and production refuse predictable development keys and fail on missing credentials."""
    # Staging with no credentials -> MUST raise ValueError
    with pytest.raises(ValueError, match="requires explicit, securely-configured authentication credentials"):
        build_auth_provider_from_env(env={"ENVIRONMENT": "staging", "AUTH_ENABLED": "true"})

    # Production with no credentials -> MUST raise ValueError
    with pytest.raises(ValueError, match="requires explicit, securely-configured authentication credentials"):
        build_auth_provider_from_env(env={"ENVIRONMENT": "production", "AUTH_ENABLED": "true"})

    # Development with auth enabled -> Allowed to use dev fallback key for local convenience
    dev_provider = build_auth_provider_from_env(env={"ENVIRONMENT": "development", "AUTH_ENABLED": "true"})
    assert isinstance(dev_provider, ApiKeyAuthProvider)
    ctx = dev_provider.authenticate({}, {"x-api-key": "waymate-dev-secret-key-2026"})
    assert ctx.authenticated is True
    assert "admin" in ctx.roles

    # Staging with explicit production API keys -> Allowed
    staging_provider = build_auth_provider_from_env(
        env={"ENVIRONMENT": "staging", "API_KEYS": "sec-staging-secret-key-999:admin"}
    )
    assert isinstance(staging_provider, ApiKeyAuthProvider)
    # The dev key must NOT work
    ctx_dev = staging_provider.authenticate({}, {"x-api-key": "waymate-dev-secret-key-2026"})
    assert ctx_dev.authenticated is False

    # The explicit staging key works
    ctx_stg = staging_provider.authenticate({}, {"x-api-key": "sec-staging-secret-key-999"})
    assert ctx_stg.authenticated is True


def test_capacity_sync_monotonic_versioning_and_stale_rejection():
    """Verifies Priority 2: Stale capacity updates are rejected and monotonic versions are strictly enforced."""
    storage = InMemoryRideStorage()
    service = PoolEngineService(
        storage=storage,
        orchestrator=None,  # type: ignore[arg-type]
        router=None,  # type: ignore[arg-type]
    )

    # Setup vehicle with 4 seats
    veh = Vehicle(
        vehicle_id="veh_sync_test_1",
        driver_id="driver_1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=8.5458, longitude=76.9032),
        is_active=True,
    )
    storage.save_vehicle(veh)

    # 1. First sync: Booking 2 seats at version 1000
    res1 = service.sync_ride_capacity(
        ride_id="veh_sync_test_1",
        available_seats=2,
        version=1000,
        idempotency_token="idem_1",
    )
    assert res1["synced"] is True
    assert res1["total_seat_capacity"] == 2
    assert storage.get_vehicle("veh_sync_test_1").total_seat_capacity == 2

    # 2. Idempotent hit: Resending with exact same idempotency token
    res1_replay = service.sync_ride_capacity(
        ride_id="veh_sync_test_1",
        available_seats=2,
        version=1000,
        idempotency_token="idem_1",
    )
    assert res1_replay["synced"] is True
    assert res1_replay.get("idempotent_replay") is True

    # 3. Newer sync: Passenger cancels 1 seat, available=3 at version 2000
    res2 = service.sync_ride_capacity(
        ride_id="veh_sync_test_1",
        available_seats=3,
        version=2000,
        idempotency_token="idem_2",
    )
    assert res2["synced"] is True
    assert res2["total_seat_capacity"] == 3
    assert storage.get_vehicle("veh_sync_test_1").total_seat_capacity == 3

    # 4. Out-of-order STALE sync: Delayed event arrives with version 500 (older than 2000)
    res_stale = service.sync_ride_capacity(
        ride_id="veh_sync_test_1",
        available_seats=0,  # Claims vehicle is full
        version=500,        # Stale version!
        idempotency_token="idem_stale",
    )
    assert res_stale["synced"] is False
    assert res_stale.get("rejected") is True
    assert res_stale["reason"] == "stale_version"
    # Authoritative capacity remains intact at 3 seats!
    assert storage.get_vehicle("veh_sync_test_1").total_seat_capacity == 3


def test_server_circuit_breaker_lifecycle():
    """Verifies Priority 5: Server-side circuit breaker isolates downstream failures and recovers."""
    cb = ServerCircuitBreaker(
        failure_threshold=3,
        recovery_timeout_seconds=0.1,  # 100ms for fast test
        half_open_success_threshold=2,
    )

    # Initial state
    assert cb.state == ServerCircuitState.CLOSED
    assert cb.can_execute() is True

    # 2 failures -> stays closed
    cb.record_failure()
    cb.record_failure()
    assert cb.state == ServerCircuitState.CLOSED
    assert cb.can_execute() is True

    # 3rd failure -> trips open
    cb.record_failure()
    assert cb.state == ServerCircuitState.OPEN
    assert cb.can_execute() is False

    # Immediate execution while OPEN is blocked
    assert cb.can_execute() is False

    # Wait for recovery timeout (120ms)
    time.sleep(0.12)

    # Transitions to HALF_OPEN
    assert cb.can_execute() is True
    assert cb.state == ServerCircuitState.HALF_OPEN

    # First success in HALF_OPEN -> stays HALF_OPEN
    cb.record_success()
    assert cb.state == ServerCircuitState.HALF_OPEN

    # Second success in HALF_OPEN -> recovers to CLOSED
    cb.record_success()
    assert cb.state == ServerCircuitState.CLOSED
    assert cb.can_execute() is True
    assert cb.failure_count == 0


def test_sensitive_endpoints_require_auth_and_health_is_public():
    """Verifies Priority 1: Sensitive endpoints reject unauthenticated/invalid requests, while health probes stay public."""
    from engine.adapters.default_policy import DefaultPolicyProvider
    from engine.adapters.h3_spatial import H3SpatialIndexAdapter
    from engine.adapters.mock_routing import MockRoutingProvider
    from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator, OrchestrationConfig
    from engine.service.app import create_app
    from engine.service.client import AsgiTestClient

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

    auth_provider = ApiKeyAuthProvider({"valid-admin-secret-2026": ("admin-user", ("admin", "dispatch_operator"))})
    cfg = ServiceConfig(
        require_auth=True,
        environment="staging",
    )
    app = create_app(service, config=cfg, auth_provider=auth_provider)
    client = AsgiTestClient(app)

    # 1. Health readiness endpoint is public (200 OK without credentials)
    res_health = client.get("/v1/health/readiness")
    assert res_health.status_code == 200

    # 2. Sensitive endpoint without credentials returns 401 Unauthorized
    res_dispatch_unauth = client.post("/v1/dispatch", json={})
    assert res_dispatch_unauth.status_code == 401
    assert res_dispatch_unauth.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

    res_sync_unauth = client.post("/v1/rides/ride_123/sync-capacity", json={"available_seats": 2})
    assert res_sync_unauth.status_code == 401

    # 3. Invalid credentials return 401 Unauthorized
    res_invalid = client.post(
        "/v1/dispatch",
        json={},
        headers={"x-api-key": "invalid-hacker-key"},
    )
    assert res_invalid.status_code == 401

    # 4. Valid credentials succeed (not 401)
    res_valid = client.post(
        "/v1/dispatch",
        json={"current_time": 1000000},
        headers={"x-api-key": "valid-admin-secret-2026"},
    )
    assert res_valid.status_code == 200


def test_asgi_capacity_sync_rejects_stale_versions_with_409():
    """Verifies Priority 2: Pool Engine HTTP endpoint returns 409 STALE_VERSION for outdated updates."""
    from engine.adapters.default_policy import DefaultPolicyProvider
    from engine.adapters.h3_spatial import H3SpatialIndexAdapter
    from engine.adapters.mock_routing import MockRoutingProvider
    from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator, OrchestrationConfig
    from engine.service.app import create_app
    from engine.service.client import AsgiTestClient

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

    veh = Vehicle(
        vehicle_id="veh_asgi_sync_1",
        driver_id="driver_asgi_1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=8.5458, longitude=76.9032),
        is_active=True,
    )
    storage.save_vehicle(veh)

    app = create_app(service, config=ServiceConfig(require_auth=False))
    client = AsgiTestClient(app)

    # 1. Monotonic sync: v1000 sets seats=2 -> 200 OK
    res1 = client.post(
        "/v1/rides/veh_asgi_sync_1/sync-capacity",
        json={"available_seats": 2, "version": 1000},
    )
    assert res1.status_code == 200
    assert res1.json()["total_seat_capacity"] == 2

    # 2. Stale sync: v500 attempts to set seats=4 -> 409 STALE_VERSION
    res_stale = client.post(
        "/v1/rides/veh_asgi_sync_1/sync-capacity",
        json={"available_seats": 4, "version": 500},
    )
    assert res_stale.status_code == 409
    assert res_stale.json()["error"]["code"] == "STALE_VERSION"

    # Capacity remains at authoritative 2 seats
    assert storage.get_vehicle("veh_asgi_sync_1").total_seat_capacity == 2
