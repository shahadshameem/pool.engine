"""Unit tests verifying marketplace proposal lifecycle and bilateral mutual acceptance APIs."""

import time
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.mock_routing import MockRoutingProvider
from engine.domain.enums import JoinStatus, RequestStatus, RideStatus
from engine.domain.models import GeoCoordinate, Ride, RideRequest, Vehicle
from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator, OrchestrationConfig
from engine.service.app import create_app
from engine.service.client import AsgiTestClient
from engine.service.config import ServiceConfig
from engine.service.schemas import CreateProposalInput
from engine.service.security import ApiKeyAuthProvider
from engine.service.service import PoolEngineService


def _setup_proposal_fixtures(
    storage: InMemoryRideStorage,
    capacity: int = 4,
    base_time: int | None = None,
) -> tuple[Vehicle, Ride, RideRequest]:
    """Helper creating a test vehicle, active ride (host), and pending request (traveller)."""
    now = base_time if base_time is not None else int(time.time())

    vehicle = Vehicle(
        vehicle_id="veh-host-1",
        driver_id="usr-host-1",
        total_seat_capacity=capacity,
        current_location=GeoCoordinate(latitude=40.7580, longitude=-73.9855),
        is_active=True,
    )
    storage.save_vehicle(vehicle)

    ride = Ride(
        ride_id="ride-host-1",
        vehicle_id=vehicle.vehicle_id,
        driver_id=vehicle.driver_id,
        lifecycle_status=RideStatus.ACTIVE,
        stops=(),
        scheduled_departure_time=now,
        active_passenger_count=0,
        version=1,
    )
    storage.save_ride(ride)

    req = RideRequest(
        request_id="req-traveller-1",
        user_id="usr-traveller-1",
        pickup_location=GeoCoordinate(latitude=40.7410, longitude=-73.9897),
        dropoff_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        seat_count=1,
        earliest_pickup_time=now - 60,
        latest_dropoff_time=now + 7200,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    storage.save_request(req)
    return vehicle, ride, req


@pytest.fixture
def service_env() -> tuple[AsgiTestClient, PoolEngineService, InMemoryRideStorage]:
    storage = InMemoryRideStorage()
    router = MockRoutingProvider(average_speed_kmh=40.0)
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
    app = create_app(service)
    client = AsgiTestClient(app)
    return client, service, storage


def test_create_and_inspect_proposal(
    service_env: tuple[AsgiTestClient, PoolEngineService, InMemoryRideStorage],
) -> None:
    """Creates a proposal and inspects it as host, traveller, and non-participant."""
    client, service, storage = service_env
    _, ride, req = _setup_proposal_fixtures(storage)

    # 1. Create proposal via API
    resp_create = client.post(
        "/v1/proposals",
        json={
            "ride_id": ride.ride_id,
            "request_id": req.request_id,
            "seat_count": 1,
        },
    )
    assert resp_create.status_code == 201
    prop = resp_create.json()
    proposal_id = prop["proposal_id"]
    assert prop["status"] == "PENDING"
    assert not prop["host_accepted"]
    assert not prop["traveller_accepted"]
    assert not prop["is_confirmed"]

    # 2. Inspect as Host
    resp_host = client.get(
        f"/v1/proposals/{proposal_id}",
        headers={"X-User-Id": "usr-host-1"},
    )
    assert resp_host.status_code == 200
    host_view = resp_host.json()
    assert not host_view["is_masked"]
    assert host_view["host_id"] == "usr-host-1"
    assert host_view["traveller_id"] == "usr-traveller-1"
    assert host_view["pickup_location"]["latitude"] == pytest.approx(40.7410, abs=1e-4)

    # 3. Inspect as Traveller
    resp_traveller = client.get(
        f"/v1/proposals/{proposal_id}",
        headers={"X-User-Id": "usr-traveller-1"},
    )
    assert resp_traveller.status_code == 200
    traveller_view = resp_traveller.json()
    assert not traveller_view["is_masked"]
    assert traveller_view["traveller_id"] == "usr-traveller-1"

    # 4. Inspect as Unauthenticated / Non-participant -> Coordinates masked (~1.1 km), user IDs redacted
    resp_public = client.get(
        f"/v1/proposals/{proposal_id}",
        headers={"X-User-Id": "usr-random-stranger"},
    )
    assert resp_public.status_code == 200
    public_view = resp_public.json()
    assert public_view["is_masked"]
    assert public_view["host_id"] is None
    assert public_view["traveller_id"] is None
    # Check coordinate was fuzzed to 2 decimal places (40.7410 -> 40.74, -73.9897 -> -73.99)
    assert public_view["pickup_location"]["latitude"] == 40.74
    assert public_view["pickup_location"]["longitude"] == -73.99


def test_host_accepts_first_ride_remains_unconfirmed(
    service_env: tuple[AsgiTestClient, PoolEngineService, InMemoryRideStorage],
) -> None:
    """An acceptance from the host alone must not confirm the ride."""
    client, service, storage = service_env
    _, ride, req = _setup_proposal_fixtures(storage)

    resp_create = client.post("/v1/proposals", json={"ride_id": ride.ride_id, "request_id": req.request_id})
    proposal_id = resp_create.json()["proposal_id"]

    # Host accepts
    resp_accept = client.post(
        f"/v1/proposals/{proposal_id}/accept",
        json={"user_id": "usr-host-1"},
    )
    assert resp_accept.status_code == 200
    data = resp_accept.json()
    assert data["status"] == "PENDING_TRAVELLER_ACCEPTANCE"
    assert data["host_accepted"]
    assert not data["traveller_accepted"]
    assert not data["is_confirmed"]

    # Verify Ride is NOT modified or confirmed
    fetched_ride = storage.get_ride(ride.ride_id)
    assert fetched_ride is not None
    assert len(fetched_ride.stops) == 0
    assert fetched_ride.active_passenger_count == 0

    # Verify RideRequest is still PENDING
    fetched_req = storage.get_request(req.request_id)
    assert fetched_req is not None
    assert fetched_req.status == RequestStatus.PENDING


def test_traveller_accepts_first_ride_remains_unconfirmed(
    service_env: tuple[AsgiTestClient, PoolEngineService, InMemoryRideStorage],
) -> None:
    """An acceptance from the traveller alone must not confirm the ride."""
    client, service, storage = service_env
    _, ride, req = _setup_proposal_fixtures(storage)

    resp_create = client.post("/v1/proposals", json={"ride_id": ride.ride_id, "request_id": req.request_id})
    proposal_id = resp_create.json()["proposal_id"]

    # Traveller accepts
    resp_accept = client.post(
        f"/v1/proposals/{proposal_id}/accept",
        json={"user_id": "usr-traveller-1"},
    )
    assert resp_accept.status_code == 200
    data = resp_accept.json()
    assert data["status"] == "PENDING_HOST_ACCEPTANCE"
    assert not data["host_accepted"]
    assert data["traveller_accepted"]
    assert not data["is_confirmed"]

    # Verify Ride is untouched
    fetched_ride = storage.get_ride(ride.ride_id)
    assert fetched_ride is not None
    assert len(fetched_ride.stops) == 0

    # Verify Request is still PENDING
    fetched_req = storage.get_request(req.request_id)
    assert fetched_req is not None
    assert fetched_req.status == RequestStatus.PENDING


def test_second_acceptance_confirms_ride_exactly_once(
    service_env: tuple[AsgiTestClient, PoolEngineService, InMemoryRideStorage],
) -> None:
    """When both parties accept, the proposal transitions to CONFIRMED and stops are scheduled."""
    client, service, storage = service_env
    _, ride, req = _setup_proposal_fixtures(storage)

    resp_create = client.post("/v1/proposals", json={"ride_id": ride.ride_id, "request_id": req.request_id})
    proposal_id = resp_create.json()["proposal_id"]

    # 1. Host accepts
    client.post(f"/v1/proposals/{proposal_id}/accept", json={"user_id": "usr-host-1"})

    # 2. Traveller accepts (second required acceptance)
    resp_confirm = client.post(
        f"/v1/proposals/{proposal_id}/accept",
        json={"user_id": "usr-traveller-1"},
    )
    assert resp_confirm.status_code == 200
    data = resp_confirm.json()
    assert data["status"] == "CONFIRMED"
    assert data["host_accepted"]
    assert data["traveller_accepted"]
    assert data["is_confirmed"]
    assert data["ride_id"] == ride.ride_id

    # 3. Verify ride now has scheduled stops and updated passenger count
    updated_ride = storage.get_ride(ride.ride_id)
    assert updated_ride is not None
    assert len(updated_ride.stops) == 2  # Pickup and dropoff stops added
    assert updated_ride.stops[0].request_id == req.request_id
    assert updated_ride.stops[1].request_id == req.request_id

    # 4. Verify request is MATCHED
    updated_req = storage.get_request(req.request_id)
    assert updated_req is not None
    assert updated_req.status == RequestStatus.MATCHED
    assert updated_req.matched_ride_id == ride.ride_id


def test_repeated_acceptance_is_idempotent(
    service_env: tuple[AsgiTestClient, PoolEngineService, InMemoryRideStorage],
) -> None:
    """Repeated calls to accept do not create duplicate stops or allocations."""
    client, service, storage = service_env
    _, ride, req = _setup_proposal_fixtures(storage)

    resp_create = client.post("/v1/proposals", json={"ride_id": ride.ride_id, "request_id": req.request_id})
    proposal_id = resp_create.json()["proposal_id"]

    # Host accepts twice
    resp_h1 = client.post(f"/v1/proposals/{proposal_id}/accept", json={"user_id": "usr-host-1"})
    assert resp_h1.status_code == 200
    resp_h2 = client.post(f"/v1/proposals/{proposal_id}/accept", json={"user_id": "usr-host-1"})
    assert resp_h2.status_code == 200

    # Traveller accepts
    resp_t1 = client.post(f"/v1/proposals/{proposal_id}/accept", json={"user_id": "usr-traveller-1"})
    assert resp_t1.status_code == 200
    assert resp_t1.json()["is_confirmed"]

    # Traveller accepts again after confirmation -> idempotent return
    resp_t2 = client.post(f"/v1/proposals/{proposal_id}/accept", json={"user_id": "usr-traveller-1"})
    assert resp_t2.status_code == 200
    assert resp_t2.json()["is_confirmed"]
    assert resp_t2.json()["message"] == "Proposal is already confirmed"

    # Confirm ride still has exactly 2 stops
    final_ride = storage.get_ride(ride.ride_id)
    assert final_ride is not None
    assert len(final_ride.stops) == 2


def test_declining_proposal_releases_seat_hold(
    service_env: tuple[AsgiTestClient, PoolEngineService, InMemoryRideStorage],
) -> None:
    """Declining a proposal releases the temporary seat hold safely."""
    client, service, storage = service_env
    _, ride, req = _setup_proposal_fixtures(storage, capacity=1)

    resp_create = client.post("/v1/proposals", json={"ride_id": ride.ride_id, "request_id": req.request_id})
    proposal_id = resp_create.json()["proposal_id"]

    # Verify hold is active in storage
    holds_before = storage.get_active_seat_holds(ride.ride_id, current_time=1000)
    assert len(holds_before) == 1

    # Host declines
    resp_decline = client.post(
        f"/v1/proposals/{proposal_id}/decline",
        json={"user_id": "usr-host-1", "reason": "HOST_UNAVAILABLE"},
    )
    assert resp_decline.status_code == 200
    assert resp_decline.json()["status"] == "DECLINED"
    assert not resp_decline.json()["is_confirmed"]

    # Seat hold must be released
    holds_after = storage.get_active_seat_holds(ride.ride_id, current_time=1000)
    assert len(holds_after) == 0

    # Attempting to accept a declined proposal fails with 409
    resp_accept = client.post(
        f"/v1/proposals/{proposal_id}/accept",
        json={"user_id": "usr-traveller-1"},
    )
    assert resp_accept.status_code == 409
    assert resp_accept.json()["error"]["code"] == "PROPOSAL_DECLINED"


def test_expired_proposal_cannot_be_accepted(
    service_env: tuple[AsgiTestClient, PoolEngineService, InMemoryRideStorage],
) -> None:
    """Proposals past their expires_at timestamp cannot be accepted and release their hold."""
    client, service, storage = service_env
    _, ride, req = _setup_proposal_fixtures(storage)

    resp_create = client.post("/v1/proposals", json={"ride_id": ride.ride_id, "request_id": req.request_id})
    proposal_id = resp_create.json()["proposal_id"]

    # Advance proposal timestamp past expires_at
    jr = storage.get_join_request(proposal_id)
    assert jr is not None
    expired_jr = jr.model_copy(update={"expires_at": 500})  # Expired at t=500
    storage.save_join_request(expired_jr)

    # Calling accept at current_time=1000 fails with 410
    resp_accept = client.post(
        f"/v1/proposals/{proposal_id}/accept",
        json={"user_id": "usr-host-1"},
    )
    assert resp_accept.status_code == 410
    assert resp_accept.json()["error"]["code"] == "PROPOSAL_EXPIRED"

    # Status updated to EXPIRED
    jr_final = storage.get_join_request(proposal_id)
    assert jr_final is not None
    assert jr_final.status == JoinStatus.EXPIRED


def test_unauthorized_user_cannot_accept_or_decline(
    service_env: tuple[AsgiTestClient, PoolEngineService, InMemoryRideStorage],
) -> None:
    """An unrelated third party cannot accept or decline a proposal."""
    client, service, storage = service_env
    _, ride, req = _setup_proposal_fixtures(storage)

    resp_create = client.post("/v1/proposals", json={"ride_id": ride.ride_id, "request_id": req.request_id})
    proposal_id = resp_create.json()["proposal_id"]

    # Stranger attempts to accept -> 403 Forbidden
    resp_accept = client.post(
        f"/v1/proposals/{proposal_id}/accept",
        json={"user_id": "usr-impostor"},
    )
    assert resp_accept.status_code == 403
    assert resp_accept.json()["error"]["code"] == "FORBIDDEN"

    # Stranger attempts to decline -> 403 Forbidden
    resp_decline = client.post(
        f"/v1/proposals/{proposal_id}/decline",
        json={"user_id": "usr-impostor"},
    )
    assert resp_decline.status_code == 403
    assert resp_decline.json()["error"]["code"] == "FORBIDDEN"


def test_auth_boundary_with_api_key_role_enforcement() -> None:
    """When authentication is enabled, only authenticated participants or admins can act."""
    storage = InMemoryRideStorage()
    router = MockRoutingProvider()
    spatial = H3SpatialIndexAdapter()
    policy = DefaultPolicyProvider()
    orchestrator = DispatchOrchestrator(
        storage=storage,
        policy_provider=policy,
        routing_provider=router,
        spatial_index=spatial,
    )
    service = PoolEngineService(storage=storage, orchestrator=orchestrator, router=router)

    # Key registry: admin key and unrelated user key
    auth_provider = ApiKeyAuthProvider({
        "key-admin": ("admin-svc", ("admin",)),
        "key-stranger": ("usr-stranger", ("read", "write")),
        "key-host": ("usr-host-1", ("write",)),
    })
    config = ServiceConfig(require_auth=True)
    app = create_app(service, config=config, auth_provider=auth_provider)
    client = AsgiTestClient(app)

    _, ride, req = _setup_proposal_fixtures(storage)
    # Create proposal with admin key
    resp_create = client.post(
        "/v1/proposals",
        json={"ride_id": ride.ride_id, "request_id": req.request_id},
        headers={"x-api-key": "key-admin"},
    )
    assert resp_create.status_code == 201
    proposal_id = resp_create.json()["proposal_id"]

    # Stranger key attempts to inspect -> 403 Forbidden
    resp_inspect = client.get(
        f"/v1/proposals/{proposal_id}",
        headers={"x-api-key": "key-stranger"},
    )
    assert resp_inspect.status_code == 403

    # Stranger key attempts to accept -> 403 Forbidden
    resp_accept = client.post(
        f"/v1/proposals/{proposal_id}/accept",
        json={"role": "host"},
        headers={"x-api-key": "key-stranger"},
    )
    assert resp_accept.status_code == 403

    # Host key accepts -> 200 OK
    resp_host_accept = client.post(
        f"/v1/proposals/{proposal_id}/accept",
        json={},
        headers={"x-api-key": "key-host"},
    )
    assert resp_host_accept.status_code == 200
    assert resp_host_accept.json()["host_accepted"]


def test_cancellation_racing_with_confirmation_aborts_cleanly(
    service_env: tuple[AsgiTestClient, PoolEngineService, InMemoryRideStorage],
) -> None:
    """If a traveller cancels before second acceptance, confirmation aborts and frees seats."""
    client, service, storage = service_env
    _, ride, req = _setup_proposal_fixtures(storage)

    resp_create = client.post("/v1/proposals", json={"ride_id": ride.ride_id, "request_id": req.request_id})
    proposal_id = resp_create.json()["proposal_id"]

    # Host accepts first
    client.post(f"/v1/proposals/{proposal_id}/accept", json={"user_id": "usr-host-1"})

    # Traveller cancels the underlying request
    client.post(f"/v1/requests/{req.request_id}/cancel")

    # Traveller now attempts to accept proposal
    resp_accept = client.post(
        f"/v1/proposals/{proposal_id}/accept",
        json={"user_id": "usr-traveller-1"},
    )
    assert resp_accept.status_code == 409
    data = resp_accept.json()
    assert data["error"]["code"] == "REQUEST_CANCELLED"

    # Ride was NOT confirmed
    fetched_ride = storage.get_ride(ride.ride_id)
    assert fetched_ride is not None
    assert len(fetched_ride.stops) == 0

    # Seat hold is released
    active_holds = storage.get_active_seat_holds(ride.ride_id, current_time=1000)
    assert len(active_holds) == 0


def test_sweep_expired_proposals_releases_stale_holds(
    service_env: tuple[AsgiTestClient, PoolEngineService, InMemoryRideStorage],
) -> None:
    """Service sweeper cleans up stale holds past their expires_at timestamp."""
    _, service, storage = service_env
    _, ride, req = _setup_proposal_fixtures(storage, base_time=1000)

    prop = service.create_proposal(
        CreateProposalInput(ride_id=ride.ride_id, request_id=req.request_id),
        current_time=1000,
    )
    proposal_id = prop.proposal_id

    # Verify hold is active at t=1000
    assert len(storage.get_active_seat_holds(ride.ride_id, current_time=1000)) == 1

    # Fast forward past expires_at and sweep
    swept_ids = service.sweep_expired_proposals(current_time=prop.expires_at + 10)
    assert proposal_id in swept_ids

    # Holds must be empty now
    assert len(storage.get_active_seat_holds(ride.ride_id, current_time=prop.expires_at + 10)) == 0

    # JoinRequest status updated to EXPIRED
    jr = storage.get_join_request(proposal_id)
    assert jr is not None
    assert jr.status == JoinStatus.EXPIRED
