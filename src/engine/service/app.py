"""Pure standard-library ASGI 3 application for the pool engine API service."""

import json
import re
from typing import Any, Awaitable, Callable, Optional, Pattern
from pydantic import ValidationError as PydanticValidationError

from engine.domain.models import GeoCoordinate
from engine.service.errors import (
    ErrorBody,
    ErrorDetail,
    ErrorEnvelope,
    ResourceNotFoundError,
    ServiceError,
    ValidationError as ApiValidationError,
)
from engine.service.schemas import (
    CancelRideRequestInput,
    CreateRideRequestInput,
    DispatchRunInput,
    RegisterVehicleInput,
    UpdateLocationInput,
    UpdateVehicleStatusInput,
)
from engine.service.service import PoolEngineService

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
HandlerFunc = Callable[[Scope, bytes, dict[str, str], dict[str, str]], Awaitable[tuple[int, dict[str, str], bytes]]]


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
    if hasattr(payload, "model_dump"):
        data = payload.model_dump(mode="json")
    elif isinstance(payload, dict):
        data = payload
    else:
        data = payload
    body = json.dumps(data, indent=2).encode("utf-8")
    headers = {
        "content-type": "application/json",
        "content-length": str(len(body)),
    }
    return status_code, headers, body


def _error_response(status_code: int, code: str, message: str, details: list[ErrorDetail] | None = None) -> tuple[int, dict[str, str], bytes]:
    """Helper formatting RFC 7807 error envelopes."""
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code=code,
            message=message,
            details=details or [],
        )
    )
    return _json_response(status_code, envelope)


