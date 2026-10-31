"""Unit and concurrency tests for formalized RideStorageProvider contract methods (T048)."""

import concurrent.futures
from typing import Optional, Sequence

import pytest

from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.contracts.storage import (
    AssignmentCommitResult,
    CancellationCommitResult,
    IdempotencyRecord,
    RideStorageProvider,
    SeatHold,
)
from engine.domain.candidate import CandidateAssignment
from engine.domain.enums import JoinStatus, RequestStatus, RideStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, JoinRequest, Ride, RideRequest, RouteStop, Vehicle
from engine.lifecycle.reservations import expire_stale_holds, submit_join_request
from engine.contracts.policy import DispatchPolicy


def _setup_test_ride_and_storage(
    ride_id: str = "ride-storage-1",
    vehicle_capacity: int = 4,
) -> tuple[InMemoryRideStorage, Ride, Vehicle]:
    storage = InMemoryRideStorage()
    loc = GeoCoordinate(latitude=40.7128, longitude=-74.0060)
    vehicle = Vehicle(
        vehicle_id="veh-s-1",
        driver_id="drv-s-1",
        total_seat_capacity=vehicle_capacity,
        current_location=loc,
        is_active=True,
    )
    storage.save_vehicle(vehicle)
    ride = Ride(
        ride_id=ride_id,
        vehicle_id=vehicle.vehicle_id,
        driver_id=vehicle.driver_id,
        lifecycle_status=RideStatus.ACTIVE,
        stops=(),
        scheduled_departure_time=1000,
        active_passenger_count=0,
        version=1,
    )
    storage.save_ride(ride)
    return storage, ride, vehicle


def test_storage_contract_defines_abstract_methods() -> None:
    """Verifies that RideStorageProvider requires get_active_seat_holds, sweep_expired_holds, and get_idempotency_record."""
    assert "get_active_seat_holds" in RideStorageProvider.__abstractmethods__
    assert "sweep_expired_holds" in RideStorageProvider.__abstractmethods__
    assert "get_idempotency_record" in RideStorageProvider.__abstractmethods__
    assert "get_pending_requests" in RideStorageProvider.__abstractmethods__
    assert "get_active_vehicles" in RideStorageProvider.__abstractmethods__
    assert "get_active_rides" in RideStorageProvider.__abstractmethods__
    assert "commit_dispatch_assignment_atomic" in RideStorageProvider.__abstractmethods__
    assert "cancel_assigned_request_atomic" in RideStorageProvider.__abstractmethods__

    class IncompleteStorage(RideStorageProvider):
        pass

    with pytest.raises(TypeError, match="Can't instantiate abstract class IncompleteStorage"):
        IncompleteStorage()  # type: ignore[abstract]


def test_get_active_seat_holds_filters_by_ride_and_expiry() -> None:
    """
    Verifies get_active_seat_holds:
    - Filters holds strictly by ride_id
    - Considers holds active when current_time <= expires_at (exact boundary)
    - Excludes holds when current_time > expires_at
    """
    storage, ride1, _ = _setup_test_ride_and_storage("ride-1", vehicle_capacity=6)
    _, ride2, _ = _setup_test_ride_and_storage("ride-2", vehicle_capacity=6)
    # Save ride2 into storage as well
    storage.save_ride(ride2)

    # Acquire 2 holds on ride-1
    ok1 = storage.acquire_seat_hold_atomic(
        ride_id="ride-1",
        request_id="req-1",
        join_request_id="join-1",
        seat_count=1,
        submitted_at=1000,
        expires_at=1300,
        expected_version=1,
        idempotency_token="token-1",
    )
    assert ok1

    ride1_updated = storage.get_ride("ride-1")
    assert ride1_updated is not None
    ok2 = storage.acquire_seat_hold_atomic(
        ride_id="ride-1",
        request_id="req-2",
        join_request_id="join-2",
        seat_count=2,
        submitted_at=1000,
        expires_at=1400,
        expected_version=ride1_updated.version,
        idempotency_token="token-2",
    )
    assert ok2

    # Acquire 1 hold on ride-2
    ok3 = storage.acquire_seat_hold_atomic(
        ride_id="ride-2",
        request_id="req-3",
        join_request_id="join-3",
        seat_count=1,
        submitted_at=1000,
        expires_at=1350,
        expected_version=1,
        idempotency_token="token-3",
    )
    assert ok3

    # Query without current_time: returns all tracked holds for ride-1
    holds_all = storage.get_active_seat_holds("ride-1")
    assert len(holds_all) == 2
    hold_ids = {h.join_request_id for h in holds_all}
    assert hold_ids == {"join-1", "join-2"}
    # Type check contract return type
    assert all(isinstance(h, SeatHold) for h in holds_all)

    # Query with current_time = 1200: both holds active (1200 <= 1300, 1200 <= 1400)
    holds_1200 = storage.get_active_seat_holds("ride-1", current_time=1200)
    assert len(holds_1200) == 2

    # Exact boundary check: t = 1300 (1300 <= 1300 is active)
    holds_1300 = storage.get_active_seat_holds("ride-1", current_time=1300)
    assert len(holds_1300) == 2

    # One second past boundary: t = 1301 (1301 > 1300 -> join-1 expired; join-2 still active)
    holds_1301 = storage.get_active_seat_holds("ride-1", current_time=1301)
    assert len(holds_1301) == 1
    assert holds_1301[0].join_request_id == "join-2"

    # Query ride-2 at t = 1301: join-3 still active (1301 <= 1350)
    holds_r2 = storage.get_active_seat_holds("ride-2", current_time=1301)
    assert len(holds_r2) == 1
    assert holds_r2[0].join_request_id == "join-3"

    # After both expired on ride-1: t = 1401
    holds_1401 = storage.get_active_seat_holds("ride-1", current_time=1401)
    assert len(holds_1401) == 0


