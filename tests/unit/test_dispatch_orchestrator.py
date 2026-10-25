"""Unit tests for DispatchOrchestrator (Phase 1, Item 1.4)."""

import concurrent.futures
import time
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.routing import RouteLookupError
from engine.dispatch import CandidateGenerationConfig
from engine.domain.enums import RequestStatus, RideStatus, SearchStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle
from engine.orchestration.dispatch_orchestrator import (
    DispatchOrchestrator,
    OrchestrationConfig,
    OrchestrationResult,
)


def _make_req(
    req_id: str,
    p_lat: float,
    p_lon: float,
    d_lat: float,
    d_lon: float,
    current_time: int = 1000,
    latest_dropoff: int = 2500,
    seat_count: int = 1,
) -> RideRequest:
    return RideRequest(
        request_id=req_id,
        user_id=f"u-{req_id}",
        pickup_location=GeoCoordinate(latitude=p_lat, longitude=p_lon),
        dropoff_location=GeoCoordinate(latitude=d_lat, longitude=d_lon),
        seat_count=seat_count,
        earliest_pickup_time=current_time,
        latest_dropoff_time=latest_dropoff,
        direct_distance_meters=2000,
        direct_duration_seconds=300,
        status=RequestStatus.PENDING,
    )


def _make_veh(
    veh_id: str,
    lat: float,
    lon: float,
    capacity: int = 4,
    is_active: bool = True,
) -> Vehicle:
    return Vehicle(
        vehicle_id=veh_id,
        driver_id=f"d-{veh_id}",
        total_seat_capacity=capacity,
        current_location=GeoCoordinate(latitude=lat, longitude=lon),
        is_active=is_active,
    )


def _build_orchestrator(
    storage: InMemoryRideStorage,
    router: MockRoutingProvider | None = None,
    config: OrchestrationConfig | None = None,
) -> DispatchOrchestrator:
    return DispatchOrchestrator(
        storage=storage,
        policy_provider=DefaultPolicyProvider(),
        routing_provider=router or MockRoutingProvider(),
        spatial_index=H3SpatialIndexAdapter(),
        config=config or OrchestrationConfig(
            candidate_generation_config=CandidateGenerationConfig.exact()
        ),
    )


# ---------------------------------------------------------------------------
# 1. Successful Dispatch from Stored Requests and Vehicles
# ---------------------------------------------------------------------------

def test_dispatch_orchestrator_successful_commit() -> None:
    storage = InMemoryRideStorage()
    veh = _make_veh("v1", 40.7100, -74.0050)
    req1 = _make_req("r1", 40.7110, -74.0040, 40.7300, -73.9900)
    req2 = _make_req("r2", 40.7120, -74.0030, 40.7320, -73.9920)

    storage.save_vehicle(veh)
    storage.save_request(req1)
    storage.save_request(req2)

    orchestrator = _build_orchestrator(storage)
    res = orchestrator.dispatch_cycle(current_time=1000, cycle_id="cycle-success-1")

    assert len(res.committed_assignments) == 1
    assert len(res.rejected_assignments) == 0
    assert len(res.unassigned_request_ids) == 0
    assert res.search_status == SearchStatus.COMPLETE
    assert res.total_vmt_savings_meters > 0

    # Verify requests in storage are MATCHED
    stored_r1 = storage.get_request("r1")
    stored_r2 = storage.get_request("r2")
    assert stored_r1 is not None and stored_r1.status == RequestStatus.MATCHED
    assert stored_r2 is not None and stored_r2.status == RequestStatus.MATCHED
    assert stored_r1.matched_ride_id is not None
    assert stored_r1.matched_ride_id == stored_r2.matched_ride_id

    # Verify Ride in storage
    committed_ride_id = stored_r1.matched_ride_id
    ride = storage.get_ride(committed_ride_id)
    assert ride is not None
    assert ride.vehicle_id == "v1"
    assert ride.lifecycle_status == RideStatus.SCHEDULED
    assert len(ride.stops) == 4  # 2 pickups + 2 dropoffs
    assert ride.version == 1


# ---------------------------------------------------------------------------
# 2. No Eligible Requests or Vehicles
# ---------------------------------------------------------------------------

