"""Thread-safe in-memory storage adapter implementing RideStorageProvider."""

import threading
from typing import Any, Optional, Sequence

from engine.contracts.storage import (
    AssignmentCommitResult,
    CancellationCommitResult,
    IdempotencyRecord,
    RideStorageProvider,
    SeatHold,
    VersionConflictError,
)
from engine.domain.candidate import CandidateAssignment
from engine.domain.enums import RequestStatus, RideStatus, StopStatus, StopType
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

    def record_proposal_acceptance(
        self,
        join_request_id: str,
        is_host: bool,
        is_traveller: bool,
    ) -> Optional[tuple[bool, bool]]:
        with self._lock:
            jr = self._join_requests.get(join_request_id)
            if jr is None:
                return None
            new_host = jr.host_accepted or is_host
            new_traveller = jr.traveller_accepted or is_traveller
            self._join_requests[join_request_id] = jr.model_copy(
                update={"host_accepted": new_host, "traveller_accepted": new_traveller}
            )
            return new_host, new_traveller

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

    def get_idempotency_record(self, idempotency_token: str) -> Optional[IdempotencyRecord]:
        """Retrieves an idempotency record by token."""
        with self._lock:
            rec = self._idempotency_records.get(idempotency_token)
            if rec is None:
                return None
            return IdempotencyRecord(
                token=idempotency_token,
                record_type=rec.get("type", "unknown"),
                join_request_id=rec.get("join_request_id", ""),
                request_id=rec.get("request_id", ""),
                ride_id=rec.get("ride_id", ""),
                version=rec.get("version", 1),
                created_at=rec.get("created_at"),
            )

    def get_pending_requests(self, limit: Optional[int] = None) -> Sequence[RideRequest]:
        with self._lock:
            pending = [r for r in self._requests.values() if r.status == RequestStatus.PENDING]
            if limit is not None:
                return pending[:limit]
            return pending

    def get_active_vehicles(self, limit: Optional[int] = None) -> Sequence[Vehicle]:
        with self._lock:
            active = [v for v in self._vehicles.values() if v.is_active]
            if limit is not None:
                return active[:limit]
            return active

    def get_active_rides(self, limit: Optional[int] = None) -> Sequence[Ride]:
        with self._lock:
            active = [
                r for r in self._rides.values()
                if r.lifecycle_status in (RideStatus.SCHEDULED, RideStatus.ACTIVE)
            ]
            if limit is not None:
                return active[:limit]
            return active

    def commit_dispatch_assignment_atomic(
        self,
        assignment: CandidateAssignment,
        idempotency_token: str,
        current_time: int,
        expected_ride_version: Optional[int] = None,
        new_ride_id: Optional[str] = None,
    ) -> AssignmentCommitResult:
        with self._lock:
            # 1. Idempotency Check
            rec = self._idempotency_records.get(idempotency_token)
            if rec is not None:
                if rec.get("type") == "dispatch_assignment":
                    if rec.get("candidate_id") == assignment.candidate_id:
                        committed_ride = self._rides.get(rec.get("ride_id", ""))
                        return AssignmentCommitResult(
                            success=True,
                            candidate_id=assignment.candidate_id,
                            ride_id=rec.get("ride_id"),
                            ride=committed_ride,
                            committed_request_ids=assignment.request_ids,
                        )
                    return AssignmentCommitResult(
                        success=False,
                        candidate_id=assignment.candidate_id,
                        rejection_reason="IDEMPOTENCY_CONFLICT",
                    )
                return AssignmentCommitResult(
                    success=False,
                    candidate_id=assignment.candidate_id,
                    rejection_reason="IDEMPOTENCY_CONFLICT",
                )

            # 2. Check Vehicle
            vehicle = self._vehicles.get(assignment.vehicle_id)
            if vehicle is None or not vehicle.is_active:
                return AssignmentCommitResult(
                    success=False,
                    candidate_id=assignment.candidate_id,
                    rejection_reason="VEHICLE_NOT_AVAILABLE",
                )

            # 3. Handle Case A: New Ride for Idle Vehicle
            if assignment.existing_ride_id is None:
                # Vehicle must not already have an active/scheduled ride
                for r in self._rides.values():
                    if (
                        r.vehicle_id == assignment.vehicle_id
                        and r.lifecycle_status in (RideStatus.SCHEDULED, RideStatus.ACTIVE)
                    ):
                        return AssignmentCommitResult(
                            success=False,
                            candidate_id=assignment.candidate_id,
                            rejection_reason="VEHICLE_BUSY",
                        )

                # All requests must exist and have status == PENDING
                reqs_to_update: list[RideRequest] = []
                for req_id in assignment.request_ids:
                    req = self._requests.get(req_id)
                    if req is None or req.status != RequestStatus.PENDING:
                        return AssignmentCommitResult(
                            success=False,
                            candidate_id=assignment.candidate_id,
                            rejection_reason="REQUEST_NOT_PENDING",
                        )
                    reqs_to_update.append(req)

                effective_ride_id = new_ride_id or f"ride-{assignment.candidate_id}"

                # Check capacity profile on ordered stops
                if not check_capacity_profile(assignment.ordered_stops, vehicle.total_seat_capacity, 0):
                    return AssignmentCommitResult(
                        success=False,
                        candidate_id=assignment.candidate_id,
                        rejection_reason="CAPACITY_EXCEEDED",
                    )

                # Ensure stops reference effective_ride_id
                updated_stops = tuple(
                    s.model_copy(update={"ride_id": effective_ride_id}) if s.ride_id != effective_ride_id else s
                    for s in assignment.ordered_stops
                )

                dep_time = updated_stops[0].scheduled_arrival_time if updated_stops else current_time
                new_ride = Ride(
                    ride_id=effective_ride_id,
                    vehicle_id=assignment.vehicle_id,
                    driver_id=vehicle.driver_id,
                    lifecycle_status=RideStatus.SCHEDULED,
                    stops=updated_stops,
                    scheduled_departure_time=dep_time,
                    active_passenger_count=0,
                    total_vmt_meters=assignment.vmt_meters,
                    version=1,
                )
                self._rides[effective_ride_id] = new_ride

                # Update requests to MATCHED
                for req in reqs_to_update:
                    self._requests[req.request_id] = req.model_copy(
                        update={"status": RequestStatus.MATCHED, "matched_ride_id": effective_ride_id}
                    )

                # Record idempotency
                self._idempotency_records[idempotency_token] = {
                    "type": "dispatch_assignment",
                    "candidate_id": assignment.candidate_id,
                    "ride_id": effective_ride_id,
                    "version": 1,
                }

                return AssignmentCommitResult(
                    success=True,
                    candidate_id=assignment.candidate_id,
                    ride_id=effective_ride_id,
                    ride=new_ride,
                    committed_request_ids=assignment.request_ids,
                )

            # 4. Handle Case B: Active Ride Insertion
            existing_ride = self._rides.get(assignment.existing_ride_id)
            if existing_ride is None or existing_ride.lifecycle_status not in (RideStatus.SCHEDULED, RideStatus.ACTIVE):
                return AssignmentCommitResult(
                    success=False,
                    candidate_id=assignment.candidate_id,
                    rejection_reason="RIDE_NOT_ACTIVE",
                )

            # OCC Check
            if expected_ride_version is not None and existing_ride.version != expected_ride_version:
                return AssignmentCommitResult(
                    success=False,
                    candidate_id=assignment.candidate_id,
                    rejection_reason="VERSION_CONFLICT",
                )

            # Capacity Check
            if not check_capacity_profile(
                assignment.ordered_stops, vehicle.total_seat_capacity, existing_ride.active_passenger_count
            ):
                return AssignmentCommitResult(
                    success=False,
                    candidate_id=assignment.candidate_id,
                    rejection_reason="CAPACITY_EXCEEDED",
                )

            # Find newly inserted requests (not already in existing ride's stops)
            existing_req_ids = {s.request_id for s in existing_ride.stops}
            if not assignment.request_ids or any(r_id in existing_req_ids for r_id in assignment.request_ids):
                return AssignmentCommitResult(
                    success=False,
                    candidate_id=assignment.candidate_id,
                    rejection_reason="REQUEST_NOT_PENDING",
                )

            reqs_to_update = []
            for req_id in assignment.request_ids:
                req = self._requests.get(req_id)
                if req is None or req.status != RequestStatus.PENDING:
                    return AssignmentCommitResult(
                        success=False,
                        candidate_id=assignment.candidate_id,
                        rejection_reason="REQUEST_NOT_PENDING",
                    )
                reqs_to_update.append(req)

            # Ensure all stops reference existing_ride.ride_id
            updated_stops = tuple(
                s.model_copy(update={"ride_id": existing_ride.ride_id}) if s.ride_id != existing_ride.ride_id else s
                for s in assignment.ordered_stops
            )

            updated_ride = existing_ride.model_copy(
                update={
                    "stops": updated_stops,
                    "total_vmt_meters": assignment.vmt_meters,
                    "version": existing_ride.version + 1,
                }
            )
            self._rides[existing_ride.ride_id] = updated_ride

            # Update newly added requests to MATCHED
            for req in reqs_to_update:
                self._requests[req.request_id] = req.model_copy(
                    update={"status": RequestStatus.MATCHED, "matched_ride_id": existing_ride.ride_id}
                )

            # Record idempotency
            self._idempotency_records[idempotency_token] = {
                "type": "dispatch_assignment",
                "candidate_id": assignment.candidate_id,
                "ride_id": existing_ride.ride_id,
                "version": updated_ride.version,
            }

            return AssignmentCommitResult(
                success=True,
                candidate_id=assignment.candidate_id,
                ride_id=existing_ride.ride_id,
                ride=updated_ride,
                committed_request_ids=assignment.request_ids,
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
        with self._lock:
            # 1. Idempotency Check
            if idempotency_token is not None and idempotency_token in self._idempotency_records:
                rec = self._idempotency_records[idempotency_token]
                if rec.get("record_type") == "cancellation" and rec.get("request_id") == request_id and rec.get("ride_id") == ride_id:
                    return CancellationCommitResult(
                        success=True,
                        request_id=request_id,
                        ride_id=ride_id,
                        ride=self._rides.get(ride_id),
                        request=self._requests.get(request_id),
                    )
                return CancellationCommitResult(
                    success=False,
                    request_id=request_id,
                    ride_id=ride_id,
                    rejection_reason="IDEMPOTENCY_CONFLICT",
                )

            # 2. Check Ride exists and OCC version
            ride = self._rides.get(ride_id)
            if ride is None:
                return CancellationCommitResult(
                    success=False,
                    request_id=request_id,
                    ride_id=ride_id,
                    rejection_reason="RIDE_NOT_FOUND",
                )

            if ride.version != expected_ride_version:
                return CancellationCommitResult(
                    success=False,
                    request_id=request_id,
                    ride_id=ride_id,
                    rejection_reason="VERSION_CONFLICT",
                )

            # 3. Check Request exists and is MATCHED to this ride
            req = self._requests.get(request_id)
            if req is None:
                return CancellationCommitResult(
                    success=False,
                    request_id=request_id,
                    ride_id=ride_id,
                    rejection_reason="REQUEST_NOT_FOUND",
                )

            if req.status == RequestStatus.CANCELLED:
                # Idempotent replay
                return CancellationCommitResult(
                    success=True,
                    request_id=request_id,
                    ride_id=ride_id,
                    ride=ride,
                    request=req,
                )

            if req.status != RequestStatus.MATCHED or req.matched_ride_id != ride_id:
                return CancellationCommitResult(
                    success=False,
                    request_id=request_id,
                    ride_id=ride_id,
                    rejection_reason="REQUEST_NOT_MATCHED",
                )

            # 4. Check if passenger already boarded
            for s in ride.stops:
                if s.request_id == request_id and s.stop_type == StopType.PICKUP and s.status == StopStatus.COMPLETED:
                    return CancellationCommitResult(
                        success=False,
                        request_id=request_id,
                        ride_id=ride_id,
                        rejection_reason="PASSENGER_ALREADY_BOARDED",
                    )

            # 5. Atomic Update
            new_version = ride.version + 1
            eff_status = new_ride_status if new_ride_status is not None else ride.lifecycle_status
            new_ride = ride.model_copy(
                update={
                    "stops": tuple(updated_stops),
                    "total_vmt_meters": new_total_vmt_meters,
                    "lifecycle_status": eff_status,
                    "version": new_version,
                }
            )
            new_req = req.model_copy(update={"status": RequestStatus.CANCELLED})

            self._rides[ride_id] = new_ride
            self._requests[request_id] = new_req

            if idempotency_token is not None:
                self._idempotency_records[idempotency_token] = {
                    "record_type": "cancellation",
                    "request_id": request_id,
                    "ride_id": ride_id,
                    "version": new_version,
                }

            return CancellationCommitResult(
                success=True,
                request_id=request_id,
                ride_id=ride_id,
                ride=new_ride,
                request=new_req,
            )