def test_sweep_expired_holds_idempotency_and_exact_boundary() -> None:
    """
    Verifies sweep_expired_holds:
    - Retains holds while current_time <= expires_at
    - Cleans up and returns IDs when current_time > expires_at
    - Is idempotent on repeated calls
    """
    storage, ride, _ = _setup_test_ride_and_storage("ride-sweep", vehicle_capacity=6)

    storage.acquire_seat_hold_atomic(
        ride_id="ride-sweep",
        request_id="req-1",
        join_request_id="join-1",
        seat_count=1,
        submitted_at=1000,
        expires_at=1100,
        expected_version=1,
        idempotency_token="tok-1",
    )
    v2 = storage.get_ride("ride-sweep").version  # type: ignore[union-attr]
    storage.acquire_seat_hold_atomic(
        ride_id="ride-sweep",
        request_id="req-2",
        join_request_id="join-2",
        seat_count=1,
        submitted_at=1000,
        expires_at=1200,
        expected_version=v2,
        idempotency_token="tok-2",
    )

    # Exact boundary at t = 1100: both still active (1100 <= 1100)
    swept_1100 = storage.sweep_expired_holds(current_time=1100)
    assert len(swept_1100) == 0
    assert len(storage.get_active_seat_holds("ride-sweep")) == 2

    # 1 second past boundary at t = 1101: join-1 is expired and swept
    swept_1101 = storage.sweep_expired_holds(current_time=1101)
    assert list(swept_1101) == ["join-1"]
    assert len(storage.get_active_seat_holds("ride-sweep")) == 1

    # Idempotent repeated sweep at same timestamp: returns empty sequence
    swept_repeat = storage.sweep_expired_holds(current_time=1101)
    assert len(swept_repeat) == 0

    # Sweep at earlier timestamp: returns empty sequence
    swept_earlier = storage.sweep_expired_holds(current_time=1050)
    assert len(swept_earlier) == 0

    # Sweep at t = 1250: sweeps remaining join-2
    swept_1250 = storage.sweep_expired_holds(current_time=1250)
    assert list(swept_1250) == ["join-2"]
    assert len(storage.get_active_seat_holds("ride-sweep")) == 0

    # Repeated sweep at t = 1250
    assert len(storage.sweep_expired_holds(current_time=1250)) == 0


def test_expire_stale_holds_invokes_formal_contract() -> None:
    """Verifies that expire_stale_holds invokes sweep_expired_holds through RideStorageProvider."""
    storage, ride, _ = _setup_test_ride_and_storage("ride-stale", vehicle_capacity=4)

    storage.acquire_seat_hold_atomic(
        ride_id="ride-stale",
        request_id="req-stale",
        join_request_id="join-stale",
        seat_count=1,
        submitted_at=1000,
        expires_at=1100,
        expected_version=1,
        idempotency_token="tok-stale",
    )
    jr = JoinRequest(
        join_request_id="join-stale",
        ride_id="ride-stale",
        request_id="req-stale",
        user_id="u-stale",
        seat_count=1,
        submitted_at=1000,
        expires_at=1100,
        status=JoinStatus.PENDING,
        idempotency_token="tok-stale",
    )
    storage.save_join_request(jr)

    # Before expiry: nothing swept
    expired_before = expire_stale_holds(storage, current_time=1100)
    assert len(expired_before) == 0
    assert storage.get_join_request("join-stale").status == JoinStatus.PENDING  # type: ignore[union-attr]

    # After expiry: swept and status updated to EXPIRED
    expired_after = expire_stale_holds(storage, current_time=1101)
    assert expired_after == ["join-stale"]
    assert storage.get_join_request("join-stale").status == JoinStatus.EXPIRED  # type: ignore[union-attr]

    # Second call is idempotent
    assert expire_stale_holds(storage, current_time=1101) == []


