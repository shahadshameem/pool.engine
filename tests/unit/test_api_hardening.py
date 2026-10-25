"""Unit tests for Phase 2.3 API hardening, security boundaries, health probes, and telemetry."""

import asyncio
from typing import Any
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.routing import Coordinate
from engine.domain.models import GeoCoordinate
from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator, OrchestrationConfig
from engine.service.app import create_app
from engine.service.client import AsgiTestClient
from engine.service.config import ServiceConfig
from engine.service.security import ApiKeyAuthProvider, NoOpAuthProvider, sanitize_sensitive_strings
from engine.service.service import PoolEngineService
from engine.service.telemetry import InMemoryTelemetry, mask_coordinate


def create_test_service(
    telemetry: InMemoryTelemetry | None = None,
) -> tuple[PoolEngineService, InMemoryRideStorage, InMemoryTelemetry]:
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
    telem = telemetry or InMemoryTelemetry()
    service = PoolEngineService(
        storage=storage,
        orchestrator=orchestrator,
        router=router,
        telemetry=telem,
    )
    return service, storage, telem


def test_liveness_probe() -> None:
    service, _, _ = create_test_service()
    app = create_app(service)
    client = AsgiTestClient(app)

    resp = client.get("/v1/health/liveness")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "alive"
    assert data["service"] == "pool-engine"


def test_readiness_probe_healthy() -> None:
    service, _, _ = create_test_service()
    app = create_app(service)
    client = AsgiTestClient(app)

    resp = client.get("/v1/health/readiness")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is True
    assert data["status"] == "ready"
    assert data["components"]["storage"] == "healthy"


def test_readiness_probe_unhealthy_with_credential_sanitization() -> None:
    service, storage, _ = create_test_service()

    # Simulate database connection failure containing a password in DSN
    def faulty_get_active_rides(limit: int = 100) -> Any:
        raise ConnectionError(
            "FATAL: password authentication failed for user postgresql://postgres:super_secret_pw@10.0.0.1:5432/pool_db"
        )

    storage.get_active_rides = faulty_get_active_rides  # type: ignore[assignment]

    app = create_app(service)
    client = AsgiTestClient(app)

    resp = client.get("/v1/health/readiness")
    assert resp.status_code == 503
    data = resp.json()
    assert data["ready"] is False
    assert data["status"] == "not_ready"
    assert data["components"]["storage"] == "unreachable"

    # Verify credentials were sanitized
    err_msg = data["components"]["storage_error"]
    assert "super_secret_pw" not in err_msg
    assert "postgresql://postgres:***@10.0.0.1:5432/pool_db" in err_msg


def test_body_size_limit_content_length_header() -> None:
    service, _, _ = create_test_service()
    config = ServiceConfig(max_request_body_bytes=1024)
    app = create_app(service, config=config)
    client = AsgiTestClient(app)

    # Content length declared as 2000 bytes > 1024 limit
    resp = client.post(
        "/v1/requests",
        data=b"{}",
        headers={"content-length": "2000"},
    )
    assert resp.status_code == 413
    data = resp.json()
    assert data["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert "1024" in data["error"]["message"]


def test_body_size_limit_stream_accumulation() -> None:
    service, _, _ = create_test_service()
    config = ServiceConfig(max_request_body_bytes=1024)
    app = create_app(service, config=config)

    # Invoke ASGI callable with multiple chunks and no content-length header
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/v1/requests",
        "headers": [(b"content-type", b"application/json")],
    }

    chunks = [b"a" * 600, b"b" * 600]
    chunk_idx = 0

    async def streaming_receive() -> dict[str, Any]:
        nonlocal chunk_idx
        if chunk_idx < len(chunks):
            chunk = chunks[chunk_idx]
            chunk_idx += 1
            return {"type": "http.request", "body": chunk, "more_body": chunk_idx < len(chunks)}
        return {"type": "http.request", "body": b"", "more_body": False}

    response_messages: list[dict[str, Any]] = []

    async def capture_send(msg: dict[str, Any]) -> None:
        response_messages.append(msg)

    async def run_app() -> None:
        await app(scope, streaming_receive, capture_send)

    asyncio.run(run_app())

    start_msg = next(m for m in response_messages if m["type"] == "http.response.start")
    assert start_msg["status"] == 413


def test_invalid_content_length_header() -> None:
    service, _, _ = create_test_service()
    app = create_app(service)
    client = AsgiTestClient(app)

    resp = client.post(
        "/v1/requests",
        data=b"{}",
        headers={"content-length": "invalid-non-numeric"},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert "Invalid Content-Length" in data["error"]["message"]


def test_client_disconnect_during_receive() -> None:
    service, _, _ = create_test_service()
    app = create_app(service)

    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/v1/requests",
        "headers": [],
    }

    async def disconnect_receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}

    sent_messages: list[dict[str, Any]] = []

    async def capture_send(msg: dict[str, Any]) -> None:
        sent_messages.append(msg)

    # Run direct ASGI invocation
    async def run_app() -> None:
        await app(scope, disconnect_receive, capture_send)

    asyncio.run(run_app())
    # On disconnect, server should safely terminate without sending an error response
    assert len(sent_messages) == 0


