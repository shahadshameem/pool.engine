"""Application-independent orchestration layer connecting persistent storage to the dispatch engine."""

import time
import uuid
from dataclasses import dataclass
from typing import Optional, Sequence

from engine.contracts.policy import DispatchPolicyProvider
from engine.contracts.routing import RoadNetworkRoutingProvider
from engine.contracts.spatial import SpatialIndexProvider
from engine.contracts.storage import AssignmentCommitResult, RideStorageProvider
from engine.dispatch import CandidateGenerationConfig, DispatchEngine
from engine.domain.candidate import CandidateAssignment
from engine.domain.enums import RequestStatus, RideStatus, SearchStatus
from engine.domain.models import Ride, RideRequest, Vehicle
from engine.routing.invariants import check_capacity_profile


@dataclass(frozen=True)
class OrchestrationConfig:
    """Configuration options for a dispatch orchestration cycle."""
    max_retries_per_conflict: int = 1
    sweep_expired_requests: bool = True
    candidate_generation_config: Optional[CandidateGenerationConfig] = None
    deadline_seconds: float = 0.500
    reserved_headroom_seconds: float = 0.050
    request_limit: Optional[int] = None
    vehicle_limit: Optional[int] = None


@dataclass(frozen=True)
class StaleAssignmentDiagnostic:
    """Detailed diagnostic metadata for an uncommitted or rejected assignment."""
    candidate_id: str
    vehicle_id: str
    request_ids: tuple[str, ...]
    rejection_reason: str
    retry_count: int


@dataclass(frozen=True)
class OrchestrationResult:
    """Result of an end-to-end dispatch orchestration cycle."""
    cycle_id: str
    batch_id: str
    timestamp: int
    committed_assignments: tuple[CandidateAssignment, ...]
    rejected_assignments: tuple[StaleAssignmentDiagnostic, ...]
    unassigned_request_ids: tuple[str, ...]
    search_status: SearchStatus
    is_approximated: bool
    total_vmt_savings_meters: int
    cycle_duration_ms: float
    routing_errors_count: int = 0