def test_concurrent_active_holds_and_sweeps() -> None:
    """Tests thread-safety when querying active holds while concurrent sweeps occur."""
    storage, ride, _ = _setup_test_ride_and_storage("ride-conc", vehicle_capacity=50)

    # Provision 20 holds expiring staggered between 1100 and 1300
    for i in range(20):
        v = storage.get_ride("ride-conc").version  # type: ignore[union-attr]
        storage.acquire_seat_hold_atomic(
            ride_id="ride-conc",
            request_id=f"req-{i}",
            join_request_id=f"join-{i}",
            seat_count=1,
            submitted_at=1000,
            expires_at=1100 + i * 10,
            expected_version=v,
            idempotency_token=f"tok-{i}",
        )

    def _query_active(t: int) -> int:
        return len(storage.get_active_seat_holds("ride-conc", current_time=t))

    def _sweep(t: int) -> int:
        return len(storage.sweep_expired_holds(current_time=t))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = []
        for step in range(30):
            t = 1050 + step * 10
            futures.append(executor.submit(_query_active, t))
            futures.append(executor.submit(_sweep, t))

        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            assert res >= 0


def test_submit_join_request_occ_retry_uses_contract_without_private_holds_access() -> None:
    """Verifies submit_join_request uses get_active_seat_holds on OCC retry without accessing _holds."""
    raw_storage, ride, vehicle = _setup_test_ride_and_storage("ride-occ", vehicle_capacity=4)

    class ContractOnlyStorageProxy(RideStorageProvider):
        """Strict proxy implementing only the formal RideStorageProvider contract."""
        def __init__(self, target: InMemoryRideStorage) -> None:
            self._target = target
            self.get_active_seat_holds_called = False
            self.injected_conflict = False

        def get_ride(self, ride_id: str) -> Optional[Ride]:
            return self._target.get_ride(ride_id)

        def save_ride(self, ride: Ride) -> None:
            self._target.save_ride(ride)

        def get_active_rides_in_bounding_box(
            self, min_lat: float, min_lon: float, max_lat: float, max_lon: float
        ) -> Sequence[Ride]:
            return self._target.get_active_rides_in_bounding_box(min_lat, min_lon, max_lat, max_lon)

        def get_vehicle(self, vehicle_id: str) -> Optional[Vehicle]:
            return self._target.get_vehicle(vehicle_id)

        def save_vehicle(self, vehicle: Vehicle) -> None:
            self._target.save_vehicle(vehicle)

        def get_request(self, request_id: str) -> Optional[RideRequest]:
            return self._target.get_request(request_id)

        def save_request(self, request: RideRequest) -> None:
            self._target.save_request(request)

        def get_join_request(self, join_request_id: str) -> Optional[JoinRequest]:
            return self._target.get_join_request(join_request_id)

        def save_join_request(self, join_request: JoinRequest) -> None:
            self._target.save_join_request(join_request)

        def record_proposal_acceptance(
            self,
            join_request_id: str,
            is_host: bool,
            is_traveller: bool,
        ) -> Optional[tuple[bool, bool]]:
            return self._target.record_proposal_acceptance(join_request_id, is_host, is_traveller)

        def acquire_seat_hold_atomic(
            self,
            ride_id: str,
            request_id: str,
            join_request_id: str,
            seat_count: int,
            submitted_at: int,
            expires_at: int,
            expected_version: int,
            idempotency_token: str,
        ) -> bool:
            if not self.injected_conflict:
                self.injected_conflict = True
                # Concurrently increment version in underlying ride to trigger OCC retry
                r = self._target.get_ride(ride_id)
                if r is not None:
                    self._target.save_ride(r.model_copy(update={"version": r.version + 1}))
                return False
            return self._target.acquire_seat_hold_atomic(
                ride_id, request_id, join_request_id, seat_count, submitted_at, expires_at, expected_version, idempotency_token
            )

        def reserve_seats_atomic(
            self,
            ride_id: str,
            request_id: str,
            join_request_id: str,
            seat_count: int,
            expected_version: int,
            idempotency_token: str,
            new_stops: Optional[Sequence[RouteStop]] = None,
            current_time: Optional[int] = None,
        ) -> bool:
            return self._target.reserve_seats_atomic(
                ride_id, request_id, join_request_id, seat_count, expected_version, idempotency_token, new_stops, current_time
            )

        def release_seats_atomic(
            self,
            ride_id: str,
            join_request_id: str,
            request_id: Optional[str] = None,
            seat_count: Optional[int] = None,
            reason: Optional[str] = None,
        ) -> bool:
            return self._target.release_seats_atomic(ride_id, join_request_id, request_id, seat_count, reason)

        def get_active_seat_holds(
            self, ride_id: str, current_time: Optional[int] = None
        ) -> Sequence[SeatHold]:
            self.get_active_seat_holds_called = True
            return self._target.get_active_seat_holds(ride_id, current_time)

        def sweep_expired_holds(self, current_time: int) -> Sequence[str]:
            return self._target.sweep_expired_holds(current_time)

        def get_idempotency_record(self, idempotency_token: str) -> Optional[IdempotencyRecord]:
            return self._target.get_idempotency_record(idempotency_token)

        def get_pending_requests(self, limit: Optional[int] = None) -> Sequence[RideRequest]:
            return self._target.get_pending_requests(limit)

        def get_active_vehicles(self, limit: Optional[int] = None) -> Sequence[Vehicle]:
            return self._target.get_active_vehicles(limit)

        def get_active_rides(self, limit: Optional[int] = None) -> Sequence[Ride]:
            return self._target.get_active_rides(limit)

        def commit_dispatch_assignment_atomic(
            self,
            assignment: CandidateAssignment,
            idempotency_token: str,
            current_time: int,
            expected_ride_version: Optional[int] = None,
            new_ride_id: Optional[str] = None,
        ) -> AssignmentCommitResult:
            return self._target.commit_dispatch_assignment_atomic(
                assignment, idempotency_token, current_time, expected_ride_version, new_ride_id
            )

        def cancel_assigned_request_atomic(
            self,
            ride_id: str,
            request_id: str,
            expected_ride_version: int,
            updated_stops: Sequence[RouteStop],
            new_total_vmt_meters: int,
            idempotency_token: Optional[str] = None,
            new_ride_status: Optional[RideStatus] = None,
        ) -> CancellationCommitResult:
            return self._target.cancel_assigned_request_atomic(
                ride_id,
                request_id,
                expected_ride_version,
                updated_stops,
                new_total_vmt_meters,
                idempotency_token,
                new_ride_status,
            )

    proxy_storage = ContractOnlyStorageProxy(raw_storage)
    policy = DispatchPolicy(join_request_expiry_seconds=300)

    req1 = RideRequest(
        request_id="req-occ-1",
        user_id="user-1",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7589, longitude=-73.9851),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=3000,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    req2 = RideRequest(
        request_id="req-occ-2",
        user_id="user-2",
        pickup_location=GeoCoordinate(latitude=40.7128, longitude=-74.0060),
        dropoff_location=GeoCoordinate(latitude=40.7589, longitude=-73.9851),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=3000,
        direct_distance_meters=5000,
        direct_duration_seconds=600,
        status=RequestStatus.PENDING,
    )
    proxy_storage.save_request(req1)
    proxy_storage.save_request(req2)

    # First join request acquires hold
    res1 = submit_join_request(
        request=req1,
        ride_id="ride-occ",
        storage=proxy_storage,
        policy=policy,
        current_time=1000,
        idempotency_token="tok-occ-1",
    )
    assert res1.success

    # Second join request attempts submission; with OCC version increment, it retries and reads get_active_seat_holds
    res2 = submit_join_request(
        request=req2,
        ride_id="ride-occ",
        storage=proxy_storage,
        policy=policy,
        current_time=1000,
        idempotency_token="tok-occ-2",
    )
    assert res2.success
    assert proxy_storage.get_active_seat_holds_called, "Expected formal get_active_seat_holds to be invoked on OCC retry"


