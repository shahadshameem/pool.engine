"""Unit and integration tests for Firebase ID token authentication, composite auth, and CORS."""

import time
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
from engine.service.schemas import CreateHostRideInput, CreateRideRequestInput, ProposalDecisionInput
from engine.service.security import (
    ApiKeyAuthProvider,
    AuthContext,
    CompositeAuthProvider,
    FirebaseAuthProvider,
    NoOpAuthProvider,
    build_auth_provider_from_env,
)
from engine.service.service import PoolEngineService
from engine.service.telemetry import InMemoryTelemetry


def make_test_service() -> tuple[PoolEngineService, InMemoryRideStorage]:
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
        telemetry=InMemoryTelemetry(),
    )
    return service, storage


def mock_firebase_verifier(token: str) -> dict[str, Any]:
    """Test verifier simulating cryptographic verification of Firebase ID tokens."""
    if token == "valid-user-token":
        return {
            "uid": "fb-user-123",
            "email": "user123@example.com",
            "aud": "waymate-app",
            "iss": "https://securetoken.google.com/waymate-app",
            "exp": int(time.time()) + 3600,
        }
    elif token == "valid-admin-token":
        return {
            "uid": "fb-admin-999",
            "email": "admin@waymate.com",
            "aud": "waymate-app",
            "iss": "https://securetoken.google.com/waymate-app",
            "admin": True,
            "roles": ["admin"],
            "exp": int(time.time()) + 3600,
        }
    elif token == "user-2-token":
        return {
            "uid": "fb-user-456",
            "email": "user456@example.com",
            "aud": "waymate-app",
            "iss": "https://securetoken.google.com/waymate-app",
            "exp": int(time.time()) + 3600,
        }
    elif token == "expired-token":
        raise ValueError("Firebase ID token has expired (exp: 1000)")
    elif token == "wrong-audience-token":
        return {
            "uid": "fb-user-evil",
            "aud": "unauthorized-different-project",
            "iss": "https://securetoken.google.com/unauthorized-different-project",
            "exp": int(time.time()) + 3600,
        }
    elif token == "malformed-token":
        raise ValueError("Decoding Firebase ID token failed: signature invalid")
    else:
        raise ValueError(f"Unknown mock token '{token}'")


def test_firebase_valid_token_authentication() -> None:
    service, _ = make_test_service()
    config = ServiceConfig(require_auth=True, firebase_project_id="waymate-app")
    fb_auth = FirebaseAuthProvider(
        project_id="waymate-app",
        verifier=mock_firebase_verifier,
    )
    app = create_app(service, config=config, auth_provider=fb_auth)
    client = AsgiTestClient(app)

    # 1. Missing header returns 401
    resp_missing = client.get("/v1/requests/req-any")
    assert resp_missing.status_code == 401
    assert resp_missing.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

    # 2. Malformed token returns 401
    resp_bad = client.get(
        "/v1/requests/req-any",
        headers={"authorization": "Bearer malformed-token"},
    )
    assert resp_bad.status_code == 401
    assert resp_bad.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

    # 3. Expired token returns 401
    resp_exp = client.get(
        "/v1/requests/req-any",
        headers={"authorization": "Bearer expired-token"},
    )
    assert resp_exp.status_code == 401

    # 4. Wrong audience/project returns 401
    resp_aud = client.get(
        "/v1/requests/req-any",
        headers={"authorization": "Bearer wrong-audience-token"},
    )
    assert resp_aud.status_code == 401


