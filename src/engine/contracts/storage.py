"""Contract for ride storage and transactional concurrency control."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Sequence

from engine.domain.candidate import CandidateAssignment
from engine.domain.enums import RideStatus
from engine.domain.models import JoinRequest, Ride, RideRequest, RouteStop, Vehicle


@dataclass(frozen=True)
class SeatHold:
    """Record of an active temporary seat hold."""
    ride_id: str
    request_id: str
    join_request_id: str
    seat_count: int
    submitted_at: int
    expires_at: int
    idempotency_token: str


@dataclass(frozen=True)
class IdempotencyRecord:
    """Canonical idempotency record tracking operation outcome and ownership."""
    token: str
    record_type: str  # "hold" | "reservation" | "dispatch_assignment"
    join_request_id: str
    request_id: str
    ride_id: str
    version: int
    created_at: Optional[int] = None


@dataclass(frozen=True)
class AssignmentCommitResult:
    """Outcome of attempting to atomically commit a single dispatch assignment."""
    success: bool
    candidate_id: str
    ride_id: Optional[str] = None
    rejection_reason: Optional[str] = None
    ride: Optional[Ride] = None
    committed_request_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CancellationCommitResult:
    """Outcome of attempting to atomically cancel an assigned request from a ride."""
    success: bool
    request_id: str
    ride_id: str
    rejection_reason: Optional[str] = None
    ride: Optional[Ride] = None
    request: Optional[RideRequest] = None


class StorageProviderError(Exception):
    """Raised on database/storage operational failure."""
    pass


class VersionConflictError(StorageProviderError):
    """Raised when an optimistic concurrency version check fails."""
    pass


class RideStorageProvider(ABC):
    """
    Vendor-independent storage and concurrency control contract.
    Guarantees atomic seat reservations, idempotent submissions, and consistent snapshots.
    """

    @abstractmethod
    def get_ride(self, ride_id: str) -> Optional[Ride]:
        """Loads an immutable snapshot of a Ride by ID."""
        pass

    @abstractmethod
    def get_active_rides_in_bounding_box(
        self,
        min_lat: float,
        min_lon: float,
        max_lat: float,
        max_lon: float
    ) -> Sequence[Ride]:
        """Loads all active rides within a geographic bounding box."""
        pass

    @abstractmethod
    def save_ride(self, ride: Ride) -> None:
        """Persists updated ride state, incrementing its version counter."""
        pass

    @abstractmethod
    def get_vehicle(self, vehicle_id: str) -> Optional[Vehicle]:
        """Loads a Vehicle by ID."""
        pass

    @abstractmethod
    def save_vehicle(self, vehicle: Vehicle) -> None:
        """Persists a Vehicle."""
        pass

    @abstractmethod
    def get_request(self, request_id: str) -> Optional[RideRequest]:
        """Loads a RideRequest by ID."""
        pass

    @abstractmethod
    def save_request(self, request: RideRequest) -> None:
        """Persists a RideRequest."""
        pass

    @abstractmethod
    def get_join_request(self, join_request_id: str) -> Optional[JoinRequest]:
        """Loads a JoinRequest by ID."""
        pass

    @abstractmethod
    def save_join_request(self, join_request: JoinRequest) -> None:
        """Persists a new or updated JoinRequest."""
        pass

    @abstractmethod
    def acquire_seat_hold_atomic(
        self,
        ride_id: str,
        request_id: str,
        join_request_id: str,
        seat_count: int,
        submitted_at: int,
        expires_at: int,
        expected_version: int,
        idempotency_token: str
    ) -> bool:
        """Atomically locks temporary seats for a pending JoinRequest."""
        pass

    @abstractmethod
    def reserve_seats_atomic(
        self,
        ride_id: str,
        request_id: str,
        join_request_id: str,
        seat_count: int,
        expected_version: int,
        idempotency_token: str,
        new_stops: Optional[Sequence[RouteStop]] = None,
        current_time: Optional[int] = None
    ) -> bool:
        """Atomically promotes an active seat hold to a permanent reservation upon approval."""
        pass

    @abstractmethod
    def release_seats_atomic(
        self,
        ride_id: str,
        join_request_id: str,
        request_id: Optional[str] = None,
        seat_count: Optional[int] = None,
        reason: Optional[str] = None
    ) -> bool:
        """Atomically releases a temporary seat hold or cancels a reservation."""
        pass

    @abstractmethod
    def get_active_seat_holds(
        self,
        ride_id: str,
        current_time: Optional[int] = None,
    ) -> Sequence[SeatHold]:
        """
        Retrieves all currently active (unexpired) temporary seat holds for the specified ride.

        If current_time is provided, a hold is considered active if current_time <= hold.expires_at.
        Expired holds (current_time > hold.expires_at) must not be returned.
        """
        pass

    @abstractmethod
    def sweep_expired_holds(self, current_time: int) -> Sequence[str]:
        """
        Sweeps and cleans up all temporary seat holds where current_time > hold.expires_at.

        Returns the sequence of join_request_ids corresponding to the swept expired holds.
        Repeated calls with the same or earlier current_time must be idempotent and safe.
        """
        pass

    @abstractmethod
    def get_idempotency_record(self, idempotency_token: str) -> Optional[IdempotencyRecord]:
        """
        Retrieves an idempotency record by token.
        Used to verify token ownership and detect idempotency conflicts without reflection.
        """
        pass

    @abstractmethod
    def get_pending_requests(self, limit: Optional[int] = None) -> Sequence[RideRequest]:
        """Loads all ride requests currently in PENDING status."""
        pass

    @abstractmethod
    def get_active_vehicles(self, limit: Optional[int] = None) -> Sequence[Vehicle]:
        """Loads all currently active vehicles (is_active == True)."""
        pass

    @abstractmethod
    def get_active_rides(self, limit: Optional[int] = None) -> Sequence[Ride]:
        """Loads all rides currently in SCHEDULED or ACTIVE lifecycle status."""
        pass

    @abstractmethod
    def commit_dispatch_assignment_atomic(
        self,
        assignment: CandidateAssignment,
        idempotency_token: str,
        current_time: int,
        expected_ride_version: Optional[int] = None,
        new_ride_id: Optional[str] = None,
    ) -> AssignmentCommitResult:
        """
        Atomically commits a single dispatch candidate assignment to storage.

        Guarantees:
        - If existing_ride_id is None (new ride for idle vehicle):
          - Verifies the vehicle is active and has no currently active/scheduled ride.
          - Verifies all request_ids in the assignment exist and have status == PENDING.
          - Persists the new Ride and RouteStops.
          - Transitions all request_ids to status == MATCHED with matched_ride_id.
        - If existing_ride_id is set (active ride insertion):
          - Verifies the ride exists and ride.version == expected_ride_version (OCC).
          - Verifies vehicle seat capacity profile is preserved.
          - Verifies newly inserted request_ids exist and have status == PENDING.
          - Updates Ride stops and total_vmt_meters, incrementing ride.version.
          - Transitions newly inserted request_ids to status == MATCHED with matched_ride_id.
        - Replay Safety & Idempotency:
          - If idempotency_token was already committed for this candidate, returns success=True with the committed Ride.
          - If idempotency_token conflicts with a different candidate or request, returns success=False with rejection_reason="IDEMPOTENCY_CONFLICT".
        - Isolation:
          - If any check fails, the transaction is completely rolled back and storage is left unmutated.
        """
        pass

    @abstractmethod
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
        """
        Atomically cancels an assigned request and commits the re-optimized ride itinerary in a single transaction.

        Guarantees:
        - Locks both the Ride and the RideRequest (and RouteStops) under row-level or thread locks.
        - Verifies the ride exists and ride.version == expected_ride_version (OCC).
        - Verifies the request exists and is currently in MATCHED status with matched_ride_id == ride_id.
        - Verifies the passenger has not already boarded (no pickup stop with status COMPLETED).
        - Replaces the ride's route stops with updated_stops and updates total_vmt_meters.
        - Increments ride.version by 1.
        - Updates the request status to CANCELLED.
        - If idempotency_token is provided, verifies/records idempotency.
        - Atomic Rollback: If any validation or database constraint fails, the entire transaction is rolled back,
          leaving both ride and request completely unmutated.
        """
        pass