def create_app(service: PoolEngineService) -> Callable[[Scope, Receive, Send], Awaitable[None]]:
    """
    Creates and returns a standard ASGI 3 application callable bound to the given PoolEngineService.
    Zero external web framework dependencies (no FastAPI/Starlette).
    """
    router = AsgiRouter()

    # Route: GET /v1/health
    async def handle_health(scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
        return _json_response(200, {"status": "ok", "service": "pool-engine"})

    router.add("GET", "/v1/health", handle_health)

    # Route: POST /v1/requests
    async def handle_create_request(scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
        try:
            raw_data = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:
            return _error_response(400, "VALIDATION_ERROR", f"Malformed JSON payload: {e}")

        try:
            dto = CreateRideRequestInput.model_validate(raw_data)
        except PydanticValidationError as e:
            details = [
                ErrorDetail(field=".".join(str(loc) for loc in err["loc"]), issue=err["msg"])
                for err in e.errors()
            ]
            return _error_response(400, "VALIDATION_ERROR", "Request input validation failed", details)

        req = service.create_request(dto)
        return _json_response(201, req)

    router.add("POST", "/v1/requests", handle_create_request)

    # Route: GET /v1/requests/{request_id}
    async def handle_get_request(scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
        req_id = params["request_id"]
        req = service.get_request(req_id)
        return _json_response(200, req)

    router.add("GET", "/v1/requests/{request_id}", handle_get_request)

    # Route: POST /v1/requests/{request_id}/cancel
    async def handle_cancel_request(scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
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
        cancelled = service.cancel_request(req_id, reason=reason, idempotency_token=eff_idemp)
        return _json_response(200, cancelled)

    router.add("POST", "/v1/requests/{request_id}/cancel", handle_cancel_request)

    # Route: POST /v1/vehicles
    async def handle_register_vehicle(scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
        try:
            raw_data = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:
            return _error_response(400, "VALIDATION_ERROR", f"Malformed JSON payload: {e}")

        try:
            dto = RegisterVehicleInput.model_validate(raw_data)
        except PydanticValidationError as e:
            details = [
                ErrorDetail(field=".".join(str(loc) for loc in err["loc"]), issue=err["msg"])
                for err in e.errors()
            ]
            return _error_response(400, "VALIDATION_ERROR", "Vehicle input validation failed", details)

        veh = service.register_vehicle(dto)
        return _json_response(201, veh)

    router.add("POST", "/v1/vehicles", handle_register_vehicle)

    # Route: GET /v1/vehicles/{vehicle_id}
    async def handle_get_vehicle(scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
        veh_id = params["vehicle_id"]
        veh = service.get_vehicle(veh_id)
        return _json_response(200, veh)

    router.add("GET", "/v1/vehicles/{vehicle_id}", handle_get_vehicle)

    # Route: PATCH /v1/vehicles/{vehicle_id}/location
    async def handle_update_vehicle_location(scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
        veh_id = params["vehicle_id"]
        try:
            raw_data = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:
            return _error_response(400, "VALIDATION_ERROR", f"Malformed JSON payload: {e}")

        try:
            dto = UpdateLocationInput.model_validate(raw_data)
        except PydanticValidationError as e:
            details = [
                ErrorDetail(field=".".join(str(loc) for loc in err["loc"]), issue=err["msg"])
                for err in e.errors()
            ]
            return _error_response(400, "VALIDATION_ERROR", "Location update validation failed", details)

        coord = GeoCoordinate(latitude=dto.latitude, longitude=dto.longitude)
        updated = service.update_vehicle_location(veh_id, coord)
        return _json_response(200, updated)

    router.add("PATCH", "/v1/vehicles/{vehicle_id}/location", handle_update_vehicle_location)

    # Route: PATCH /v1/vehicles/{vehicle_id}/status
    async def handle_update_vehicle_status(scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
        veh_id = params["vehicle_id"]
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

        updated = service.update_vehicle_status(veh_id, dto.is_active)
        return _json_response(200, updated)

    router.add("PATCH", "/v1/vehicles/{vehicle_id}/status", handle_update_vehicle_status)

    # Route: POST /v1/dispatch
    async def handle_dispatch(scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
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
        result = service.run_dispatch(dto, header_idempotency_key=header_idemp)
        return _json_response(200, result)

    router.add("POST", "/v1/dispatch", handle_dispatch)

    # Route: GET /v1/rides/{ride_id}
    async def handle_get_ride(scope: Scope, body: bytes, headers: dict[str, str], params: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
        ride_id = params["ride_id"]
        ride = service.get_ride(ride_id)
        return _json_response(200, ride)

    router.add("GET", "/v1/rides/{ride_id}", handle_get_ride)

    async def asgi_app(scope: Scope, receive: Receive, send: Send) -> None:
        """Standard ASGI 3 entry point."""
        scope_type = scope.get("type")

        if scope_type == "lifespan":
            while True:
                message = await receive()
                msg_type = message.get("type")
                if msg_type == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif msg_type == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
            return

        if scope_type != "http":
            return

        method = scope.get("method", "GET").upper()
        path = scope.get("path", "/")

        # Parse request headers
        headers_dict: dict[str, str] = {}
        for raw_k, raw_v in scope.get("headers", []):
            try:
                headers_dict[raw_k.decode("latin1").lower()] = raw_v.decode("latin1")
            except Exception:
                pass

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
            # Read complete request body
            body_chunks: list[bytes] = []
            more_body = True
            while more_body:
                msg = await receive()
                if msg.get("type") == "http.request":
                    chunk = msg.get("body", b"")
                    if chunk:
                        body_chunks.append(chunk)
                    more_body = msg.get("more_body", False)
                else:
                    break
            full_body = b"".join(body_chunks)

            # Invoke matched handler with error boundaries
            try:
                status, resp_headers, resp_body = await handler(scope, full_body, headers_dict, path_params)
            except ServiceError as e:
                status, resp_headers, resp_body = _error_response(
                    e.status_code, e.code, e.message, e.details
                )
            except Exception as e:
                status, resp_headers, resp_body = _error_response(
                    500, "INTERNAL_SERVER_ERROR", f"Unhandled server error: {e}"
                )

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

    return asgi_app
