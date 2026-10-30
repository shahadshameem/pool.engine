"""Pure standard-library ASGI 3 application for the pool engine API service."""

import asyncio
import json
import logging
import re
import time
import urllib.parse
from typing import Any, Awaitable, Callable, Optional, Pattern
from pydantic import ValidationError as PydanticValidationError

from engine.contracts.storage import StorageProviderError
from engine.domain.models import GeoCoordinate
from engine.service.config import ServiceConfig
from engine.service.errors import (
    AuthenticationRequiredError,
    AuthorizationForbiddenError,
    ErrorBody,
    ErrorDetail,
    ErrorEnvelope,
    PayloadTooLargeError,
    ResourceNotFoundError,
    ServiceError,
    ValidationError as ApiValidationError,
)
from engine.service.schemas import (
    CancelRideRequestInput,
    CreateHostRideInput,
    CreateProposalInput,
    CreateRideRequestInput,
    DispatchRunInput,
    EnRouteJoinInput,
    ProposalDecisionInput,
    RegisterVehicleInput,
    UpdateLocationInput,
    UpdateVehicleLocationInput,
    UpdateVehicleStatusInput,
    UpdateVehicleCapacityInput,
    SyncRideCapacityInput,
    ReconcileRideInput,
    ReconcileBatchInput,
)
from engine.service.security import (
    AuthContext,
    AuthProvider,
    NoOpAuthProvider,
    sanitize_sensitive_strings,
)
from engine.service.service import PoolEngineService
from engine.service.telemetry import EngineTelemetryProvider

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
HandlerFunc = Callable[[Scope, bytes, dict[str, str], dict[str, str]], Awaitable[tuple[int, dict[str, str], bytes]]]

logger = logging.getLogger("pool_engine.api")

PUBLIC_HEALTH_PATHS = frozenset({
    "/v1/health",
    "/v1/health/liveness",
    "/v1/health/readiness",
})


class AsgiRouter:
    """Lightweight URI pattern router matching HTTP methods and dynamic path parameters."""

    def __init__(self) -> None:
        self.routes: list[tuple[str, Pattern[str], list[str], HandlerFunc]] = []

    def add(self, method: str, pattern_str: str, handler: HandlerFunc) -> None:
        param_names: list[str] = re.findall(r"\{([a-zA-Z0-9_]+)\}", pattern_str)
        regex_pattern = "^" + re.sub(r"\{[a-zA-Z0-9_]+\}", r"([^/]+)", pattern_str) + "$"
        self.routes.append((method.upper(), re.compile(regex_pattern), param_names, handler))

    def match(self, method: str, path: str) -> tuple[Optional[HandlerFunc], dict[str, str], bool]:
        """
        Returns (handler, path_params, method_mismatch).
        If path matches but method differs, method_mismatch is True.
        """
        method_matched = False
        for r_method, r_regex, r_params, r_handler in self.routes:
            match = r_regex.match(path)
            if match:
                if r_method == method.upper():
                    extracted = {name: match.group(i + 1) for i, name in enumerate(r_params)}
                    return r_handler, extracted, False
                else:
                    method_matched = True
        return None, {}, method_matched


def _json_response(status_code: int, payload: Any) -> tuple[int, dict[str, str], bytes]:
    """Helper formatting JSON responses."""
    def _to_jsonable(obj: Any) -> Any:
        if hasattr(obj, "model_dump"):
            return obj.model_dump(mode="json")
        if isinstance(obj, dict):
            return {k: _to_jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)):
            return [_to_jsonable(v) for v in obj]
        return obj

    data = _to_jsonable(payload)
    body = json.dumps(data, indent=2).encode("utf-8")
    headers = {
        "content-type": "application/json",
        "content-length": str(len(body)),
    }
    return status_code, headers, body


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """Helper formatting RFC 7807 error envelopes."""
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code=code,
            message=message,
            details=details or [],
        )
    )
    return _json_response(status_code, envelope)


