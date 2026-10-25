# Contract: RideStorageProvider

**Interface**: `RideStorageProvider`  
**Namespace**: `engine.contracts.storage`  
**Purpose**: Decouple state persistence, transactional seat reservations, and atomic state transitions from underlying databases (PostgreSQL, Redis, in-memory test store).

---

## 1. Interface Definition (Python Abstract Base Class)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence, Optional
from engine.domain.models import Ride, RideRequest, JoinRequest, Vehicle, Driver

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

    @abstractmethod
    def get_active_seat_holds(
        self,
        ride_id: str,
        current_time: Optional[int] = None,
    ) -> Sequence[SeatHold]:
        """
        Retrieves all currently active (unexpired) temporary seat holds for the specified ride.
        If current_time is provided, a hold is active if current_time <= hold.expires_at.
        Expired holds (current_time > hold.expires_at) must not be returned.
        """
        pass

    @abstractmethod
    def sweep_expired_holds(self, current_time: int) -> Sequence[str]:
        """
        Sweeps and cleans up all temporary seat holds where current_time > hold.expires_at.
        Returns the sequence of join_request_ids corresponding to swept expired holds.
        Repeated calls with the same or earlier current_time must be safe and idempotent.
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
        """
        pass
```

## 2. Invariants & Concurrency Contract
- **Serializable Isolation & Race Resolution**: `acquire_seat_hold_atomic`, `reserve_seats_atomic`, and `commit_dispatch_assignment_atomic` MUST guarantee serializable isolation for concurrent seat requests and batch dispatch commits.
- **Per-Assignment Atomic Commits**: In batch dispatch orchestration, each candidate assignment is committed in an independent, atomic database transaction with row-level locks (`SELECT ... FOR UPDATE`) on the vehicle, ride, and requests:
  - If a concurrent collision occurs (e.g. `VERSION_CONFLICT` on an existing active ride, or a request was cancelled), only that specific assignment fails and rolls back.
  - Other valid assignments in the same batch continue to commit without interruption or data corruption.
- **Unified Seat-Hold Lifecycle**:
  - The seat hold expiration and join request expiration are governed by a single unified timestamp: $T_{\text{expires}} = T_{\text{submitted}} + \text{join\_request\_expiry\_seconds}$.
  - The hold is strictly valid while $t \le T_{\text{expires}}$ and expires when $t > T_{\text{expires}}$.
  - The hold is directly owned by `join_request_id` and `request_id`.
  - Automatic release: If $t > T_{\text{expires}}$ or the creator declines, the hold is freed immediately via `release_seats_atomic`.
- **Idempotency & Replay Safety**: Every reservation hold or dispatch commit includes an `idempotency_token`. Duplicate submissions return success with the existing status without consuming additional seat capacity or creating duplicate rides/stops.
- **Optimistic Concurrency Control (OCC)**: Any update to an existing `Ride` must verify that the stored version matches `expected_version`. If another process modified the ride concurrently, a version conflict is safely detected and the commit is rejected or retried within a bounded policy.
- **Stateless Read Snapshots**: Reads for batch optimization solvers provide immutable point-in-time snapshots, completely decoupled from active database transactions.

---

## 3. Implementations & Operational Setup

### 3.1. In-Memory Adapter (`InMemoryRideStorage`)
- **Namespace**: `engine.adapters.in_memory_storage`
- **Use Case**: In-process development, fast unit tests, deterministic simulation replays.
- **Concurrency**: Thread-safe with `threading.RLock()`.
- **Limitation**: Volatile; does not survive process termination and cannot coordinate across multiple container instances or OS processes.

### 3.2. PostgreSQL / PostGIS Persistent Adapter (`PostgresRideStorage`)
- **Namespace**: `engine.adapters.postgres_storage`
- **Use Case**: Durable, multi-process, distributed production persistence.
- **Database Schema**: Managed via [`src/engine/adapters/schema.sql`](file:///C:/Users/shaha/pool%20engine/src/engine/adapters/schema.sql). Initialize programmatically via `storage.create_schema()`.
  - Canonical relational tables: `vehicles`, `rides`, `route_stops`, `ride_requests`, `join_requests`, `seat_holds`, `idempotency_records`.
  - Indexes: B-Tree coordinates on `vehicles` and `route_stops`, expiry index on `seat_holds(expires_at, ride_id)`, idempotency token lookups on `idempotency_records(idempotency_token)`.
  - PostGIS Support: Automatically creates the `postgis` extension when PostGIS is installed on PostgreSQL; falls back to standard indexed coordinate bounding boxes if PostGIS extension is unavailable.
- **Concurrency Model**:
  - **Pessimistic Row Locking**: Uses `SELECT ... FOR UPDATE` on `rides` and `seat_holds` during `acquire_seat_hold_atomic` and `reserve_seats_atomic` transactions.
  - **Optimistic Version Checks**: Verifies `rides.version == expected_version` and atomically increments version upon every state or stop mutation.
  - **Multi-Process Contention**: Multiple processes or service replicas safely contend without double-booking or capacity over-allocation.
- **Environment Configuration**:
  - `DATABASE_URL`: PostgreSQL connection DSN for production or development (e.g. `postgresql://user:pass@localhost:5432/pool_engine`).
  - `TEST_DATABASE_URL`: Dedicated database connection DSN for running integration tests against a live database.
- **Integration Test Execution**:
  ```powershell
  # When PostgreSQL is running:
  $env:TEST_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/pool_engine_test"
  python -m pytest tests/integration/test_postgres_integration.py -v
  ```
  If neither `TEST_DATABASE_URL` nor `DATABASE_URL` is set (or the PostgreSQL server is unreachable), integration tests are cleanly and explicitly skipped with a message detailing the missing environment. No silent fallback to in-memory storage is permitted.