def test_firebase_user_ownership_enforcement() -> None:
    service, storage = make_test_service()
    config = ServiceConfig(require_auth=True, firebase_project_id="waymate-app")
    fb_auth = FirebaseAuthProvider(
        project_id="waymate-app",
        verifier=mock_firebase_verifier,
    )
    app = create_app(service, config=config, auth_provider=fb_auth)
    client = AsgiTestClient(app)

    user1_headers = {"authorization": "Bearer valid-user-token"}
    user2_headers = {"authorization": "Bearer user-2-token"}

    # User 1 creates a request
    resp_create = client.post(
        "/v1/requests",
        json={
            "pickup_location": {"latitude": 8.545, "longitude": 76.905},
            "dropoff_location": {"latitude": 8.505, "longitude": 76.955},
            "seat_count": 1,
            "earliest_departure_time": 1000,
            "latest_arrival_time": 2000,
        },
        headers=user1_headers,
    )
    assert resp_create.status_code == 201
    req_data = resp_create.json()
    req_id = req_data["request_id"]
    assert req_data["user_id"] == "fb-user-123"

    # User 1 attempting to forge another user's rider_id in request body is rejected
    resp_forge = client.post(
        "/v1/requests",
        json={
            "rider_id": "impersonated-user-999",
            "pickup_location": {"latitude": 8.545, "longitude": 76.905},
            "dropoff_location": {"latitude": 8.505, "longitude": 76.955},
            "seat_count": 1,
            "earliest_departure_time": 1000,
            "latest_arrival_time": 2000,
        },
        headers=user1_headers,
    )
    assert resp_forge.status_code == 403
    assert resp_forge.json()["error"]["code"] == "FORBIDDEN"

    # User 1 can view their own request
    resp_get_own = client.get(f"/v1/requests/{req_id}", headers=user1_headers)
    assert resp_get_own.status_code == 200

    # User 2 cannot view User 1's request
    resp_get_other = client.get(f"/v1/requests/{req_id}", headers=user2_headers)
    assert resp_get_other.status_code == 403
    assert resp_get_other.json()["error"]["code"] == "FORBIDDEN"

    # User 2 cannot cancel User 1's request
    resp_cancel_other = client.post(
        f"/v1/requests/{req_id}/cancel",
        json={"reason": "Malicious cancellation attempt"},
        headers=user2_headers,
    )
    assert resp_cancel_other.status_code == 403

    # User 1 can safely cancel their own request
    resp_cancel_own = client.post(
        f"/v1/requests/{req_id}/cancel",
        json={"reason": "Plans changed"},
        headers=user1_headers,
    )
    assert resp_cancel_own.status_code == 200
    assert resp_cancel_own.json()["status"] == "CANCELLED"


def test_host_ride_ownership_and_matching_isolation() -> None:
    service, _ = make_test_service()
    config = ServiceConfig(require_auth=True, firebase_project_id="waymate-app")
    fb_auth = FirebaseAuthProvider(
        project_id="waymate-app",
        verifier=mock_firebase_verifier,
    )
    app = create_app(service, config=config, auth_provider=fb_auth)
    client = AsgiTestClient(app)

    user1_headers = {"authorization": "Bearer valid-user-token"}  # uid: fb-user-123
    user2_headers = {"authorization": "Bearer user-2-token"}       # uid: fb-user-456

    # 1. User 1 creates a host ride
    resp_host = client.post(
        "/v1/host-rides",
        json={
            "origin": {"latitude": 8.545, "longitude": 76.905},
            "destination": {"latitude": 8.505, "longitude": 76.955},
            "scheduled_departure_time": 2000,
            "available_seats": 3,
            "max_detour_seconds": 600,
        },
        headers=user1_headers,
    )
    assert resp_host.status_code == 201
    ride_data = resp_host.json()
    ride_id = ride_data["ride_id"]
    assert ride_data["driver_id"] == "fb-user-123"

    # 2. User 1 attempting to impersonate another driver_id is forbidden
    resp_impersonate = client.post(
        "/v1/host-rides",
        json={
            "driver_id": "other-driver-999",
            "origin": {"latitude": 8.545, "longitude": 76.905},
            "destination": {"latitude": 8.505, "longitude": 76.955},
            "scheduled_departure_time": 2000,
            "available_seats": 3,
            "max_detour_seconds": 600,
        },
        headers=user1_headers,
    )
    assert resp_impersonate.status_code == 403

    # 3. User 1 can view host ride
    resp_get = client.get(f"/v1/host-rides/{ride_id}", headers=user1_headers)
    assert resp_get.status_code == 200

    # 4. User 2 cannot view User 1's host ride
    resp_get_unauthorized = client.get(f"/v1/host-rides/{ride_id}", headers=user2_headers)
    assert resp_get_unauthorized.status_code == 403

    # 5. User 2 cannot trigger matching on User 1's host ride
    resp_match_unauthorized = client.post(
        f"/v1/host-rides/{ride_id}/match",
        json={},
        headers=user2_headers,
    )
    assert resp_match_unauthorized.status_code == 403

    # 6. User 1 can trigger matching
    resp_match_authorized = client.post(
        f"/v1/host-rides/{ride_id}/match",
        json={},
        headers=user1_headers,
    )
    assert resp_match_authorized.status_code == 200


