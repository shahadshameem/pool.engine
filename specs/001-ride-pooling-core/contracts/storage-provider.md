# Contract: RideStorageProvider

**Interface**: `RideStorageProvider`  
**Namespace**: `engine.contracts.storage`  
**Purpose**: Decouple state persistence, transactional seat reservations, and atomic state transitions from underlying databases (PostgreSQL, Redis, in-memory test store).

---

## 1. Interface Definition (Python Abstract Base Class)

```python
from abc import ABC, abstractmethod
from typing import Sequence, Optional
from engine.domain.models import Ride, RideRequest, JoinRequest, Vehicle, Driver

class RideStorageProvider(ABC):
    """
    Vendor-independent storage and concurrency control contract.
    Guarantees atomic seat reservations, idempotent submissions, and consistent point-in-time snapshots.
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
        """
        Atomically locks temporary seats for a pending JoinRequest.
        
        Hold Lifecycle & Timing:
        - Unified Timestamp: expires_at = submitted_at + join_request_expiry_seconds.
        - Exact Boundary: The seat hold is strictly valid while current time t <= expires_at;
          at t > expires_at, the hold is considered expired and non-binding.
        - Hold Ownership: Directly owned by join_request_id and request_id for ride_id.
        - Replay Safety: If idempotency_token is already active for this join_request_id,
          returns True without decrementing additional capacity.
        - Isolation: Acquires transactional lock on Ride(ride_id), checks expected_version,
          verifies peak load + active holds + seat_count <= Vehicle.capacity,
          persists hold, increments Ride.version, and returns True. Otherwise aborts and returns False.
        """
        pass

    @abstractmethod
    def reserve_seats_atomic(
        self,
        ride_id: str,
        request_id: str,
        join_request_id: str,
        seat_count: int,
        expected_version: int,
        idempotency_token: str
    ) -> bool:
        """
        Atomically promotes an active seat hold to a permanent reservation upon creator approval.
        
        Consistency Protocol:
        1. Idempotency Check: Verifies if idempotency_token was already committed; if so, returns True.
        2. Transactional Lock: Acquires transactional lock on Ride(ride_id).
        3. Optimistic Concurrency Check: Verifies Ride.version == expected_version.
        4. Expiry Check: Validates that current wall-clock time t <= expires_at. If t > expires_at,
           hold has expired; aborts and returns False.
        5. Double Revalidation: Re-verifies that total passengers + seat_count <= Vehicle.capacity
           and route detour constraints remain satisfied under active policy.
        6. Atomic Commit: Converts hold to confirmed reservation, increments Ride.version,
           records idempotency_token, and returns True.
        7. Conflict & Race Resolution: If another transaction modified the ride (version mismatch)
           or capacity was exhausted, aborts transaction, releases the hold, and returns False.
        """
        pass

    @abstractmethod
    def release_seats_atomic(
        self,
        ride_id: str,
        request_id: str,
        join_request_id: str,
        seat_count: int,
        reason: str
    ) -> None:
        """
        Atomically releases previously held or reserved seats back to available capacity.
        Triggered automatically on creator rejection, request cancellation, or timer expiry (t > expires_at).
        """
        pass

    @abstractmethod
    def save_join_request(self, join_request: JoinRequest) -> None:
        """Persists a new or updated JoinRequest."""
        pass

    @abstractmethod
    def get_join_request(self, join_request_id: str) -> Optional[JoinRequest]:
        """Loads a JoinRequest by ID."""
        pass
```

## 2. Invariants & Concurrency Contract
- **Serializable Isolation & Race Resolution**: `acquire_seat_hold_atomic` and `reserve_seats_atomic` MUST guarantee serializable isolation for concurrent seat requests on the same ride. When two concurrent requests compete for the last available seat, atomic transactional locks serialize execution: the first transaction commits and increments `Ride.version`, and the second transaction fails version or capacity checks and is cleanly rejected.
- **Unified Seat-Hold Lifecycle**:
  - The seat hold expiration and join request expiration are governed by a single unified timestamp: $T_{\text{expires}} = T_{\text{submitted}} + \text{join\_request\_expiry\_seconds}$.
  - The hold is strictly valid while $t \le T_{\text{expires}}$ and expires when $t > T_{\text{expires}}$.
  - The hold is directly owned by `join_request_id` and `request_id`.
  - Automatic release: If $t > T_{\text{expires}}$ or the creator declines, the hold is freed immediately via `release_seats_atomic`.
- **Idempotency & Replay Safety**: Every reservation hold or commit includes an `idempotency_token`. Duplicate submissions within the hold window return success with the existing status without consuming additional seat capacity.
- **Optimistic Concurrency Control (OCC)**: Any update to an existing `Ride` must verify that the stored version matches `expected_version`. If another process modified the ride concurrently, a `ConcurrencyConflictError` is raised and caught for double-revalidation.
- **Stateless Read Snapshots**: Reads for batch optimization solvers provide immutable point-in-time snapshots, completely decoupled from active database transactions.
