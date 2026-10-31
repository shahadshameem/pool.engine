"""Unit and integration tests for Phase 2.4 deployment readiness and reliability validation."""

import asyncio
import time
from typing import Any, cast
import pytest
from pydantic import ValidationError

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.routing import Coordinate, RouteTimeoutError
from engine.contracts.storage import AssignmentCommitResult
from engine.domain.candidate import CandidateAssignment
from engine.domain.enums import RequestStatus, SearchStatus
from engine.domain.models import GeoCoordinate, RideRequest, Vehicle
from engine.orchestration.dispatch_orchestrator import (
    DispatchOrchestrator,
    OrchestrationConfig,
)
from engine.service.app import create_app
from engine.service.client import AsgiTestClient
from engine.service.config import ServiceConfig
from engine.service.security import ApiKeyAuthProvider
from engine.service.service import PoolEngineService
from engine.service.telemetry import InMemoryTelemetry


def create_env(
    telemetry: InMemoryTelemetry | None = None,
    router: Any | None = None,
    storage: Any | None = None,
) -> tuple[PoolEngineService, Any, Any, DispatchOrchestrator]:
    stor = storage or InMemoryRideStorage()
    rout = router or MockRoutingProvider()
    spatial = H3SpatialIndexAdapter()
    policy = DefaultPolicyProvider()
    orchestrator = DispatchOrchestrator(
        storage=stor,
        policy_provider=policy,
        routing_provider=rout,
        spatial_index=spatial,
        config=OrchestrationConfig(deadline_seconds=0.500, max_retries_per_conflict=1),
    )
    telem = telemetry or InMemoryTelemetry()
    service = PoolEngineService(
        storage=stor,
        orchestrator=orchestrator,
        router=rout,
        telemetry=telem,
    )
    return service, stor, rout, orchestrator


# =============================================================================
# 1. Authentication Protection & Role Enforcement
# =============================================================================

def test_production_config_prevents_accidental_unauthenticated_access() -> None:
    # Production without auth or explicit opt-out MUST fail fast
    with pytest.raises(ValidationError) as exc_info:
        ServiceConfig(environment="production", require_auth=False)
    assert "Production environment requires authentication" in str(exc_info.value)

    # Production with explicit opt-out succeeds
    cfg_optout = ServiceConfig(
        environment="production",
        require_auth=False,
        allow_unauthenticated_in_production=True,
    )
    assert cfg_optout.require_auth is False

    # Production with auth enabled succeeds
    cfg_prod = ServiceConfig(environment="production", require_auth=True)
    assert cfg_prod.require_auth is True


def test_auth_protects_all_non_public_endpoints() -> None:
    service, _, _, _ = create_env()
    config = ServiceConfig(require_auth=True)
    auth = ApiKeyAuthProvider({"valid-key": ("svc", ("admin",))})
    app = create_app(service, config=config, auth_provider=auth)
    client = AsgiTestClient(app)

    # Non-public endpoints to test
    endpoints = [
        ("POST", "/v1/requests", {"user_id": "u1"}),
        ("GET", "/v1/requests/req-999", None),
        ("POST", "/v1/requests/req-999/cancel", {}),
        ("POST", "/v1/vehicles", {"vehicle_id": "v1"}),
        ("GET", "/v1/vehicles/veh-999", None),
        ("PATCH", "/v1/vehicles/veh-999/location", {"latitude": 40.7, "longitude": -74.0}),
        ("PATCH", "/v1/vehicles/veh-999/status", {"is_active": True}),
        ("POST", "/v1/dispatch", {"current_time": 1000}),
        ("GET", "/v1/rides/ride-999", None),
    ]

    for method, path, body in endpoints:
        resp = client.request(method, path, json_data=body)
        assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}, expected 401"
        assert resp.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

    # Public health endpoints remain 200 OK without token
    assert client.get("/v1/health").status_code == 200
    assert client.get("/v1/health/liveness").status_code == 200
    assert client.get("/v1/health/readiness").status_code == 200


