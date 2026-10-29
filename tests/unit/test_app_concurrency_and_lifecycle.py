"""Unit tests for FastAPI / ASGI concurrency, event-loop offloading, and pool lifecycle.

Verifies:
1. Application startup initializes storage exactly once via lifespan.
2. Application shutdown closes owned resources safely.
3. Injected connections are preserved and not closed on shutdown.
4. Slow synchronous database operations do not block concurrent event-loop tasks.
5. Pool exhaustion produces a controlled RFC 7807 error response (HTTP 503).
6. Readiness probe reports unavailable storage when persistent storage is required but missing.
7. Readiness probe reports unreachable when database query fails.
"""

import asyncio
import time
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.mock_routing import MockRoutingProvider
from engine.adapters.postgres_storage import PostgresRideStorage
from engine.contracts.storage import StorageProviderError
from engine.domain.models import GeoCoordinate
from engine.service.app import create_app
from engine.service.client import AsgiTestClient
from engine.service.config import ServiceConfig
from engine.service.schemas import CreateRideRequestInput, UpdateLocationInput
from engine.service.service import PoolEngineService


class MockStorageWithLifecycle(InMemoryRideStorage):
    """Storage mock recording open and close lifecycle calls."""

    def __init__(self) -> None:
        super().__init__()
        self.open_call_count = 0
        self.close_call_count = 0

    def open(self) -> None:
        self.open_call_count += 1

    def close(self) -> None:
        self.close_call_count += 1


def _build_test_service(storage: Any) -> PoolEngineService:
    from engine.adapters.default_policy import DefaultPolicyProvider
    from engine.adapters.h3_spatial import H3SpatialIndexAdapter
    from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator
    from engine.service.telemetry import StructuredLoggerTelemetry

    router = MockRoutingProvider()
    spatial = H3SpatialIndexAdapter()
    policy = DefaultPolicyProvider()
    orchestrator = DispatchOrchestrator(
        storage=storage,
        policy_provider=policy,
        routing_provider=router,
        spatial_index=spatial,
    )
    return PoolEngineService(
        storage=storage,
        orchestrator=orchestrator,
        router=router,
        telemetry=StructuredLoggerTelemetry(),
    )


def test_lifespan_startup_initializes_storage_once() -> None:
    storage = MockStorageWithLifecycle()
    service = _build_test_service(storage)
    app = create_app(service=service)

    async def run() -> None:
        scope = {"type": "lifespan"}
        events_received: list[str] = []
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        queue.put_nowait({"type": "lifespan.startup"})

        async def receive() -> dict[str, str]:
            return await queue.get()

        async def send(message: dict[str, str]) -> None:
            events_received.append(message.get("type", ""))
            if message.get("type") == "lifespan.startup.complete":
                queue.put_nowait({"type": "lifespan.shutdown"})

        await app(scope, receive, send)
        assert "lifespan.startup.complete" in events_received
        assert "lifespan.shutdown.complete" in events_received

    asyncio.run(run())
    assert storage.open_call_count == 1
    assert storage.close_call_count == 1


def test_injected_connection_not_closed_on_app_shutdown() -> None:
    mock_conn = MagicMock()
    mock_conn.closed = False
    mock_conn.broken = False

    storage = PostgresRideStorage(connection=mock_conn)
    service = _build_test_service(storage)
    app = create_app(service=service)

    async def run() -> None:
        scope = {"type": "lifespan"}
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        queue.put_nowait({"type": "lifespan.startup"})

        async def receive() -> dict[str, str]:
            return await queue.get()

        async def send(message: dict[str, str]) -> None:
            if message.get("type") == "lifespan.startup.complete":
                queue.put_nowait({"type": "lifespan.shutdown"})

        await app(scope, receive, send)

    asyncio.run(run())
    # External connection must not be closed by application shutdown
    assert mock_conn.close.call_count == 0


