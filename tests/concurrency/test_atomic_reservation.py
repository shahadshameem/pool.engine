"""Concurrency and lifecycle tests for atomic seat reservations and join requests."""

import concurrent.futures
from typing import Sequence

import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.policy import DispatchPolicy
from engine.domain.enums import JoinStatus, RequestStatus, RideStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, JoinRequest, Ride, RideRequest, RouteStop, Vehicle
from engine.lifecycle.transitions import LifecycleTransitionError
from engine.lifecycle.reservations import (
    ReservationResult,
    confirm_join_request,
    expire_stale_holds,
    reject_join_request,
    submit_join_request,
)


def _create_test_entities(
    vehicle_capacity: int = 1,
    vehicle_loc: GeoCoordinate = GeoCoordinate(latitude=40.7128, longitude=-74.0060),
    existing_stops: Sequence[RouteStop] = (),
    active_passenger_count: int = 0,
) -> tuple[Vehicle, Ride, InMemoryRideStorage]:
    """Helper to provision storage with vehicle and ride."""
    storage = InMemoryRideStorage()
    vehicle = Vehicle(
        vehicle_id="veh-test-1",
        driver_id="drv-test-1",
        total_seat_capacity=vehicle_capacity,
        current_location=vehicle_loc,
        is_active=True,
    )
    storage.save_vehicle(vehicle)

    ride = Ride(
        ride_id="ride-test-1",
        vehicle_id=vehicle.vehicle_id,
        driver_id=vehicle.driver_id,
        lifecycle_status=RideStatus.ACTIVE,
        stops=tuple(existing_stops),
        scheduled_departure_time=1000,
        active_passenger_count=active_passenger_count,
        version=1,
    )
    storage.save_ride(ride)
    return vehicle, ride, storage


def test_concurrent_seat_reservation_race() -> None:
    """
    T038: 10 concurrent threads contending for 1 remaining seat.
    Verifies that exactly 1 commits (APPROVED), 9 are rejected with OVER_CAPACITY,
    and vehicle capacity is never overbooked.
    """
    vehicle, ride, storage = _create_test_entities(vehicle_capacity=1)
    policy_provider = DefaultPolicyProvider()
    router = MockRoutingProvider(average_speed_kmh=40.0)

    # 10 distinct requests each asking for 1 seat
    requests: list[RideRequest] = []
    for i in range(10):
        req = RideRequest(
            request_id=f"req-race-{i}",
            user_id=f"user-{i}",
            pickup_location=GeoCoordinate(latitude=40.7128 + i * 0.001, longitude=-74.0060),
            dropoff_location=GeoCoordinate(latitude=40.7589 + i * 0.001, longitude=-73.9851),
            seat_count=1,
            earliest_pickup_time=1000,
            latest_dropoff_time=4000,
            direct_distance_meters=5000,
            direct_duration_seconds=600,
            status=RequestStatus.PENDING,
        )
        storage.save_request(req)
        requests.append(req)

    def _attempt_join(req: RideRequest) -> ReservationResult:
        # Submit join request
        token = f"token-{req.request_id}"
        sub_res = submit_join_request(
            request=req,
            ride_id=ride.ride_id,
            storage=storage,
            policy=policy_provider.get_policy(),
            current_time=1000,
            idempotency_token=token,
        )
        if not sub_res.success:
            return sub_res

        # Confirm join request
        return confirm_join_request(
            join_request_id=sub_res.join_request.join_request_id,
            storage=storage,
            policy_provider=policy_provider,
            router=router,
            current_time=1010,
            idempotency_token=token,
        )

    results: list[ReservationResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_attempt_join, req) for req in requests]
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())

    approved = [r for r in results if r.success and r.join_request.status == JoinStatus.APPROVED]
    rejected = [r for r in results if not r.success and r.join_request.status == JoinStatus.REJECTED]

    # Exactly 1 approved, exactly 9 rejected
    assert len(approved) == 1, f"Expected 1 approved, got {len(approved)}"
    assert len(rejected) == 9, f"Expected 9 rejected, got {len(rejected)}"

    # All 9 rejections must cite OVER_CAPACITY
    for rej in rejected:
        assert rej.rejection_reason == "OVER_CAPACITY"

    # Verify storage state: ride has stops for only the 1 approved passenger
    updated_ride = storage.get_ride(ride.ride_id)
    assert updated_ride is not None
    assert len(updated_ride.stops) == 2  # 1 pickup + 1 dropoff
    assert updated_ride.stops[0].request_id == approved[0].join_request.request_id
    assert updated_ride.stops[1].request_id == approved[0].join_request.request_id


