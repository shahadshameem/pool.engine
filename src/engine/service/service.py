"""Domain service layer bridging API endpoints to storage, routing, and dispatch orchestration."""

import time
import uuid
from typing import Any, Mapping, Optional, Sequence

from engine.contracts.routing import (
    Coordinate,
    InvalidRouteDataError,
    OutOfRegionError,
    RoadNetworkRoutingProvider,
    RouteLookupError,
    RouteTimeoutError,
    RoutingProviderError,
    validate_route_leg,
)
from engine.contracts.storage import RideStorageProvider
from engine.domain.enums import JoinStatus, RequestStatus, RideStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle
from engine.lifecycle.reservations import (
    confirm_join_request,
    expire_stale_holds,
    reject_join_request,
    submit_join_request,
)
from engine.lifecycle.transitions import LifecycleTransitionError, cancel_en_route_request
from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator
from engine.service.errors import (
    AuthorizationForbiddenError,
    ConflictError,
    LifecycleError,
    OutOfRegionServiceError,
    ResourceNotFoundError,
    RoutingError,
    RoutingTimeoutError as ApiRoutingTimeoutError,
    ValidationError,
)
from engine.service.schemas import (
    CreateHostRideInput,
    CreateProposalInput,
    CreateRideRequestInput,
    DispatchCycleResponse,
    DispatchRunInput,
    EnRouteJoinInput,
    EnRouteJoinResult,
    HostRideDTO,
    ProposalDTO,
    ProposalDecisionInput,
    ProposalDecisionResult,
    ReconcileRideInput,
    RegisterVehicleInput,
    StaleAssignmentDiagnosticResponse,
    UpdateVehicleLocationInput,
)
from engine.service.security import AuthContext, sanitize_sensitive_strings
from engine.service.telemetry import EngineTelemetryProvider, StructuredLoggerTelemetry, mask_coordinate


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
        self._capacity_sync_versions: dict[str, int] = {}
        self._capacity_idempotency_tokens: set[str] = set()
        self._pending_capacities: dict[str, dict[str, Any]] = {}

    def open(self) -> None:
        """Initializes and pre-warms underlying storage pools and routing transports."""
        if hasattr(self.storage, "open"):
            self.storage.open()
        if hasattr(self.router, "open"):
            self.router.open()

    def check_readiness(
        self,
        strict_routing: bool = False,
        require_persistent_storage: bool = False,
        region_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Operational readiness probe verifying persistent storage and routing readiness.
        Storage failure is an essential dependency outage and marks ready=False (503).
        Routing outages are reported as degraded without making the entire service unready
        unless strict_routing=True.
        If region_id is provided, verifies routing readiness specifically for that target region.
        Sanitizes connection strings so passwords or internal credentials are never leaked.
        """
        storage_status = "healthy"
        storage_error = None

        if require_persistent_storage:
            from engine.adapters.in_memory_storage import InMemoryRideStorage
            if isinstance(self.storage, InMemoryRideStorage):
                storage_status = "unavailable"
                storage_error = "Persistent storage required but in-memory storage is active"

        if storage_status == "healthy":
            try:
                _ = self.storage.get_active_rides(limit=1)
            except Exception as exc:
                storage_status = "unreachable"
                storage_error = sanitize_sensitive_strings(str(exc))

        routing_status = "healthy"
        routing_error = None
        try:
            if region_id is not None and hasattr(self.router, "get_provider"):
                try:
                    regional_provider = self.router.get_provider(region_id)
                    is_healthy = regional_provider.check_health()
                    if not is_healthy:
                        routing_status = "degraded"
                        routing_error = f"Routing backend for region '{region_id}' is unhealthy"
                except KeyError:
                    routing_status = "degraded"
                    routing_error = f"Target region '{region_id}' is not configured"
            elif hasattr(self.router, "check_health"):
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
        if region_id is not None:
            components["target_region"] = region_id
        if storage_error:
            components["storage_error"] = storage_error
        if routing_error:
            components["routing_error"] = routing_error
        if hasattr(self.router, "check_regions_health"):
            components["regions"] = self.router.check_regions_health()

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

        coord_from = Coordinate(
            latitude=input_data.pickup_location.latitude,
            longitude=input_data.pickup_location.longitude,
        )
        coord_to = Coordinate(
            latitude=input_data.dropoff_location.latitude,
            longitude=input_data.dropoff_location.longitude,
        )
        try:
            self.router.validate_coordinate(coord_from, "Pickup location")
            self.router.validate_coordinate(coord_to, "Dropoff location")
            if hasattr(self.router, "find_region_for_coordinate"):
                reg_from = self.router.find_region_for_coordinate(coord_from)
                reg_to = self.router.find_region_for_coordinate(coord_to)
                if input_data.region_id is not None:
                    if reg_from is None or reg_from.region_id != input_data.region_id:
                        raise OutOfRegionServiceError(
                            f"Pickup coordinate ({coord_from.latitude}, {coord_from.longitude}) "
                            f"does not match declared region '{input_data.region_id}'"
                        )
                    if reg_to is None or reg_to.region_id != input_data.region_id:
                        raise OutOfRegionServiceError(
                            f"Dropoff coordinate ({coord_to.latitude}, {coord_to.longitude}) "
                            f"does not match declared region '{input_data.region_id}'"
                        )
                if reg_from is not None and reg_to is not None and reg_from.region_id != reg_to.region_id:
                    raise OutOfRegionServiceError(
                        f"Cross-region journey from '{reg_from.region_id}' to '{reg_to.region_id}' is unsupported"
                    )
        except OutOfRegionError as err:
            self.telemetry.record_routing_failure("router", "out_of_region")
            raise OutOfRegionServiceError(
                f"Requested coordinates fall outside the operational service region: {err}"
            ) from err

        direct_dist = input_data.direct_distance_meters
        direct_dur = input_data.direct_duration_seconds

        if direct_dist is None or direct_dur is None:
            try:
                raw_leg = self.router.get_direct_leg(coord_from, coord_to)
                valid_dist, valid_dur = validate_route_leg(coord_from, coord_to, raw_leg)
            except OutOfRegionError as err:
                self.telemetry.record_routing_failure("router", "out_of_region")
                raise OutOfRegionServiceError(
                    f"Requested coordinates fall outside the operational service region: {err}"
                ) from err
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

    def get_request(
        self,
        request_id: str,
        auth_context: Optional[AuthContext] = None,
    ) -> RideRequest:
        """Retrieves a RideRequest by its identifier with caller ownership validation."""
        req = self.storage.get_request(request_id)
        if req is None:
            raise ResourceNotFoundError(f"RideRequest '{request_id}' not found")
        if auth_context and auth_context.authenticated and "admin" not in auth_context.roles:
            is_owner = (req.user_id == auth_context.subject_id)
            is_driver = False
            if req.matched_ride_id:
                matched_ride = self.storage.get_ride(req.matched_ride_id)
                if matched_ride and matched_ride.driver_id == auth_context.subject_id:
                    is_driver = True
            if not (is_owner or is_driver):
                raise AuthorizationForbiddenError(
                    f"Caller '{auth_context.subject_id}' is not authorized to inspect request '{request_id}'"
                )
        return req

    def cancel_request(
        self,
        request_id: str,
        reason: Optional[str] = None,
        current_time: Optional[int] = None,
        idempotency_token: Optional[str] = None,
        auth_context: Optional[AuthContext] = None,
    ) -> RideRequest:
        """
        Safely cancels a ride request preserving lifecycle invariants and caller ownership rules.

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

        if auth_context and auth_context.authenticated and "admin" not in auth_context.roles:
            if req.user_id != auth_context.subject_id:
                raise AuthorizationForbiddenError(
                    f"Caller '{auth_context.subject_id}' is not authorized to cancel request '{request_id}' belonging to '{req.user_id}'"
                )

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

            # Bounded retry on optimistic concurrency conflict
            max_attempts = 2
            for attempt in range(max_attempts):
                ride = self.storage.get_ride(req.matched_ride_id)
                if ride is None:
                    raise ResourceNotFoundError(
                        f"Matched Ride '{req.matched_ride_id}' for request '{request_id}' not found"
                    )

                eff_time = (
                    current_time
                    if current_time is not None
                    else (ride.scheduled_departure_time if ride.lifecycle_status != RideStatus.ACTIVE else int(time.time()))
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
        veh_coord = Coordinate(
            latitude=input_data.current_location.latitude,
            longitude=input_data.current_location.longitude,
        )
        try:
            self.router.validate_coordinate(veh_coord, "Vehicle location")
            if input_data.region_id is not None and hasattr(self.router, "find_region_for_coordinate"):
                reg = self.router.find_region_for_coordinate(veh_coord)
                if reg is None or reg.region_id != input_data.region_id:
                    raise OutOfRegionServiceError(
                        f"Vehicle location ({veh_coord.latitude}, {veh_coord.longitude}) "
                        f"does not match declared region '{input_data.region_id}'"
                    )
        except OutOfRegionError as err:
            raise OutOfRegionServiceError(
                f"Vehicle location falls outside the operational service region: {err}"
            ) from err

        existing = self.storage.get_vehicle(input_data.vehicle_id)
        if existing is not None:
            if existing.driver_id == input_data.driver_id:
                # Same vehicle and driver: idempotent hit, retain current synchronized capacity
                self.telemetry.record_idempotency_hit(input_data.vehicle_id, "register_vehicle")
                return existing
            self.telemetry.record_conflict("vehicle_duplicate", input_data.vehicle_id)
            raise ConflictError(
                f"Vehicle '{input_data.vehicle_id}' already registered with different configuration"
            )

        eff_capacity = input_data.total_seat_capacity
        if input_data.vehicle_id in self._pending_capacities:
            eff_capacity = self._pending_capacities[input_data.vehicle_id]["available_seats"]

        new_vehicle = Vehicle(
            vehicle_id=input_data.vehicle_id,
            driver_id=input_data.driver_id,
            total_seat_capacity=eff_capacity,
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

    def update_vehicle_location(
        self,
        vehicle_id: str,
        location: GeoCoordinate,
        ride_id: Optional[str] = None,
        completed_stop_ids: Optional[Sequence[str]] = None,
        current_time: Optional[int] = None,
    ) -> Vehicle:
        """Updates the current coordinates of an existing vehicle and optional ride progress."""
        veh_coord = Coordinate(latitude=location.latitude, longitude=location.longitude)
        try:
            self.router.validate_coordinate(veh_coord, "Vehicle location")
        except OutOfRegionError as err:
            raise OutOfRegionServiceError(
                f"Vehicle location falls outside the operational service region: {err}"
            ) from err

        veh = self.get_vehicle(vehicle_id)
        updated = veh.model_copy(update={"current_location": location})
        self.storage.save_vehicle(updated)

        if ride_id:
            ride = self.storage.get_ride(ride_id)
            if ride is not None:
                now = (
                    current_time
                    if current_time is not None
                    else (
                        ride.scheduled_departure_time
                        if (ride.scheduled_departure_time and ride.scheduled_departure_time < 1_000_000_000)
                        else int(time.time())
                    )
                )
                done_ids = set(completed_stop_ids or ())
                updated_stops = []
                for s in ride.stops:
                    if s.stop_id in done_ids and s.status != StopStatus.COMPLETED:
                        updated_stops.append(s.model_copy(update={
                            "status": StopStatus.COMPLETED,
                            "actual_arrival_time": now,
                        }))
                    else:
                        updated_stops.append(s)
                active_occ = sum(s.passenger_delta for s in updated_stops if s.status == StopStatus.COMPLETED)
                active_occ = max(0, active_occ)
                updated_ride = ride.model_copy(update={
                    "stops": tuple(updated_stops),
                    "lifecycle_status": RideStatus.ACTIVE,
                    "active_passenger_count": active_occ,
                    "actual_departure_time": ride.actual_departure_time or now,
                })
                self.storage.save_ride(updated_ride)

        return updated

    def update_vehicle_status(self, vehicle_id: str, is_active: bool) -> Vehicle:
        """Updates the active operational status of an existing vehicle."""
        veh = self.get_vehicle(vehicle_id)
        updated = veh.model_copy(update={"is_active": is_active})
        self.storage.save_vehicle(updated)
        return updated

    def update_vehicle_capacity(self, vehicle_id: str, total_seat_capacity: int) -> Vehicle:
        """Updates the total passenger seat capacity of an existing vehicle."""
        veh = self.get_vehicle(vehicle_id)
        updated = veh.model_copy(update={"total_seat_capacity": max(0, total_seat_capacity)})
        self.storage.save_vehicle(updated)
        return updated

    def sync_ride_capacity(
        self,
        ride_id: str,
        available_seats: int,
        version: Optional[int] = None,
        idempotency_token: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Reconciles authoritative Firestore available seats with Pool Engine state.
        Updates vehicle seat capacity and ride operational status if full.
        Enforces monotonic version validation and idempotency tokens to prevent
        outdated or duplicated synchronization requests from overwriting newer capacity.
        """
        if idempotency_token and idempotency_token in self._capacity_idempotency_tokens:
            return {
                "synced": True,
                "ride_id": ride_id,
                "available_seats": available_seats,
                "idempotent_replay": True,
                "message": "Capacity update already processed (idempotent hit)",
            }

        last_ver = self._capacity_sync_versions.get(ride_id, 0)
        if version is not None and version < last_ver:
            return {
                "synced": False,
                "rejected": True,
                "reason": "stale_version",
                "current_version": last_ver,
                "received_version": version,
                "message": f"Sync rejected: received version {version} is older than current version {last_ver}",
            }

        ride = self.storage.get_ride(ride_id)
        if ride is not None:
            if ride.vehicle_id:
                veh = self.storage.get_vehicle(ride.vehicle_id)
                if veh is not None:
                    updated_veh = veh.model_copy(update={"total_seat_capacity": max(0, available_seats)})
                    self.storage.save_vehicle(updated_veh)
            new_status = RideStatus.FULL if available_seats == 0 and ride.status == RideStatus.ACTIVE else ride.status
            updated_ride = ride.model_copy(update={"status": new_status})
            self.storage.save_ride(updated_ride)

            if version is not None:
                self._capacity_sync_versions[ride_id] = version
            if idempotency_token:
                self._capacity_idempotency_tokens.add(idempotency_token)

            return {
                "synced": True,
                "ride_id": ride_id,
                "available_seats": available_seats,
                "status": new_status.value,
                "version": version or last_ver,
            }

        veh = self.storage.get_vehicle(ride_id)
        if veh is not None:
            updated_veh = veh.model_copy(update={"total_seat_capacity": max(0, available_seats)})
            self.storage.save_vehicle(updated_veh)

            if version is not None:
                self._capacity_sync_versions[ride_id] = version
            if idempotency_token:
                self._capacity_idempotency_tokens.add(idempotency_token)

            return {
                "synced": True,
                "vehicle_id": ride_id,
                "total_seat_capacity": max(0, available_seats),
                "version": version or last_ver,
            }

        # Neither ride nor vehicle in storage yet: buffer capacity for when it is registered or queried
        if version is not None:
            self._capacity_sync_versions[ride_id] = version
        if idempotency_token:
            self._capacity_idempotency_tokens.add(idempotency_token)
        self._pending_capacities[ride_id] = {
            "available_seats": max(0, available_seats),
            "version": version or last_ver,
            "idempotency_token": idempotency_token,
        }
        return {
            "synced": True,
            "buffered": True,
            "ride_id": ride_id,
            "available_seats": max(0, available_seats),
            "version": version or last_ver,
            "message": f"Capacity update buffered for uninitialized ride/vehicle '{ride_id}'",
        }

    def reconcile_ride(self, input_data: ReconcileRideInput) -> dict[str, Any]:
        """
        Authoritatively reconciles a ride's available seats from Firestore.
        Ensures monotonic version protection and idempotency.
        """
        return self.sync_ride_capacity(
            ride_id=input_data.ride_id,
            available_seats=input_data.available_seats,
            version=input_data.version,
            idempotency_token=input_data.idempotency_token,
        )

    def run_dispatch(
        self,
        input_data: DispatchRunInput,
        header_idempotency_key: Optional[str] = None,
    ) -> DispatchCycleResponse:
        """
        Executes a bounded batch optimization cycle via DispatchOrchestrator.
        Enforces idempotency token consistency and returns structured match results.
        """
        if input_data.authoritative_capacities:
            for cap in input_data.authoritative_capacities:
                self.reconcile_ride(cap)
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
            region_id=input_data.region_id,
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

    # -------------------------------------------------------------------------
    # Marketplace Proposals & Mutual Acceptance Protocol
    # -------------------------------------------------------------------------

    def create_proposal(
        self,
        input_data: CreateProposalInput,
        current_time: Optional[int] = None,
    ) -> ProposalDTO:
        """
        Creates an unconfirmed match proposal and acquires an atomic temporary seat hold.
        Does not confirm the ride; confirmation requires bilateral acceptance.
        """
        req = self.storage.get_request(input_data.request_id)
        if req is None:
            raise ResourceNotFoundError(f"RideRequest '{input_data.request_id}' not found")
        if req.status in (RequestStatus.CANCELLED, RequestStatus.EXPIRED):
            raise LifecycleError(
                f"Cannot create proposal for request in '{req.status.value}' status",
                code="REQUEST_NOT_ACTIVE",
                status_code=422,
            )

        ride = self.storage.get_ride(input_data.ride_id)
        if ride is None:
            raise ResourceNotFoundError(f"Ride '{input_data.ride_id}' not found")
        if ride.lifecycle_status in (RideStatus.CANCELLED, RideStatus.COMPLETED):
            raise LifecycleError(
                f"Cannot create proposal for ride in '{ride.lifecycle_status.value}' status",
                code="RIDE_NOT_ACTIVE",
                status_code=422,
            )

        eff_time = (
            current_time
            if current_time is not None
            else (ride.scheduled_departure_time if ride.lifecycle_status != RideStatus.ACTIVE else int(time.time()))
        )
        idemp_token = input_data.idempotency_token or f"prop-{uuid.uuid4().hex[:12]}"
        join_id = f"prop-{uuid.uuid4().hex[:12]}"
        policy = self.orchestrator.policy_provider.get_policy()

        # For host rides, verify corridor compatibility and ahead-of-vehicle constraints
        if ride.is_host_ride:
            from engine.routing.corridor import evaluate_host_corridor_match
            veh = self.storage.get_vehicle(ride.vehicle_id)
            if veh is not None:
                corridor_res = evaluate_host_corridor_match(
                    ride=ride,
                    request=req,
                    vehicle=veh,
                    router=self.router,
                    policy=policy,
                    current_time=eff_time,
                )
                if not corridor_res.is_eligible:
                    raise ConflictError(
                        f"Proposal creation rejected: {corridor_res.rejection_reason or 'INCOMPATIBLE_CORRIDOR'}",
                        code=corridor_res.rejection_reason or "INCOMPATIBLE_CORRIDOR",
                        status_code=409,
                    )

        res = submit_join_request(
            request=req,
            ride_id=ride.ride_id,
            storage=self.storage,
            policy=policy,
            current_time=eff_time,
            idempotency_token=idemp_token,
            join_request_id=join_id,
        )

        if not res.success:
            if res.rejection_reason in ("REQUEST_CANCELLED", "REQUEST_EXPIRED"):
                raise LifecycleError(
                    f"Proposal creation rejected: {res.rejection_reason}",
                    code=res.rejection_reason,
                    status_code=409,
                )
            raise ConflictError(
                f"Proposal creation rejected: {res.rejection_reason or 'SEAT_UNAVAILABLE'}",
                code=res.rejection_reason or "SEAT_UNAVAILABLE",
                status_code=409,
            )

        jr = res.join_request
        return ProposalDTO(
            proposal_id=jr.join_request_id,
            ride_id=jr.ride_id,
            request_id=jr.request_id,
            host_id=ride.driver_id,
            traveller_id=jr.user_id,
            seat_count=jr.seat_count,
            submitted_at=jr.submitted_at,
            expires_at=jr.expires_at,
            status="PENDING",
            host_accepted=jr.host_accepted,
            traveller_accepted=jr.traveller_accepted,
            is_confirmed=False,
            pickup_location=req.pickup_location,
            dropoff_location=req.dropoff_location,
            is_masked=False,
        )

    def get_proposal(
        self,
        proposal_id: str,
        auth_context: Optional[AuthContext] = None,
        caller_user_id: Optional[str] = None,
    ) -> ProposalDTO:
        """
        Retrieves proposal details. Masking coordinates and hiding personal details
        for unauthorized non-participants.
        """
        jr = self.storage.get_join_request(proposal_id)
        if jr is None:
            raise ResourceNotFoundError(f"Proposal '{proposal_id}' was not found")

        ride = self.storage.get_ride(jr.ride_id)
        req = self.storage.get_request(jr.request_id)
        if ride is None or req is None:
            raise ResourceNotFoundError(f"Associated entities for proposal '{proposal_id}' not found")

        eff_user = auth_context.subject_id if (auth_context and auth_context.authenticated) else caller_user_id
        is_host = bool(eff_user and eff_user == ride.driver_id)
        is_traveller = bool(eff_user and eff_user == jr.user_id)
        is_admin = bool(auth_context and auth_context.authenticated and "admin" in auth_context.roles)
        is_participant = is_host or is_traveller or is_admin

        # Strict authorization check when caller context is present
        if auth_context and auth_context.authenticated and not is_participant:
            raise AuthorizationForbiddenError(
                f"Caller '{eff_user}' is not authorized to inspect proposal '{proposal_id}'"
            )

        # Status computation
        if jr.status == JoinStatus.APPROVED:
            status_str = "CONFIRMED"
        elif jr.status == JoinStatus.REJECTED:
            status_str = "DECLINED"
        elif jr.status == JoinStatus.EXPIRED:
            status_str = "EXPIRED"
        elif jr.host_accepted and not jr.traveller_accepted:
            status_str = "PENDING_TRAVELLER_ACCEPTANCE"
        elif jr.traveller_accepted and not jr.host_accepted:
            status_str = "PENDING_HOST_ACCEPTANCE"
        else:
            status_str = "PENDING"

        if is_participant:
            return ProposalDTO(
                proposal_id=jr.join_request_id,
                ride_id=jr.ride_id,
                request_id=jr.request_id,
                host_id=ride.driver_id,
                traveller_id=jr.user_id,
                seat_count=jr.seat_count,
                submitted_at=jr.submitted_at,
                expires_at=jr.expires_at,
                status=status_str,
                host_accepted=jr.host_accepted,
                traveller_accepted=jr.traveller_accepted,
                is_confirmed=(jr.status == JoinStatus.APPROVED),
                pickup_location=req.pickup_location,
                dropoff_location=req.dropoff_location,
                is_masked=False,
            )

        # Unauthenticated / non-participant view: mask coordinates (~1.1 km) and redact personal user identifiers
        plat, plon = mask_coordinate(req.pickup_location.latitude, req.pickup_location.longitude, precision=2)
        dlat, dlon = mask_coordinate(req.dropoff_location.latitude, req.dropoff_location.longitude, precision=2)
        return ProposalDTO(
            proposal_id=jr.join_request_id,
            ride_id=jr.ride_id,
            request_id=None,
            host_id=None,
            traveller_id=None,
            seat_count=jr.seat_count,
            submitted_at=jr.submitted_at,
            expires_at=jr.expires_at,
            status=status_str,
            host_accepted=jr.host_accepted,
            traveller_accepted=jr.traveller_accepted,
            is_confirmed=(jr.status == JoinStatus.APPROVED),
            pickup_location=GeoCoordinate(latitude=plat, longitude=plon),
            dropoff_location=GeoCoordinate(latitude=dlat, longitude=dlon),
            is_masked=True,
        )

    def accept_proposal(
        self,
        proposal_id: str,
        decision: ProposalDecisionInput,
        auth_context: Optional[AuthContext] = None,
        current_time: Optional[int] = None,
    ) -> ProposalDecisionResult:
        """
        Records an acceptance from a participant (host or traveller).
        Executes atomic double-revalidation and confirmed seat allocation only when
        both participants have explicitly accepted.
        """
        jr = self.storage.get_join_request(proposal_id)
        if jr is None:
            raise ResourceNotFoundError(f"Proposal '{proposal_id}' was not found")

        ride = self.storage.get_ride(jr.ride_id)
        req = self.storage.get_request(jr.request_id)
        if ride is None or req is None:
            raise ResourceNotFoundError(f"Associated entities for proposal '{proposal_id}' not found")

        now = (
            current_time
            if current_time is not None
            else (
                decision.current_time
                if decision.current_time is not None
                else (
                    ride.scheduled_departure_time
                    if (ride.scheduled_departure_time and ride.lifecycle_status != RideStatus.ACTIVE and jr.submitted_at < 1_000_000_000)
                    else (jr.submitted_at if jr.submitted_at < 1_000_000_000 else int(time.time()))
                )
            )
        )

        # Expiry check: exact boundary
        if now > jr.expires_at or jr.status == JoinStatus.EXPIRED:
            if jr.status == JoinStatus.PENDING:
                self.storage.release_seats_atomic(
                    ride_id=jr.ride_id,
                    join_request_id=jr.join_request_id,
                    reason="EXPIRED",
                )
                jr = jr.model_copy(update={"status": JoinStatus.EXPIRED})
                self.storage.save_join_request(jr)
            raise LifecycleError(
                f"Proposal '{proposal_id}' has expired and cannot be accepted",
                code="PROPOSAL_EXPIRED",
                status_code=410,
            )

        if jr.status == JoinStatus.REJECTED:
            raise LifecycleError(
                f"Proposal '{proposal_id}' was declined and cannot be accepted",
                code="PROPOSAL_DECLINED",
                status_code=409,
            )

        # Idempotent replay: already approved
        if jr.status == JoinStatus.APPROVED:
            return ProposalDecisionResult(
                proposal_id=jr.join_request_id,
                status="CONFIRMED",
                host_accepted=True,
                traveller_accepted=True,
                is_confirmed=True,
                ride_id=jr.ride_id,
                message="Proposal is already confirmed",
            )

        # Identify participant
        caller_id = auth_context.subject_id if (auth_context and auth_context.authenticated) else decision.user_id
        is_admin = bool(auth_context and auth_context.authenticated and "admin" in auth_context.roles)

        is_host = False
        is_traveller = False

        if is_admin:
            role_hint = (decision.role or "").lower()
            if role_hint == "host" or caller_id == ride.driver_id:
                is_host = True
            elif role_hint in ("traveller", "traveler", "rider") or caller_id == jr.user_id:
                is_traveller = True
            else:
                raise ValidationError("Admin decision must specify role ('host' or 'traveller') or matching user_id")
        else:
            if auth_context and auth_context.authenticated and decision.user_id and decision.user_id != auth_context.subject_id:
                raise AuthorizationForbiddenError(
                    f"Caller '{auth_context.subject_id}' cannot act on behalf of user '{decision.user_id}'"
                )
            if caller_id:
                if caller_id == ride.driver_id:
                    if decision.role and decision.role.lower() not in ("host", "driver"):
                        raise AuthorizationForbiddenError("Host participant cannot accept on behalf of traveller")
                    is_host = True
                elif caller_id == jr.user_id:
                    if decision.role and decision.role.lower() not in ("traveller", "traveler", "rider"):
                        raise AuthorizationForbiddenError("Traveller participant cannot accept on behalf of host")
                    is_traveller = True
                else:
                    raise AuthorizationForbiddenError(
                        f"User '{caller_id}' is not a participant in proposal '{proposal_id}'"
                    )
            elif decision.role:
                role_hint = decision.role.lower()
                if role_hint == "host":
                    is_host = True
                elif role_hint in ("traveller", "traveler", "rider"):
                    is_traveller = True
                else:
                    raise ValidationError(f"Invalid role '{decision.role}'; must be 'host' or 'traveller'")
            else:
                raise ValidationError("Caller identity required: provide user_id or role ('host' or 'traveller')")

        # Atomically record acceptance
        acceptance = self.storage.record_proposal_acceptance(
            join_request_id=proposal_id,
            is_host=is_host,
            is_traveller=is_traveller,
        )
        if acceptance is None:
            raise ResourceNotFoundError(f"Proposal '{proposal_id}' was not found")

        new_host_accepted, new_traveller_accepted = acceptance

        # Case A: Only one participant has accepted so far
        if not (new_host_accepted and new_traveller_accepted):
            status_str = "PENDING_TRAVELLER_ACCEPTANCE" if new_host_accepted else "PENDING_HOST_ACCEPTANCE"
            return ProposalDecisionResult(
                proposal_id=jr.join_request_id,
                status=status_str,
                host_accepted=new_host_accepted,
                traveller_accepted=new_traveller_accepted,
                is_confirmed=False,
                ride_id=jr.ride_id,
                expires_at=jr.expires_at,
                message="Accepted. Waiting for other participant to accept.",
            )

        # Case B: Both participants have accepted -> execute atomic confirmation
        commit_token = decision.idempotency_token or jr.idempotency_token
        confirm_res = confirm_join_request(
            join_request_id=jr.join_request_id,
            storage=self.storage,
            policy_provider=self.orchestrator.policy_provider,
            router=self.router,
            current_time=now,
            idempotency_token=commit_token,
        )

        if confirm_res.success and confirm_res.ride is not None:
            return ProposalDecisionResult(
                proposal_id=jr.join_request_id,
                status="CONFIRMED",
                host_accepted=True,
                traveller_accepted=True,
                is_confirmed=True,
                ride_id=confirm_res.ride.ride_id,
                message="Proposal successfully confirmed by both participants.",
            )

        # If already confirmed (e.g. concurrent race where another thread completed confirmation)
        latest_jr = self.storage.get_join_request(proposal_id)
        if latest_jr is not None and latest_jr.status == JoinStatus.APPROVED:
            return ProposalDecisionResult(
                proposal_id=jr.join_request_id,
                status="CONFIRMED",
                host_accepted=True,
                traveller_accepted=True,
                is_confirmed=True,
                ride_id=jr.ride_id,
                message="Proposal successfully confirmed by both participants.",
            )

        rej = confirm_res.rejection_reason or "CONFIRMATION_FAILED"
        if rej == "OVER_CAPACITY":
            raise ConflictError(
                "Vehicle seat is no longer available (over capacity)",
                code="SEAT_UNAVAILABLE",
                status_code=409,
            )
        elif rej in ("REQUEST_CANCELLED", "REQUEST_EXPIRED"):
            raise LifecycleError(f"Request was cancelled or expired: {rej}", code=rej, status_code=409)
        elif rej == "EXPIRED":
            raise LifecycleError(
                "Proposal expired during confirmation attempt",
                code="PROPOSAL_EXPIRED",
                status_code=410,
            )
        else:
            raise ConflictError(f"Confirmation failed: {rej}", code=rej, status_code=409)

    def decline_proposal(
        self,
        proposal_id: str,
        decision: ProposalDecisionInput,
        auth_context: Optional[AuthContext] = None,
        current_time: Optional[int] = None,
    ) -> ProposalDecisionResult:
        """
        Explicitly declines a match proposal and immediately releases its temporary seat hold.
        """
        jr = self.storage.get_join_request(proposal_id)
        if jr is None:
            raise ResourceNotFoundError(f"Proposal '{proposal_id}' was not found")

        ride = self.storage.get_ride(jr.ride_id)
        req = self.storage.get_request(jr.request_id)
        if ride is None or req is None:
            raise ResourceNotFoundError(f"Associated entities for proposal '{proposal_id}' not found")

        caller_id = auth_context.subject_id if (auth_context and auth_context.authenticated) else decision.user_id
        is_admin = bool(auth_context and auth_context.authenticated and "admin" in auth_context.roles)

        if not is_admin:
            if auth_context and auth_context.authenticated and decision.user_id and decision.user_id != auth_context.subject_id:
                raise AuthorizationForbiddenError(
                    f"Caller '{auth_context.subject_id}' cannot act on behalf of user '{decision.user_id}'"
                )
            if caller_id:
                if caller_id not in (ride.driver_id, jr.user_id):
                    raise AuthorizationForbiddenError(
                        f"User '{caller_id}' is not a participant in proposal '{proposal_id}'"
                    )
            elif decision.role:
                role_hint = decision.role.lower()
                if role_hint not in ("host", "traveller", "traveler", "rider"):
                    raise ValidationError(f"Invalid role '{decision.role}'; must be 'host' or 'traveller'")
            else:
                raise ValidationError("Caller identity required: provide user_id or role ('host' or 'traveller')")

        if jr.status == JoinStatus.APPROVED:
            raise LifecycleError(
                "Cannot decline proposal: already confirmed. Use request cancellation instead.",
                code="ALREADY_CONFIRMED",
                status_code=422,
            )

        if jr.status == JoinStatus.REJECTED:
            return ProposalDecisionResult(
                proposal_id=jr.join_request_id,
                status="DECLINED",
                host_accepted=jr.host_accepted,
                traveller_accepted=jr.traveller_accepted,
                is_confirmed=False,
                ride_id=jr.ride_id,
                message="Proposal was already declined.",
            )

        reason = decision.reason or "DECLINED_BY_PARTICIPANT"
        res = reject_join_request(proposal_id, self.storage, reason=reason)

        return ProposalDecisionResult(
            proposal_id=res.join_request.join_request_id,
            status="DECLINED",
            host_accepted=res.join_request.host_accepted,
            traveller_accepted=res.join_request.traveller_accepted,
            is_confirmed=False,
            ride_id=res.join_request.ride_id,
            message="Proposal declined and temporary seat hold released.",
        )

    def sweep_expired_proposals(self, current_time: Optional[int] = None) -> list[str]:
        """
        Sweeps and cleans up expired proposals and holds whose expires_at timestamp has passed.
        """
        eff_time = current_time if current_time is not None else int(time.time())
        return expire_stale_holds(self.storage, eff_time)

    def register_host_ride(
        self,
        input_data: CreateHostRideInput,
    ) -> HostRideDTO:
        """
        Registers a private car host's planned commute or fixed-corridor journey.
        Calculates direct road travel time and distance, creates or registers the host vehicle,
        and sets mandatory origin and destination route waypoints.
        """
        orig_c = Coordinate(latitude=input_data.origin.latitude, longitude=input_data.origin.longitude)
        dest_c = Coordinate(latitude=input_data.destination.latitude, longitude=input_data.destination.longitude)
        try:
            self.router.validate_coordinate(orig_c, "Host origin")
            self.router.validate_coordinate(dest_c, "Host destination")
            if hasattr(self.router, "find_region_for_coordinate"):
                reg_orig = self.router.find_region_for_coordinate(orig_c)
                reg_dest = self.router.find_region_for_coordinate(dest_c)
                if input_data.region_id is not None:
                    if reg_orig is None or reg_orig.region_id != input_data.region_id:
                        raise OutOfRegionServiceError(
                            f"Host origin coordinate ({orig_c.latitude}, {orig_c.longitude}) "
                            f"does not match declared region '{input_data.region_id}'"
                        )
                    if reg_dest is None or reg_dest.region_id != input_data.region_id:
                        raise OutOfRegionServiceError(
                            f"Host destination coordinate ({dest_c.latitude}, {dest_c.longitude}) "
                            f"does not match declared region '{input_data.region_id}'"
                        )
                if reg_orig is not None and reg_dest is not None and reg_orig.region_id != reg_dest.region_id:
                    raise OutOfRegionServiceError(
                        f"Cross-region journey from '{reg_orig.region_id}' to '{reg_dest.region_id}' is unsupported"
                    )
        except OutOfRegionError as err:
            self.telemetry.record_routing_failure("router", "out_of_region")
            raise OutOfRegionServiceError(
                f"Requested host ride coordinates fall outside operational service region: {err}"
            ) from err

        try:
            direct_leg = self.router.get_direct_leg(orig_c, dest_c)
        except OutOfRegionError as err:
            self.telemetry.record_routing_failure("router", "out_of_region")
            raise OutOfRegionServiceError(
                f"Requested host ride coordinates fall outside operational service region: {err}"
            ) from err
        except (RouteLookupError, RoutingProviderError) as err:
            raise ValidationError(f"Unable to calculate road route between host origin and destination: {err}") from err
        if direct_leg is None:
            raise ValidationError("Unable to calculate road route between host origin and destination")
        direct_dist, direct_dur = direct_leg

        veh_id = input_data.vehicle_id or f"veh-{input_data.driver_id}"
        vehicle = self.storage.get_vehicle(veh_id)
        if vehicle is None:
            vehicle = Vehicle(
                vehicle_id=veh_id,
                driver_id=input_data.driver_id,
                total_seat_capacity=input_data.available_seats,
                current_location=input_data.origin,
                is_active=True,
            )
            self.storage.save_vehicle(vehicle)
        else:
            vehicle = vehicle.model_copy(update={
                "current_location": input_data.origin,
                "total_seat_capacity": max(vehicle.total_seat_capacity, input_data.available_seats),
                "is_active": True,
            })
            self.storage.save_vehicle(vehicle)

        ride_id = input_data.ride_id or f"ride-host-{int(time.time())}-{input_data.driver_id[:8]}"
        dep_time = input_data.scheduled_departure_time
        dest_arr_time = dep_time + direct_dur
        latest_arr_time = dest_arr_time + input_data.max_detour_seconds

        origin_stop = RouteStop(
            stop_id=f"stop-origin-{ride_id}",
            ride_id=ride_id,
            request_id=f"host:{input_data.driver_id}",
            stop_type=StopType.WAYPOINT,
            location=input_data.origin,
            passenger_delta=0,
            scheduled_arrival_time=dep_time,
            promised_window_start=dep_time,
            promised_window_end=dep_time,
            status=StopStatus.SCHEDULED,
        )
        dest_stop = RouteStop(
            stop_id=f"stop-dest-{ride_id}",
            ride_id=ride_id,
            request_id=f"host:{input_data.driver_id}",
            stop_type=StopType.WAYPOINT,
            location=input_data.destination,
            passenger_delta=0,
            scheduled_arrival_time=dest_arr_time,
            promised_window_start=dest_arr_time,
            promised_window_end=latest_arr_time,
            status=StopStatus.SCHEDULED,
        )

        ride = Ride(
            ride_id=ride_id,
            vehicle_id=veh_id,
            driver_id=input_data.driver_id,
            lifecycle_status=RideStatus.SCHEDULED,
            stops=(origin_stop, dest_stop),
            scheduled_departure_time=dep_time,
            active_passenger_count=0,
            total_vmt_meters=direct_dist,
            version=1,
            origin_location=input_data.origin,
            destination_location=input_data.destination,
            max_detour_seconds=input_data.max_detour_seconds,
            direct_duration_seconds=direct_dur,
            direct_distance_meters=direct_dist,
        )
        self.storage.save_ride(ride)

        return HostRideDTO(
            ride_id=ride.ride_id,
            driver_id=ride.driver_id,
            vehicle_id=ride.vehicle_id,
            origin=input_data.origin,
            destination=input_data.destination,
            scheduled_departure_time=ride.scheduled_departure_time,
            available_seats=input_data.available_seats,
            max_detour_seconds=input_data.max_detour_seconds,
            direct_duration_seconds=direct_dur,
            direct_distance_meters=direct_dist,
            status=ride.lifecycle_status.value,
            stops=list(ride.stops),
        )

    def get_host_ride(
        self,
        ride_id: str,
        auth_context: Optional[AuthContext] = None,
    ) -> HostRideDTO:
        ride = self.storage.get_ride(ride_id)
        if ride is None:
            raise ResourceNotFoundError(f"Host ride '{ride_id}' not found")
        if not ride.is_host_ride or ride.origin_location is None or ride.destination_location is None:
            raise ValidationError(f"Ride '{ride_id}' is not a private host ride")

        if auth_context and auth_context.authenticated and "admin" not in auth_context.roles:
            if ride.driver_id != auth_context.subject_id:
                raise AuthorizationForbiddenError(
                    f"Caller '{auth_context.subject_id}' is not authorized to inspect host ride '{ride_id}'"
                )

        vehicle = self.storage.get_vehicle(ride.vehicle_id)
        seats = vehicle.total_seat_capacity if vehicle else 3

        return HostRideDTO(
            ride_id=ride.ride_id,
            driver_id=ride.driver_id,
            vehicle_id=ride.vehicle_id,
            origin=ride.origin_location,
            destination=ride.destination_location,
            scheduled_departure_time=ride.scheduled_departure_time,
            available_seats=seats,
            max_detour_seconds=ride.max_detour_seconds or 0,
            direct_duration_seconds=ride.direct_duration_seconds or 0,
            direct_distance_meters=ride.direct_distance_meters or 0,
            status=ride.lifecycle_status.value,
            stops=list(ride.stops),
        )

    def match_host_ride(
        self,
        ride_id: str,
        request_id: Optional[str] = None,
        current_time: Optional[int] = None,
        auth_context: Optional[AuthContext] = None,
    ) -> list[ProposalDTO]:
        """
        Evaluates pending traveller requests against a host's corridor,
        generating proposals with atomic temporary seat holds for compatible routes.
        """
        ride = self.storage.get_ride(ride_id)
        if ride is None:
            raise ResourceNotFoundError(f"Host ride '{ride_id}' not found")
        if not ride.is_host_ride:
            raise ValidationError(f"Ride '{ride_id}' is not configured as a host corridor ride")

        if auth_context and auth_context.authenticated and "admin" not in auth_context.roles:
            if ride.driver_id != auth_context.subject_id:
                raise AuthorizationForbiddenError(
                    f"Caller '{auth_context.subject_id}' is not authorized to match host ride '{ride_id}'"
                )

        vehicle = self.storage.get_vehicle(ride.vehicle_id)
        if vehicle is None:
            raise ResourceNotFoundError(f"Vehicle '{ride.vehicle_id}' not found")

        requests_to_evaluate: list[RideRequest] = []
        if request_id:
            req = self.storage.get_request(request_id)
            if req is None:
                raise ResourceNotFoundError(f"Request '{request_id}' not found")
            if req.status != RequestStatus.PENDING:
                raise ValidationError(f"Request '{request_id}' is not in PENDING status (current: {req.status.value})")
            requests_to_evaluate.append(req)
        else:
            pending = self.storage.get_pending_requests()
            if hasattr(self.router, "find_region_for_coordinate"):
                host_loc = ride.origin_location or vehicle.current_location
                host_reg = self.router.find_region_for_coordinate(
                    Coordinate(host_loc.latitude, host_loc.longitude)
                )
                if host_reg is not None:
                    pending = [
                        r
                        for r in pending
                        if (
                            self.router.find_region_for_coordinate(
                                Coordinate(r.pickup_location.latitude, r.pickup_location.longitude)
                            )
                            is not None
                            and self.router.find_region_for_coordinate(
                                Coordinate(r.pickup_location.latitude, r.pickup_location.longitude)
                            ).region_id
                            == host_reg.region_id
                        )
                    ]
            requests_to_evaluate.extend(pending)

        created_proposals: list[ProposalDTO] = []
        now = (
            current_time
            if current_time is not None
            else (ride.scheduled_departure_time if ride.lifecycle_status != RideStatus.ACTIVE else int(time.time()))
        )

        for req in requests_to_evaluate:
            try:
                proposal = self.create_proposal(
                    CreateProposalInput(
                        ride_id=ride.ride_id,
                        request_id=req.request_id,
                        seat_count=req.seat_count,
                    ),
                    current_time=now,
                )
                created_proposals.append(proposal)
            except (ConflictError, LifecycleError):
                # Incompatible corridor or seat hold unavailable
                continue

        return created_proposals

    def evaluate_en_route_join(
        self,
        ride_id: str,
        input_data: EnRouteJoinInput,
        current_time: Optional[int] = None,
        auth_context: Optional[AuthContext] = None,
    ) -> EnRouteJoinResult:
        """
        Evaluates an en-route join request against an active in-transit ride.
        Applies the Ahead-of-Vehicle Spatial Gate, capacity conservation, and deadline revalidation.
        If eligible, creates an unconfirmed proposal with a temporary seat hold.
        """
        from engine.routing.corridor import evaluate_host_corridor_match

        ride = self.storage.get_ride(ride_id)
        if ride is None:
            raise ResourceNotFoundError(f"Ride '{ride_id}' not found")
        vehicle = self.storage.get_vehicle(ride.vehicle_id)
        if vehicle is None:
            raise ResourceNotFoundError(f"Vehicle '{ride.vehicle_id}' not found")
        req = self.storage.get_request(input_data.request_id)
        if req is None:
            raise ResourceNotFoundError(f"Request '{input_data.request_id}' not found")

        if auth_context and auth_context.authenticated and "admin" not in auth_context.roles:
            if req.user_id != auth_context.subject_id:
                raise AuthorizationForbiddenError(
                    f"Caller '{auth_context.subject_id}' is not authorized to join using request '{input_data.request_id}' belonging to '{req.user_id}'"
                )
        if req.status != RequestStatus.PENDING:
            return EnRouteJoinResult(
                eligible=False,
                rejection_reason=f"REQUEST_{req.status.value}",
                message=f"Request is not PENDING (current status: {req.status.value})",
            )

        now = (
            input_data.current_time
            or current_time
            or (
                (ride.actual_departure_time or ride.scheduled_departure_time)
                if (ride.scheduled_departure_time and ride.scheduled_departure_time < 1_000_000_000)
                else (ride.scheduled_departure_time if ride.lifecycle_status != RideStatus.ACTIVE else int(time.time()))
            )
        )
        policy = self.orchestrator.policy_provider.get_policy()

        # Run corridor match evaluation
        match_res = evaluate_host_corridor_match(
            ride=ride,
            request=req,
            vehicle=vehicle,
            router=self.router,
            policy=policy,
            current_time=now,
        )

        if not match_res.is_eligible:
            return EnRouteJoinResult(
                eligible=False,
                rejection_reason=match_res.rejection_reason,
                message=f"Request ineligible for en-route join: {match_res.rejection_reason}",
            )

        # Eligible: create unconfirmed proposal with atomic seat hold
        try:
            proposal = self.create_proposal(
                CreateProposalInput(
                    ride_id=ride.ride_id,
                    request_id=req.request_id,
                    seat_count=req.seat_count,
                ),
                current_time=now,
            )
            return EnRouteJoinResult(
                eligible=True,
                rejection_reason=None,
                proposal=proposal,
                estimated_pickup_time=match_res.estimated_pickup_time,
                estimated_dropoff_time=match_res.estimated_dropoff_time,
                host_detour_seconds=match_res.host_detour_seconds,
                message="En-route join request eligible. Proposal created; requires bilateral acceptance.",
            )
        except (ConflictError, LifecycleError) as err:
            err_code = getattr(err, "code", "PROPOSAL_CREATION_FAILED")
            return EnRouteJoinResult(
                eligible=False,
                rejection_reason=err_code,
                message=f"Proposal creation failed: {str(err)}",
            )


def build_service_from_env(env: Optional[Mapping[str, str]] = None) -> PoolEngineService:
    """
    Constructs a production-ready PoolEngineService from environment variables or mapping:
    - Storage: PostgresRideStorage if DATABASE_URL is set, else InMemoryRideStorage
    - Routing: OsrmRoutingAdapter if OSRM_BASE_URL is set, else MockRoutingProvider
    - Spatial: H3SpatialIndexAdapter
    - Policy: DefaultPolicyProvider
    - Telemetry: StructuredLoggerTelemetry
    """
    import os
    from engine.adapters.default_policy import DefaultPolicyProvider
    from engine.adapters.h3_spatial import H3SpatialIndexAdapter
    from engine.service.config import ServiceConfig

    source = os.environ if env is None else env
    db_url = source.get("DATABASE_URL")
    require_persistent = (
        source.get("REQUIRE_PERSISTENT_STORAGE", "").lower().strip() in ("true", "1", "yes")
    )
    if require_persistent and not db_url:
        raise ValueError(
            "Persistent storage is required (REQUIRE_PERSISTENT_STORAGE=true), but DATABASE_URL is not set."
        )

    if db_url:
        from engine.adapters.postgres_storage import PostgresRideStorage

        storage: RideStorageProvider = PostgresRideStorage(dsn=db_url)
    else:
        from engine.adapters.in_memory_storage import InMemoryRideStorage

        storage = InMemoryRideStorage()

    cfg = ServiceConfig.from_env(source)
    is_multi_region = bool(
        cfg.regions
        and ("ROUTING_REGIONS" in source or "ROUTING_REGIONS_FILE" in source or len(cfg.regions) > 1)
    )

    osrm_url = source.get("OSRM_BASE_URL")
    require_real_routing = (
        source.get("REQUIRE_REAL_ROUTING", "").lower().strip() in ("true", "1", "yes")
    )
    if require_real_routing and not is_multi_region and not osrm_url:
        raise ValueError(
            "Real road network routing is required (REQUIRE_REAL_ROUTING=true), but OSRM_BASE_URL is not set."
        )

    timeout_raw = source.get("ROUTING_TIMEOUT_SECONDS")
    timeout_seconds = float(timeout_raw) if timeout_raw else 0.500
    if is_multi_region:
        from engine.adapters.regional_router import RegionalRoutingRouter

        regional_router = RegionalRoutingRouter(regions=cfg.regions)
        router: RoadNetworkRoutingProvider = regional_router
        if require_real_routing:
            for r_id, region_cfg in regional_router.regions.items():
                if region_cfg.provider_type == "osrm":
                    p = regional_router.get_provider(r_id)
                    if not p.check_health():
                        raise RoutingProviderError(
                            f"Real road network routing is required (REQUIRE_REAL_ROUTING=true), "
                            f"but OSRM service at {region_cfg.endpoint_url} for region '{r_id}' is unreachable or unhealthy."
                        )
    elif osrm_url:
        from engine.adapters.osrm_routing import OsrmRoutingAdapter
        from engine.contracts.routing import BoundingBox

        bbox = BoundingBox.from_env(source)
        snap_raw = source.get("ROUTING_MAX_SNAP_DISTANCE_METERS")
        max_snap = float(snap_raw) if snap_raw else 5000.0

        router = OsrmRoutingAdapter(
            base_url=osrm_url,
            timeout_seconds=timeout_seconds,
            bounding_box=bbox,
            max_snap_distance_meters=max_snap,
        )
        if require_real_routing:
            if not router.check_health():
                raise RoutingProviderError(
                    f"Real road network routing is required (REQUIRE_REAL_ROUTING=true), "
                    f"but OSRM service at {osrm_url} is unreachable or unhealthy."
                )
    else:
        from engine.adapters.mock_routing import MockRoutingProvider

        router = MockRoutingProvider()

    spatial = H3SpatialIndexAdapter()
    policy = DefaultPolicyProvider()
    orchestrator = DispatchOrchestrator(
        storage=storage,
        policy_provider=policy,
        routing_provider=router,
        spatial_index=spatial,
    )
    telemetry = StructuredLoggerTelemetry()

    return PoolEngineService(
        storage=storage,
        orchestrator=orchestrator,
        router=router,
        telemetry=telemetry,
    )
