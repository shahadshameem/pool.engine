"""Live PostgreSQL integration tests for DispatchOrchestrator (Phase 1, Item 1.4).

Verifies persistence across adapter instances, transactional row locking (SELECT ... FOR UPDATE),
optimistic concurrency control (OCC), rollback on conflict, and multi-threaded race prevention.
"""

import concurrent.futures
import os
import time
from typing import Generator

import psycopg
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.mock_routing import MockRoutingProvider
from engine.adapters.postgres_storage import PostgresRideStorage
from engine.contracts.policy import DispatchPolicy
from engine.dispatch import CandidateGenerationConfig
from engine.domain.enums import RequestStatus, RideStatus, SearchStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle
from engine.orchestration.dispatch_orchestrator import (
    DispatchOrchestrator,
    OrchestrationConfig,
    OrchestrationResult,
)

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest.fixture(scope="module")
def postgres_storage() -> Generator[PostgresRideStorage, None, None]:
    """Provides an initialized PostgresRideStorage connected to a live test database."""
    if not TEST_DB_URL:
        pytest.skip(
            "Live PostgreSQL database environment is unavailable (set TEST_DATABASE_URL or DATABASE_URL to execute)"
        )

    try:
        conn = psycopg.connect(TEST_DB_URL, connect_timeout=3)
        conn.close()
    except Exception as exc:
        pytest.skip(f"Live PostgreSQL database is unreachable at {TEST_DB_URL}: {exc}")

    storage = PostgresRideStorage(dsn=TEST_DB_URL)
    storage.create_schema()
    yield storage
    storage.close()