def create_app(
    service: Optional[PoolEngineService] = None,
    config: Optional[ServiceConfig] = None,
    auth_provider: Optional[AuthProvider] = None,
    telemetry: Optional[EngineTelemetryProvider] = None,
) -> Callable[[Scope, Receive, Send], Awaitable[None]]:
    """
    Creates and returns a standard ASGI 3 application callable.
    If service is omitted, constructs PoolEngineService from environment variables.
    Zero external web framework dependencies (no FastAPI/Starlette).
    """
    from engine.service.security import build_auth_provider_from_env
    from engine.service.service import build_service_from_env

    eff_config = config or ServiceConfig.from_env()
    eff_service = service or build_service_from_env()
    eff_auth = auth_provider or (
        build_auth_provider_from_env(config=eff_config) if eff_config.require_auth else NoOpAuthProvider()
    )
    eff_telemetry = telemetry or eff_service.telemetry
    router = AsgiRouter()

    is_shutting_down = False
    active_request_count = 0

    # Route: GET /v1/health (general health check)
    async def handle_health(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        return _json_response(200, {"status": "ok", "service": "pool-engine"})

    router.add("GET", "/v1/health", handle_health)

    # Route: GET /v1/health/liveness (k8s liveness probe)
    async def handle_liveness(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        return _json_response(200, {"status": "alive", "service": "pool-engine"})

    router.add("GET", "/v1/health/liveness", handle_liveness)

    # Route: GET /v1/health/readiness (k8s readiness probe)
    async def handle_readiness(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        query_string = scope.get("query_string", b"").decode("utf-8")
        query_params = urllib.parse.parse_qs(query_string)
        target_region = query_params.get("region", [None])[0]

        readiness = await asyncio.to_thread(
            eff_service.check_readiness,
            strict_routing=eff_config.strict_routing_readiness,
            require_persistent_storage=eff_config.require_persistent_storage,
            region_id=target_region,
        )
        status_code = 200 if readiness.get("ready") else 503
        return _json_response(status_code, readiness)

    router.add("GET", "/v1/health/readiness", handle_readiness)

    # Route: POST /v1/requests
    async def handle_create_request(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        try:
            raw_data = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:
            return _error_response(400, "VALIDATION_ERROR", f"Malformed JSON payload: {e}")

        # Enforce owner identity for authenticated non-admin users
        auth_ctx: Optional[AuthContext] = scope.get("auth")
        if auth_ctx and auth_ctx.authenticated and "admin" not in auth_ctx.roles:
            body_rider = raw_data.get("user_id") or raw_data.get("rider_id")
            if body_rider and body_rider != auth_ctx.subject_id:
                return _error_response(
                    403,
                    "FORBIDDEN",
                    f"Authenticated user '{auth_ctx.subject_id}' cannot create ride request for user '{body_rider}'",
                )
            raw_data["user_id"] = auth_ctx.subject_id
            raw_data.pop("rider_id", None)
        else:
            if "rider_id" in raw_data and "user_id" not in raw_data:
                raw_data["user_id"] = raw_data.pop("rider_id")

        if "earliest_departure_time" in raw_data and "earliest_pickup_time" not in raw_data:
            raw_data["earliest_pickup_time"] = raw_data.pop("earliest_departure_time")
        if "latest_arrival_time" in raw_data and "latest_dropoff_time" not in raw_data:
            raw_data["latest_dropoff_time"] = raw_data.pop("latest_arrival_time")

        header_idemp = headers.get("idempotency-key")
        body_req_id = raw_data.get("request_id")
        if header_idemp and body_req_id and header_idemp != body_req_id:
            return _error_response(
                400,
                "VALIDATION_ERROR",
                f"Idempotency-Key header ('{header_idemp}') does not match body request_id ('{body_req_id}')",
            )
        if header_idemp and not body_req_id:
            raw_data["request_id"] = header_idemp

        try:
            dto = CreateRideRequestInput.model_validate(raw_data)
        except PydanticValidationError as e:
            details = [
                ErrorDetail(field=".".join(str(loc) for loc in err["loc"]), issue=err["msg"])
                for err in e.errors()
            ]
            return _error_response(400, "VALIDATION_ERROR", "Request input validation failed", details)

        def _execute_create() -> tuple[Any, bool]:
            is_existing = (
                eff_service.storage.get_request(dto.request_id) is not None
                if dto.request_id
                else False
            )
            req = eff_service.create_request(dto)
            return req, is_existing

        req, is_existing = await asyncio.to_thread(_execute_create)
        status_code = 200 if is_existing else 201
        return _json_response(status_code, req)

    router.add("POST", "/v1/requests", handle_create_request)

    # Route: GET /v1/requests/{request_id}
    async def handle_get_request(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        req_id = params["request_id"]
        auth_ctx: Optional[AuthContext] = scope.get("auth")
        req = await asyncio.to_thread(eff_service.get_request, req_id, auth_context=auth_ctx)
        return _json_response(200, req)

    router.add("GET", "/v1/requests/{request_id}", handle_get_request)

    # Route: POST /v1/requests/{request_id}/cancel
    async def handle_cancel_request(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        req_id = params["request_id"]
        reason = None
        body_idemp = None
        if body:
            try:
                raw_data = json.loads(body.decode("utf-8"))
                cancel_dto = CancelRideRequestInput.model_validate(raw_data)
                reason = cancel_dto.reason
                body_idemp = cancel_dto.idempotency_token
            except Exception:
                pass

        header_idemp = headers.get("idempotency-key")
        if header_idemp is not None and body_idemp is not None and header_idemp != body_idemp:
            return _error_response(
                400,
                "VALIDATION_ERROR",
                f"Idempotency-Key header ('{header_idemp}') does not match body idempotency_token ('{body_idemp}')",
            )
        eff_idemp = header_idemp or body_idemp
        auth_ctx: Optional[AuthContext] = scope.get("auth")
        cancelled = await asyncio.to_thread(
            eff_service.cancel_request,
            req_id,
            reason=reason,
            idempotency_token=eff_idemp,
            auth_context=auth_ctx,
        )
        return _json_response(200, cancelled)

    router.add("POST", "/v1/requests/{request_id}/cancel", handle_cancel_request)

    # Route: POST /v1/vehicles
    async def handle_register_vehicle(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        try:
            raw_data = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:
            return _error_response(400, "VALIDATION_ERROR", f"Malformed JSON payload: {e}")

        auth_ctx: Optional[AuthContext] = scope.get("auth")
        if auth_ctx and auth_ctx.authenticated and "admin" not in auth_ctx.roles:
            body_driver = raw_data.get("driver_id")
            if body_driver and body_driver != auth_ctx.subject_id:
                return _error_response(
                    403,
                    "FORBIDDEN",
                    f"Authenticated user '{auth_ctx.subject_id}' cannot register vehicle for driver '{body_driver}'",
                )
            raw_data["driver_id"] = auth_ctx.subject_id

        try:
            dto = RegisterVehicleInput.model_validate(raw_data)
        except PydanticValidationError as e:
            details = [
                ErrorDetail(field=".".join(str(loc) for loc in err["loc"]), issue=err["msg"])
                for err in e.errors()
            ]
            return _error_response(400, "VALIDATION_ERROR", "Vehicle input validation failed", details)

        veh = await asyncio.to_thread(eff_service.register_vehicle, dto)
        return _json_response(201, veh)

    router.add("POST", "/v1/vehicles", handle_register_vehicle)

    # Route: GET /v1/vehicles/{vehicle_id}
    async def handle_get_vehicle(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        veh_id = params["vehicle_id"]
        auth_ctx: Optional[AuthContext] = scope.get("auth")
        def _execute_get_vehicle() -> tuple[Any, Optional[tuple[int, dict[str, str], bytes]]]:
            veh = eff_service.get_vehicle(veh_id)
            if auth_ctx and auth_ctx.authenticated and "admin" not in auth_ctx.roles:
                if veh.driver_id != auth_ctx.subject_id:
                    return None, _error_response(
                        403, "FORBIDDEN", f"Caller is not authorized to inspect vehicle '{veh_id}'"
                    )
            return veh, None

        veh, err = await asyncio.to_thread(_execute_get_vehicle)
        if err is not None:
            return err
        return _json_response(200, veh)

    router.add("GET", "/v1/vehicles/{vehicle_id}", handle_get_vehicle)

    # Route: PATCH /v1/vehicles/{vehicle_id}/location
    async def handle_update_vehicle_location(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        veh_id = params["vehicle_id"]
        auth_ctx: Optional[AuthContext] = scope.get("auth")

        try:
            raw_data = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:
            return _error_response(400, "VALIDATION_ERROR", f"Malformed JSON payload: {e}")

        try:
            dto = UpdateVehicleLocationInput.model_validate(raw_data)
        except PydanticValidationError as e:
            details = [
                ErrorDetail(field=".".join(str(loc) for loc in err["loc"]), issue=err["msg"])
                for err in e.errors()
            ]
            return _error_response(400, "VALIDATION_ERROR", "Location update validation failed", details)

        coord = GeoCoordinate(latitude=dto.latitude, longitude=dto.longitude)

        def _execute_update_loc() -> tuple[Any, Optional[tuple[int, dict[str, str], bytes]]]:
            veh = eff_service.get_vehicle(veh_id)
            if auth_ctx and auth_ctx.authenticated and "admin" not in auth_ctx.roles:
                if veh.driver_id != auth_ctx.subject_id:
                    return None, _error_response(
                        403, "FORBIDDEN", f"Caller is not authorized to update vehicle '{veh_id}'"
                    )
            updated = eff_service.update_vehicle_location(
                veh_id,
                coord,
                ride_id=dto.ride_id,
                completed_stop_ids=dto.completed_stop_ids,
            )
            return updated, None

        updated, err = await asyncio.to_thread(_execute_update_loc)
        if err is not None:
            return err
        return _json_response(200, updated)

    router.add("PATCH", "/v1/vehicles/{vehicle_id}/location", handle_update_vehicle_location)
    router.add("POST", "/v1/vehicles/{vehicle_id}/location", handle_update_vehicle_location)

    # Route: PATCH /v1/vehicles/{vehicle_id}/status
    async def handle_update_vehicle_status(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        veh_id = params["vehicle_id"]
        auth_ctx: Optional[AuthContext] = scope.get("auth")

        try:
            raw_data = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:
            return _error_response(400, "VALIDATION_ERROR", f"Malformed JSON payload: {e}")

        try:
            dto = UpdateVehicleStatusInput.model_validate(raw_data)
        except PydanticValidationError as e:
            details = [
                ErrorDetail(field=".".join(str(loc) for loc in err["loc"]), issue=err["msg"])
                for err in e.errors()
            ]
            return _error_response(400, "VALIDATION_ERROR", "Status update validation failed", details)

        def _execute_update_status() -> tuple[Any, Optional[tuple[int, dict[str, str], bytes]]]:
            veh = eff_service.get_vehicle(veh_id)
            if auth_ctx and auth_ctx.authenticated and "admin" not in auth_ctx.roles:
                if veh.driver_id != auth_ctx.subject_id:
                    return None, _error_response(
                        403, "FORBIDDEN", f"Caller is not authorized to update status for vehicle '{veh_id}'"
                    )
            updated = eff_service.update_vehicle_status(veh_id, dto.is_active)
            return updated, None

        updated, err = await asyncio.to_thread(_execute_update_status)
        if err is not None:
            return err
        return _json_response(200, updated)

    router.add("PATCH", "/v1/vehicles/{vehicle_id}/status", handle_update_vehicle_status)

    # Route: PATCH /v1/vehicles/{vehicle_id}/capacity
    async def handle_update_vehicle_capacity(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        veh_id = params["vehicle_id"]
        try:
            raw_data = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:
            return _error_response(400, "VALIDATION_ERROR", f"Malformed JSON payload: {e}")

        try:
            dto = UpdateVehicleCapacityInput.model_validate(raw_data)
        except PydanticValidationError as e:
            details = [
                ErrorDetail(field=".".join(str(loc) for loc in err["loc"]), issue=err["msg"])
                for err in e.errors()
            ]
            return _error_response(400, "VALIDATION_ERROR", "Vehicle capacity validation failed", details)

        updated = await asyncio.to_thread(eff_service.update_vehicle_capacity, veh_id, dto.total_seat_capacity)
        return _json_response(200, updated)

    router.add("PATCH", "/v1/vehicles/{vehicle_id}/capacity", handle_update_vehicle_capacity)

    # Route: POST & PATCH /v1/rides/{ride_id}/capacity and /v1/rides/{ride_id}/sync-capacity
    async def handle_sync_ride_capacity(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        ride_id = params["ride_id"]
        try:
            raw_data = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:
            return _error_response(400, "VALIDATION_ERROR", f"Malformed JSON payload: {e}")

        try:
            dto = SyncRideCapacityInput.model_validate(raw_data)
        except PydanticValidationError as e:
            details = [
                ErrorDetail(field=".".join(str(loc) for loc in err["loc"]), issue=err["msg"])
                for err in e.errors()
            ]
            return _error_response(400, "VALIDATION_ERROR", "Sync capacity validation failed", details)

        idem_token = dto.idempotency_token or headers.get("idempotency-key")
        result = await asyncio.to_thread(
            eff_service.sync_ride_capacity,
            ride_id,
            dto.available_seats,
            dto.version,
            idem_token,
        )
        if result.get("rejected"):
            return _error_response(409, "STALE_VERSION", result.get("message", "Stale sync version rejected"))
        return _json_response(200, result)

    router.add("PATCH", "/v1/rides/{ride_id}/capacity", handle_sync_ride_capacity)
    router.add("POST", "/v1/rides/{ride_id}/sync-capacity", handle_sync_ride_capacity)

    # Route: POST /v1/rides/{ride_id}/reconcile
    async def handle_reconcile_ride(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        ride_id = params["ride_id"]
        try:
            raw_data = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:
            return _error_response(400, "VALIDATION_ERROR", f"Malformed JSON payload: {e}")

        raw_data["ride_id"] = ride_id
        try:
            dto = ReconcileRideInput.model_validate(raw_data)
        except PydanticValidationError as e:
            details = [
                ErrorDetail(field=".".join(str(loc) for loc in err["loc"]), issue=err["msg"])
                for err in e.errors()
            ]
            return _error_response(400, "VALIDATION_ERROR", "Reconcile input validation failed", details)

        idem_token = dto.idempotency_token or headers.get("idempotency-key")
        eff_dto = dto.model_copy(update={"idempotency_token": idem_token})
        result = await asyncio.to_thread(eff_service.reconcile_ride, eff_dto)
        if result.get("rejected"):
            return _error_response(409, "STALE_VERSION", result.get("message", "Stale reconciliation rejected"))
        return _json_response(200, result)

    router.add("POST", "/v1/rides/{ride_id}/reconcile", handle_reconcile_ride)

    # Route: POST /v1/reconcile/batch
    async def handle_reconcile_batch(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        try:
            raw_data = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:
            return _error_response(400, "VALIDATION_ERROR", f"Malformed JSON payload: {e}")

        try:
            dto = ReconcileBatchInput.model_validate(raw_data)
        except PydanticValidationError as e:
            details = [
                ErrorDetail(field=".".join(str(loc) for loc in err["loc"]), issue=err["msg"])
                for err in e.errors()
            ]
            return _error_response(400, "VALIDATION_ERROR", "Batch reconcile input validation failed", details)

        results = []
        for ride_input in dto.rides:
            res = await asyncio.to_thread(eff_service.reconcile_ride, ride_input)
            results.append(res)
        return _json_response(200, {"reconciled_count": len(results), "results": results})

    router.add("POST", "/v1/reconcile/batch", handle_reconcile_batch)

    # Route: POST /v1/dispatch
    async def handle_dispatch(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        auth_ctx: Optional[AuthContext] = scope.get("auth")
        if auth_ctx and auth_ctx.authenticated:
            if (
                "admin" not in auth_ctx.roles
                and "dispatch_operator" not in auth_ctx.roles
                and "dispatch" not in auth_ctx.roles
            ):
                return _error_response(
                    403, "FORBIDDEN", "Dispatch optimization requires admin or dispatch_operator role"
                )

        try:
            raw_data = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:
            return _error_response(400, "VALIDATION_ERROR", f"Malformed JSON payload: {e}")

        try:
            dto = DispatchRunInput.model_validate(raw_data)
        except PydanticValidationError as e:
            details = [
                ErrorDetail(field=".".join(str(loc) for loc in err["loc"]), issue=err["msg"])
                for err in e.errors()
            ]
            return _error_response(400, "VALIDATION_ERROR", "Dispatch input validation failed", details)

        header_idemp = headers.get("idempotency-key")
        result = await asyncio.to_thread(eff_service.run_dispatch, dto, header_idempotency_key=header_idemp)
        return _json_response(200, result)

    router.add("POST", "/v1/dispatch", handle_dispatch)

    # Route: GET /v1/rides/{ride_id}
    async def handle_get_ride(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        ride_id = params["ride_id"]
        auth_ctx: Optional[AuthContext] = scope.get("auth")

        def _execute_get_ride() -> tuple[Any, Optional[tuple[int, dict[str, str], bytes]]]:
            ride = eff_service.get_ride(ride_id)
            if auth_ctx and auth_ctx.authenticated and "admin" not in auth_ctx.roles:
                is_driver = bool(auth_ctx.subject_id and ride.driver_id == auth_ctx.subject_id)
                is_passenger = any(
                    bool(auth_ctx.subject_id and stop.request_id and auth_ctx.subject_id in stop.request_id)
                    for stop in ride.stops
                )
                if not (is_driver or is_passenger):
                    return None, _error_response(
                        403, "FORBIDDEN", f"Caller is not authorized to inspect ride '{ride_id}'"
                    )
            return ride, None

        ride, err = await asyncio.to_thread(_execute_get_ride)
        if err is not None:
            return err
        return _json_response(200, ride)

    router.add("GET", "/v1/rides/{ride_id}", handle_get_ride)

    # Route: POST /v1/proposals
    async def handle_create_proposal(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        auth_ctx: Optional[AuthContext] = scope.get("auth")
        if auth_ctx and auth_ctx.authenticated and "admin" not in auth_ctx.roles:
            return _error_response(
                403, "FORBIDDEN", "Manual proposal creation requires admin role"
            )

        try:
            raw_data = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:
            return _error_response(400, "VALIDATION_ERROR", f"Malformed JSON payload: {e}")

        header_idemp = headers.get("idempotency-key")
        if header_idemp and not raw_data.get("idempotency_token"):
            raw_data["idempotency_token"] = header_idemp

        try:
            dto = CreateProposalInput.model_validate(raw_data)
        except PydanticValidationError as e:
            details = [
                ErrorDetail(field=".".join(str(loc) for loc in err["loc"]), issue=err["msg"])
                for err in e.errors()
            ]
            return _error_response(400, "VALIDATION_ERROR", "Proposal input validation failed", details)

        proposal = await asyncio.to_thread(eff_service.create_proposal, dto)
        return _json_response(201, proposal)

    router.add("POST", "/v1/proposals", handle_create_proposal)

    # Route: GET /v1/proposals/{proposal_id}
    async def handle_get_proposal(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        proposal_id = params["proposal_id"]
        auth_ctx: Optional[AuthContext] = scope.get("auth")
        caller_user_id = headers.get("x-user-id")
        proposal = await asyncio.to_thread(
            eff_service.get_proposal, proposal_id, auth_context=auth_ctx, caller_user_id=caller_user_id
        )
        return _json_response(200, proposal)

    router.add("GET", "/v1/proposals/{proposal_id}", handle_get_proposal)

    # Route: POST /v1/proposals/{proposal_id}/accept
    async def handle_accept_proposal(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        proposal_id = params["proposal_id"]
        raw_data = {}
        if body:
            try:
                raw_data = json.loads(body.decode("utf-8"))
            except Exception as e:
                return _error_response(400, "VALIDATION_ERROR", f"Malformed JSON payload: {e}")

        header_idemp = headers.get("idempotency-key")
        if header_idemp and not raw_data.get("idempotency_token"):
            raw_data["idempotency_token"] = header_idemp

        header_user = headers.get("x-user-id")
        if header_user and not raw_data.get("user_id"):
            raw_data["user_id"] = header_user

        header_role = headers.get("x-role")
        if header_role and not raw_data.get("role"):
            raw_data["role"] = header_role

        try:
            dto = ProposalDecisionInput.model_validate(raw_data)
        except PydanticValidationError as e:
            details = [
                ErrorDetail(field=".".join(str(loc) for loc in err["loc"]), issue=err["msg"])
                for err in e.errors()
            ]
            return _error_response(400, "VALIDATION_ERROR", "Proposal decision validation failed", details)

        auth_ctx: Optional[AuthContext] = scope.get("auth")
        result = await asyncio.to_thread(
            eff_service.accept_proposal, proposal_id, dto, auth_context=auth_ctx
        )
        return _json_response(200, result)

    router.add("POST", "/v1/proposals/{proposal_id}/accept", handle_accept_proposal)

    # Route: POST /v1/proposals/{proposal_id}/decline
    async def handle_decline_proposal(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        proposal_id = params["proposal_id"]
        raw_data = {}
        if body:
            try:
                raw_data = json.loads(body.decode("utf-8"))
            except Exception as e:
                return _error_response(400, "VALIDATION_ERROR", f"Malformed JSON payload: {e}")

        header_user = headers.get("x-user-id")
        if header_user and not raw_data.get("user_id"):
            raw_data["user_id"] = header_user

        header_role = headers.get("x-role")
        if header_role and not raw_data.get("role"):
            raw_data["role"] = header_role

        try:
            dto = ProposalDecisionInput.model_validate(raw_data)
        except PydanticValidationError as e:
            details = [
                ErrorDetail(field=".".join(str(loc) for loc in err["loc"]), issue=err["msg"])
                for err in e.errors()
            ]
            return _error_response(400, "VALIDATION_ERROR", "Proposal decision validation failed", details)

        auth_ctx: Optional[AuthContext] = scope.get("auth")
        result = await asyncio.to_thread(
            eff_service.decline_proposal, proposal_id, dto, auth_context=auth_ctx
        )
        return _json_response(200, result)

    router.add("POST", "/v1/proposals/{proposal_id}/decline", handle_decline_proposal)

    # Route: POST /v1/host-rides
    async def handle_create_host_ride(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        try:
            raw_data = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:
            return _error_response(400, "VALIDATION_ERROR", f"Malformed JSON payload: {e}")

        auth_ctx: Optional[AuthContext] = scope.get("auth")
        if auth_ctx and auth_ctx.authenticated and "admin" not in auth_ctx.roles:
            body_driver = raw_data.get("driver_id")
            if body_driver and body_driver != auth_ctx.subject_id:
                return _error_response(
                    403,
                    "FORBIDDEN",
                    f"Authenticated user '{auth_ctx.subject_id}' cannot create host ride for driver '{body_driver}'",
                )
            raw_data["driver_id"] = auth_ctx.subject_id
        else:
            header_user = headers.get("x-user-id")
            if header_user and not raw_data.get("driver_id"):
                raw_data["driver_id"] = header_user

        try:
            dto = CreateHostRideInput.model_validate(raw_data)
        except PydanticValidationError as e:
            details = [
                ErrorDetail(field=".".join(str(loc) for loc in err["loc"]), issue=err["msg"])
                for err in e.errors()
            ]
            return _error_response(400, "VALIDATION_ERROR", "Host ride input validation failed", details)

        host_ride = await asyncio.to_thread(eff_service.register_host_ride, dto)
        return _json_response(201, host_ride)

    router.add("POST", "/v1/host-rides", handle_create_host_ride)

    # Route: GET /v1/host-rides/{ride_id}
    async def handle_get_host_ride(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        ride_id = params["ride_id"]
        auth_ctx: Optional[AuthContext] = scope.get("auth")
        host_ride = await asyncio.to_thread(eff_service.get_host_ride, ride_id, auth_context=auth_ctx)
        return _json_response(200, host_ride)

    router.add("GET", "/v1/host-rides/{ride_id}", handle_get_host_ride)

    # Route: POST /v1/host-rides/{ride_id}/match
    async def handle_match_host_ride(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        ride_id = params["ride_id"]
        auth_ctx: Optional[AuthContext] = scope.get("auth")
        raw_data = {}
        if body:
            try:
                raw_data = json.loads(body.decode("utf-8"))
            except Exception as e:
                return _error_response(400, "VALIDATION_ERROR", f"Malformed JSON payload: {e}")

        req_id = raw_data.get("request_id")
        proposals = await asyncio.to_thread(
            eff_service.match_host_ride, ride_id, request_id=req_id, auth_context=auth_ctx
        )
        return _json_response(200, {"proposals": proposals, "total_matched": len(proposals)})

    router.add("POST", "/v1/host-rides/{ride_id}/match", handle_match_host_ride)

    # Route: POST /v1/rides/{ride_id}/en-route-join
    async def handle_en_route_join(
        scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        ride_id = params["ride_id"]
        auth_ctx: Optional[AuthContext] = scope.get("auth")
        try:
            raw_data = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:
            return _error_response(400, "VALIDATION_ERROR", f"Malformed JSON payload: {e}")

        try:
            dto = EnRouteJoinInput.model_validate(raw_data)
        except PydanticValidationError as e:
            details = [
                ErrorDetail(field=".".join(str(loc) for loc in err["loc"]), issue=err["msg"])
                for err in e.errors()
            ]
            return _error_response(400, "VALIDATION_ERROR", "En-route join input validation failed", details)

        result = await asyncio.to_thread(
            eff_service.evaluate_en_route_join, ride_id, dto, auth_context=auth_ctx
        )
        status_code = 200 if result.eligible else 409
        return _json_response(status_code, result)

    router.add("POST", "/v1/rides/{ride_id}/en-route-join", handle_en_route_join)

    async def asgi_app(scope: Scope, receive: Receive, send: Send) -> None:
        """Standard ASGI 3 entry point."""
        nonlocal is_shutting_down, active_request_count
        scope_type = scope.get("type")

        if scope_type == "lifespan":
            while True:
                message = await receive()
                msg_type = message.get("type")
                if msg_type == "lifespan.startup":
                    try:
                        await asyncio.to_thread(eff_service.open)
                        await send({"type": "lifespan.startup.complete"})
                    except Exception as exc:
                        logger.error("Failed to initialize service during startup: %s", exc, exc_info=True)
                        await send({"type": "lifespan.startup.failed", "message": str(exc)})
                        return
                elif msg_type == "lifespan.shutdown":
                    is_shutting_down = True
                    start_shutdown = time.monotonic()
                    while active_request_count > 0:
                        if time.monotonic() - start_shutdown >= eff_config.shutdown_timeout_seconds:
                            logger.warning(
                                "Shutdown grace period exceeded with %d active requests remaining.",
                                active_request_count,
                            )
                            break
                        await asyncio.sleep(0.02)
                    await asyncio.to_thread(eff_service.close)
                    await send({"type": "lifespan.shutdown.complete"})
                    return
            return

        if scope_type != "http":
            return

        status: int
        resp_headers: dict[str, str]
        resp_body: bytes

        if is_shutting_down:
            status, resp_headers, resp_body = _error_response(
                503,
                "SERVICE_SHUTTING_DOWN",
                "Service is shutting down and no longer accepting new requests",
            )
            header_tuples = [
                (k.encode("latin1"), v.encode("latin1")) for k, v in resp_headers.items()
            ]
            await send(
                {
                    "type": "http.response.start",
                    "status": status,
                    "headers": header_tuples,
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": resp_body,
                    "more_body": False,
                }
            )
            return

        active_request_count += 1
        try:
            start_time = time.monotonic()
            method = scope.get("method", "GET").upper()
            path = scope.get("path", "/")

            # Parse request headers
            headers_dict: dict[str, str] = {}
            for raw_k, raw_v in scope.get("headers", []):
                try:
                    headers_dict[raw_k.decode("latin1").lower()] = raw_v.decode("latin1")
                except Exception:
                    pass

            # CORS origin validation and preflight handling
            req_origin = headers_dict.get("origin")
            origin_allowed = False
            cors_headers: dict[str, str] = {}
            if req_origin:
                if "*" in eff_config.cors_allowed_origins:
                    origin_allowed = True
                    cors_headers["access-control-allow-origin"] = "*"
                elif req_origin in eff_config.cors_allowed_origins:
                    origin_allowed = True
                    cors_headers["access-control-allow-origin"] = req_origin
                    cors_headers["vary"] = "Origin"

            if method == "OPTIONS":
                if origin_allowed:
                    cors_resp_headers = {
                        **cors_headers,
                        "access-control-allow-methods": "GET, POST, PATCH, DELETE, OPTIONS",
                        "access-control-allow-headers": "authorization, content-type, idempotency-key, x-api-key, x-user-id, x-role",
                        "access-control-max-age": "86400",
                        "content-length": "0",
                    }
                    header_tuples = [
                        (k.encode("latin1"), v.encode("latin1")) for k, v in cors_resp_headers.items()
                    ]
                    await send({"type": "http.response.start", "status": 204, "headers": header_tuples})
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                    return
                else:
                    status, resp_headers, resp_body = _error_response(
                        403, "CORS_ORIGIN_NOT_ALLOWED", f"Origin '{req_origin}' is not permitted by CORS policy"
                    )
                    header_tuples = [
                        (k.encode("latin1"), v.encode("latin1")) for k, v in resp_headers.items()
                    ]
                    await send({"type": "http.response.start", "status": status, "headers": header_tuples})
                    await send({"type": "http.response.body", "body": resp_body, "more_body": False})
                    return

            # Match route
            handler, path_params, method_mismatch = router.match(method, path)

            if method_mismatch:
                status, resp_headers, resp_body = _error_response(
                    405, "METHOD_NOT_ALLOWED", f"HTTP method '{method}' not allowed on path '{path}'"
                )
            elif handler is None:
                status, resp_headers, resp_body = _error_response(
                    404, "ROUTE_NOT_FOUND", f"Endpoint '{method} {path}' does not exist"
                )
            else:
                # Establish authentication context and enforce if required
                auth_ctx = eff_auth.authenticate(scope, headers_dict)
                scope["auth"] = auth_ctx
                auth_error: Optional[tuple[int, dict[str, str], bytes]] = None
                if eff_config.require_auth and path not in PUBLIC_HEALTH_PATHS:
                    if not auth_ctx.authenticated:
                        auth_error = _error_response(
                            401,
                            "AUTHENTICATION_REQUIRED",
                            "Authentication credentials are missing or invalid",
                        )
                    else:
                        action = "read" if method == "GET" else ("dispatch" if path == "/v1/dispatch" else "write")
                        if not eff_auth.authorize(auth_ctx, action, path):
                            auth_error = _error_response(
                                403,
                                "FORBIDDEN",
                                f"Caller is not authorized to execute '{action}' on '{path}'",
                            )

                if auth_error is not None:
                    status, resp_headers, resp_body = auth_error
                else:
                    # Pre-check Content-Length header against max body size
                    content_length_str = headers_dict.get("content-length")
                    length_error: Optional[tuple[int, dict[str, str], bytes]] = None
                    if content_length_str is not None:
                        try:
                            content_len = int(content_length_str)
                            if content_len > eff_config.max_request_body_bytes:
                                length_error = _error_response(
                                    413,
                                    "PAYLOAD_TOO_LARGE",
                                    f"Request body exceeds maximum permitted size of {eff_config.max_request_body_bytes} bytes",
                                )
                        except ValueError:
                            length_error = _error_response(
                                400, "VALIDATION_ERROR", "Invalid Content-Length header"
                            )

                    if length_error is not None:
                        status, resp_headers, resp_body = length_error
                    else:
                        # Stream request body with size guarding and disconnect handling
                        body_chunks: list[bytes] = []
                        accumulated_bytes = 0
                        payload_too_large = False
                        client_disconnected = False
                        more_body = True

                        while more_body:
                            msg = await receive()
                            msg_type = msg.get("type")
                            if msg_type == "http.disconnect":
                                client_disconnected = True
                                break
                            elif msg_type == "http.request":
                                chunk = msg.get("body", b"")
                                if chunk:
                                    accumulated_bytes += len(chunk)
                                    if accumulated_bytes > eff_config.max_request_body_bytes:
                                        payload_too_large = True
                                        break
                                    body_chunks.append(chunk)
                                more_body = msg.get("more_body", False)
                            else:
                                break

                        if client_disconnected:
                            return

                        if payload_too_large:
                            status, resp_headers, resp_body = _error_response(
                                413,
                                "PAYLOAD_TOO_LARGE",
                                f"Request body exceeds maximum permitted size of {eff_config.max_request_body_bytes} bytes",
                            )
                        else:
                            full_body = b"".join(body_chunks)

                            # Invoke matched handler with strict error boundaries
                            try:
                                status, resp_headers, resp_body = await handler(
                                    scope, full_body, headers_dict, path_params
                                )
                            except ServiceError as e:
                                status, resp_headers, resp_body = _error_response(
                                    e.status_code, e.code, e.message, e.details
                                )
                            except StorageProviderError as e:
                                err_str = str(e).lower()
                                if "exhausted" in err_str or "timeout" in err_str:
                                    status, resp_headers, resp_body = _error_response(
                                        503,
                                        "STORAGE_POOL_EXHAUSTED",
                                        "Database connection pool exhausted; please retry shortly.",
                                    )
                                else:
                                    status, resp_headers, resp_body = _error_response(
                                        503,
                                        "STORAGE_UNAVAILABLE",
                                        "Database storage provider is currently unavailable.",
                                    )
                            except Exception as e:
                                sanitized_detail = sanitize_sensitive_strings(str(e))
                                logger.error(
                                    "Unhandled internal error on %s %s: %s",
                                    method,
                                    path,
                                    sanitized_detail,
                                    exc_info=True,
                                )
                                # Never leak raw internal exception details or DSN secrets to the client
                                status, resp_headers, resp_body = _error_response(
                                    500,
                                    "INTERNAL_SERVER_ERROR",
                                    "An unexpected internal error occurred.",
                                )

            # Record operational API telemetry metrics
            duration_ms = (time.monotonic() - start_time) * 1000.0
            eff_telemetry.record_api_request(
                method=method,
                path=path,
                status_code=status,
                duration_ms=duration_ms,
            )

            # Attach CORS response headers if origin is permitted
            if origin_allowed:
                for cors_k, cors_v in cors_headers.items():
                    if cors_k not in resp_headers:
                        resp_headers[cors_k] = cors_v

            # Send ASGI HTTP response
            header_tuples = [
                (k.encode("latin1"), v.encode("latin1")) for k, v in resp_headers.items()
            ]
            await send(
                {
                    "type": "http.response.start",
                    "status": status,
                    "headers": header_tuples,
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": resp_body,
                    "more_body": False,
                }
            )
        finally:
            active_request_count -= 1

    return asgi_app


# Canonical ASGI module-level entrypoint for standard ASGI servers (e.g. uvicorn engine.service.app:app)
app = create_app()