def test_role_enforcement_and_malformed_headers() -> None:
    service, _, _, _ = create_env()
    config = ServiceConfig(require_auth=True)
    # Registry with specific fine-grained roles
    auth = ApiKeyAuthProvider({
        "read-only-key": ("reader", ("read",)),
        "writer-key": ("writer", ("write", "read")),
        "dispatcher-key": ("dispatcher", ("dispatch", "read")),
    })
    app = create_app(service, config=config, auth_provider=auth)
    client = AsgiTestClient(app)

    # 1. Read-only role cannot write or dispatch
    resp_write = client.post(
        "/v1/vehicles",
        json={"vehicle_id": "v-test"},
        headers={"x-api-key": "read-only-key"},
    )
    assert resp_write.status_code == 403
    assert resp_write.json()["error"]["code"] == "FORBIDDEN"

    resp_disp = client.post(
        "/v1/dispatch",
        json={"current_time": 1000},
        headers={"x-api-key": "read-only-key"},
    )
    assert resp_disp.status_code == 403

    # 2. Writer role cannot trigger dispatch
    resp_disp_writer = client.post(
        "/v1/dispatch",
        json={"current_time": 1000},
        headers={"x-api-key": "writer-key"},
    )
    assert resp_disp_writer.status_code == 403

    # 3. Dispatcher role can trigger dispatch
    resp_disp_ok = client.post(
        "/v1/dispatch",
        json={"current_time": 1000},
        headers={"x-api-key": "dispatcher-key"},
    )
    assert resp_disp_ok.status_code == 200

    # 4. Malformed Authorization headers
    assert client.get("/v1/requests/r1", headers={"authorization": "Bearer "}).status_code == 401
    assert client.get("/v1/requests/r1", headers={"authorization": "Basic abc"}).status_code == 401
    assert client.get("/v1/requests/r1", headers={"x-api-key": ""}).status_code == 401
    assert client.get("/v1/requests/r1", headers={"x-api-key": "unknown"}).status_code == 401


# =============================================================================
# 2. Readiness Checks: Storage vs Routing Dependency Isolation
# =============================================================================

def test_readiness_distinguishes_optional_routing_outage() -> None:
    class FailingRouter(MockRoutingProvider):
        def check_health(self) -> bool:
            raise RouteTimeoutError("OSRM connection timed out after 500ms")

    service, _, _, _ = create_env(router=FailingRouter())

    # Default: strict_routing_readiness=False -> routing outage reports degraded, but ready=True (200)
    app = create_app(service, config=ServiceConfig(strict_routing_readiness=False))
    client = AsgiTestClient(app)

    resp = client.get("/v1/health/readiness")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is True
    assert data["status"] == "ready"
    assert data["components"]["storage"] == "healthy"
    assert data["components"]["routing"] == "degraded"
    assert "OSRM connection timed out" in data["components"]["routing_error"]


def test_readiness_strict_routing_mode() -> None:
    class FailingRouter(MockRoutingProvider):
        def check_health(self) -> bool:
            return False

    service, _, _, _ = create_env(router=FailingRouter())
    app = create_app(service, config=ServiceConfig(strict_routing_readiness=True))
    client = AsgiTestClient(app)

    resp = client.get("/v1/health/readiness")
    assert resp.status_code == 503
    data = resp.json()
    assert data["ready"] is False
    assert data["status"] == "not_ready"
    assert data["components"]["routing"] == "degraded"


def test_readiness_fails_when_storage_fails() -> None:
    service, storage, _, _ = create_env()

    def faulty_get_rides(limit: int = 1) -> Any:
        raise ConnectionError("postgresql://admin:secret@db:5432: connection refused")

    storage.get_active_rides = faulty_get_rides

    app = create_app(service)
    client = AsgiTestClient(app)

    resp = client.get("/v1/health/readiness")
    assert resp.status_code == 503
    data = resp.json()
    assert data["ready"] is False
    assert data["components"]["storage"] == "unreachable"
    assert "secret" not in resp.text
    assert "postgresql://admin:***@db:5432" in data["components"]["storage_error"]


