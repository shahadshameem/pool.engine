"""Configuration models for the pool engine API service."""

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ServiceConfig(BaseModel):
    """Operational and security configuration for the pool engine API service."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_request_body_bytes: int = Field(
        default=1_048_576,  # 1 MB
        ge=1024,
        le=52_428_800,  # 50 MB
        description="Maximum permitted request body size in bytes to prevent DoS.",
    )
    require_auth: bool = Field(
        default=False,
        description="Whether authentication is required for protected endpoints.",
    )
    allow_unauthenticated_in_production: bool = Field(
        default=False,
        description="Explicit opt-out required if running in production without authentication.",
    )
    strict_routing_readiness: bool = Field(
        default=False,
        description="Whether routing provider degradation causes readiness probe to fail (503).",
    )
    shutdown_timeout_seconds: float = Field(
        default=5.0,
        ge=0.1,
        le=60.0,
        description="Grace period in seconds to await active requests during ASGI shutdown.",
    )
    mask_coordinates_in_logs: bool = Field(
        default=True,
        description="Whether to obfuscate exact latitude/longitude coordinates in logs.",
    )
    enable_telemetry: bool = Field(
        default=True,
        description="Whether to emit structured metrics and operational telemetry events.",
    )
    environment: str = Field(
        default="development",
        description="Deployment environment name (e.g., development, staging, production).",
    )

    @model_validator(mode="after")
    def validate_production_security(self) -> "ServiceConfig":
        """Ensures production configuration cannot accidentally enable unrestricted access without explicit choice."""
        if self.environment.lower() == "production" and not self.require_auth and not self.allow_unauthenticated_in_production:
            raise ValueError(
                "Production environment requires authentication ('require_auth=True') "
                "unless explicitly overridden by 'allow_unauthenticated_in_production=True'."
            )
        return self