def test_proposal_mutual_consent_and_authorization() -> None:
    service, storage = make_test_service()
    config = ServiceConfig(require_auth=True, firebase_project_id="waymate-app")
    fb_auth = FirebaseAuthProvider(
        project_id="waymate-app",
        verifier=mock_firebase_verifier,
    )
    app = create_app(service, config=config, auth_provider=fb_auth)
    client = AsgiTestClient(app)

    host_headers = {"authorization": "Bearer valid-user-token"}   # uid: fb-user-123
    rider_headers = {"authorization": "Bearer user-2-token"}       # uid: fb-user-456
    admin_headers = {"authorization": "Bearer valid-admin-token"} # uid: fb-admin-999

    # Setup entities with host (fb-user-123) and traveller (fb-user-456)
    from tests.unit.test_proposals_api import _setup_proposal_fixtures
    _, ride, req = _setup_proposal_fixtures(storage)
    ride = ride.model_copy(update={"driver_id": "fb-user-123"})
    req = req.model_copy(update={"user_id": "fb-user-456"})
    storage.save_ride(ride)
    storage.save_request(req)

    ride_id = ride.ride_id
    req_id = req.request_id

    # Admin creates proposal for the ride and request
    resp_prop = client.post(
        "/v1/proposals",
        json={
            "ride_id": ride_id,
            "request_id": req_id,
            "seat_count": 1,
        },
        headers=admin_headers,
    )
    assert resp_prop.status_code == 201
    proposal_id = resp_prop.json()["proposal_id"]

    # Mutual consent test:
    # 1. Host attempts to accept as traveller -> forbidden
    resp_host_as_traveller = client.post(
        f"/v1/proposals/{proposal_id}/accept",
        json={"role": "traveller"},
        headers=host_headers,
    )
    assert resp_host_as_traveller.status_code == 403
    assert "Host participant cannot accept on behalf of traveller" in resp_host_as_traveller.json()["error"]["message"]

    # 2. Host accepts legitimately
    resp_host_accept = client.post(
        f"/v1/proposals/{proposal_id}/accept",
        json={"role": "host"},
        headers=host_headers,
    )
    assert resp_host_accept.status_code == 200
    res1 = resp_host_accept.json()
    assert res1["host_accepted"] is True
    assert res1["traveller_accepted"] is False
    assert res1["is_confirmed"] is False

    # 3. Traveller accepts legitimately -> confirmation commits
    resp_rider_accept = client.post(
        f"/v1/proposals/{proposal_id}/accept",
        json={"role": "traveller"},
        headers=rider_headers,
    )
    assert resp_rider_accept.status_code == 200
    res2 = resp_rider_accept.json()
    assert res2["host_accepted"] is True
    assert res2["traveller_accepted"] is True
    assert res2["is_confirmed"] is True


def test_composite_auth_compatibility() -> None:
    """Verifies that API keys and Firebase ID tokens operate seamlessly in CompositeAuthProvider."""
    service, _ = make_test_service()
    config = ServiceConfig(require_auth=True)

    api_auth = ApiKeyAuthProvider({"svc-key-1": ("admin-backend", ("admin",))})
    fb_auth = FirebaseAuthProvider(project_id="waymate-app", verifier=mock_firebase_verifier)
    composite = CompositeAuthProvider(api_key_provider=api_auth, firebase_provider=fb_auth)

    app = create_app(service, config=config, auth_provider=composite)
    client = AsgiTestClient(app)

    # 1. Calls with X-API-Key succeed
    resp_key = client.get("/v1/requests/req-none", headers={"x-api-key": "svc-key-1"})
    # Not found (404) means auth succeeded and reached the domain handler
    assert resp_key.status_code == 404

    # 2. Calls with Bearer API key succeed
    resp_bearer_key = client.get("/v1/requests/req-none", headers={"authorization": "Bearer svc-key-1"})
    assert resp_bearer_key.status_code == 404

    # 3. Calls with Bearer Firebase ID token succeed
    resp_fb = client.get("/v1/requests/req-none", headers={"authorization": "Bearer valid-user-token"})
    assert resp_fb.status_code == 404

    # 4. Calls with bad token fail (401)
    resp_fail = client.get("/v1/requests/req-none", headers={"authorization": "Bearer invalid-unknown"})
    assert resp_fail.status_code == 401