@pytest.fixture(autouse=True)
def clean_database(postgres_storage: PostgresRideStorage) -> Generator[None, None, None]:
    """Truncates all tables before each test to guarantee isolated test execution."""
    conn = postgres_storage._get_connection()
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                TRUNCATE vehicles, rides, route_stops, ride_requests, join_requests, seat_holds, idempotency_records
                CASCADE;
                """
            )
    yield


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
    storage: PostgresRideStorage,
    config: OrchestrationConfig | None = None,
) -> DispatchOrchestrator:
    return DispatchOrchestrator(
        storage=storage,
        policy_provider=DefaultPolicyProvider(),
        routing_provider=MockRoutingProvider(),
        spatial_index=H3SpatialIndexAdapter(),
        config=config or OrchestrationConfig(
            candidate_generation_config=CandidateGenerationConfig.exact()
        ),
    )


# ---------------------------------------------------------------------------
# 1. End-to-End Dispatch and Persistence Across Adapter Instances
# ---------------------------------------------------------------------------

def test_postgres_orchestrator_end_to_end_dispatch(postgres_storage: PostgresRideStorage) -> None:
    veh = _make_veh("veh-pg-1", 40.7100, -74.0050)
    req1 = _make_req("req-pg-1", 40.7110, -74.0040, 40.7300, -73.9900)
    req2 = _make_req("req-pg-2", 40.7120, -74.0030, 40.7320, -73.9920)

    postgres_storage.save_vehicle(veh)
    postgres_storage.save_request(req1)
    postgres_storage.save_request(req2)

    orchestrator = _build_orchestrator(postgres_storage)
    res = orchestrator.dispatch_cycle(current_time=1000, cycle_id="cycle-pg-1")

    assert len(res.committed_assignments) == 1
    assert len(res.rejected_assignments) == 0
    assert len(res.unassigned_request_ids) == 0
    assert res.search_status == SearchStatus.COMPLETE

    # Verify persistence using a completely separate storage adapter instance
    fresh_storage = PostgresRideStorage(dsn=TEST_DB_URL)
    try:
        r1 = fresh_storage.get_request("req-pg-1")
        r2 = fresh_storage.get_request("req-pg-2")
        assert r1 is not None and r1.status == RequestStatus.MATCHED
        assert r2 is not None and r2.status == RequestStatus.MATCHED
        assert r1.matched_ride_id is not None
        assert r1.matched_ride_id == r2.matched_ride_id

        ride = fresh_storage.get_ride(r1.matched_ride_id)
        assert ride is not None
        assert ride.vehicle_id == "veh-pg-1"
        assert ride.lifecycle_status == RideStatus.SCHEDULED
        assert len(ride.stops) == 4
        assert ride.version == 1
    finally:
        fresh_storage.close()


# ---------------------------------------------------------------------------
# 2. Concurrent Dispatch Race Prevention Under Row Locks
# ---------------------------------------------------------------------------

def test_postgres_orchestrator_concurrent_dispatch_race_prevention(
    postgres_storage: PostgresRideStorage,
) -> None:
    # 2 vehicles, 1 request
    v1 = _make_veh("veh-pg-c1", 40.7100, -74.0050)
    v2 = _make_veh("veh-pg-c2", 40.7105, -74.0045)
    req = _make_req("req-pg-single", 40.7110, -74.0040, 40.7300, -73.9900)

    postgres_storage.save_vehicle(v1)
    postgres_storage.save_vehicle(v2)
    postgres_storage.save_request(req)

    def run_concurrent_worker(worker_id: int) -> OrchestrationResult:
        # Each thread gets its own storage connection
        thread_storage = PostgresRideStorage(dsn=TEST_DB_URL)
        try:
            orch = _build_orchestrator(thread_storage)
            return orch.dispatch_cycle(
                current_time=1000,
                cycle_id=f"cycle-worker-{worker_id}",
                idempotency_token=f"tok-worker-{worker_id}",
            )
        finally:
            thread_storage.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(run_concurrent_worker, 1)
        f2 = executor.submit(run_concurrent_worker, 2)
        r1 = f1.result()
        r2 = f2.result()

    total_committed = len(r1.committed_assignments) + len(r2.committed_assignments)
    # Database row locks ensure exactly 1 assignment successfully commits
    assert total_committed == 1
    # Check that request in DB is MATCHED exactly once
    final_req = postgres_storage.get_request("req-pg-single")
    assert final_req is not None
    assert final_req.status == RequestStatus.MATCHED


# ---------------------------------------------------------------------------
# 3. Stale Ride Version OCC Rollback in PostgreSQL
# ---------------------------------------------------------------------------

def test_postgres_orchestrator_stale_ride_version_occ_rollback(
    postgres_storage: PostgresRideStorage,
) -> None:
    # Vehicle 1 has an active ride in Downtown Manhattan
    v1 = _make_veh("v-pg-1", 40.7100, -74.0050)
    postgres_storage.save_vehicle(v1)
    stop0 = RouteStop(
        stop_id="s0",
        ride_id="ride-pg-active-1",
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
        ride_id="ride-pg-active-1",
        vehicle_id="v-pg-1",
        driver_id="d-v-pg-1",
        lifecycle_status=RideStatus.ACTIVE,
        stops=(stop0,),
        scheduled_departure_time=1000,
        active_passenger_count=1,
        total_vmt_meters=4000,
        version=1,
    )
    postgres_storage.save_ride(ride1)

    # Vehicle 2 is idle in Washington Heights (~15 km away)
    v2 = _make_veh("v-pg-2", 40.8500, -73.9300)
    postgres_storage.save_vehicle(v2)

    # r1 near v1, r2 and r3 near v2
    r1 = _make_req("req-pg-r1", 40.7120, -74.0030, 40.7380, -73.9870)
    r2 = _make_req("req-pg-r2", 40.8520, -73.9280, 40.8700, -73.9150)
    r3 = _make_req("req-pg-r3", 40.8530, -73.9270, 40.8720, -73.9140)
    postgres_storage.save_request(r1)
    postgres_storage.save_request(r2)
    postgres_storage.save_request(r3)

    orchestrator = _build_orchestrator(
        postgres_storage,
        config=OrchestrationConfig(
            max_retries_per_conflict=0,
            candidate_generation_config=CandidateGenerationConfig.exact(),
        ),
    )

    # Simulate concurrent mutation of ride1 during solving
    orig_dispatch_batch = orchestrator._dispatch_engine.dispatch_batch
    def mutate_during_solve(*args: object, **kwargs: object) -> object:
        res = orig_dispatch_batch(*args, **kwargs)  # type: ignore[arg-type]
        # Concurrently increment version in database
        cur_ride = postgres_storage.get_ride("ride-pg-active-1")
        if cur_ride is not None:
            postgres_storage.save_ride(cur_ride.model_copy(update={"version": cur_ride.version + 1}))
        return res

    setattr(orchestrator._dispatch_engine, "dispatch_batch", mutate_during_solve)

    res = orchestrator.dispatch_cycle(current_time=1000)

    # Assignment on v1 suffered VERSION_CONFLICT
    assert any(diag.rejection_reason == "VERSION_CONFLICT" for diag in res.rejected_assignments)
    # Assignment on v2 committed successfully
    assert len(res.committed_assignments) >= 1
    assert any(c.vehicle_id == "v-pg-2" for c in res.committed_assignments)


# ---------------------------------------------------------------------------
# 4. Idempotent Replay in PostgreSQL
# ---------------------------------------------------------------------------

def test_postgres_orchestrator_idempotent_replay(
    postgres_storage: PostgresRideStorage,
) -> None:
    veh = _make_veh("veh-pg-idemp", 40.7100, -74.0050)
    req1 = _make_req("req-pg-idemp-1", 40.7110, -74.0040, 40.7300, -73.9900)

    postgres_storage.save_vehicle(veh)
    postgres_storage.save_request(req1)

    orchestrator = _build_orchestrator(postgres_storage)
    res = orchestrator.dispatch_cycle(
        current_time=1000,
        cycle_id="cycle-pg-idemp",
        idempotency_token="tok-pg-idemp",
    )
    assert len(res.committed_assignments) == 1
    committed_cand = res.committed_assignments[0]

    # Replay direct assignment commit with identical token
    replay_res = postgres_storage.commit_dispatch_assignment_atomic(
        assignment=committed_cand,
        idempotency_token=f"tok-pg-idemp:{committed_cand.candidate_id}",
        current_time=1000,
    )
    assert replay_res.success is True
    assert replay_res.ride is not None

    # Replay with conflicting candidate ID on same token fails
    conflict_cand = committed_cand.model_copy(update={"candidate_id": "cand-different"})
    conflict_res = postgres_storage.commit_dispatch_assignment_atomic(
        assignment=conflict_cand,
        idempotency_token=f"tok-pg-idemp:{committed_cand.candidate_id}",
        current_time=1000,
    )
    assert conflict_res.success is False
    assert conflict_res.rejection_reason == "IDEMPOTENCY_CONFLICT"