def test_unhandled_exception_sanitization() -> None:
    service, storage, _ = create_test_service()

    # Simulate an unexpected storage crash leaking a password string
    def crashing_get_request(req_id: str) -> Any:
        raise RuntimeError("Crash with secret postgresql://user:my_secret_token@host:5432/db")

    storage.get_request = crashing_get_request  # type: ignore[assignment]

    app = create_app(service)
    client = AsgiTestClient(app)

    resp = client.get("/v1/requests/req-fail")
    assert resp.status_code == 500
    data = resp.json()
    assert data["error"]["code"] == "INTERNAL_SERVER_ERROR"
    # Client should only receive a safe generic message, not the stack trace or secret
    assert data["error"]["message"] == "An unexpected internal error occurred."
    assert "my_secret_token" not in resp.text
    assert "postgresql" not in resp.text


def test_auth_boundary_disabled_by_default() -> None:
    service, _, _ = create_test_service()
    config = ServiceConfig(require_auth=False)
    app = create_app(service, config=config)
    client = AsgiTestClient(app)

    # Without auth credentials, requests succeed
    resp = client.get("/v1/health")
    assert resp.status_code == 200


def test_auth_boundary_required_missing_token() -> None:
    service, _, _ = create_test_service()
    config = ServiceConfig(require_auth=True)
    auth_provider = ApiKeyAuthProvider({"secret-key-1": ("admin-usr", ("admin",))})
    app = create_app(service, config=config, auth_provider=auth_provider)
    client = AsgiTestClient(app)

    # Health probes remain unauthenticated
    resp_liveness = client.get("/v1/health/liveness")
    assert resp_liveness.status_code == 200
    resp_readiness = client.get("/v1/health/readiness")
    assert resp_readiness.status_code == 200

    # Protected endpoints require authentication
    resp = client.get("/v1/requests/req-123")
    assert resp.status_code == 401
    data = resp.json()
    assert data["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_auth_boundary_valid_token_headers() -> None:
    service, _, _ = create_test_service()
    config = ServiceConfig(require_auth=True)
    auth_provider = ApiKeyAuthProvider({"valid-api-key": ("client-svc", ("admin",))})
    app = create_app(service, config=config, auth_provider=auth_provider)
    client = AsgiTestClient(app)

    # Using X-API-Key
    resp1 = client.get("/v1/requests/req-nonexistent", headers={"x-api-key": "valid-api-key"})
    # Reaches domain handler (404 since request doesn't exist, but authenticated!)
    assert resp1.status_code == 404

    # Using Authorization: Bearer <key>
    resp2 = client.get(
        "/v1/requests/req-nonexistent",
        headers={"authorization": "Bearer valid-api-key"},
    )
    assert resp2.status_code == 404


def test_auth_boundary_forbidden_role() -> None:
    service, _, _ = create_test_service()
    config = ServiceConfig(require_auth=True)
    # Token only has 'read' role, not 'write' or 'admin'
    auth_provider = ApiKeyAuthProvider({"reader-key": ("reader-usr", ("read",))})
    app = create_app(service, config=config, auth_provider=auth_provider)
    client = AsgiTestClient(app)

    # Read action allowed
    resp_read = client.get("/v1/requests/req-nonexistent", headers={"x-api-key": "reader-key"})
    assert resp_read.status_code == 404

    # Write action forbidden (403)
    resp_write = client.post(
        "/v1/requests",
        json={"user_id": "u1"},
        headers={"x-api-key": "reader-key"},
    )
    assert resp_write.status_code == 403
    data = resp_write.json()
    assert data["error"]["code"] == "FORBIDDEN"


def test_in_memory_telemetry_captures_events() -> None:
    telemetry = InMemoryTelemetry()
    service, storage, _ = create_test_service(telemetry=telemetry)
    app = create_app(service, telemetry=telemetry)
    client = AsgiTestClient(app)

    # 1. API request event
    client.get("/v1/health")
    assert len(telemetry.api_requests) == 1
    assert telemetry.api_requests[0]["method"] == "GET"
    assert telemetry.api_requests[0]["path"] == "/v1/health"
    assert telemetry.api_requests[0]["status_code"] == 200
    assert telemetry.api_requests[0]["duration_ms"] >= 0.0

    # 2. Vehicle registration and idempotency
    veh_payload = {
        "vehicle_id": "veh-tel-1",
        "driver_id": "drv-1",
        "total_seat_capacity": 4,
        "current_location": {"latitude": 40.7128, "longitude": -74.0060},
        "is_active": True,
    }
    client.post("/v1/vehicles", json=veh_payload)
    # Duplicate vehicle submission -> idempotency hit
    client.post("/v1/vehicles", json=veh_payload)
    assert any(hit["operation"] == "register_vehicle" for hit in telemetry.idempotency_hits)

    # 3. Dispatch run
    dispatch_payload = {
        "cycle_id": "cycle-tel-1",
        "current_time": 1000,
        "deadline_seconds": 1.0,
    }
    client.post("/v1/dispatch", json=dispatch_payload)
    assert len(telemetry.dispatch_cycles) == 1
    assert telemetry.dispatch_cycles[0]["cycle_id"] == "cycle-tel-1"
    assert telemetry.dispatch_cycles[0]["committed_count"] == 0


def test_mask_coordinate_and_sanitization() -> None:
    # Coordinate masking: ~1.1 km precision
    masked = mask_coordinate(40.758896, -73.985130, precision=2)
    assert masked == (40.76, -73.99)

    # Credential sanitization
    dsn = "postgresql://my_user:secret_p@ssword!@db.internal:5432/fleet"
    sanitized = sanitize_sensitive_strings(dsn)
    assert "secret_p@ssword!" not in sanitized
    assert sanitized == "postgresql://my_user:***@db.internal:5432/fleet"