def test_dispatch_orchestrator_empty_inputs() -> None:
    storage = InMemoryRideStorage()
    orchestrator = _build_orchestrator(storage)

    # Completely empty storage
    res = orchestrator.dispatch_cycle(current_time=1000)
    assert len(res.committed_assignments) == 0
    assert len(res.unassigned_request_ids) == 0
    assert res.search_status == SearchStatus.COMPLETE

    # Only requests, no vehicles
    req1 = _make_req("r1", 40.7110, -74.0040, 40.7300, -73.9900)
    storage.save_request(req1)
    res = orchestrator.dispatch_cycle(current_time=1000)
    assert len(res.committed_assignments) == 0
    assert "r1" in res.unassigned_request_ids
    assert res.search_status == SearchStatus.COMPLETE


# ---------------------------------------------------------------------------
# 3. Sweeping Expired Requests
# ---------------------------------------------------------------------------

def test_dispatch_orchestrator_sweeps_expired_requests() -> None:
    storage = InMemoryRideStorage()
    veh = _make_veh("v1", 40.7100, -74.0050)
    # req1 is already expired at current_time=2000 (latest_dropoff=1500)
    req1 = _make_req("r1", 40.7110, -74.0040, 40.7300, -73.9900, current_time=1000, latest_dropoff=1500)
    # req2 is valid with current_time=2000
    req2 = _make_req("r2", 40.7120, -74.0030, 40.7320, -73.9920, current_time=2000, latest_dropoff=4000)

    storage.save_vehicle(veh)
    storage.save_request(req1)
    storage.save_request(req2)

    orchestrator = _build_orchestrator(storage)
    res = orchestrator.dispatch_cycle(current_time=2000)

    # req1 was swept and marked EXPIRED
    stored_r1 = storage.get_request("r1")
    assert stored_r1 is not None and stored_r1.status == RequestStatus.EXPIRED

    # req2 was dispatched
    assert len(res.committed_assignments) == 1
    assert "r2" in res.committed_assignments[0].request_ids
    assert "r1" not in res.committed_assignments[0].request_ids


# ---------------------------------------------------------------------------
# 4. Stale Ride Version Conflict and Partial Commit Isolation
# ---------------------------------------------------------------------------

def test_dispatch_orchestrator_stale_ride_version_and_isolation() -> None:
    storage = InMemoryRideStorage()

    # Active ride on vehicle 1 (Downtown Manhattan)
    v1 = _make_veh("v1", 40.7100, -74.0050)
    storage.save_vehicle(v1)
    stop0 = RouteStop(
        stop_id="s0",
        ride_id="ride-active-1",
        request_id="r0",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=40.7400, longitude=-73.9850),
        passenger_delta=-1,
        scheduled_arrival_time=1500,
        promised_window_start=1000,
        promised_window_end=2000,
        status=StopStatus.SCHEDULED,
    )
    ride1 = Ride(
        ride_id="ride-active-1",
        vehicle_id="v1",
        driver_id="d-v1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop0,),
        scheduled_departure_time=1000,
        active_passenger_count=1,
        total_vmt_meters=4000,
        version=1,
    )
    storage.save_ride(ride1)

    # Idle vehicle 2 (Washington Heights, ~15 km away)
    v2 = _make_veh("v2", 40.8500, -73.9300)
    storage.save_vehicle(v2)

    # r1 near v1, r2 and r3 near v2
    r1 = _make_req("r1", 40.7120, -74.0030, 40.7380, -73.9870)
    r2 = _make_req("r2", 40.8520, -73.9280, 40.8700, -73.9150)
    r3 = _make_req("r3", 40.8530, -73.9270, 40.8720, -73.9140)
    storage.save_request(r1)
    storage.save_request(r2)
    storage.save_request(r3)

    orchestrator = _build_orchestrator(
        storage,
        config=OrchestrationConfig(
            max_retries_per_conflict=0,
            candidate_generation_config=CandidateGenerationConfig.exact(),
        ),
    )

    # Simulate concurrent modification to ride1 BEFORE commit:
    # We subclass/wrap storage to mutate ride1 version when dispatch_batch finishes
    orig_dispatch_batch = orchestrator._dispatch_engine.dispatch_batch
    def mutate_during_solve(*args: object, **kwargs: object) -> object:
        res = orig_dispatch_batch(*args, **kwargs)  # type: ignore[arg-type]
        # Concurrently increment version in storage
        current_r = storage.get_ride("ride-active-1")
        if current_r is not None:
            storage.save_ride(current_r.model_copy(update={"version": current_r.version + 1}))
        return res

    setattr(orchestrator._dispatch_engine, "dispatch_batch", mutate_during_solve)

    res = orchestrator.dispatch_cycle(current_time=1000)

    # The assignment on v1 suffered VERSION_CONFLICT
    assert any(diag.rejection_reason == "VERSION_CONFLICT" for diag in res.rejected_assignments)
    # The assignment on v2 succeeded! One failed commit does NOT corrupt or abort other assignments!
    assert len(res.committed_assignments) >= 1
    assert any(c.vehicle_id == "v2" for c in res.committed_assignments)


