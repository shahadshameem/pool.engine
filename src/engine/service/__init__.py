"""API service layer for the pool engine."""

from engine.service.app import create_app
from engine.service.client import AsgiResponse, AsgiTestClient
from engine.service.errors import (
    ConflictError,
    ErrorBody,
    ErrorDetail,
    ErrorEnvelope,
    LifecycleError,
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
from engine.service.service import PoolEngineService

__all__ = [
    "create_app",
    "AsgiTestClient",
    "AsgiResponse",
    "ServiceError",
    "ValidationError",
    "ResourceNotFoundError",
    "ConflictError",
    "LifecycleError",
    "RoutingError",
    "RoutingTimeoutError",
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
]