# Alias matching quickstart validation guide
test_concurrent_seat_contention = test_concurrent_seat_reservation_race



def test_idempotent_join_request_replay() -> None:
    """
    T039: Idempotency tests submitting repeated join requests with identical idempotency_token.
    Verifies that approved state is returned without consuming additional capacity or duplicating stops.
    """
    vehicle, ride, storage = _create_test_entities(vehicle_capacity=4)
    policy_provider = DefaultPolicyProvider()
    router = MockRoutingProvider(average_speed_kmh=40.0)

    req = RideRequest(
        request_id="req-idemp-1",
        user_id="user-idemp-1",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7589, longitude=-73.9851),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=4000,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    storage.save_request(req)

    token = "idempotency-token-abc-123"

    # 1. Initial submission
    sub_1 = submit_join_request(
        request=req,
        ride_id=ride.ride_id,
        storage=storage,
        policy=policy_provider.get_policy(),
        current_time=1000,
        idempotency_token=token,
    )
    assert sub_1.success
    assert sub_1.join_request.status == JoinStatus.PENDING

    # 2. Replayed submission with identical token returns identical JoinRequest
    sub_2 = submit_join_request(
        request=req,
        ride_id=ride.ride_id,
        storage=storage,
        policy=policy_provider.get_policy(),
        current_time=1005,
        idempotency_token=token,
    )
    assert sub_2.success
    assert sub_2.join_request.join_request_id == sub_1.join_request.join_request_id
    assert sub_2.join_request.status == JoinStatus.PENDING

    # 3. Initial confirmation
    conf_1 = confirm_join_request(
        join_request_id=sub_1.join_request.join_request_id,
        storage=storage,
        policy_provider=policy_provider,
        router=router,
        current_time=1010,
        idempotency_token=token,
    )
    assert conf_1.success
    assert conf_1.join_request.status == JoinStatus.APPROVED
    assert conf_1.ride is not None
    assert len(conf_1.ride.stops) == 2

    ride_version_after_conf1 = conf_1.ride.version

    # 4. Replayed confirmation with identical token returns identical approved state
    conf_2 = confirm_join_request(
        join_request_id=sub_1.join_request.join_request_id,
        storage=storage,
        policy_provider=policy_provider,
        router=router,
        current_time=1020,
        idempotency_token=token,
    )
    assert conf_2.success
    assert conf_2.join_request.status == JoinStatus.APPROVED
    assert conf_2.ride is not None
    assert len(conf_2.ride.stops) == 2  # Stops not duplicated!
    assert conf_2.ride.version == ride_version_after_conf1  # No unnecessary version bump


