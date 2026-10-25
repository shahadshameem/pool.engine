"""Collaborative ride pooling: JoinRequest handling, atomic seat holds, and double-revalidation commit."""

from dataclasses import dataclass
from typing import Optional

from engine.contracts.policy import DispatchPolicy, DispatchPolicyProvider
from engine.contracts.routing import RoadNetworkRoutingProvider
from engine.contracts.storage import RideStorageProvider
from engine.domain.enums import JoinStatus, RequestStatus, StopType
from engine.domain.models import JoinRequest, Ride, RideRequest, Vehicle
from engine.lifecycle.transitions import LifecycleTransitionError
from engine.optimization.tie_breaking import candidate_sort_key
from engine.routing.invariants import check_detour_bound
from engine.routing.insertion import generate_single_request_insertions


@dataclass(frozen=True)
class ReservationResult:
    """Outcome of a join request submission or confirmation attempt."""
    success: bool
    join_request: JoinRequest
    ride: Optional[Ride] = None
    rejection_reason: Optional[str] = None


def submit_join_request(
    request: RideRequest,
    ride_id: str,
    storage: RideStorageProvider,
    policy: DispatchPolicy,
    current_time: int,
    idempotency_token: str,
    user_id: Optional[str] = None,
    join_request_id: Optional[str] = None,
    max_retries: int = 5,
) -> ReservationResult:
    """
    Submits a new join request and attempts to acquire an atomic temporary seat hold.
    Enforces replay safety: if an identical idempotency_token was already processed,
    returns the existing JoinRequest without double-holding seats.
    """
    effective_join_id = (
        join_request_id
        if join_request_id is not None
        else f"join-{idempotency_token}"
    )

    # Validate request status and expiry
    if request.status in (RequestStatus.CANCELLED, RequestStatus.EXPIRED):
        dummy_jr = JoinRequest(
            join_request_id=effective_join_id,
            ride_id=ride_id,
            request_id=request.request_id,
            user_id=user_id if user_id is not None else request.user_id,
            seat_count=request.seat_count,
            submitted_at=current_time,
            expires_at=current_time + policy.join_request_expiry_seconds,
            status=JoinStatus.REJECTED,
            idempotency_token=idempotency_token,
        )
        return ReservationResult(
            success=False,
            join_request=dummy_jr,
            rejection_reason="REQUEST_CANCELLED" if request.status == RequestStatus.CANCELLED else "REQUEST_EXPIRED",
        )

    if current_time > request.latest_dropoff_time:
        dummy_jr = JoinRequest(
            join_request_id=effective_join_id,
            ride_id=ride_id,
            request_id=request.request_id,
            user_id=user_id if user_id is not None else request.user_id,
            seat_count=request.seat_count,
            submitted_at=current_time,
            expires_at=current_time + policy.join_request_expiry_seconds,
            status=JoinStatus.REJECTED,
            idempotency_token=idempotency_token,
        )
        return ReservationResult(
            success=False,
            join_request=dummy_jr,
            rejection_reason="REQUEST_EXPIRED",
        )

    # Replay check
    existing = storage.get_join_request(effective_join_id)
    if existing is not None:
        if (
            existing.request_id != request.request_id
            or existing.ride_id != ride_id
            or (existing.idempotency_token is not None and existing.idempotency_token != idempotency_token)
        ):
            return ReservationResult(
                success=False,
                join_request=existing,
                rejection_reason="IDEMPOTENCY_TOKEN_CONFLICT",
            )
        # Check if the existing pending join request has expired by current_time
        if existing.status == JoinStatus.PENDING and current_time > existing.expires_at:
            storage.release_seats_atomic(
                ride_id=existing.ride_id,
                join_request_id=existing.join_request_id,
                reason="EXPIRED",
            )
            expired_jr = existing.model_copy(update={"status": JoinStatus.EXPIRED})
            storage.save_join_request(expired_jr)
            return ReservationResult(
                success=False,
                join_request=expired_jr,
                rejection_reason="EXPIRED",
            )
        ride_snapshot = storage.get_ride(ride_id)
        rejection_reason = None
        if existing.status == JoinStatus.REJECTED:
            rejection_reason = "OVER_CAPACITY"
        elif existing.status == JoinStatus.EXPIRED:
            rejection_reason = "EXPIRED"
        return ReservationResult(
            success=(existing.status in (JoinStatus.PENDING, JoinStatus.APPROVED)),
            join_request=existing,
            ride=ride_snapshot,
            rejection_reason=rejection_reason,
        )

    # Attempt atomic temporary seat hold with OCC retry
    join_req = JoinRequest(
        join_request_id=effective_join_id,
        ride_id=ride_id,
        request_id=request.request_id,
        user_id=user_id if user_id is not None else request.user_id,
        seat_count=request.seat_count,
        submitted_at=current_time,
        expires_at=current_time + policy.join_request_expiry_seconds,
        status=JoinStatus.PENDING,
        idempotency_token=idempotency_token,
    )

    for _ in range(max_retries):
        ride = storage.get_ride(ride_id)
        if ride is None:
            dummy_jr = join_req.model_copy(update={"status": JoinStatus.REJECTED})
            return ReservationResult(
                success=False,
                join_request=dummy_jr,
                rejection_reason="RIDE_NOT_FOUND",
            )

        expires_at = current_time + policy.join_request_expiry_seconds
        join_req = join_req.model_copy(update={"expires_at": expires_at})

        acquired = storage.acquire_seat_hold_atomic(
            ride_id=ride.ride_id,
            request_id=request.request_id,
            join_request_id=join_req.join_request_id,
            seat_count=join_req.seat_count,
            submitted_at=current_time,
            expires_at=expires_at,
            expected_version=ride.version,
            idempotency_token=idempotency_token,
        )

        if acquired:
            storage.save_join_request(join_req)
            updated_ride = storage.get_ride(ride_id)
            return ReservationResult(
                success=True,
                join_request=join_req,
                ride=updated_ride,
            )

        if hasattr(storage, "_idempotency_records"):
            records = getattr(storage, "_idempotency_records", {})
            rec = records.get(idempotency_token)
            if rec is not None and (
                rec.get("join_request_id") != join_req.join_request_id
                or rec.get("request_id") != request.request_id
                or rec.get("ride_id") != ride.ride_id
            ):
                rejected_jr = join_req.model_copy(update={"status": JoinStatus.REJECTED})
                storage.save_join_request(rejected_jr)
                return ReservationResult(
                    success=False,
                    join_request=rejected_jr,
                    rejection_reason="IDEMPOTENCY_TOKEN_CONFLICT",
                )

        # Check if failure was an optimistic concurrency version mismatch
        latest_ride = storage.get_ride(ride_id)
        if latest_ride is not None and latest_ride.version != ride.version:
            vehicle = storage.get_vehicle(latest_ride.vehicle_id)
            capacity = vehicle.total_seat_capacity if vehicle is not None else 4
            curr_occ = latest_ride.active_passenger_count
            peak_occ = curr_occ
            for stop in latest_ride.stops:
                curr_occ += stop.passenger_delta
                if curr_occ > peak_occ:
                    peak_occ = curr_occ
            active_holds = storage.get_active_seat_holds(ride_id, current_time=current_time)
            active_held_seats = sum(
                h.seat_count for h in active_holds
                if h.join_request_id != join_req.join_request_id
            )
            if peak_occ + active_held_seats + join_req.seat_count <= capacity:
                continue

        break

    rejected_jr = join_req.model_copy(update={"status": JoinStatus.REJECTED})
    storage.save_join_request(rejected_jr)
    return ReservationResult(
        success=False,
        join_request=rejected_jr,
        rejection_reason="OVER_CAPACITY",
    )