def test_production_refuses_unsafe_noop_auth() -> None:
    """Ensures production configuration strictly refuses unsafe NoOp authentication."""
    # 1. ServiceConfig validation rejects production with require_auth=False
    with pytest.raises(ValueError, match="Production environment requires authentication"):
        ServiceConfig(environment="production", require_auth=False)

    # 2. build_auth_provider_from_env rejects NoOpAuthProvider in production
    with pytest.raises(ValueError, match="Production environment requires a configured authentication provider"):
        build_auth_provider_from_env(
            env={"ENVIRONMENT": "production", "REQUIRE_AUTH": "true"},
            config=ServiceConfig(environment="production", require_auth=True, allow_unauthenticated_in_production=False),
        )

    # 3. Wildcard CORS rejected in production with require_auth=True
    with pytest.raises(ValueError, match="Production environment cannot use wildcard"):
        ServiceConfig(
            environment="production",
            require_auth=True,
            cors_allowed_origins=("*",),
            allow_unauthenticated_in_production=False,
        )


def test_cors_preflight_and_response_headers() -> None:
    service, _ = make_test_service()
    config = ServiceConfig(
        require_auth=False,
        cors_allowed_origins=("http://localhost:5173", "https://wmate.web.app"),
    )
    app = create_app(service, config=config)
    client = AsgiTestClient(app)

    # 1. OPTIONS preflight from allowed origin
    resp_preflight = client.options(
        "/v1/host-rides",
        headers={"origin": "http://localhost:5173"},
    )
    assert resp_preflight.status_code == 204
    assert resp_preflight.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "authorization" in resp_preflight.headers.get("access-control-allow-headers", "").lower()

    # 2. OPTIONS preflight from disallowed origin
    resp_disallowed = client.options(
        "/v1/host-rides",
        headers={"origin": "http://evil-attacker.com"},
    )
    assert resp_disallowed.status_code == 403
    assert resp_disallowed.json()["error"]["code"] == "CORS_ORIGIN_NOT_ALLOWED"

    # 3. GET request carries CORS header for allowed origin
    resp_get = client.get(
        "/v1/health",
        headers={"origin": "https://wmate.web.app"},
    )
    assert resp_get.status_code == 200
    assert resp_get.headers.get("access-control-allow-origin") == "https://wmate.web.app"


def test_vehicle_ownership_and_dispatch_role_enforcement() -> None:
    service, _ = make_test_service()
    config = ServiceConfig(require_auth=True, firebase_project_id="waymate-app")
    fb_auth = FirebaseAuthProvider(
        project_id="waymate-app",
        verifier=mock_firebase_verifier,
    )
    app = create_app(service, config=config, auth_provider=fb_auth)
    client = AsgiTestClient(app)

    user1_headers = {"authorization": "Bearer valid-user-token"}   # uid: fb-user-123
    user2_headers = {"authorization": "Bearer user-2-token"}       # uid: fb-user-456
    admin_headers = {"authorization": "Bearer valid-admin-token"} # uid: fb-admin-999

    # 1. User 1 registers a vehicle
    resp_veh = client.post(
        "/v1/vehicles",
        json={
            "vehicle_id": "veh-user1",
            "total_seat_capacity": 4,
            "current_location": {"latitude": 8.545, "longitude": 76.905},
        },
        headers=user1_headers,
    )
    assert resp_veh.status_code == 201
    assert resp_veh.json()["driver_id"] == "fb-user-123"

    # 2. User 2 cannot inspect User 1's vehicle
    resp_get_veh = client.get("/v1/vehicles/veh-user1", headers=user2_headers)
    assert resp_get_veh.status_code == 403
    assert resp_get_veh.json()["error"]["code"] == "FORBIDDEN"

    # 3. User 2 cannot update User 1's vehicle location
    resp_patch_loc = client.patch(
        "/v1/vehicles/veh-user1/location",
        json={"latitude": 8.550, "longitude": 76.910},
        headers=user2_headers,
    )
    assert resp_patch_loc.status_code == 403

    # 4. User 2 cannot update User 1's vehicle status
    resp_patch_status = client.patch(
        "/v1/vehicles/veh-user1/status",
        json={"is_active": False},
        headers=user2_headers,
    )
    assert resp_patch_status.status_code == 403

    # 5. User 1 can update their own vehicle location
    resp_patch_loc_own = client.patch(
        "/v1/vehicles/veh-user1/location",
        json={"latitude": 8.550, "longitude": 76.910},
        headers=user1_headers,
    )
    assert resp_patch_loc_own.status_code == 200

    # 6. Regular Firebase user attempting dispatch is denied with 403
    resp_dispatch_denied = client.post(
        "/v1/dispatch",
        json={"current_time": 1000},
        headers=user1_headers,
    )
    assert resp_dispatch_denied.status_code == 403
    assert resp_dispatch_denied.json()["error"]["code"] == "FORBIDDEN"

    # 7. Admin Firebase user can trigger dispatch
    resp_dispatch_admin = client.post(
        "/v1/dispatch",
        json={"current_time": 1000},
        headers=admin_headers,
    )
    assert resp_dispatch_admin.status_code == 200


