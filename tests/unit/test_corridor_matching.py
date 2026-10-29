"""Unit tests for private-host corridor matching, fixed endpoints, and ahead-of-vehicle en-route joining."""

import time
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.policy import DispatchPolicy
from engine.domain.enums import JoinStatus, RequestStatus, RideStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle
from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator, OrchestrationConfig
from engine.routing.corridor import check_ahead_of_vehicle, evaluate_host_corridor_match
from engine.service.app import create_app
from engine.service.client import AsgiTestClient
from engine.service.schemas import CreateHostRideInput, EnRouteJoinInput
from engine.service.service import PoolEngineService


# Landmarks (Manhattan Southbound Corridor)
MIDTOWN = GeoCoordinate(latitude=40.7580, longitude=-73.9855)      # Host Origin (North)
FLATIRON = GeoCoordinate(latitude=40.7410, longitude=-73.9897)     # Downstream 1
FOURTEENTH_ST = GeoCoordinate(latitude=40.7350, longitude=-73.9910) # En-Route Vehicle Position
CANAL_ST = GeoCoordinate(latitude=40.7180, longitude=-74.0010)     # Downstream 2 (Ahead)
CITY_HALL = GeoCoordinate(latitude=40.7128, longitude=-74.0060)    # Downstream 3 (Ahead)
WALL_ST = GeoCoordinate(latitude=40.7070, longitude=-74.0090)      # Host Destination (South)
HARLEM = GeoCoordinate(latitude=40.8100, longitude=-73.9400)       # Incompatible (Opposite direction / North)


@pytest.fixture
def service_env() -> tuple[AsgiTestClient, PoolEngineService, InMemoryRideStorage, MockRoutingProvider]:
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
    service = PoolEngineService(storage=storage, orchestrator=orchestrator, router=router)
    app = create_app(service)
    client = AsgiTestClient(app)
    return client, service, storage, router


def test_compatible_host_and_traveller_routes(
    service_env: tuple[AsgiTestClient, PoolEngineService, InMemoryRideStorage, MockRoutingProvider],
) -> None:
    """1. Compatible host and traveller routes: proposal generated with temporary seat hold."""
    client, service, storage, router = service_env
    now = 1000

    # Host registers ride: Midtown -> Wall St (dep: 1000, 3 seats, max detour: 600s)
    resp_host = client.post(
        "/v1/host-rides",
        json={
            "driver_id": "usr-host",
            "origin": {"latitude": MIDTOWN.latitude, "longitude": MIDTOWN.longitude},
            "destination": {"latitude": WALL_ST.latitude, "longitude": WALL_ST.longitude},
            "scheduled_departure_time": now,
            "available_seats": 3,
            "max_detour_seconds": 600,
        },
    )
    assert resp_host.status_code == 201
    host_ride = resp_host.json()
    ride_id = host_ride["ride_id"]

    # Traveller 1: Flatiron -> City Hall (ready: 1000, deadline: 3000, 1 seat)
    resp_req = client.post(
        "/v1/requests",
        json={
            "request_id": "req-traveller-1",
            "user_id": "usr-traveller-1",
            "pickup_location": {"latitude": FLATIRON.latitude, "longitude": FLATIRON.longitude},
            "dropoff_location": {"latitude": CITY_HALL.latitude, "longitude": CITY_HALL.longitude},
            "seat_count": 1,
            "earliest_pickup_time": now,
            "latest_dropoff_time": now + 2000,
            "direct_distance_meters": 3500,
            "direct_duration_seconds": 350,
        },
    )
    assert resp_req.status_code == 201

    # Match host corridor
    resp_match = client.post(f"/v1/host-rides/{ride_id}/match", json={"request_id": "req-traveller-1"})
    assert resp_match.status_code == 200
    proposals = resp_match.json()["proposals"]
    assert len(proposals) == 1
    prop = proposals[0]
    assert prop["ride_id"] == ride_id
    assert prop["status"] == "PENDING"
    assert not prop["is_confirmed"]

    # Verify atomic seat hold acquired
    holds = storage.get_active_seat_holds(ride_id, current_time=now)
    assert len(holds) == 1
    assert holds[0].seat_count == 1


