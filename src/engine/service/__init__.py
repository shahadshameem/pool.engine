"""API service layer for the pool engine."""

from engine.service.app import create_app
from engine.service.client import AsgiResponse, AsgiTestClient
from engine.service.config import ServiceConfig
from engine.service.errors import (
    AuthenticationRequiredError,
    AuthorizationForbiddenError,
    ConflictError,
    ErrorBody,
    ErrorDetail,
    ErrorEnvelope,
    LifecycleError,
    PayloadTooLargeError,
    ResourceNotFoundError,
    RoutingError,
    RoutingTimeoutError,
    ServiceError,
    ValidationError,
)
from engine.service.schemas import (
    CancelRideRequestInput,
    CreateRideRequestInput,
    DispatchCycleResponse,
    DispatchRunInput,
    RegisterVehicleInput,
    StaleAssignmentDiagnosticResponse,
    UpdateLocationInput,
    UpdateVehicleStatusInput,
)
from engine.service.security import (
    ApiKeyAuthProvider,
    AuthContext,
    AuthProvider,
    NoOpAuthProvider,
    build_auth_provider_from_env,
    sanitize_sensitive_strings,
)
from engine.service.service import PoolEngineService, build_service_from_env
from engine.service.telemetry import (
    EngineTelemetryProvider,
    InMemoryTelemetry,
    StructuredLoggerTelemetry,
    mask_coordinate,
)

__all__ = [
    "create_app",
    "AsgiTestClient",
    "AsgiResponse",
    "ServiceConfig",
    "AuthContext",
    "AuthProvider",
    "NoOpAuthProvider",
    "ApiKeyAuthProvider",
    "build_auth_provider_from_env",
    "sanitize_sensitive_strings",
    "EngineTelemetryProvider",
    "StructuredLoggerTelemetry",
    "InMemoryTelemetry",
    "mask_coordinate",
    "ServiceError",
    "ValidationError",
    "ResourceNotFoundError",
    "ConflictError",
    "LifecycleError",
    "RoutingError",
    "RoutingTimeoutError",
    "AuthenticationRequiredError",
    "AuthorizationForbiddenError",
    "PayloadTooLargeError",
    "ErrorDetail",
    "ErrorBody",
    "ErrorEnvelope",
    "CreateRideRequestInput",
    "CancelRideRequestInput",
    "RegisterVehicleInput",
    "UpdateLocationInput",
    "UpdateVehicleStatusInput",
    "DispatchRunInput",
    "StaleAssignmentDiagnosticResponse",
    "DispatchCycleResponse",
    "PoolEngineService",
    "build_service_from_env",
]