def test_timer_expiry_exact_boundary() -> None:
    """
    T040: Timer expiry race tests verifying exact second-level boundaries:
    - Confirmation at t = T_expires is VALID and succeeds.
    - Confirmation at t = T_expires + 1s is EXPIRED, auto-released, and rejected.
    """
    vehicle, ride, storage = _create_test_entities(vehicle_capacity=1)
    policy = DispatchPolicy(join_request_expiry_seconds=300)
    policy_provider = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider(average_speed_kmh=40.0)

    # Case A: Confirmation at exact boundary t = T_expires (t = 1300)
    req_a = RideRequest(
        request_id="req-boundary-valid",
        user_id="user-a",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7589, longitude=-73.9851),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=4000,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    storage.save_request(req_a)

    sub_a = submit_join_request(
        request=req_a,
        ride_id=ride.ride_id,
        storage=storage,
        policy=policy,
        current_time=1000,  # submitted at 1000 -> expires at 1300
        idempotency_token="token-boundary-a",
    )
    assert sub_a.success
    assert sub_a.join_request.expires_at == 1300

    # Confirm at t = 1300 (valid!)
    conf_a = confirm_join_request(
        join_request_id=sub_a.join_request.join_request_id,
        storage=storage,
        policy_provider=policy_provider,
        router=router,
        current_time=1300,
        idempotency_token="token-boundary-a",
    )
    assert conf_a.success
    assert conf_a.join_request.status == JoinStatus.APPROVED

    # Now create fresh vehicle and ride for Case B
    vehicle_b, ride_b, storage_b = _create_test_entities(vehicle_capacity=1)
    req_b = RideRequest(
        request_id="req-boundary-expired",
        user_id="user-b",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7589, longitude=-73.9851),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=4000,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    storage_b.save_request(req_b)

    sub_b = submit_join_request(
        request=req_b,
        ride_id=ride_b.ride_id,
        storage=storage_b,
        policy=policy,
        current_time=1000,  # submitted at 1000 -> expires at 1300
        idempotency_token="token-boundary-b",
    )
    assert sub_b.success
    assert sub_b.join_request.expires_at == 1300

    # Confirm at t = 1301 (t > T_expires -> EXPIRED!)
    conf_b = confirm_join_request(
        join_request_id=sub_b.join_request.join_request_id,
        storage=storage_b,
        policy_provider=policy_provider,
        router=router,
        current_time=1301,
        idempotency_token="token-boundary-b",
    )
    assert not conf_b.success
    assert conf_b.join_request.status == JoinStatus.EXPIRED
    assert conf_b.rejection_reason == "EXPIRED"

    # Verify that the seat hold was released:
    # A subsequent request can now claim the 1 seat on ride_b
    req_c = RideRequest(
        request_id="req-subsequent",
        user_id="user-c",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7589, longitude=-73.9851),
        seat_count=1,
        earliest_pickup_time=1305,
        latest_dropoff_time=4000,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    storage_b.save_request(req_c)

    sub_c = submit_join_request(
        request=req_c,
        ride_id=ride_b.ride_id,
        storage=storage_b,
        policy=policy,
        current_time=1305,
        idempotency_token="token-boundary-c",
    )
    assert sub_c.success
    conf_c = confirm_join_request(
        join_request_id=sub_c.join_request.join_request_id,
        storage=storage_b,
        policy_provider=policy_provider,
        router=router,
        current_time=1310,
        idempotency_token="token-boundary-c",
    )
    assert conf_c.success
    assert conf_c.join_request.status == JoinStatus.APPROVED