def test_incompatible_route_and_excessive_detour_rejection(
    service_env: tuple[AsgiTestClient, PoolEngineService, InMemoryRideStorage, MockRoutingProvider],
) -> None:
    """2. Incompatible route (opposite direction / excessive detour) is rejected."""
    client, service, storage, _ = service_env
    now = 1000

    resp_host = client.post(
        "/v1/host-rides",
        json={
            "driver_id": "usr-host",
            "origin": {"latitude": MIDTOWN.latitude, "longitude": MIDTOWN.longitude},
            "destination": {"latitude": WALL_ST.latitude, "longitude": WALL_ST.longitude},
            "scheduled_departure_time": now,
            "available_seats": 3,
            "max_detour_seconds": 300,  # Strict 5 min max detour
        },
    )
    ride_id = resp_host.json()["ride_id"]

    # Incompatible traveller: pickup in Harlem (North, opposite of Southbound route)
    client.post(
        "/v1/requests",
        json={
            "request_id": "req-incompatible",
            "user_id": "usr-harlem",
            "pickup_location": {"latitude": HARLEM.latitude, "longitude": HARLEM.longitude},
            "dropoff_location": {"latitude": WALL_ST.latitude, "longitude": WALL_ST.longitude},
            "seat_count": 1,
            "earliest_pickup_time": now,
            "latest_dropoff_time": now + 3600,
            "direct_distance_meters": 12000,
            "direct_duration_seconds": 1200,
        },
    )

    resp_match = client.post(f"/v1/host-rides/{ride_id}/match", json={"request_id": "req-incompatible"})
    assert resp_match.status_code == 200
    assert resp_match.json()["total_matched"] == 0

    # Also directly attempting to create proposal returns 409
    resp_prop = client.post(
        "/v1/proposals",
        json={"ride_id": ride_id, "request_id": "req-incompatible"},
    )
    assert resp_prop.status_code == 409
    assert any(term in resp_prop.json()["error"]["message"].lower() for term in ("detour", "incompatible", "window_breach", "rejected"))


def test_host_origin_and_destination_remain_fixed(
    service_env: tuple[AsgiTestClient, PoolEngineService, InMemoryRideStorage, MockRoutingProvider],
) -> None:
    """3. Host origin and destination remain mandatory route endpoints."""
    client, service, storage, router = service_env
    now = 1000

    resp_host = client.post(
        "/v1/host-rides",
        json={
            "driver_id": "usr-host",
            "origin": {"latitude": MIDTOWN.latitude, "longitude": MIDTOWN.longitude},
            "destination": {"latitude": WALL_ST.latitude, "longitude": WALL_ST.longitude},
            "scheduled_departure_time": now,
            "available_seats": 3,
            "max_detour_seconds": 900,
        },
    )
    ride_id = resp_host.json()["ride_id"]

    client.post(
        "/v1/requests",
        json={
            "request_id": "req-traveller-1",
            "user_id": "usr-traveller-1",
            "pickup_location": {"latitude": FLATIRON.latitude, "longitude": FLATIRON.longitude},
            "dropoff_location": {"latitude": CANAL_ST.latitude, "longitude": CANAL_ST.longitude},
            "seat_count": 1,
            "earliest_pickup_time": now,
            "latest_dropoff_time": now + 2500,
            "direct_distance_meters": 3000,
            "direct_duration_seconds": 300,
        },
    )

    resp_match = client.post(f"/v1/host-rides/{ride_id}/match", json={"request_id": "req-traveller-1"})
    proposal_id = resp_match.json()["proposals"][0]["proposal_id"]

    # Mutual acceptance
    client.post(f"/v1/proposals/{proposal_id}/accept", json={"user_id": "usr-host"})
    client.post(f"/v1/proposals/{proposal_id}/accept", json={"user_id": "usr-traveller-1"})

    # Inspect confirmed ride itinerary
    confirmed_ride = storage.get_ride(ride_id)
    assert confirmed_ride is not None
    stops = confirmed_ride.stops
    assert len(stops) >= 3

    # Stop 0 MUST be host Origin
    assert stops[0].location.latitude == pytest.approx(MIDTOWN.latitude, abs=1e-4)
    assert stops[0].location.longitude == pytest.approx(MIDTOWN.longitude, abs=1e-4)

    # Final stop MUST be host Destination
    assert stops[-1].location.latitude == pytest.approx(WALL_ST.latitude, abs=1e-4)
    assert stops[-1].location.longitude == pytest.approx(WALL_ST.longitude, abs=1e-4)

    # Passenger pickup and dropoff are strictly internal
    req_stops = [s for s in stops if s.request_id == "req-traveller-1"]
    assert len(req_stops) == 2
    assert stops[0] != req_stops[0]
    assert stops[-1] != req_stops[1]