# ---------------------------------------------------------------------------
# 5. Request Concurrently Cancelled / Not Pending
# ---------------------------------------------------------------------------

def test_dispatch_orchestrator_request_concurrently_cancelled() -> None:
    storage = InMemoryRideStorage()
    veh = _make_veh("v1", 40.7100, -74.0050)
    req1 = _make_req("r1", 40.7110, -74.0040, 40.7300, -73.9900)

    storage.save_vehicle(veh)
    storage.save_request(req1)

    orchestrator = _build_orchestrator(storage)

    # Concurrently cancel request right before commit
    orig_dispatch_batch = orchestrator._dispatch_engine.dispatch_batch
    def cancel_during_solve(*args: object, **kwargs: object) -> object:
        res = orig_dispatch_batch(*args, **kwargs)  # type: ignore[arg-type]
        storage.save_request(req1.model_copy(update={"status": RequestStatus.CANCELLED}))
        return res

    setattr(orchestrator._dispatch_engine, "dispatch_batch", cancel_during_solve)

    res = orchestrator.dispatch_cycle(current_time=1000)

    assert len(res.committed_assignments) == 0
    assert len(res.rejected_assignments) == 1
    assert res.rejected_assignments[0].rejection_reason == "REQUEST_NOT_PENDING"
    assert "r1" in res.unassigned_request_ids


# ---------------------------------------------------------------------------
# 6. Bounded Retry on Version Conflict
# ---------------------------------------------------------------------------

def test_dispatch_orchestrator_bounded_retry() -> None:
    storage = InMemoryRideStorage()
    v1 = _make_veh("v1", 40.7100, -74.0050, capacity=6)
    storage.save_vehicle(v1)

    stop0 = RouteStop(
        stop_id="s0",
        ride_id="ride-active-1",
        request_id="r0",
        stop_type=StopType.DROPOFF,
        location=GeoCoordinate(latitude=40.7400, longitude=-73.9850),
        passenger_delta=-1,
        scheduled_arrival_time=1500,
        promised_window_start=1000,
        promised_window_end=2000,
        status=StopStatus.SCHEDULED,
    )
    ride1 = Ride(
        ride_id="ride-active-1",
        vehicle_id="v1",
        driver_id="d-v1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop0,),
        scheduled_departure_time=1000,
        active_passenger_count=1,
        total_vmt_meters=4000,
        version=1,
    )
    storage.save_ride(ride1)

    r1 = _make_req("r1", 40.7120, -74.0030, 40.7380, -73.9870)
    storage.save_request(r1)

    orchestrator = _build_orchestrator(
        storage,
        config=OrchestrationConfig(
            max_retries_per_conflict=1,
            candidate_generation_config=CandidateGenerationConfig.exact(),
        ),
    )

    # Increment version concurrently
    orig_dispatch_batch = orchestrator._dispatch_engine.dispatch_batch
    def mutate_during_solve(*args: object, **kwargs: object) -> object:
        res = orig_dispatch_batch(*args, **kwargs)  # type: ignore[arg-type]
        current_r = storage.get_ride("ride-active-1")
        if current_r is not None:
            storage.save_ride(current_r.model_copy(update={"version": 2}))
        return res

    setattr(orchestrator._dispatch_engine, "dispatch_batch", mutate_during_solve)

    res = orchestrator.dispatch_cycle(current_time=1000)

    # Bounded retry successfully commits the assignment against version 2
    assert len(res.committed_assignments) == 1
    assert len(res.rejected_assignments) == 0
    updated_ride = storage.get_ride("ride-active-1")
    assert updated_ride is not None
    assert updated_ride.version == 3


# ---------------------------------------------------------------------------
# 7. Idempotent Replays
# ---------------------------------------------------------------------------