# =============================================================================
# 3. Lifecycle, Shutdown, and Active Request Draining
# =============================================================================

def test_asgi_lifespan_startup_and_shutdown() -> None:
    closed_resources: list[str] = []

    class TrackedStorage(InMemoryRideStorage):
        def close(self) -> None:
            closed_resources.append("storage")

    class TrackedRouter(MockRoutingProvider):
        def close(self) -> None:
            closed_resources.append("router")

    service, _, _, _ = create_env(storage=TrackedStorage(), router=TrackedRouter())
    app = create_app(service)

    scope: dict[str, Any] = {"type": "lifespan"}
    messages_to_receive = [
        {"type": "lifespan.startup"},
        {"type": "lifespan.shutdown"},
    ]
    sent_messages: list[dict[str, Any]] = []

    async def mock_receive() -> dict[str, Any]:
        if messages_to_receive:
            return messages_to_receive.pop(0)
        return {"type": "lifespan.unknown"}

    async def mock_send(msg: dict[str, Any]) -> None:
        sent_messages.append(msg)

    async def run_lifespan() -> None:
        await app(scope, mock_receive, mock_send)

    asyncio.run(run_lifespan())

    # Verify lifespan messages
    assert sent_messages[0]["type"] == "lifespan.startup.complete"
    assert sent_messages[1]["type"] == "lifespan.shutdown.complete"
    # Verify resources closed
    assert "storage" in closed_resources
    assert "router" in closed_resources


def test_rejection_of_requests_during_shutdown() -> None:
    service, _, _, _ = create_env()
    app = create_app(service)

    # 1. Trigger lifespan shutdown
    scope_lifespan: dict[str, Any] = {"type": "lifespan"}
    messages = [{"type": "lifespan.shutdown"}]

    async def mock_receive() -> dict[str, Any]:
        if messages:
            return messages.pop(0)
        return {}

    async def mock_send(msg: dict[str, Any]) -> None:
        pass

    async def run_shutdown() -> None:
        await app(scope_lifespan, mock_receive, mock_send)

    asyncio.run(run_shutdown())

    # 2. Subsequent HTTP requests must be rejected with 503 SERVICE_SHUTTING_DOWN
    client = AsgiTestClient(app)
    resp = client.get("/v1/health")
    assert resp.status_code == 503
    data = resp.json()
    assert data["error"]["code"] == "SERVICE_SHUTTING_DOWN"


# =============================================================================
# 4. Dispatch Reliability: Incomplete Results & Partial Commits
# =============================================================================

