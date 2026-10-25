"""Domain service layer bridging API endpoints to storage, routing, and dispatch orchestration."""

import time
import uuid
from typing import Any, Optional

from engine.contracts.routing import (
    Coordinate,
    InvalidRouteDataError,
    RoadNetworkRoutingProvider,
    RouteLookupError,
    RouteTimeoutError,
    RoutingProviderError,
    validate_route_leg,
)
from engine.contracts.storage import RideStorageProvider
from engine.domain.enums import RequestStatus
from engine.domain.models import GeoCoordinate, Ride, RideRequest, Vehicle
from engine.lifecycle.transitions import LifecycleTransitionError, cancel_en_route_request
from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator
from engine.service.errors import (
    ConflictError,
    LifecycleError,
    ResourceNotFoundError,
    RoutingError,
    RoutingTimeoutError as ApiRoutingTimeoutError,
    ValidationError,
)
from engine.service.schemas import (
    CreateRideRequestInput,
    DispatchCycleResponse,
    DispatchRunInput,
    RegisterVehicleInput,
    StaleAssignmentDiagnosticResponse,
)
from engine.service.security import sanitize_sensitive_strings
from engine.service.telemetry import EngineTelemetryProvider, StructuredLoggerTelemetry


class PoolEngineService:
    """
    Application service orchestrating pool engine operations across storage,
    road network routing, and dispatch orchestration.
    """

    def __init__(
        self,
        storage: RideStorageProvider,
        orchestrator: DispatchOrchestrator,
        router: RoadNetworkRoutingProvider,
        telemetry: Optional[EngineTelemetryProvider] = None,
    ) -> None:
        self.storage = storage
        self.orchestrator = orchestrator
        self.router = router
        self.telemetry: EngineTelemetryProvider = telemetry or StructuredLoggerTelemetry()
        self._dispatch_cache: dict[str, DispatchCycleResponse] = {}

    def check_readiness(self, strict_routing: bool = False) -> dict[str, Any]:
        """
        Operational readiness probe verifying persistent storage and routing readiness.
        Storage failure is an essential dependency outage and marks ready=False (503).
        Routing outages are reported as degraded without making the entire service unready
        unless strict_routing=True.
        Sanitizes connection strings so passwords or internal credentials are never leaked.
        """
        storage_status = "healthy"
        storage_error = None
        try:
            _ = self.storage.get_active_rides(limit=1)
        except Exception as exc:
            storage_status = "unreachable"
            storage_error = sanitize_sensitive_strings(str(exc))

        routing_status = "healthy"
        routing_error = None
        try:
            if hasattr(self.router, "check_health"):
                is_healthy = self.router.check_health()
                if not is_healthy:
                    routing_status = "degraded"
                    routing_error = "Routing backend health probe failed"
        except Exception as exc:
            routing_status = "degraded"
            routing_error = sanitize_sensitive_strings(str(exc))

        is_ready = storage_status == "healthy"
        if strict_routing and routing_status != "healthy":
            is_ready = False

        components: dict[str, Any] = {
            "storage": storage_status,
            "routing": routing_status,
        }
        if storage_error:
            components["storage_error"] = storage_error
        if routing_error:
            components["routing_error"] = routing_error

        return {
            "ready": is_ready,
            "status": "ready" if is_ready else "not_ready",
            "components": components,
        }

    def close(self) -> None:
        """Closes underlying storage connections and routing transports cleanly."""
        if hasattr(self.storage, "close"):
            try:
                self.storage.close()
            except Exception:
                pass
        if hasattr(self.router, "close"):
            try:
                self.router.close()
            except Exception:
                pass
        if hasattr(self.router, "transport") and hasattr(self.router.transport, "close"):
            try:
                self.router.transport.close()
            except Exception:
                pass

    def create_request(self, input_data: CreateRideRequestInput) -> RideRequest:
        """
        Creates and persists a canonical RideRequest.
        Validates pickup/dropoff coordinates and calculates direct road distance/duration
        using the configured routing provider if not explicitly supplied.
        """
        req_id = input_data.request_id or f"req-{uuid.uuid4()}"

        existing = self.storage.get_request(req_id)
        if existing is not None:
            if (
                existing.user_id == input_data.user_id
                and existing.pickup_location == input_data.pickup_location
                and existing.dropoff_location == input_data.dropoff_location
                and existing.seat_count == input_data.seat_count
                and existing.earliest_pickup_time == input_data.earliest_pickup_time
                and existing.latest_dropoff_time == input_data.latest_dropoff_time
            ):
                self.telemetry.record_idempotency_hit(req_id, "create_request")
                return existing
            self.telemetry.record_conflict("request_duplicate", req_id)
            raise ConflictError(f"RideRequest with ID '{req_id}' already exists with different attributes")

        direct_dist = input_data.direct_distance_meters
        direct_dur = input_data.direct_duration_seconds

        if direct_dist is None or direct_dur is None:
            coord_from = Coordinate(
                latitude=input_data.pickup_location.latitude,
                longitude=input_data.pickup_location.longitude,
            )
            coord_to = Coordinate(
                latitude=input_data.dropoff_location.latitude,
                longitude=input_data.dropoff_location.longitude,
            )
            try:
                raw_leg = self.router.get_direct_leg(coord_from, coord_to)
                valid_dist, valid_dur = validate_route_leg(coord_from, coord_to, raw_leg)
            except RouteTimeoutError as err:
                self.telemetry.record_routing_failure("router", "timeout")
                raise ApiRoutingTimeoutError(
                    f"Routing provider timed out calculating direct route leg: {err}"
                ) from err
            except (RouteLookupError, InvalidRouteDataError, RoutingProviderError, TimeoutError, ConnectionError) as err:
                self.telemetry.record_routing_failure("router", str(err))
                raise RoutingError(
                    f"Failed to resolve direct road route from pickup to dropoff: {err}"
                ) from err

            direct_dist = valid_dist if direct_dist is None else direct_dist
            direct_dur = valid_dur if direct_dur is None else direct_dur

        # Enforce that time window accommodates the direct duration
        min_dropoff = input_data.earliest_pickup_time + direct_dur
        if input_data.latest_dropoff_time < min_dropoff:
            raise ValidationError(
                f"latest_dropoff_time ({input_data.latest_dropoff_time}) cannot accommodate direct "
                f"road travel duration of {direct_dur}s from earliest_pickup_time "
                f"({input_data.earliest_pickup_time}). Earliest reachable dropoff is {min_dropoff}."
            )

        new_request = RideRequest(
            request_id=req_id,
            user_id=input_data.user_id,
            pickup_location=input_data.pickup_location,
            dropoff_location=input_data.dropoff_location,
            seat_count=input_data.seat_count,
            earliest_pickup_time=input_data.earliest_pickup_time,
            latest_dropoff_time=input_data.latest_dropoff_time,
            direct_distance_meters=direct_dist,
            direct_duration_seconds=direct_dur,
            status=RequestStatus.PENDING,
            matched_ride_id=None,
        )
        self.storage.save_request(new_request)
        return new_request

    def get_request(self, request_id: str) -> RideRequest:
        """Retrieves a RideRequest by its identifier."""
        req = self.storage.get_request(request_id)
        if req is None:
            raise ResourceNotFoundError(f"RideRequest '{request_id}' not found")
        return req

    def cancel_request(
        self,
        request_id: str,
        reason: Optional[str] = None,
        current_time: Optional[int] = None,
        idempotency_token: Optional[str] = None,
    ) -> RideRequest:
        """
        Safely cancels a ride request preserving lifecycle invariants.

        - If PENDING: marks CANCELLED directly in storage.
        - If MATCHED: safely adjusts active ride stops, revalidates itinerary, updates ETAs,
          and commits both the re-optimized ride and request status atomically via
          storage.cancel_assigned_request_atomic().
        - If CANCELLED: idempotent, returns existing request.
        - If COMPLETED or EXPIRED: raises LifecycleError (422).
        - If IN_TRANSIT (already boarded): raises LifecycleError (422).
        """
        req = self.storage.get_request(request_id)
        if req is None:
            raise ResourceNotFoundError(f"RideRequest '{request_id}' not found")

        if req.status == RequestStatus.CANCELLED:
            self.telemetry.record_idempotency_hit(request_id, "cancel_request")
            return req

        if req.status in (RequestStatus.COMPLETED, RequestStatus.EXPIRED):
            raise LifecycleError(f"Cannot cancel ride request currently in '{req.status.value}' status")

        if req.status == RequestStatus.PENDING:
            cancelled_req = req.model_copy(update={"status": RequestStatus.CANCELLED})
            self.storage.save_request(cancelled_req)
            self.telemetry.record_cancellation(request_id, None, was_matched=False)
            return cancelled_req

        if req.status == RequestStatus.MATCHED:
            if not req.matched_ride_id:
                cancelled_req = req.model_copy(update={"status": RequestStatus.CANCELLED})
                self.storage.save_request(cancelled_req)
                self.telemetry.record_cancellation(request_id, None, was_matched=False)
                return cancelled_req

            eff_time = current_time if current_time is not None else int(time.time())

            # Bounded retry on optimistic concurrency conflict
            max_attempts = 2
            for attempt in range(max_attempts):
                ride = self.storage.get_ride(req.matched_ride_id)
                if ride is None:
                    raise ResourceNotFoundError(
                        f"Matched Ride '{req.matched_ride_id}' for request '{request_id}' not found"
                    )

                vehicle = self.storage.get_vehicle(ride.vehicle_id)
                veh_loc = vehicle.current_location if vehicle else None

                # Compute re-optimized itinerary without modifying storage (storage=None)
                try:
                    computed_ride, _ = cancel_en_route_request(
                        ride=ride,
                        request_id=request_id,
                        router=self.router,
                        current_time=eff_time,
                        vehicle_location=veh_loc,
                        storage=None,
                    )
                except LifecycleTransitionError as err:
                    raise LifecycleError(str(err)) from err
                except (RoutingProviderError, TimeoutError, ConnectionError) as err:
                    raise RoutingError(
                        f"Routing provider failure during en-route cancellation: {err}"
                    ) from err

                # Commit atomically across ride and request in one single transaction
                eff_token = f"{idempotency_token}:att{attempt}" if idempotency_token is not None else None
                commit_res = self.storage.cancel_assigned_request_atomic(
                    ride_id=ride.ride_id,
                    request_id=request_id,
                    expected_ride_version=ride.version,
                    updated_stops=computed_ride.stops,
                    new_total_vmt_meters=computed_ride.total_vmt_meters,
                    idempotency_token=eff_token,
                )

                if commit_res.success and commit_res.request is not None:
                    self.telemetry.record_cancellation(request_id, ride.ride_id, was_matched=True)
                    return commit_res.request

                if commit_res.rejection_reason == "VERSION_CONFLICT":
                    self.telemetry.record_conflict("cancellation_version_conflict", request_id)
                    if attempt < max_attempts - 1:
                        continue  # retry with freshly fetched ride
                    raise ConflictError(
                        f"Optimistic concurrency conflict cancelling request '{request_id}': "
                        f"ride '{ride.ride_id}' was modified concurrently"
                    )
                elif commit_res.rejection_reason == "PASSENGER_ALREADY_BOARDED":
                    raise LifecycleError(f"Passenger {request_id} has already boarded; cannot cancel en-route")
                elif commit_res.rejection_reason == "REQUEST_NOT_FOUND":
                    raise ResourceNotFoundError(f"RideRequest '{request_id}' not found")
                elif commit_res.rejection_reason == "RIDE_NOT_FOUND":
                    raise ResourceNotFoundError(f"Ride '{ride.ride_id}' not found")
                else:
                    raise LifecycleError(f"Cancellation rejected: {commit_res.rejection_reason}")

            raise ConflictError(f"Concurrency conflict cancelling request '{request_id}'")

        if req.status == RequestStatus.IN_TRANSIT:
            raise LifecycleError("Passenger has already boarded vehicle; cannot cancel en-route")

        return req

    def register_vehicle(self, input_data: RegisterVehicleInput) -> Vehicle:
        """Registers a new vehicle in storage."""
        existing = self.storage.get_vehicle(input_data.vehicle_id)
        if existing is not None:
            if (
                existing.driver_id == input_data.driver_id
                and existing.total_seat_capacity == input_data.total_seat_capacity
                and existing.luggage_capacity_units == input_data.luggage_capacity_units
            ):
                self.telemetry.record_idempotency_hit(input_data.vehicle_id, "register_vehicle")
                return existing
            self.telemetry.record_conflict("vehicle_duplicate", input_data.vehicle_id)
            raise ConflictError(
                f"Vehicle '{input_data.vehicle_id}' already registered with different configuration"
            )

        new_vehicle = Vehicle(
            vehicle_id=input_data.vehicle_id,
            driver_id=input_data.driver_id,
            total_seat_capacity=input_data.total_seat_capacity,
            current_location=input_data.current_location,
            is_active=input_data.is_active,
            luggage_capacity_units=input_data.luggage_capacity_units,
        )
        self.storage.save_vehicle(new_vehicle)
        return new_vehicle

    def get_vehicle(self, vehicle_id: str) -> Vehicle:
        """Retrieves a Vehicle by its identifier."""
        veh = self.storage.get_vehicle(vehicle_id)
        if veh is None:
            raise ResourceNotFoundError(f"Vehicle '{vehicle_id}' not found")
        return veh

    def update_vehicle_location(self, vehicle_id: str, location: GeoCoordinate) -> Vehicle:
        """Updates the current coordinates of an existing vehicle."""
        veh = self.get_vehicle(vehicle_id)
        updated = veh.model_copy(update={"current_location": location})
        self.storage.save_vehicle(updated)
        return updated

    def update_vehicle_status(self, vehicle_id: str, is_active: bool) -> Vehicle:
        """Updates the active operational status of an existing vehicle."""
        veh = self.get_vehicle(vehicle_id)
        updated = veh.model_copy(update={"is_active": is_active})
        self.storage.save_vehicle(updated)
        return updated

    def run_dispatch(
        self,
        input_data: DispatchRunInput,
        header_idempotency_key: Optional[str] = None,
    ) -> DispatchCycleResponse:
        """
        Executes a bounded batch optimization cycle via DispatchOrchestrator.
        Enforces idempotency token consistency and returns structured match results.
        """
        if header_idempotency_key is not None and input_data.idempotency_token is not None:
            if header_idempotency_key != input_data.idempotency_token:
                raise ValidationError(
                    f"Idempotency-Key header ('{header_idempotency_key}') does not match "
                    f"body idempotency_token ('{input_data.idempotency_token}')"
                )

        eff_token = (
            header_idempotency_key
            or input_data.idempotency_token
            or f"idemp-dispatch-{uuid.uuid4()}"
        )

        # Idempotent replay: return cached cycle result without running solver again
        if eff_token in self._dispatch_cache:
            self.telemetry.record_idempotency_hit(eff_token, "run_dispatch")
            return self._dispatch_cache[eff_token]

        deadline = (
            time.monotonic() + input_data.deadline_seconds
            if input_data.deadline_seconds is not None
            else None
        )

        orch_result = self.orchestrator.dispatch_cycle(
            current_time=input_data.current_time,
            cycle_id=input_data.cycle_id,
            idempotency_token=eff_token,
            deadline=deadline,
        )

        response = DispatchCycleResponse(
            cycle_id=orch_result.cycle_id,
            batch_id=orch_result.batch_id,
            timestamp=orch_result.timestamp,
            search_status=orch_result.search_status,
            is_approximated=orch_result.is_approximated,
            total_vmt_savings_meters=orch_result.total_vmt_savings_meters,
            cycle_duration_ms=orch_result.cycle_duration_ms,
            routing_errors_count=orch_result.routing_errors_count,
            committed_assignments=orch_result.committed_assignments,
            rejected_assignments=tuple(
                StaleAssignmentDiagnosticResponse(
                    candidate_id=r.candidate_id,
                    vehicle_id=r.vehicle_id,
                    request_ids=r.request_ids,
                    rejection_reason=r.rejection_reason,
                    retry_count=r.retry_count,
                )
                for r in orch_result.rejected_assignments
            ),
            unassigned_request_ids=orch_result.unassigned_request_ids,
        )

        self._dispatch_cache[eff_token] = response
        self.telemetry.record_dispatch_cycle(
            cycle_id=response.cycle_id,
            duration_ms=response.cycle_duration_ms,
            search_status=response.search_status,
            committed_count=len(response.committed_assignments),
            rejected_count=len(response.rejected_assignments),
            unassigned_count=len(response.unassigned_request_ids),
            routing_errors=response.routing_errors_count,
            vmt_savings=response.total_vmt_savings_meters,
        )
        return response

    def get_ride(self, ride_id: str) -> Ride:
        """Retrieves a Ride by its identifier."""
        ride = self.storage.get_ride(ride_id)
        if ride is None:
            raise ResourceNotFoundError(f"Ride '{ride_id}' not found")
        return ride