def test_dynamic_policy_update_revalidation() -> None:
    """
    T041: Dynamic policy update revalidation test:
    - Join request created under Policy 1 (generous detour multiplier 1.50).
    - Policy updated to Policy 2 (stricter detour multiplier 1.10).
    - Upon confirmation, double revalidation evaluates under active Policy 2,
      detecting detour cap breach and rejecting the request.
    """
    policy_1 = DispatchPolicy(
        detour_relative_multiplier=1.50,
        detour_absolute_cap_seconds=900,
        max_pickup_delay_seconds=600,
    )
    policy_provider = DefaultPolicyProvider(initial_policy=policy_1)
    router = MockRoutingProvider(average_speed_kmh=40.0)

    # Initial ride with passenger 1 onboard
    # Existing route: from P1 (40.7128, -74.0060) to D1 (40.7589, -73.9851)
    loc_p1 = GeoCoordinate(latitude=40.7128, longitude=-74.0060)
    loc_d1 = GeoCoordinate(latitude=40.7589, longitude=-73.9851)

    req1 = RideRequest(
        request_id="req-existing-1",
        user_id="user-1",
        pickup_location=loc_p1,
        dropoff_location=loc_d1,
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=4000,
        direct_distance_meters=5500,
        direct_duration_seconds=500,
        status=RequestStatus.MATCHED,
    )

    stop_p1 = RouteStop(
        stop_id="stop-p1",
        ride_id="ride-policy-1",
        request_id=req1.request_id,
        stop_type=StopType.PICKUP,
        location=loc_p1,
        passenger_delta=+1,
        scheduled_arrival_time=1000,
        promised_window_start=1000,
        promised_window_end=1600,
        status=StopStatus.COMPLETED,
    )
    stop_d1 = RouteStop(
        stop_id="stop-d1",
        ride_id="ride-policy-1",
        request_id=req1.request_id,
        stop_type=StopType.DROPOFF,
        location=loc_d1,
        passenger_delta=-1,
        scheduled_arrival_time=1500,
        promised_window_start=1000,
        promised_window_end=4000,
        status=StopStatus.SCHEDULED,
    )

    storage = InMemoryRideStorage()
    vehicle = Vehicle(
        vehicle_id="veh-policy-1",
        driver_id="drv-policy-1",
        total_seat_capacity=4,
        current_location=loc_p1,
        is_active=True,
    )
    storage.save_vehicle(vehicle)
    storage.save_request(req1)

    ride = Ride(
        ride_id="ride-policy-1",
        vehicle_id=vehicle.vehicle_id,
        driver_id=vehicle.driver_id,
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop_p1, stop_d1),
        scheduled_departure_time=1000,
        active_passenger_count=1,
        version=1,
    )
    storage.save_ride(ride)

    # New request req2 requires a detour for passenger 1
    # Direct duration of req1 is 500s. Under Policy 1 (1.50), max travel time is min(750, 500+900) = 750s (detour <= 250s).
    # Under Policy 2 (1.10), max travel time is min(550, 500+900) = 550s (detour <= 50s).
    # We place req2's pickup and dropoff with enough deviation that req1's total travel time becomes ~650s.
    loc_p2 = GeoCoordinate(latitude=40.7200, longitude=-73.9900)
    loc_d2 = GeoCoordinate(latitude=40.7300, longitude=-73.9800)

    req2 = RideRequest(
        request_id="req-joiner-2",
        user_id="user-2",
        pickup_location=loc_p2,
        dropoff_location=loc_d2,
        seat_count=1,
        earliest_pickup_time=1050,
        latest_dropoff_time=4000,
        direct_distance_meters=2000,
        direct_duration_seconds=200,
        status=RequestStatus.PENDING,
    )
    storage.save_request(req2)

    # 1. Submit join request under Policy 1
    sub_res = submit_join_request(
        request=req2,
        ride_id=ride.ride_id,
        storage=storage,
        policy=policy_provider.get_policy(),
        current_time=1010,
        idempotency_token="token-dyn-policy",
    )
    assert sub_res.success
    assert sub_res.join_request.status == JoinStatus.PENDING

    # 2. Deploy Policy 2: stricter detour multiplier (1.05)
    policy_2 = DispatchPolicy(
        detour_relative_multiplier=1.05,  # Only 5% detour allowed (25s on 500s trip!)
        detour_absolute_cap_seconds=900,
        max_pickup_delay_seconds=600,
    )
    policy_provider.update_policy(policy_2)

    # 3. Creator approves / confirms join request after Policy 2 is active
    conf_res = confirm_join_request(
        join_request_id=sub_res.join_request.join_request_id,
        storage=storage,
        policy_provider=policy_provider,
        router=router,
        current_time=1020,
        idempotency_token="token-dyn-policy",
    )

    # Double revalidation must fail because req1's detour exceeds Policy 2's 1.05 cap!
    assert not conf_res.success
    assert conf_res.join_request.status == JoinStatus.REJECTED
    assert conf_res.rejection_reason in ("DETOUR_BREACH", "ROUTE_INVALIDATED")

    # Stops of the ride remain intact
    updated_ride = storage.get_ride(ride.ride_id)
    assert updated_ride is not None
    assert len(updated_ride.stops) == 2
    assert updated_ride.stops[0].request_id == req1.request_id
    assert updated_ride.stops[1].request_id == req1.request_id


def test_creator_declines_join_request() -> None:
    """Explicit rejection by creator releases hold immediately and frees capacity."""
    vehicle, ride, storage = _create_test_entities(vehicle_capacity=1)
    policy = DispatchPolicy(join_request_expiry_seconds=300)
    policy_provider = DefaultPolicyProvider(initial_policy=policy)
    router = MockRoutingProvider()

    req = RideRequest(
        request_id="req-decline-1",
        user_id="user-decline-1",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7589, longitude=-73.9851),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=4000,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    storage.save_request(req)

    sub = submit_join_request(
        request=req,
        ride_id=ride.ride_id,
        storage=storage,
        policy=policy,
        current_time=1000,
        idempotency_token="token-decline-1",
    )
    assert sub.success
    assert sub.join_request.status == JoinStatus.PENDING

    # Creator declines
    rej = reject_join_request(
        join_request_id=sub.join_request.join_request_id,
        storage=storage,
        reason="DECLINED_BY_CREATOR",
    )
    assert not rej.success
    assert rej.join_request.status == JoinStatus.REJECTED
    assert rej.rejection_reason == "DECLINED_BY_CREATOR"

    # Now another request can claim the 1 seat
    req2 = RideRequest(
        request_id="req-decline-2",
        user_id="user-decline-2",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7589, longitude=-73.9851),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=4000,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    storage.save_request(req2)

    sub2 = submit_join_request(
        request=req2,
        ride_id=ride.ride_id,
        storage=storage,
        policy=policy,
        current_time=1005,
        idempotency_token="token-decline-2",
    )
    assert sub2.success
    conf2 = confirm_join_request(
        join_request_id=sub2.join_request.join_request_id,
        storage=storage,
        policy_provider=policy_provider,
        router=router,
        current_time=1010,
        idempotency_token="token-decline-2",
    )
    assert conf2.success
    assert conf2.join_request.status == JoinStatus.APPROVED