def test_dispatch_orchestrator_idempotent_replay() -> None:
    storage = InMemoryRideStorage()
    veh = _make_veh("v1", 40.7100, -74.0050)
    req1 = _make_req("r1", 40.7110, -74.0040, 40.7300, -73.9900)

    storage.save_vehicle(veh)
    storage.save_request(req1)

    orchestrator = _build_orchestrator(storage)

    # First cycle
    res1 = orchestrator.dispatch_cycle(
        current_time=1000,
        cycle_id="cycle-idemp-1",
        idempotency_token="tok-1",
    )
    assert len(res1.committed_assignments) == 1
    committed_ride_id = res1.committed_assignments[0].existing_ride_id or storage.get_request("r1").matched_ride_id  # type: ignore[union-attr]

    # Replay with same token: requests are now MATCHED, so snapshot query will see 0 PENDING
    # But if calling commit_dispatch_assignment_atomic with the same token directly, it returns success
    cand = res1.committed_assignments[0]
    replay_commit = storage.commit_dispatch_assignment_atomic(
        assignment=cand,
        idempotency_token="tok-1:" + cand.candidate_id,
        current_time=1000,
    )
    assert replay_commit.success is True
    assert replay_commit.ride_id == committed_ride_id


# ---------------------------------------------------------------------------
# 8. Routing Errors and Deadline Expired Diagnostics
# ---------------------------------------------------------------------------

class FailingRouter(MockRoutingProvider):
    def get_direct_leg(self, origin: object, destination: object) -> tuple[int, int]:
        raise RouteLookupError("Simulated downstream routing error")


def test_dispatch_orchestrator_surfaces_routing_error_status() -> None:
    storage = InMemoryRideStorage()
    veh = _make_veh("v1", 40.7100, -74.0050)
    req1 = _make_req("r1", 40.7110, -74.0040, 40.7300, -73.9900)
    storage.save_vehicle(veh)
    storage.save_request(req1)

    failing_router = FailingRouter()
    orchestrator = _build_orchestrator(storage, router=failing_router)

    res = orchestrator.dispatch_cycle(current_time=1000)
    assert res.search_status == SearchStatus.INCOMPLETE_ROUTING_ERROR
    assert res.is_approximated is True
    assert res.routing_errors_count > 0
    assert len(res.committed_assignments) == 0


def test_dispatch_orchestrator_surfaces_deadline_expired_status() -> None:
    storage = InMemoryRideStorage()
    veh = _make_veh("v1", 40.7100, -74.0050)
    req1 = _make_req("r1", 40.7110, -74.0040, 40.7300, -73.9900)
    storage.save_vehicle(veh)
    storage.save_request(req1)

    orchestrator = _build_orchestrator(storage)
    # Supply an already expired deadline
    res = orchestrator.dispatch_cycle(
        current_time=1000,
        deadline=time.monotonic() - 0.001,
    )
    assert res.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
    assert res.is_approximated is True
    assert len(res.committed_assignments) == 0


# ---------------------------------------------------------------------------
# 9. Concurrent Orchestrator Calls Race Prevention
# ---------------------------------------------------------------------------

def test_concurrent_orchestrator_calls_race_prevention() -> None:
    storage = InMemoryRideStorage()
    # 2 vehicles, 1 request
    v1 = _make_veh("v1", 40.7100, -74.0050)
    v2 = _make_veh("v2", 40.7105, -74.0045)
    req1 = _make_req("r1", 40.7110, -74.0040, 40.7300, -73.9900)

    storage.save_vehicle(v1)
    storage.save_vehicle(v2)
    storage.save_request(req1)

    orchestrator = _build_orchestrator(storage)

    def run_worker(idx: int) -> OrchestrationResult:
        return orchestrator.dispatch_cycle(
            current_time=1000,
            cycle_id=f"concurrent-cycle-{idx}",
            idempotency_token=f"tok-worker-{idx}",
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(run_worker, 1)
        f2 = executor.submit(run_worker, 2)
        r1 = f1.result()
        r2 = f2.result()

    total_committed = len(r1.committed_assignments) + len(r2.committed_assignments)
    # Exactly one worker must have successfully committed request r1
    assert total_committed == 1
    # Exactly one ride created
    assert storage.get_request("r1").status == RequestStatus.MATCHED  # type: ignore[union-attr]
