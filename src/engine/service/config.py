"""Configuration models for the pool engine API service."""

import os
from typing import Any, Mapping, Optional
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

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "ServiceConfig":
        """Instantiates ServiceConfig by inspecting environment variables or provided mapping."""
        source = os.environ if env is None else env
        kwargs: dict[str, Any] = {}
        if "MAX_REQUEST_BODY_BYTES" in source:
            try:
                kwargs["max_request_body_bytes"] = int(source["MAX_REQUEST_BODY_BYTES"])
            except ValueError:
                pass
        auth_env = source.get("REQUIRE_AUTH") or source.get("AUTH_ENABLED")
        if auth_env is not None:
            kwargs["require_auth"] = auth_env.lower() in ("true", "1", "yes")
        if "ALLOW_UNAUTHENTICATED_IN_PRODUCTION" in source:
            kwargs["allow_unauthenticated_in_production"] = source[
                "ALLOW_UNAUTHENTICATED_IN_PRODUCTION"
            ].lower() in ("true", "1", "yes")
        if "STRICT_ROUTING_READINESS" in source:
            kwargs["strict_routing_readiness"] = source[
                "STRICT_ROUTING_READINESS"
            ].lower() in ("true", "1", "yes")
        if "SHUTDOWN_TIMEOUT_SECONDS" in source:
            try:
                kwargs["shutdown_timeout_seconds"] = float(source["SHUTDOWN_TIMEOUT_SECONDS"])
            except ValueError:
                pass
        if "MASK_COORDINATES_IN_LOGS" in source:
            kwargs["mask_coordinates_in_logs"] = source[
                "MASK_COORDINATES_IN_LOGS"
            ].lower() in ("true", "1", "yes")
        if "ENABLE_TELEMETRY" in source:
            kwargs["enable_telemetry"] = source[
                "ENABLE_TELEMETRY"
            ].lower() in ("true", "1", "yes")
        if "ENVIRONMENT" in source:
            kwargs["environment"] = source["ENVIRONMENT"]
        return cls(**kwargs)