def test_expire_stale_holds_sweeper() -> None:
    """expire_stale_holds sweeps storage and transitions expired holds to EXPIRED."""
    vehicle, ride, storage = _create_test_entities(vehicle_capacity=4)
    policy = DispatchPolicy(join_request_expiry_seconds=300)

    # Request 1 submitted at 1000 (expires at 1300)
    req1 = RideRequest(
        request_id="req-sweep-1",
        user_id="user-sweep-1",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7589, longitude=-73.9851),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=4000,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    storage.save_request(req1)
    sub1 = submit_join_request(
        request=req1,
        ride_id=ride.ride_id,
        storage=storage,
        policy=policy,
        current_time=1000,
        idempotency_token="token-sweep-1",
    )

    # Request 2 submitted at 1200 (expires at 1500)
    req2 = RideRequest(
        request_id="req-sweep-2",
        user_id="user-sweep-2",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7589, longitude=-73.9851),
        seat_count=1,
        earliest_pickup_time=1200,
        latest_dropoff_time=4000,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    storage.save_request(req2)
    sub2 = submit_join_request(
        request=req2,
        ride_id=ride.ride_id,
        storage=storage,
        policy=policy,
        current_time=1200,
        idempotency_token="token-sweep-2",
    )

    # Run sweeper at t = 1350
    # Hold 1 (expires 1300) is expired, Hold 2 (expires 1500) is still valid
    expired = expire_stale_holds(storage, current_time=1350)
    assert sub1.join_request.join_request_id in expired
    assert sub2.join_request.join_request_id not in expired

    jr1 = storage.get_join_request(sub1.join_request.join_request_id)
    assert jr1 is not None
    assert jr1.status == JoinStatus.EXPIRED

    jr2 = storage.get_join_request(sub2.join_request.join_request_id)
    assert jr2 is not None
    assert jr2.status == JoinStatus.PENDING


def test_storage_bounding_box_and_persistence() -> None:
    """Verifies bounding box queries and entity persistence on InMemoryRideStorage."""
    storage = InMemoryRideStorage()
    loc1 = GeoCoordinate(latitude=40.7128, longitude=-74.0060)
    loc2 = GeoCoordinate(latitude=40.7589, longitude=-73.9851)
    loc_far = GeoCoordinate(latitude=41.5000, longitude=-75.0000)

    v1 = Vehicle(
        vehicle_id="v-box-1",
        driver_id="d1",
        total_seat_capacity=4,
        current_location=loc1,
        is_active=True,
    )
    storage.save_vehicle(v1)
    assert storage.get_vehicle("v-box-1") == v1

    ride1 = Ride(
        ride_id="ride-box-1",
        vehicle_id="v-box-1",
        driver_id="d1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(),
        scheduled_departure_time=1000,
        active_passenger_count=0,
    )
    storage.save_ride(ride1)

    v2 = Vehicle(
        vehicle_id="v-box-2",
        driver_id="d2",
        total_seat_capacity=4,
        current_location=loc_far,
        is_active=True,
    )
    storage.save_vehicle(v2)
    ride2 = Ride(
        ride_id="ride-box-2",
        vehicle_id="v-box-2",
        driver_id="d2",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(),
        scheduled_departure_time=1000,
        active_passenger_count=0,
    )
    storage.save_ride(ride2)

    # Query bounding box covering NYC (loc1 and loc2), excluding loc_far
    rides_in_box = storage.get_active_rides_in_bounding_box(
        min_lat=40.7000,
        min_lon=-74.0500,
        max_lat=40.8000,
        max_lon=-73.9000,
    )
    ride_ids = [r.ride_id for r in rides_in_box]
    assert "ride-box-1" in ride_ids
    assert "ride-box-2" not in ride_ids