def test_pickup_ahead_of_vehicle_accepted_and_behind_rejected() -> None:
    """4 & 5. Ahead-of-Vehicle Spatial Gate accepts ahead pickups and rejects behind pickups."""
    router = MockRoutingProvider(average_speed_kmh=40.0)

    # Vehicle is driving South along Broadway, currently at 14th Street
    veh_loc = FOURTEENTH_ST
    dest_loc = WALL_ST
    origin_loc = MIDTOWN

    # Candidate 1: Canal Street (ahead, south of 14th St)
    is_ahead, reason = check_ahead_of_vehicle(
        vehicle_location=veh_loc,
        pickup_location=CANAL_ST,
        destination_location=dest_loc,
        remaining_stops=(),
        completed_stops=(),
        router=router,
        origin_location=origin_loc,
    )
    assert is_ahead is True
    assert reason is None

    # Candidate 2: Midtown (behind vehicle, north of 14th St)
    is_behind, reason_behind = check_ahead_of_vehicle(
        vehicle_location=veh_loc,
        pickup_location=MIDTOWN,
        destination_location=dest_loc,
        remaining_stops=(),
        completed_stops=(),
        router=router,
        origin_location=origin_loc,
    )
    assert is_behind is False
    assert reason_behind == "PICKUP_BEHIND_VEHICLE"


def test_insufficient_capacity_rejected(
    service_env: tuple[AsgiTestClient, PoolEngineService, InMemoryRideStorage, MockRoutingProvider],
) -> None:
    """6. Request exceeding vehicle available seat capacity is rejected."""
    client, service, storage, _ = service_env
    now = 1000

    resp_host = client.post(
        "/v1/host-rides",
        json={
            "driver_id": "usr-host",
            "origin": {"latitude": MIDTOWN.latitude, "longitude": MIDTOWN.longitude},
            "destination": {"latitude": WALL_ST.latitude, "longitude": WALL_ST.longitude},
            "scheduled_departure_time": now,
            "available_seats": 2,  # Only 2 seats!
            "max_detour_seconds": 600,
        },
    )
    ride_id = resp_host.json()["ride_id"]

    # Traveller asking for 3 seats
    client.post(
        "/v1/requests",
        json={
            "request_id": "req-too-large",
            "user_id": "usr-large-group",
            "pickup_location": {"latitude": FLATIRON.latitude, "longitude": FLATIRON.longitude},
            "dropoff_location": {"latitude": CITY_HALL.latitude, "longitude": CITY_HALL.longitude},
            "seat_count": 3,
            "earliest_pickup_time": now,
            "latest_dropoff_time": now + 3600,
            "direct_distance_meters": 3500,
            "direct_duration_seconds": 350,
        },
    )

    resp_match = client.post(f"/v1/host-rides/{ride_id}/match", json={"request_id": "req-too-large"})
    assert resp_match.status_code == 200
    assert resp_match.json()["total_matched"] == 0


def test_existing_passenger_deadline_violation_rejected(
    service_env: tuple[AsgiTestClient, PoolEngineService, InMemoryRideStorage, MockRoutingProvider],
) -> None:
    """7. New insertion that would violate existing passenger's promised arrival deadline is rejected."""
    client, service, storage, _ = service_env
    now = 1000

    resp_host = client.post(
        "/v1/host-rides",
        json={
            "driver_id": "usr-host",
            "origin": {"latitude": MIDTOWN.latitude, "longitude": MIDTOWN.longitude},
            "destination": {"latitude": WALL_ST.latitude, "longitude": WALL_ST.longitude},
            "scheduled_departure_time": now,
            "available_seats": 4,
            "max_detour_seconds": 1200,
        },
    )
    ride_id = resp_host.json()["ride_id"]

    # Passenger 1 has a very tight deadline (e.g. flight or train)
    client.post(
        "/v1/requests",
        json={
            "request_id": "req-tight-deadline",
            "user_id": "usr-urgent",
            "pickup_location": {"latitude": FLATIRON.latitude, "longitude": FLATIRON.longitude},
            "dropoff_location": {"latitude": CANAL_ST.latitude, "longitude": CANAL_ST.longitude},
            "seat_count": 1,
            "earliest_pickup_time": now,
            "latest_dropoff_time": now + 650,  # Very tight deadline!
            "direct_distance_meters": 3000,
            "direct_duration_seconds": 300,
        },
    )
    m1 = client.post(f"/v1/host-rides/{ride_id}/match", json={"request_id": "req-tight-deadline"}).json()["proposals"][0]
    client.post(f"/v1/proposals/{m1['proposal_id']}/accept", json={"user_id": "usr-host"})
    client.post(f"/v1/proposals/{m1['proposal_id']}/accept", json={"user_id": "usr-urgent"})

    # Now Passenger 2 wants a detour that would push Passenger 1 past now + 650
    client.post(
        "/v1/requests",
        json={
            "request_id": "req-competing-detour",
            "user_id": "usr-detour",
            "pickup_location": {"latitude": 40.7450, "longitude": -73.9700},  # East side detour
            "dropoff_location": {"latitude": 40.7200, "longitude": -73.9800},
            "seat_count": 1,
            "earliest_pickup_time": now,
            "latest_dropoff_time": now + 3600,
            "direct_distance_meters": 4000,
            "direct_duration_seconds": 400,
        },
    )

    resp_m2 = client.post(f"/v1/host-rides/{ride_id}/match", json={"request_id": "req-competing-detour"})
    assert resp_m2.status_code == 200
    assert resp_m2.json()["total_matched"] == 0