def test_event_loop_unblocked_during_slow_storage_operation() -> None:
    class SlowStorage(InMemoryRideStorage):
        def get_request(self, request_id: str) -> Any:
            # Simulate slow database query (blocking socket I/O in worker thread)
            time.sleep(0.15)
            return super().get_request(request_id)

    slow_storage = SlowStorage()
    service = _build_test_service(slow_storage)
    app = create_app(service=service)

    async def run_scenario() -> None:
        # Create an ASGI client in async context
        client = AsgiTestClient(app)

        # Background task that checks /v1/health repeatedly while the slow request executes
        health_latencies: list[float] = []
        stop_health = False

        async def probe_health() -> None:
            while not stop_health:
                t0 = time.monotonic()
                resp = await client._async_request("GET", "/v1/health")
                t1 = time.monotonic()
                assert resp.status_code == 200
                health_latencies.append(t1 - t0)
                await asyncio.sleep(0.01)

        health_task = asyncio.create_task(probe_health())

        # Fire slow request
        t_req_start = time.monotonic()
        req_resp = await client._async_request("GET", "/v1/requests/req-nonexistent")
        t_req_end = time.monotonic()

        stop_health = True
        await health_task

        # Slow request should have taken >= 0.15s
        assert (t_req_end - t_req_start) >= 0.14
        assert req_resp.status_code == 404

        # Health probes must have executed concurrently during the slow request
        # and none of them should have been blocked for 0.15s
        assert len(health_latencies) >= 3
        max_health_latency = max(health_latencies)
        assert max_health_latency < 0.08, f"Event loop was blocked! Max health latency: {max_health_latency}s"

    asyncio.run(run_scenario())


def test_pool_exhaustion_returns_503_storage_pool_exhausted() -> None:
    class ExhaustedStorage(InMemoryRideStorage):
        def get_request(self, request_id: str) -> Any:
            raise StorageProviderError("Database connection pool exhausted (timeout=5.0s)")

    service = _build_test_service(ExhaustedStorage())
    app = create_app(service=service)
    client = AsgiTestClient(app)

    resp = client.get("/v1/requests/req-test-1")
    assert resp.status_code == 503
    data = resp.json()
    assert data["error"]["code"] == "STORAGE_POOL_EXHAUSTED"
    assert "exhausted" in data["error"]["message"].lower()


def test_generic_storage_error_returns_503_storage_unavailable() -> None:
    class UnavailableStorage(InMemoryRideStorage):
        def get_request(self, request_id: str) -> Any:
            raise StorageProviderError("Connection refused by database server")

    service = _build_test_service(UnavailableStorage())
    app = create_app(service=service)
    client = AsgiTestClient(app)

    resp = client.get("/v1/requests/req-test-1")
    assert resp.status_code == 503
    data = resp.json()
    assert data["error"]["code"] == "STORAGE_UNAVAILABLE"


def test_readiness_probe_reports_unavailable_when_persistent_storage_required_but_in_memory() -> None:
    in_memory = InMemoryRideStorage()
    service = _build_test_service(in_memory)
    config = ServiceConfig(require_persistent_storage=True)
    app = create_app(service=service, config=config)
    client = AsgiTestClient(app)

    resp = client.get("/v1/health/readiness")
    assert resp.status_code == 503
    data = resp.json()
    assert data["ready"] is False
    assert data["components"]["storage"] == "unavailable"


def test_readiness_probe_reports_unreachable_on_db_exception() -> None:
    class FailingStorage(InMemoryRideStorage):
        def get_active_rides(self, limit: int = 100) -> Any:
            raise StorageProviderError("connection to postgresql://postgres:secret_pass123@127.0.0.1:5433/db failed")

    service = _build_test_service(FailingStorage())
    app = create_app(service=service)
    client = AsgiTestClient(app)

    resp = client.get("/v1/health/readiness")
    assert resp.status_code == 503
    data = resp.json()
    assert data["ready"] is False
    assert data["components"]["storage"] == "unreachable"
    # Ensure sensitive credentials in connection strings are sanitized
    storage_err = data["components"].get("storage_error", "")
    assert "secret_pass123" not in storage_err
    assert "postgresql://postgres:***@127.0.0.1:5433" in storage_err