def test_idempotency_token_reuse_different_request_fails() -> None:
    """
    Fix 2 Regression: Replaying identical token for same request is idempotent,
    but reusing the same token for a different request or join request must fail
    with IDEMPOTENCY_TOKEN_CONFLICT.
    """
    vehicle, ride, storage = _create_test_entities(vehicle_capacity=4)
    policy = DispatchPolicy(join_request_expiry_seconds=300)

    req1 = RideRequest(
        request_id="req-idem-1",
        user_id="user-1",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7589, longitude=-73.9851),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=4000,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    storage.save_request(req1)

    req2 = RideRequest(
        request_id="req-idem-2",
        user_id="user-2",
        pickup_location=GeoCoordinate(latitude=40.7130, longitude=-74.0062),
        dropoff_location=GeoCoordinate(latitude=40.7590, longitude=-73.9850),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=4000,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    storage.save_request(req2)

    shared_token = "token-unique-12345"

    # Submit for req1 -> succeeds
    sub1 = submit_join_request(
        request=req1,
        ride_id=ride.ride_id,
        storage=storage,
        policy=policy,
        current_time=1000,
        idempotency_token=shared_token,
    )
    assert sub1.success is True
    assert sub1.join_request.request_id == "req-idem-1"

    # Replay for req1 with same token -> idempotent success
    sub1_replay = submit_join_request(
        request=req1,
        ride_id=ride.ride_id,
        storage=storage,
        policy=policy,
        current_time=1005,
        idempotency_token=shared_token,
    )
    assert sub1_replay.success is True
    assert sub1_replay.join_request.request_id == "req-idem-1"

    # Reuse same token for req2 -> MUST FAIL with IDEMPOTENCY_TOKEN_CONFLICT
    sub2 = submit_join_request(
        request=req2,
        ride_id=ride.ride_id,
        storage=storage,
        policy=policy,
        current_time=1010,
        idempotency_token=shared_token,
    )
    assert sub2.success is False
    assert sub2.rejection_reason == "IDEMPOTENCY_TOKEN_CONFLICT"


def test_reserve_seats_atomic_token_reuse_different_reservation_fails() -> None:
    """
    Fix 2 Regression: reserve_seats_atomic must not succeed when an idempotency token
    belonging to an existing reservation is reused for a different join request.
    """
    vehicle, ride, storage = _create_test_entities(vehicle_capacity=4)

    # 1. Acquire hold and confirm reservation 1
    hold1 = storage.acquire_seat_hold_atomic(
        ride_id=ride.ride_id,
        request_id="req-atom-1",
        join_request_id="join-atom-1",
        seat_count=1,
        submitted_at=1000,
        expires_at=1300,
        expected_version=1,
        idempotency_token="token-res-1",
    )
    assert hold1 is True

    res1 = storage.reserve_seats_atomic(
        ride_id=ride.ride_id,
        request_id="req-atom-1",
        join_request_id="join-atom-1",
        seat_count=1,
        expected_version=2,
        idempotency_token="token-res-1",
    )
    assert res1 is True

    # Idempotent replay for reservation 1 -> returns True
    res1_replay = storage.reserve_seats_atomic(
        ride_id=ride.ride_id,
        request_id="req-atom-1",
        join_request_id="join-atom-1",
        seat_count=1,
        expected_version=3,
        idempotency_token="token-res-1",
    )
    assert res1_replay is True

    # 2. Acquire hold for reservation 2 with a different token
    hold2 = storage.acquire_seat_hold_atomic(
        ride_id=ride.ride_id,
        request_id="req-atom-2",
        join_request_id="join-atom-2",
        seat_count=1,
        submitted_at=1000,
        expires_at=1300,
        expected_version=3,
        idempotency_token="token-hold-2",
    )
    assert hold2 is True

    # Attempt to reserve seats for join-atom-2 reusing token-res-1 -> MUST RETURN FALSE
    res2_stolen = storage.reserve_seats_atomic(
        ride_id=ride.ride_id,
        request_id="req-atom-2",
        join_request_id="join-atom-2",
        seat_count=1,
        expected_version=4,
        idempotency_token="token-res-1",
    )
    assert res2_stolen is False


def test_acquire_seat_hold_atomic_token_reuse_different_join_fails() -> None:
    """
    Fix 2 Regression: acquire_seat_hold_atomic must reject token reuse across different join requests.
    """
    vehicle, ride, storage = _create_test_entities(vehicle_capacity=4)

    hold1 = storage.acquire_seat_hold_atomic(
        ride_id=ride.ride_id,
        request_id="req-hold-1",
        join_request_id="join-hold-1",
        seat_count=1,
        submitted_at=1000,
        expires_at=1300,
        expected_version=1,
        idempotency_token="token-hold-shared",
    )
    assert hold1 is True

    # Replay identical hold -> True
    hold1_replay = storage.acquire_seat_hold_atomic(
        ride_id=ride.ride_id,
        request_id="req-hold-1",
        join_request_id="join-hold-1",
        seat_count=1,
        submitted_at=1000,
        expires_at=1300,
        expected_version=2,
        idempotency_token="token-hold-shared",
    )
    assert hold1_replay is True

    # Token reuse for different join request -> False
    hold2_conflict = storage.acquire_seat_hold_atomic(
        ride_id=ride.ride_id,
        request_id="req-hold-2",
        join_request_id="join-hold-2",
        seat_count=1,
        submitted_at=1000,
        expires_at=1300,
        expected_version=2,
        idempotency_token="token-hold-shared",
    )
    assert hold2_conflict is False


def test_concurrent_submissions_multi_capacity_occ_retry() -> None:
    """
    Verifies that multiple concurrent join request submissions on a multi-capacity
    vehicle succeed via optimistic concurrency retries without false OVER_CAPACITY rejections.
    """
    vehicle, ride, storage = _create_test_entities(vehicle_capacity=4)
    policy = DispatchPolicy(join_request_expiry_seconds=300)

    requests = [
        RideRequest(
            request_id=f"req-multi-{i}",
            user_id=f"user-multi-{i}",
            pickup_location=GeoCoordinate(latitude=40.7128 + i * 0.001, longitude=-74.0060),
            dropoff_location=GeoCoordinate(latitude=40.7589 + i * 0.001, longitude=-73.9851),
            seat_count=1,
            earliest_pickup_time=1000,
            latest_dropoff_time=4000,
            direct_distance_meters=5000,
            direct_duration_seconds=600,
            status=RequestStatus.PENDING,
        )
        for i in range(4)
    ]
    for r in requests:
        storage.save_request(r)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = [
            ex.submit(submit_join_request, req, ride.ride_id, storage, policy, 1000, f"token-multi-{req.request_id}")
            for req in requests
        ]
        results = [f.result() for f in futures]

    approved = [r for r in results if r.success]
    rejected = [r for r in results if not r.success]
    assert len(approved) == 4, f"Expected 4 approved holds, got {len(approved)}"
    assert len(rejected) == 0, f"Expected 0 rejected, got {len(rejected)}"


def test_concurrent_confirmations_multi_capacity_occ_retry() -> None:
    """
    Verifies that concurrent confirmations on a multi-capacity vehicle succeed
    via OCC retries when capacity and detour bounds remain satisfied.
    """
    vehicle, ride, storage = _create_test_entities(vehicle_capacity=4)
    policy_provider = DefaultPolicyProvider()
    router = MockRoutingProvider(average_speed_kmh=40.0)

    req1 = RideRequest(
        request_id="req-conf-race-1",
        user_id="user-conf-1",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7589, longitude=-73.9851),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=4000,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    req2 = RideRequest(
        request_id="req-conf-race-2",
        user_id="user-conf-2",
        pickup_location=GeoCoordinate(latitude=40.7130, longitude=-74.0062),
        dropoff_location=GeoCoordinate(latitude=40.7590, longitude=-73.9850),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=4000,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    storage.save_request(req1)
    storage.save_request(req2)

    sub1 = submit_join_request(req1, ride.ride_id, storage, policy_provider.get_policy(), 1000, "token-conf-1")
    sub2 = submit_join_request(req2, ride.ride_id, storage, policy_provider.get_policy(), 1000, "token-conf-2")
    assert sub1.success and sub2.success

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(
            confirm_join_request,
            sub1.join_request.join_request_id,
            storage,
            policy_provider,
            router,
            1010,
            "token-conf-1",
        )
        f2 = ex.submit(
            confirm_join_request,
            sub2.join_request.join_request_id,
            storage,
            policy_provider,
            router,
            1010,
            "token-conf-2",
        )
        res1 = f1.result()
        res2 = f2.result()

    assert res1.success is True
    assert res2.success is True
    updated_ride = storage.get_ride(ride.ride_id)
    assert updated_ride is not None
    assert len(updated_ride.stops) == 4


def test_submit_join_request_replay_past_expiry_releases_hold() -> None:
    """
    Verifies that replaying submit_join_request after the 300s expiry period
    detects expiry, releases the hold, marks status EXPIRED, and returns failure.
    """
    vehicle, ride, storage = _create_test_entities(vehicle_capacity=1)
    policy = DispatchPolicy(join_request_expiry_seconds=300)

    req = RideRequest(
        request_id="req-exp-replay",
        user_id="user-exp",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7589, longitude=-73.9851),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=4000,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    storage.save_request(req)

    sub = submit_join_request(req, ride.ride_id, storage, policy, 1000, "token-exp-replay")
    assert sub.success is True
    assert sub.join_request.status == JoinStatus.PENDING
    assert sub.join_request.expires_at == 1300

    # Replay at t = 1301 (past 1300 expiry)
    replay = submit_join_request(req, ride.ride_id, storage, policy, 1301, "token-exp-replay")
    assert replay.success is False
    assert replay.join_request.status == JoinStatus.EXPIRED
    assert replay.rejection_reason == "EXPIRED"

    # Verify hold is freed in storage
    hold = storage.get_seat_hold(sub.join_request.join_request_id)
    assert hold is None


def test_acquire_seat_hold_atomic_replay_past_expiry_returns_false() -> None:
    """
    Verifies that acquire_seat_hold_atomic cleans up and rejects replayed tokens
    when current submitted_at exceeds hold.expires_at.
    """
    _, ride, storage = _create_test_entities(vehicle_capacity=1)

    acquired = storage.acquire_seat_hold_atomic(
        ride_id=ride.ride_id,
        request_id="req-hold-exp",
        join_request_id="join-hold-exp",
        seat_count=1,
        submitted_at=1000,
        expires_at=1300,
        expected_version=1,
        idempotency_token="token-hold-exp",
    )
    assert acquired is True

    # Replay at t = 1301
    replayed = storage.acquire_seat_hold_atomic(
        ride_id=ride.ride_id,
        request_id="req-hold-exp",
        join_request_id="join-hold-exp",
        seat_count=1,
        submitted_at=1301,
        expires_at=1601,
        expected_version=2,
        idempotency_token="token-hold-exp",
    )
    assert replayed is False
    assert storage.get_seat_hold("join-hold-exp") is None


def test_submit_join_request_rejects_cancelled_and_expired_requests() -> None:
    """
    Verifies that requests with CANCELLED status or where current_time > latest_dropoff_time
    cannot acquire seat holds.
    """
    _, ride, storage = _create_test_entities(vehicle_capacity=4)
    policy = DispatchPolicy(join_request_expiry_seconds=300)

    req_cancelled = RideRequest(
        request_id="req-canc",
        user_id="user-c",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7589, longitude=-73.9851),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=4000,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.CANCELLED,
    )
    res_canc = submit_join_request(req_cancelled, ride.ride_id, storage, policy, 1000, "token-canc")
    assert res_canc.success is False
    assert res_canc.rejection_reason == "REQUEST_CANCELLED"
    assert storage.get_seat_hold(res_canc.join_request.join_request_id) is None

    req_expired = RideRequest(
        request_id="req-past-drop",
        user_id="user-e",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7589, longitude=-73.9851),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=1500,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    res_exp = submit_join_request(req_expired, ride.ride_id, storage, policy, 1501, "token-past")
    assert res_exp.success is False
    assert res_exp.rejection_reason == "REQUEST_EXPIRED"
    assert storage.get_seat_hold(res_exp.join_request.join_request_id) is None


def test_reject_already_approved_join_request_fails() -> None:
    """
    Verifies that attempting to reject an already APPROVED join request raises LifecycleTransitionError.
    """
    _, ride, storage = _create_test_entities(vehicle_capacity=4)
    policy_provider = DefaultPolicyProvider()
    router = MockRoutingProvider()

    req = RideRequest(
        request_id="req-approved-rej",
        user_id="user-appr",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7589, longitude=-73.9851),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=4000,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    storage.save_request(req)

    sub = submit_join_request(req, ride.ride_id, storage, policy_provider.get_policy(), 1000, "token-appr")
    assert sub.success is True
    conf = confirm_join_request(sub.join_request.join_request_id, storage, policy_provider, router, 1010, "token-appr")
    assert conf.success is True

    with pytest.raises(LifecycleTransitionError, match="already APPROVED"):
        reject_join_request(sub.join_request.join_request_id, storage)