def confirm_join_request(
    join_request_id: str,
    storage: RideStorageProvider,
    policy_provider: DispatchPolicyProvider,
    router: RoadNetworkRoutingProvider,
    current_time: int,
    idempotency_token: Optional[str] = None,
) -> ReservationResult:
    """
    Executes the Double-Revalidation Consistency Protocol and atomically commits a seat reservation.
    1. Idempotency Check: Returns already approved state without duplicate modification.
    2. Exact Boundary Timer Check: Valid while t <= expires_at; at t > expires_at, releases hold and marks EXPIRED.
    3. Double-Revalidation: Evaluates candidate insertion under currently active policy and vehicle capacity.
    4. Atomic Commit: Converts hold to confirmed reservation with OCC on Ride.version.
    """
    join_request = storage.get_join_request(join_request_id)
    if join_request is None:
        raise ValueError(f"JoinRequest {join_request_id} not found in storage")

    token = idempotency_token if idempotency_token is not None else join_request.idempotency_token

    # 1. Idempotency check: already approved
    if join_request.status == JoinStatus.APPROVED:
        return ReservationResult(
            success=True,
            join_request=join_request,
            ride=storage.get_ride(join_request.ride_id),
        )

    if join_request.status == JoinStatus.EXPIRED:
        return ReservationResult(
            success=False,
            join_request=join_request,
            rejection_reason="EXPIRED",
        )

    if join_request.status == JoinStatus.REJECTED:
        return ReservationResult(
            success=False,
            join_request=join_request,
            rejection_reason="OVER_CAPACITY",
        )

    # 2. Exact Second-Level Timer Expiry Check
    # Valid while current_time <= expires_at; expired when current_time > expires_at
    if current_time > join_request.expires_at:
        storage.release_seats_atomic(
            ride_id=join_request.ride_id,
            join_request_id=join_request.join_request_id,
            reason="EXPIRED",
        )
        expired_jr = join_request.model_copy(update={"status": JoinStatus.EXPIRED})
        storage.save_join_request(expired_jr)
        return ReservationResult(
            success=False,
            join_request=expired_jr,
            rejection_reason="EXPIRED",
        )

    ride = storage.get_ride(join_request.ride_id)
    if ride is None:
        return ReservationResult(
            success=False,
            join_request=join_request,
            rejection_reason="RIDE_NOT_FOUND",
        )

    vehicle = storage.get_vehicle(ride.vehicle_id)
    if vehicle is None:
        return ReservationResult(
            success=False,
            join_request=join_request,
            rejection_reason="VEHICLE_NOT_FOUND",
        )

    request = storage.get_request(join_request.request_id)
    if request is None:
        return ReservationResult(
            success=False,
            join_request=join_request,
            rejection_reason="REQUEST_NOT_FOUND",
        )

    # 3. Double-Revalidation against active policy and current road/network conditions
    active_policy = policy_provider.get_policy()
    raw_candidates = generate_single_request_insertions(
        active_ride=ride,
        request=request,
        vehicle=vehicle,
        router=router,
        policy=active_policy,
        current_time=current_time,
    )

    # Double-revalidate: ensure every onboard/scheduled request satisfies active policy
    candidates = []
    for cand in raw_candidates:
        cand_feasible = True
        for s in cand.ordered_stops:
            if s.stop_type == StopType.DROPOFF:
                stored_req = storage.get_request(s.request_id)
                if stored_req is not None:
                    p_stop = next(
                        (p for p in cand.ordered_stops if p.request_id == s.request_id and p.stop_type == StopType.PICKUP),
                        None,
                    )
                    if p_stop is not None:
                        p_time = p_stop.scheduled_arrival_time
                    else:
                        orig_p = next(
                            (p for p in ride.stops if p.request_id == s.request_id and p.stop_type == StopType.PICKUP),
                            None,
                        )
                        p_time = (
                            orig_p.actual_arrival_time or orig_p.scheduled_arrival_time
                            if orig_p is not None
                            else ride.scheduled_departure_time
                        )
                    d_time = s.scheduled_arrival_time
                    dur = max(0, d_time - p_time)
                    if not check_detour_bound(
                        actual_duration=dur,
                        direct_duration=stored_req.direct_duration_seconds,
                        policy=active_policy,
                    ):
                        cand_feasible = False
                        break
        if cand_feasible:
            candidates.append(cand)

    if not candidates:
        # Revalidation failed! No feasible insertions satisfy active policy and capacity
        storage.release_seats_atomic(
            ride_id=ride.ride_id,
            join_request_id=join_request.join_request_id,
            reason="REVALIDATION_FAILED",
        )
        rejected_jr = join_request.model_copy(update={"status": JoinStatus.REJECTED})
        storage.save_join_request(rejected_jr)

        # Check whether capacity or detour caused failure
        current_occ = ride.active_passenger_count
        peak_occ = current_occ
        for stop in ride.stops:
            current_occ += stop.passenger_delta
            if current_occ > peak_occ:
                peak_occ = current_occ

        rejection_reason = (
            "OVER_CAPACITY"
            if peak_occ + join_request.seat_count > vehicle.total_seat_capacity
            else "DETOUR_BREACH"
        )
        return ReservationResult(
            success=False,
            join_request=rejected_jr,
            rejection_reason=rejection_reason,
        )

    # Pick best candidate using deterministic tie-breaking sort key
    best_candidate = sorted(candidates, key=candidate_sort_key())[0]

    # 4. Atomic Commit with OCC retry
    max_commit_retries = 3
    for _ in range(max_commit_retries):
        committed = storage.reserve_seats_atomic(
            ride_id=ride.ride_id,
            request_id=request.request_id,
            join_request_id=join_request.join_request_id,
            seat_count=join_request.seat_count,
            expected_version=ride.version,
            idempotency_token=token,
            new_stops=best_candidate.ordered_stops,
            current_time=current_time,
        )

        if committed:
            approved_jr = join_request.model_copy(update={"status": JoinStatus.APPROVED})
            storage.save_join_request(approved_jr)

            updated_req = request.model_copy(
                update={"status": RequestStatus.MATCHED, "matched_ride_id": ride.ride_id}
            )
            storage.save_request(updated_req)

            updated_ride = storage.get_ride(ride.ride_id)
            return ReservationResult(
                success=True,
                join_request=approved_jr,
                ride=updated_ride,
            )

        if hasattr(storage, "_idempotency_records"):
            records = getattr(storage, "_idempotency_records", {})
            rec = records.get(token)
            if rec is not None and (
                rec.get("join_request_id") != join_request.join_request_id
                or rec.get("request_id") != request.request_id
                or rec.get("ride_id") != ride.ride_id
            ):
                storage.release_seats_atomic(
                    ride_id=ride.ride_id,
                    join_request_id=join_request.join_request_id,
                    reason="IDEMPOTENCY_TOKEN_CONFLICT",
                )
                rejected_jr = join_request.model_copy(update={"status": JoinStatus.REJECTED})
                storage.save_join_request(rejected_jr)
                return ReservationResult(
                    success=False,
                    join_request=rejected_jr,
                    rejection_reason="IDEMPOTENCY_TOKEN_CONFLICT",
                )

        # Check if failure was an optimistic concurrency version mismatch
        latest_ride = storage.get_ride(ride.ride_id)
        if latest_ride is not None and latest_ride.version != ride.version:
            ride = latest_ride
            raw_candidates = generate_single_request_insertions(
                active_ride=ride,
                request=request,
                vehicle=vehicle,
                router=router,
                policy=active_policy,
                current_time=current_time,
            )
            candidates = []
            for cand in raw_candidates:
                cand_feasible = True
                for s in cand.ordered_stops:
                    if s.stop_type == StopType.DROPOFF:
                        stored_req = storage.get_request(s.request_id)
                        if stored_req is not None:
                            p_stop = next(
                                (p for p in cand.ordered_stops if p.request_id == s.request_id and p.stop_type == StopType.PICKUP),
                                None,
                            )
                            p_time = (
                                p_stop.scheduled_arrival_time
                                if p_stop is not None
                                else (
                                    next(
                                        (p.actual_arrival_time or p.scheduled_arrival_time
                                         for p in ride.stops if p.request_id == s.request_id and p.stop_type == StopType.PICKUP),
                                        ride.scheduled_departure_time,
                                    )
                                )
                            )
                            d_time = s.scheduled_arrival_time
                            dur = max(0, d_time - p_time)
                            if not check_detour_bound(
                                actual_duration=dur,
                                direct_duration=stored_req.direct_duration_seconds,
                                policy=active_policy,
                            ):
                                cand_feasible = False
                                break
                if cand_feasible:
                    candidates.append(cand)
            if candidates:
                best_candidate = sorted(candidates, key=candidate_sort_key())[0]
                continue

        break

    storage.release_seats_atomic(
        ride_id=ride.ride_id,
        join_request_id=join_request.join_request_id,
        reason="OVER_CAPACITY",
    )
    rejected_jr = join_request.model_copy(update={"status": JoinStatus.REJECTED})
    storage.save_join_request(rejected_jr)
    return ReservationResult(
        success=False,
        join_request=rejected_jr,
        rejection_reason="OVER_CAPACITY",
    )


