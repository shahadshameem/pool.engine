"""Contract for ride storage and transactional concurrency control."""

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from engine.domain.models import JoinRequest, Ride, RideRequest, RouteStop, Vehicle


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