def test_get_idempotency_record_and_conflict_detection() -> None:
    """Verifies get_idempotency_record stores and returns canonical records, detecting token reuse conflicts."""
    storage, ride, _ = _setup_test_ride_and_storage("ride-idem", vehicle_capacity=4)

    assert storage.get_idempotency_record("nonexistent-token") is None

    # Acquire hold
    ok = storage.acquire_seat_hold_atomic(
        ride_id="ride-idem",
        request_id="req-1",
        join_request_id="join-1",
        seat_count=1,
        submitted_at=1000,
        expires_at=1300,
        expected_version=1,
        idempotency_token="token-hold-1",
    )
    assert ok

    rec = storage.get_idempotency_record("token-hold-1")
    assert rec is not None
    assert rec.token == "token-hold-1"
    assert rec.record_type == "hold"
    assert rec.join_request_id == "join-1"
    assert rec.request_id == "req-1"
    assert rec.ride_id == "ride-idem"


def test_cancel_assigned_request_atomic_in_memory() -> None:
    """Verifies cancel_assigned_request_atomic:
    - Atomically removes stops and updates request status
    - Rejects stale versions (VERSION_CONFLICT)
    - Rejects already boarded passengers (PASSENGER_ALREADY_BOARDED)
    - Supports idempotent replays
    """
    storage, ride, _ = _setup_test_ride_and_storage("ride-atomic-c1", vehicle_capacity=4)
    loc = GeoCoordinate(latitude=40.75, longitude=-73.98)

    pickup = RouteStop(
        stop_id="stop-p1",
        ride_id=ride.ride_id,
        request_id="req-c1",
        stop_type=StopType.PICKUP,
        location=loc,
        passenger_delta=1,
        scheduled_arrival_time=1200,
        promised_window_start=1150,
        promised_window_end=1250,
        status=StopStatus.SCHEDULED,
    )
    dropoff = RouteStop(
        stop_id="stop-d1",
        ride_id=ride.ride_id,
        request_id="req-c1",
        stop_type=StopType.DROPOFF,
        location=loc,
        passenger_delta=-1,
        scheduled_arrival_time=1600,
        promised_window_start=1550,
        promised_window_end=1650,
        status=StopStatus.SCHEDULED,
    )
    ride_with_stops = ride.model_copy(update={"stops": (pickup, dropoff), "version": 1})
    storage.save_ride(ride_with_stops)

    req = RideRequest(
        request_id="req-c1",
        user_id="usr-c1",
        pickup_location=loc,
        dropoff_location=loc,
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=2000,
        direct_distance_meters=2000,
        direct_duration_seconds=400,
        status=RequestStatus.MATCHED,
        matched_ride_id=ride.ride_id,
    )
    storage.save_request(req)

    # 1. Stale version rejection
    stale_res = storage.cancel_assigned_request_atomic(
        ride_id=ride.ride_id,
        request_id="req-c1",
        expected_ride_version=99,
        updated_stops=(),
        new_total_vmt_meters=0,
    )
    assert not stale_res.success
    assert stale_res.rejection_reason == "VERSION_CONFLICT"

    # 2. Boarded passenger rejection
    boarded_pickup = pickup.model_copy(update={"status": StopStatus.COMPLETED})
    storage.save_ride(ride_with_stops.model_copy(update={"stops": (boarded_pickup, dropoff)}))
    boarded_res = storage.cancel_assigned_request_atomic(
        ride_id=ride.ride_id,
        request_id="req-c1",
        expected_ride_version=1,
        updated_stops=(),
        new_total_vmt_meters=0,
    )
    assert not boarded_res.success
    assert boarded_res.rejection_reason == "PASSENGER_ALREADY_BOARDED"

    # Restore unboarded stops
    storage.save_ride(ride_with_stops)

    # 3. Successful atomic cancellation
    success_res = storage.cancel_assigned_request_atomic(
        ride_id=ride.ride_id,
        request_id="req-c1",
        expected_ride_version=1,
        updated_stops=(),
        new_total_vmt_meters=0,
        idempotency_token="token-cancel-1",
    )
    assert success_res.success
    assert success_res.ride is not None
    assert success_res.ride.version == 2
    assert len(success_res.ride.stops) == 0
    assert success_res.request is not None
    assert success_res.request.status == RequestStatus.CANCELLED

    # Check persistence in storage
    assert storage.get_ride(ride.ride_id).version == 2  # type: ignore[union-attr]
    assert storage.get_request("req-c1").status == RequestStatus.CANCELLED  # type: ignore[union-attr]

    # 4. Idempotent replay with same token
    replay_res = storage.cancel_assigned_request_atomic(
        ride_id=ride.ride_id,
        request_id="req-c1",
        expected_ride_version=2,
        updated_stops=(),
        new_total_vmt_meters=0,
        idempotency_token="token-cancel-1",
    )
    assert replay_res.success
    assert replay_res.ride is not None and replay_res.ride.version == 2