def test_proposal_non_participant_isolation_and_decline_authorization() -> None:
    service, storage = make_test_service()
    config = ServiceConfig(require_auth=True, firebase_project_id="waymate-app")
    fb_auth = FirebaseAuthProvider(
        project_id="waymate-app",
        verifier=mock_firebase_verifier,
    )
    app = create_app(service, config=config, auth_provider=fb_auth)
    client = AsgiTestClient(app)

    host_headers = {"authorization": "Bearer valid-user-token"}   # uid: fb-user-123
    rider_headers = {"authorization": "Bearer user-2-token"}       # uid: fb-user-456
    admin_headers = {"authorization": "Bearer valid-admin-token"} # uid: fb-admin-999

    from tests.unit.test_proposals_api import _setup_proposal_fixtures
    _, ride, req = _setup_proposal_fixtures(storage)
    ride = ride.model_copy(update={"driver_id": "fb-user-123"})
    req = req.model_copy(update={"user_id": "fb-user-456"})
    storage.save_ride(ride)
    storage.save_request(req)

    resp_prop = client.post(
        "/v1/proposals",
        json={"ride_id": ride.ride_id, "request_id": req.request_id, "seat_count": 1},
        headers=admin_headers,
    )
    proposal_id = resp_prop.json()["proposal_id"]

    # Simulate third unrelated user
    def verifier_user3(token: str) -> dict[str, Any]:
        if token == "user-3-token":
            return {
                "uid": "fb-user-789",
                "email": "intruder@example.com",
                "aud": "waymate-app",
                "iss": "https://securetoken.google.com/waymate-app",
                "exp": int(time.time()) + 3600,
            }
        return mock_firebase_verifier(token)

    fb_auth._custom_verifier = verifier_user3
    user3_headers = {"authorization": "Bearer user-3-token"}

    # 1. Unrelated user attempting to inspect proposal receives 403 Forbidden
    resp_inspect_unauth = client.get(f"/v1/proposals/{proposal_id}", headers=user3_headers)
    assert resp_inspect_unauth.status_code == 403
    assert resp_inspect_unauth.json()["error"]["code"] == "FORBIDDEN"

    # 2. Unrelated user attempting to decline proposal receives 403 Forbidden
    resp_decline_unauth = client.post(
        f"/v1/proposals/{proposal_id}/decline",
        json={"reason": "Intrusion attempt"},
        headers=user3_headers,
    )
    assert resp_decline_unauth.status_code == 403

    # 3. Legitimate traveller can decline the proposal
    resp_decline_legit = client.post(
        f"/v1/proposals/{proposal_id}/decline",
        json={"reason": "No longer needed"},
        headers=rider_headers,
    )
    assert resp_decline_legit.status_code == 200
    assert resp_decline_legit.json()["status"] == "DECLINED"
