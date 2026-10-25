"""Typed service exceptions and structured error models for the pool engine API."""

from typing import Any, Sequence
from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    """Specific field-level or contextual error detail."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str | None = None
    issue: str


class ErrorBody(BaseModel):
    """Standardized error payload conforming to RFC 7807 problem details."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorEnvelope(BaseModel):
    """Uniform root error envelope."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    error: ErrorBody


class ServiceError(Exception):
    """Base class for all API service exceptions."""

    status_code: int = 500
    code: str = "INTERNAL_SERVER_ERROR"

    def __init__(
        self,
        message: str,
        details: Sequence[ErrorDetail] | None = None,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = list(details or [])
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code

    def to_envelope(self) -> ErrorEnvelope:
        """Converts exception into a structured error envelope."""
        return ErrorEnvelope(
            error=ErrorBody(
                code=self.code,
                message=self.message,
                details=self.details,
            )
        )


class ValidationError(ServiceError):
    """Raised when client input fails syntax, schema, or invariant validation."""

    status_code = 400
    code = "VALIDATION_ERROR"


class ResourceNotFoundError(ServiceError):
    """Raised when a requested resource (request, vehicle, ride) is not found."""

    status_code = 404
    code = "RESOURCE_NOT_FOUND"


class ConflictError(ServiceError):
    """Raised on optimistic concurrency, idempotency, or capacity conflicts."""

    status_code = 409
    code = "CONCURRENCY_CONFLICT"


class LifecycleError(ServiceError):
    """Raised on invalid entity state transitions or illegal lifecycle mutations."""

    status_code = 422
    code = "LIFECYCLE_ERROR"


class RoutingError(ServiceError):
    """Raised when the upstream road-network routing provider fails or cannot resolve a route."""

    status_code = 502
    code = "ROUTING_BACKEND_ERROR"


class RoutingTimeoutError(RoutingError):
    """Raised when the routing backend query exceeds its allotted deadline."""

    status_code = 504
    code = "ROUTING_TIMEOUT_ERROR"