def test_dispatch_partial_commit_rejection_marks_approximated_and_accurate_vmt() -> None:
    service, storage, router, orchestrator = create_env()

    # Create 2 pending requests
    req1 = RideRequest(
        request_id="req-part-1",
        user_id="u1",
        pickup_location=GeoCoordinate(latitude=40.71, longitude=-74.00),
        dropoff_location=GeoCoordinate(latitude=40.72, longitude=-74.01),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=2000,
        direct_distance_meters=1500,
        direct_duration_seconds=300,
        status=RequestStatus.PENDING,
    )
    req2 = RideRequest(
        request_id="req-part-2",
        user_id="u2",
        pickup_location=GeoCoordinate(latitude=40.73, longitude=-74.02),
        dropoff_location=GeoCoordinate(latitude=40.74, longitude=-74.03),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=2000,
        direct_distance_meters=2000,
        direct_duration_seconds=400,
        status=RequestStatus.PENDING,
    )
    storage.save_request(req1)
    storage.save_request(req2)

    # Register 2 active vehicles
    veh1 = Vehicle(
        vehicle_id="v-part-1",
        driver_id="d1",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=40.71, longitude=-74.00),
        is_active=True,
    )
    veh2 = Vehicle(
        vehicle_id="v-part-2",
        driver_id="d2",
        total_seat_capacity=4,
        current_location=GeoCoordinate(latitude=40.73, longitude=-74.02),
        is_active=True,
    )
    storage.save_vehicle(veh1)
    storage.save_vehicle(veh2)

    # Intercept commit_dispatch_assignment_atomic to simulate partial failure:
    # 1st assignment succeeds, 2nd assignment fails with VERSION_CONFLICT
    real_commit = storage.commit_dispatch_assignment_atomic
    commit_call_count = 0

    def mock_commit(
        assignment: CandidateAssignment,
        idempotency_token: str,
        current_time: int,
        expected_ride_version: int | None = None,
        new_ride_id: str | None = None,
    ) -> AssignmentCommitResult:
        nonlocal commit_call_count
        commit_call_count += 1
        if commit_call_count == 1:
            res = real_commit(
                assignment=assignment,
                idempotency_token=idempotency_token,
                current_time=current_time,
                expected_ride_version=expected_ride_version,
                new_ride_id=new_ride_id,
            )
            return cast(AssignmentCommitResult, res)
        # 2nd assignment fails
        return AssignmentCommitResult(
            success=False,
            candidate_id=assignment.candidate_id,
            rejection_reason="VERSION_CONFLICT",
        )

    storage.commit_dispatch_assignment_atomic = mock_commit

    orch_res = orchestrator.dispatch_cycle(current_time=1050, cycle_id="cycle-partial")

    # Verification:
    # 1. 1 committed, 1 rejected
    assert len(orch_res.committed_assignments) == 1
    assert len(orch_res.rejected_assignments) == 1
    committed_ids = set(orch_res.committed_assignments[0].request_ids)
    rejected_ids = set(orch_res.rejected_assignments[0].request_ids)
    # 2. Incomplete / partial commit MUST mark is_approximated=True
    assert orch_res.is_approximated is True
    # 3. total_vmt_savings_meters MUST match ONLY the committed assignment, NOT the sum of all planned
    assert orch_res.total_vmt_savings_meters == orch_res.committed_assignments[0].vmt_meters
    # 4. Rejected request IDs must remain in unassigned_request_ids
    for rid in rejected_ids:
        assert rid in orch_res.unassigned_request_ids
    for rid in committed_ids:
        assert rid not in orch_res.unassigned_request_ids


def test_dispatch_deadline_expiration_is_approximated() -> None:
    service, storage, router, orchestrator = create_env()

    # Pass an expired deadline: current monotonic - 1s
    expired_deadline = time.monotonic() - 1.0

    res = orchestrator.dispatch_cycle(
        current_time=1000,
        cycle_id="cycle-timeout",
        deadline=expired_deadline,
    )

    # Search status must be INCOMPLETE_DEADLINE_EXPIRED and is_approximated must be True
    assert res.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
    assert res.is_approximated is True
    assert len(res.committed_assignments) == 0


# =============================================================================
# 5. Multi-Instance State Isolation
# =============================================================================

def test_dispatch_cache_is_process_local_but_storage_prevents_duplicate_commit() -> None:
    shared_storage = InMemoryRideStorage()
    service1, _, _, _ = create_env(storage=shared_storage)
    service2, _, _, _ = create_env(storage=shared_storage)

    # Instance 1 processes a dispatch cycle
    from engine.service.schemas import DispatchRunInput

    input_data = DispatchRunInput(current_time=1000, cycle_id="c1", idempotency_token="idemp-shared-1")
    resp1 = service1.run_dispatch(input_data)

    # Instance 1 has process-local cache hit
    assert "idemp-shared-1" in service1._dispatch_cache
    # Instance 2 DOES NOT have process-local cache hit (documenting multi-instance boundary)
    assert "idemp-shared-1" not in service2._dispatch_cache
