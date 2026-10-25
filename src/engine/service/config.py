"""Configuration models for the pool engine API service."""

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


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
    mask_coordinates_in_logs: bool = Field(
        default=True,
        description="Whether to obfuscate exact latitude/longitude coordinates in logs.",
    )
    enable_telemetry: bool = Field(
        default=True,
        description="Whether to emit structured metrics and operational telemetry events.",
    )
    environment: str = Field(
        default="production",
        description="Deployment environment name (e.g., development, test, production).",
    )
