"""Thread-safe in-memory storage adapter implementing RideStorageProvider."""

import threading
from typing import Any, Optional, Sequence

from engine.contracts.storage import RideStorageProvider, SeatHold, VersionConflictError
from engine.domain.enums import RideStatus
from engine.domain.models import JoinRequest, Ride, RideRequest, RouteStop, Vehicle
from engine.routing.invariants import check_capacity_profile


class InMemoryRideStorage(RideStorageProvider):
    """
    Thread-safe in-memory implementation of RideStorageProvider.
    Uses reentrant locks (RLock) to provide serializable isolation,
    atomic compare-and-swap (CAS) version checking, and idempotent replays.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rides: dict[str, Ride] = {}
        self._vehicles: dict[str, Vehicle] = {}
        self._requests: dict[str, RideRequest] = {}
        self._join_requests: dict[str, JoinRequest] = {}
        self._holds: dict[str, SeatHold] = {}  # join_request_id -> SeatHold
        self._idempotency_records: dict[str, dict[str, Any]] = {}

    def get_ride(self, ride_id: str) -> Optional[Ride]:
        with self._lock:
            return self._rides.get(ride_id)

    def save_ride(self, ride: Ride) -> None:
        with self._lock:
            self._rides[ride.ride_id] = ride

    def get_active_rides_in_bounding_box(
        self,
        min_lat: float,
        min_lon: float,
        max_lat: float,
        max_lon: float,
    ) -> Sequence[Ride]:
        with self._lock:
            active_rides: list[Ride] = []
            for ride in self._rides.values():
                if ride.lifecycle_status not in (RideStatus.SCHEDULED, RideStatus.ACTIVE):
                    continue

                # Check if vehicle location or any stop falls in bounding box
                matched = False
                vehicle = self._vehicles.get(ride.vehicle_id)
                if vehicle is not None:
                    loc = vehicle.current_location
                    if min_lat <= loc.latitude <= max_lat and min_lon <= loc.longitude <= max_lon:
                        matched = True

                if not matched:
                    for stop in ride.stops:
                        if (
                            min_lat <= stop.location.latitude <= max_lat
                            and min_lon <= stop.location.longitude <= max_lon
                        ):
                            matched = True
                            break

                if matched:
                    active_rides.append(ride)

            return active_rides

    def get_vehicle(self, vehicle_id: str) -> Optional[Vehicle]:
        with self._lock:
            return self._vehicles.get(vehicle_id)

    def save_vehicle(self, vehicle: Vehicle) -> None:
        with self._lock:
            self._vehicles[vehicle.vehicle_id] = vehicle

    def get_request(self, request_id: str) -> Optional[RideRequest]:
        with self._lock:
            return self._requests.get(request_id)

    def save_request(self, request: RideRequest) -> None:
        with self._lock:
            self._requests[request.request_id] = request

    def get_join_request(self, join_request_id: str) -> Optional[JoinRequest]:
        with self._lock:
            return self._join_requests.get(join_request_id)

    def save_join_request(self, join_request: JoinRequest) -> None:
        with self._lock:
            self._join_requests[join_request.join_request_id] = join_request

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
        with self._lock:
            # Replay safety: check if identical idempotency token already recorded
            rec = self._idempotency_records.get(idempotency_token)
            if rec is not None:
                if (
                    rec.get("join_request_id") == join_request_id
                    and rec.get("request_id") == request_id
                    and rec.get("ride_id") == ride_id
                ):
                    hold = self._holds.get(join_request_id)
                    if hold is not None:
                        if submitted_at <= hold.expires_at:
                            return True
                        else:
                            del self._holds[join_request_id]
                            return False
                    return False
                return False

            ride = self._rides.get(ride_id)
            if ride is None:
                return False

            # Optimistic Concurrency Check: Ride.version == expected_version
            if ride.version != expected_version:
                return False

            vehicle = self._vehicles.get(ride.vehicle_id)
            capacity = vehicle.total_seat_capacity if vehicle is not None else 4

            # Calculate current peak occupancy from existing stops
            current_occ = ride.active_passenger_count
            peak_occ = current_occ
            for stop in ride.stops:
                current_occ += stop.passenger_delta
                if current_occ > peak_occ:
                    peak_occ = current_occ

            # Sum active seat holds for this ride (excluding current join_request_id if already holding)
            active_held_seats = 0
            for hold in list(self._holds.values()):
                if hold.ride_id == ride_id and hold.join_request_id != join_request_id:
                    # Hold is active if current time (submitted_at) <= hold.expires_at
                    if submitted_at <= hold.expires_at:
                        active_held_seats += hold.seat_count
                    else:
                        # Auto-clean expired hold
                        del self._holds[hold.join_request_id]

            if peak_occ + active_held_seats + seat_count > capacity:
                return False

            # Persist hold
            new_hold = SeatHold(
                ride_id=ride_id,
                request_id=request_id,
                join_request_id=join_request_id,
                seat_count=seat_count,
                submitted_at=submitted_at,
                expires_at=expires_at,
                idempotency_token=idempotency_token,
            )
            self._holds[join_request_id] = new_hold

            # Increment ride version on state mutation
            updated_ride = ride.model_copy(update={"version": ride.version + 1})
            self._rides[ride_id] = updated_ride

            # Record idempotency record
            self._idempotency_records[idempotency_token] = {
                "type": "hold",
                "join_request_id": join_request_id,
                "request_id": request_id,
                "ride_id": ride_id,
                "version": updated_ride.version,
            }
            return True

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
        with self._lock:
            # 1. Idempotency Check: if token already recorded
            rec = self._idempotency_records.get(idempotency_token)
            if rec is not None:
                if rec.get("type") == "reservation":
                    if (
                        rec.get("join_request_id") == join_request_id
                        and rec.get("request_id") == request_id
                        and rec.get("ride_id") == ride_id
                    ):
                        return True
                    return False
                elif (
                    rec.get("join_request_id") != join_request_id
                    or rec.get("request_id") != request_id
                    or rec.get("ride_id") != ride_id
                ):
                    return False

            ride = self._rides.get(ride_id)
            if ride is None:
                return False

            # 2. Optimistic Concurrency Check: Ride.version == expected_version
            if ride.version != expected_version:
                return False

            # 3. Expiry Check on temporary seat hold
            hold = self._holds.get(join_request_id)
            if hold is None:
                return False

            now = current_time if current_time is not None else hold.submitted_at
            # Exact boundary: valid while now <= expires_at; expired when now > expires_at
            if now > hold.expires_at:
                del self._holds[join_request_id]
                return False

            # 4. Double Revalidation of Capacity
            vehicle = self._vehicles.get(ride.vehicle_id)
            capacity = vehicle.total_seat_capacity if vehicle is not None else 4

            if new_stops is not None:
                if not check_capacity_profile(new_stops, capacity, ride.active_passenger_count):
                    del self._holds[join_request_id]
                    return False
                final_stops = tuple(new_stops)
            else:
                current_occ = ride.active_passenger_count
                peak_occ = current_occ
                for stop in ride.stops:
                    current_occ += stop.passenger_delta
                    if current_occ > peak_occ:
                        peak_occ = current_occ
                if peak_occ + seat_count > capacity:
                    del self._holds[join_request_id]
                    return False
                final_stops = ride.stops

            # 5. Atomic Commit: promote hold to permanent reservation
            del self._holds[join_request_id]
            updated_ride = ride.model_copy(
                update={
                    "stops": final_stops,
                    "version": ride.version + 1,
                }
            )
            self._rides[ride_id] = updated_ride

            # Record idempotency token for confirmed reservation
            self._idempotency_records[idempotency_token] = {
                "type": "reservation",
                "join_request_id": join_request_id,
                "request_id": request_id,
                "ride_id": ride_id,
                "version": updated_ride.version,
            }
            return True

    def release_seats_atomic(
        self,
        ride_id: str,
        join_request_id: str,
        request_id: Optional[str] = None,
        seat_count: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> bool:
        with self._lock:
            if join_request_id in self._holds:
                del self._holds[join_request_id]
                return True
            return False

    def get_seat_hold(self, join_request_id: str) -> Optional[SeatHold]:
        with self._lock:
            return self._holds.get(join_request_id)

    def get_active_seat_holds(
        self,
        ride_id: str,
        current_time: Optional[int] = None,
    ) -> Sequence[SeatHold]:
        """Returns all active temporary seat holds for a ride."""
        with self._lock:
            active: list[SeatHold] = []
            for hold in list(self._holds.values()):
                if hold.ride_id != ride_id:
                    continue
                if current_time is not None:
                    if current_time <= hold.expires_at:
                        active.append(hold)
                    else:
                        # Auto-clean expired hold if observed
                        del self._holds[hold.join_request_id]
                else:
                    active.append(hold)
            return active

    def sweep_expired_holds(self, current_time: int) -> list[str]:
        """Auto-releases all holds where current_time > expires_at."""
        with self._lock:
            expired_ids: list[str] = []
            for hold in list(self._holds.values()):
                if current_time > hold.expires_at:
                    expired_ids.append(hold.join_request_id)
                    del self._holds[hold.join_request_id]
            return expired_ids