def reject_join_request(
    join_request_id: str,
    storage: RideStorageProvider,
    reason: str = "DECLINED_BY_CREATOR",
) -> ReservationResult:
    """Explicitly declines a pending join request and immediately releases its seat hold."""
    join_request = storage.get_join_request(join_request_id)
    if join_request is None:
        raise ValueError(f"JoinRequest {join_request_id} not found in storage")

    if join_request.status == JoinStatus.APPROVED:
        raise LifecycleTransitionError(
            f"Cannot reject join request {join_request_id}: already APPROVED. Use cancel_en_route_request instead."
        )

    if join_request.status == JoinStatus.REJECTED:
        return ReservationResult(
            success=False,
            join_request=join_request,
            rejection_reason=reason,
        )

    if join_request.status == JoinStatus.EXPIRED:
        return ReservationResult(
            success=False,
            join_request=join_request,
            rejection_reason="EXPIRED",
        )

    storage.release_seats_atomic(
        ride_id=join_request.ride_id,
        join_request_id=join_request.join_request_id,
        reason=reason,
    )
    rejected_jr = join_request.model_copy(update={"status": JoinStatus.REJECTED})
    storage.save_join_request(rejected_jr)

    return ReservationResult(
        success=False,
        join_request=rejected_jr,
        rejection_reason=reason,
    )


def expire_stale_holds(
    storage: RideStorageProvider,
    current_time: int,
) -> list[str]:
    """
    Sweeps storage and transitions all expired holds (current_time > expires_at)
    to EXPIRED status, freeing held seats.
    """
    expired_ids = list(storage.sweep_expired_holds(current_time))
    for j_id in expired_ids:
        jr = storage.get_join_request(j_id)
        if jr is not None and jr.status == JoinStatus.PENDING:
            storage.save_join_request(jr.model_copy(update={"status": JoinStatus.EXPIRED}))
    return expired_ids