class DispatchOrchestrator:
    """
    Application-independent orchestration layer connecting persistent storage
    to the unified dispatch engine.

    Orchestrates:
    - Point-in-time state snapshot fetching (pending requests, active vehicles, active rides).
    - Expired request sweeping and graceful timer cleanups.
    - Delegation to DispatchEngine under strict monotonic wall-clock deadline.
    - Per-assignment isolated atomic commits with OCC and database row locking.
    - Safe handling of stale versions, reservation conflicts, and bounded retries.
    - Idempotent replays and transparent search-status reporting.
    """

    def __init__(
        self,
        storage: RideStorageProvider,
        policy_provider: DispatchPolicyProvider,
        routing_provider: RoadNetworkRoutingProvider,
        spatial_index: SpatialIndexProvider,
        config: Optional[OrchestrationConfig] = None,
    ) -> None:
        self.storage = storage
        self.policy_provider = policy_provider
        self.routing_provider = routing_provider
        self.spatial_index = spatial_index
        self.config = config or OrchestrationConfig()
        self._dispatch_engine = DispatchEngine(
            policy_provider=self.policy_provider,
            routing_provider=self.routing_provider,
            spatial_index=self.spatial_index,
            storage=self.storage,
            config=self.config.candidate_generation_config or CandidateGenerationConfig.bounded(),
        )

    def dispatch_cycle(
        self,
        current_time: int,
        cycle_id: Optional[str] = None,
        idempotency_token: Optional[str] = None,
        deadline: Optional[float] = None,
    ) -> OrchestrationResult:
        """
        Executes a single end-to-end dispatch orchestration cycle.
        """
        start_monotonic = time.monotonic()
        effective_cycle_id = cycle_id or f"cycle-{uuid.uuid4()}"
        effective_batch_id = f"batch-{effective_cycle_id}"
        effective_idempotency_token = idempotency_token or f"idemp-{effective_cycle_id}"
        effective_deadline = (
            deadline if deadline is not None else start_monotonic + self.config.deadline_seconds
        )

        # Stage 1: Snapshot Retrieval
        raw_requests = self.storage.get_pending_requests(limit=self.config.request_limit)
        active_vehicles = self.storage.get_active_vehicles(limit=self.config.vehicle_limit)
        active_rides = self.storage.get_active_rides()

        # Sweep expired requests and holds if enabled
        pending_requests: list[RideRequest] = []
        if self.config.sweep_expired_requests:
            self.storage.sweep_expired_holds(current_time)
            for req in raw_requests:
                if current_time > req.latest_dropoff_time:
                    expired_req = req.model_copy(update={"status": RequestStatus.EXPIRED})
                    self.storage.save_request(expired_req)
                else:
                    pending_requests.append(req)
        else:
            pending_requests = list(raw_requests)

        all_input_req_ids = tuple(sorted(r.request_id for r in pending_requests))

        # Check for empty inputs
        if not pending_requests or not active_vehicles:
            elapsed_ms = (time.monotonic() - start_monotonic) * 1000.0
            return OrchestrationResult(
                cycle_id=effective_cycle_id,
                batch_id=effective_batch_id,
                timestamp=current_time,
                committed_assignments=(),
                rejected_assignments=(),
                unassigned_request_ids=all_input_req_ids,
                search_status=SearchStatus.COMPLETE,
                is_approximated=False,
                total_vmt_savings_meters=0,
                cycle_duration_ms=round(elapsed_ms, 2),
                routing_errors_count=0,
            )

        # Capture snapshot of expected ride versions for OCC
        expected_ride_versions: dict[str, int] = {
            ride.ride_id: ride.version for ride in active_rides
        }

        # Stage 2: Solve via DispatchEngine
        dispatch_cfg = self.config.candidate_generation_config
        match_result = self._dispatch_engine.dispatch_batch(
            requests=pending_requests,
            vehicles=active_vehicles,
            active_rides=active_rides,
            current_time=current_time,
            batch_id=effective_batch_id,
            deadline=effective_deadline,
            reserved_headroom=self.config.reserved_headroom_seconds,
            config=dispatch_cfg,
        )

        # Stage 3: Atomic Commit per Assignment
        committed_assignments: list[CandidateAssignment] = []
        rejected_assignments: list[StaleAssignmentDiagnostic] = []
        unassigned_ids_set = set(match_result.unassigned_request_ids)
        total_vmt_savings = 0

        for assignment in match_result.selected_assignments:
            exp_version = (
                expected_ride_versions.get(assignment.existing_ride_id)
                if assignment.existing_ride_id is not None
                else None
            )
            asgn_token = f"{effective_idempotency_token}:{assignment.candidate_id}"

            commit_result = self.storage.commit_dispatch_assignment_atomic(
                assignment=assignment,
                idempotency_token=asgn_token,
                current_time=current_time,
                expected_ride_version=exp_version,
            )

            if commit_result.success:
                committed_assignments.append(assignment)
                total_vmt_savings += assignment.vmt_meters
            else:
                # Concurrency / Stale conflict encountered
                retry_success = False
                retry_count = 0

                # Bounded retry on version conflict if enabled
                if (
                    self.config.max_retries_per_conflict > 0
                    and commit_result.rejection_reason == "VERSION_CONFLICT"
                    and assignment.existing_ride_id is not None
                ):
                    retry_count = 1
                    latest_ride = self.storage.get_ride(assignment.existing_ride_id)
                    vehicle = self.storage.get_vehicle(assignment.vehicle_id)
                    if (
                        latest_ride is not None
                        and vehicle is not None
                        and vehicle.is_active
                        and check_capacity_profile(
                            assignment.ordered_stops,
                            vehicle.total_seat_capacity,
                            latest_ride.active_passenger_count,
                        )
                    ):
                        retry_token = f"{asgn_token}:retry1"
                        retry_commit = self.storage.commit_dispatch_assignment_atomic(
                            assignment=assignment,
                            idempotency_token=retry_token,
                            current_time=current_time,
                            expected_ride_version=latest_ride.version,
                        )
                        if retry_commit.success:
                            committed_assignments.append(assignment)
                            total_vmt_savings += assignment.vmt_meters
                            retry_success = True

                if not retry_success:
                    rejected_assignments.append(
                        StaleAssignmentDiagnostic(
                            candidate_id=assignment.candidate_id,
                            vehicle_id=assignment.vehicle_id,
                            request_ids=assignment.request_ids,
                            rejection_reason=commit_result.rejection_reason or "UNKNOWN_CONFLICT",
                            retry_count=retry_count,
                        )
                    )
                    unassigned_ids_set.update(assignment.request_ids)

        elapsed_ms = (time.monotonic() - start_monotonic) * 1000.0

        return OrchestrationResult(
            cycle_id=effective_cycle_id,
            batch_id=effective_batch_id,
            timestamp=current_time,
            committed_assignments=tuple(committed_assignments),
            rejected_assignments=tuple(rejected_assignments),
            unassigned_request_ids=tuple(sorted(unassigned_ids_set)),
            search_status=match_result.search_status,
            is_approximated=match_result.is_approximated,
            total_vmt_savings_meters=match_result.total_vmt_savings_meters if committed_assignments else 0,
            cycle_duration_ms=round(elapsed_ms, 2),
            routing_errors_count=match_result.routing_errors_count,
        )