def test_en_route_join_requires_mutual_acceptance(
    service_env: tuple[AsgiTestClient, PoolEngineService, InMemoryRideStorage, MockRoutingProvider],
) -> None:
    """8. En-route join request creates an unconfirmed proposal requiring mutual acceptance."""
    client, service, storage, _ = service_env
    now = 1000

    resp_host = client.post(
        "/v1/host-rides",
        json={
            "driver_id": "usr-host",
            "origin": {"latitude": MIDTOWN.latitude, "longitude": MIDTOWN.longitude},
            "destination": {"latitude": WALL_ST.latitude, "longitude": WALL_ST.longitude},
            "scheduled_departure_time": now,
            "available_seats": 3,
            "max_detour_seconds": 900,
        },
    )
    ride_id = resp_host.json()["ride_id"]
    veh_id = resp_host.json()["vehicle_id"]

    # Initial traveller confirms ride
    client.post(
        "/v1/requests",
        json={
            "request_id": "req-p1",
            "user_id": "usr-p1",
            "pickup_location": {"latitude": FLATIRON.latitude, "longitude": FLATIRON.longitude},
            "dropoff_location": {"latitude": WALL_ST.latitude, "longitude": WALL_ST.longitude},
            "seat_count": 1,
            "earliest_pickup_time": now,
            "latest_dropoff_time": now + 2500,
            "direct_distance_meters": 4500,
            "direct_duration_seconds": 450,
        },
    )
    p1 = client.post(f"/v1/host-rides/{ride_id}/match", json={"request_id": "req-p1"}).json()["proposals"][0]
    client.post(f"/v1/proposals/{p1['proposal_id']}/accept", json={"user_id": "usr-host"})
    client.post(f"/v1/proposals/{p1['proposal_id']}/accept", json={"user_id": "usr-p1"})

    # Host departs; vehicle is now in transit at 14th Street
    client.post(
        f"/v1/vehicles/{veh_id}/location",
        json={
            "latitude": FOURTEENTH_ST.latitude,
            "longitude": FOURTEENTH_ST.longitude,
            "ride_id": ride_id,
            "completed_stop_ids": [f"stop-origin-{ride_id}", "stop-p-req-p1"],
        },
    )

    # New Traveller C requests join from Canal Street (ahead)
    client.post(
        "/v1/requests",
        json={
            "request_id": "req-en-route",
            "user_id": "usr-en-route",
            "pickup_location": {"latitude": CANAL_ST.latitude, "longitude": CANAL_ST.longitude},
            "dropoff_location": {"latitude": CITY_HALL.latitude, "longitude": CITY_HALL.longitude},
            "seat_count": 1,
            "earliest_pickup_time": now + 300,
            "latest_dropoff_time": now + 3000,
            "direct_distance_meters": 1500,
            "direct_duration_seconds": 180,
        },
    )

    resp_join = client.post(
        f"/v1/rides/{ride_id}/en-route-join",
        json={"request_id": "req-en-route"},
    )
    assert resp_join.status_code == 200
    join_res = resp_join.json()
    assert join_res["eligible"] is True
    assert join_res["proposal"] is not None
    proposal_id = join_res["proposal"]["proposal_id"]
    assert not join_res["proposal"]["is_confirmed"]

    # Initial ride stops NOT updated yet
    ride_pre = storage.get_ride(ride_id)
    assert ride_pre is not None
    assert not any(s.request_id == "req-en-route" for s in ride_pre.stops)

    # Host and traveller accept
    client.post(f"/v1/proposals/{proposal_id}/accept", json={"user_id": "usr-host"})
    client.post(f"/v1/proposals/{proposal_id}/accept", json={"user_id": "usr-en-route"})

    # Now ride is confirmed with en-route passenger stops included!
    ride_post = storage.get_ride(ride_id)
    assert ride_post is not None
    assert any(s.request_id == "req-en-route" for s in ride_post.stops)
