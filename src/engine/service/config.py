"""Configuration models for the pool engine API service."""

import json
import os
from typing import Any, Mapping, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

from engine.contracts.routing import BoundingBox, Coordinate, RegionConfig


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
    require_persistent_storage: bool = Field(
        default=False,
        description="Whether persistent storage is strictly required (prohibits in-memory fallback).",
    )
    require_real_routing: bool = Field(
        default=False,
        description="Whether real OSRM road routing is strictly required (prohibits mock routing fallback).",
    )
    routing_region_min_lat: Optional[float] = Field(
        default=None,
        description="Minimum latitude for regional road-network routing bounding box.",
    )
    routing_region_min_lon: Optional[float] = Field(
        default=None,
        description="Minimum longitude for regional road-network routing bounding box.",
    )
    routing_region_max_lat: Optional[float] = Field(
        default=None,
        description="Maximum latitude for regional road-network routing bounding box.",
    )
    routing_region_max_lon: Optional[float] = Field(
        default=None,
        description="Maximum longitude for regional road-network routing bounding box.",
    )
    routing_max_snap_distance_meters: float = Field(
        default=5000.0,
        ge=1.0,
        description="Maximum permitted snapping distance from coordinate to nearest road edge.",
    )
    regions: tuple[RegionConfig, ...] = Field(
        default_factory=tuple,
        description="Explicit multi-region routing configuration with isolated endpoints and boundaries.",
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
    firebase_project_id: Optional[str] = Field(
        default=None,
        description="Google Firebase project ID used for cryptographic ID token verification.",
    )
    firebase_credentials_path: Optional[str] = Field(
        default=None,
        description="Path to Firebase service account JSON key file (optional; prefers ADC/workload identity).",
    )
    firebase_check_revoked: bool = Field(
        default=False,
        description="Whether to check token revocation status against Firebase Auth during token verification.",
    )
    cors_allowed_origins: tuple[str, ...] = Field(
        default=("http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"),
        description="List of approved browser origins permitted for CORS preflight and requests.",
    )
    auth_provider_type: str = Field(
        default="auto",
        description="Authentication strategy: 'auto', 'firebase', 'api_key', 'composite', or 'noop'.",
    )

    @model_validator(mode="after")
    def validate_regional_bounding_box(self) -> "ServiceConfig":
        """Ensures that regional bounding box fields are either all set or all None, and valid."""
        bbox_fields = [
            self.routing_region_min_lat,
            self.routing_region_min_lon,
            self.routing_region_max_lat,
            self.routing_region_max_lon,
        ]
        set_count = sum(1 for v in bbox_fields if v is not None)
        if 0 < set_count < 4:
            raise ValueError(
                "Incomplete regional bounding box configuration: all four bounds "
                "(min_lat, min_lon, max_lat, max_lon) must be specified if any are provided."
            )
        if set_count == 4:
            min_lat, min_lon, max_lat, max_lon = (
                self.routing_region_min_lat,
                self.routing_region_min_lon,
                self.routing_region_max_lat,
                self.routing_region_max_lon,
            )
            assert min_lat is not None and min_lon is not None and max_lat is not None and max_lon is not None
            if not (-90.0 <= min_lat <= 90.0 and -90.0 <= max_lat <= 90.0):
                raise ValueError(f"Regional bounding box latitudes must be in [-90.0, 90.0]: [{min_lat}, {max_lat}]")
            if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0):
                raise ValueError(f"Regional bounding box longitudes must be in [-180.0, 180.0]: [{min_lon}, {max_lon}]")
            if min_lat > max_lat:
                raise ValueError(f"Regional bounding box min_lat ({min_lat}) cannot exceed max_lat ({max_lat})")
            if min_lon > max_lon:
                raise ValueError(f"Regional bounding box min_lon ({min_lon}) cannot exceed max_lon ({max_lon})")
        return self

    @model_validator(mode="after")
    def validate_regions(self) -> "ServiceConfig":
        """Ensures that configured regions have unique IDs and strictly disjoint bounding boxes."""
        if not self.regions:
            return self
        seen_ids: set[str] = set()
        for r in self.regions:
            if r.region_id in seen_ids:
                raise ValueError(f"Duplicate region_id detected in ServiceConfig: '{r.region_id}'")
            seen_ids.add(r.region_id)

        for i in range(len(self.regions)):
            for j in range(i + 1, len(self.regions)):
                r1 = self.regions[i]
                r2 = self.regions[j]
                if r1.bounding_box.overlaps(r2.bounding_box):
                    raise ValueError(
                        f"Regional bounding boxes for '{r1.region_id}' and '{r2.region_id}' overlap: "
                        f"[{r1.bounding_box.min_lat}, {r1.bounding_box.min_lon}, {r1.bounding_box.max_lat}, {r1.bounding_box.max_lon}] "
                        f"and [{r2.bounding_box.min_lat}, {r2.bounding_box.min_lon}, {r2.bounding_box.max_lat}, {r2.bounding_box.max_lon}]"
                    )
        return self

    @model_validator(mode="after")
    def validate_production_security(self) -> "ServiceConfig":
        """Ensures production configuration cannot accidentally enable unrestricted access without explicit choice."""
        if self.environment.lower() == "production":
            if not self.require_auth and not self.allow_unauthenticated_in_production:
                raise ValueError(
                    "Production environment requires authentication ('require_auth=True') "
                    "unless explicitly overridden by 'allow_unauthenticated_in_production=True'."
                )
            if self.require_auth and "*" in self.cors_allowed_origins and not self.allow_unauthenticated_in_production:
                raise ValueError(
                    "Production environment cannot use wildcard '*' in cors_allowed_origins with authenticated endpoints."
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
        if "REQUIRE_PERSISTENT_STORAGE" in source:
            kwargs["require_persistent_storage"] = source[
                "REQUIRE_PERSISTENT_STORAGE"
            ].lower() in ("true", "1", "yes")
        if "REQUIRE_REAL_ROUTING" in source:
            kwargs["require_real_routing"] = source[
                "REQUIRE_REAL_ROUTING"
            ].lower() in ("true", "1", "yes")
        for k, field in (
            ("ROUTING_REGION_MIN_LAT", "routing_region_min_lat"),
            ("ROUTING_REGION_MIN_LON", "routing_region_min_lon"),
            ("ROUTING_REGION_MAX_LAT", "routing_region_max_lat"),
            ("ROUTING_REGION_MAX_LON", "routing_region_max_lon"),
            ("ROUTING_MAX_SNAP_DISTANCE_METERS", "routing_max_snap_distance_meters"),
        ):
            if k in source and source[k].strip():
                try:
                    kwargs[field] = float(source[k].strip())
                except ValueError:
                    pass

        # Multi-region configuration: ROUTING_REGIONS (JSON string) or ROUTING_REGIONS_FILE
        raw_regions = source.get("ROUTING_REGIONS")
        if not raw_regions and "ROUTING_REGIONS_FILE" in source:
            file_path = source["ROUTING_REGIONS_FILE"].strip()
            if not os.path.exists(file_path):
                raise ValueError(f"Configured ROUTING_REGIONS_FILE '{file_path}' does not exist")
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    raw_regions = f.read()
            except Exception as err:
                raise ValueError(f"Failed to read ROUTING_REGIONS_FILE '{file_path}': {err}") from err

        if raw_regions and raw_regions.strip():
            try:
                parsed = json.loads(raw_regions)
                if not isinstance(parsed, list):
                    raise ValueError("ROUTING_REGIONS JSON must be a list of region objects")
                region_configs: list[RegionConfig] = []
                for item in parsed:
                    bbox_data = item["bounding_box"]
                    bbox = BoundingBox(
                        min_lat=float(bbox_data["min_lat"]),
                        min_lon=float(bbox_data["min_lon"]),
                        max_lat=float(bbox_data["max_lat"]),
                        max_lon=float(bbox_data["max_lon"]),
                    )
                    probe_coord = None
                    if "probe_coordinate" in item and item["probe_coordinate"]:
                        probe_coord = Coordinate(
                            latitude=float(item["probe_coordinate"]["latitude"]),
                            longitude=float(item["probe_coordinate"]["longitude"]),
                        )
                    region_configs.append(
                        RegionConfig(
                            region_id=str(item["region_id"]),
                            bounding_box=bbox,
                            provider_type=str(item.get("provider_type", "osrm")),
                            endpoint_url=item.get("endpoint_url"),
                            dataset_id=str(item.get("dataset_id", "default")),
                            profile=str(item.get("profile", "driving")),
                            max_snap_distance_meters=float(item.get("max_snap_distance_meters", 5000.0)),
                            timeout_seconds=float(item.get("timeout_seconds", 0.500)),
                            probe_coordinate=probe_coord,
                        )
                    )
                kwargs["regions"] = tuple(region_configs)
            except Exception as err:
                raise ValueError(f"Failed to parse ROUTING_REGIONS configuration: {err}") from err
        elif all(
            k in kwargs
            for k in (
                "routing_region_min_lat",
                "routing_region_min_lon",
                "routing_region_max_lat",
                "routing_region_max_lon",
            )
        ):
            # Synthesize single default RegionConfig for backward compatibility
            bbox = BoundingBox(
                min_lat=kwargs["routing_region_min_lat"],
                min_lon=kwargs["routing_region_min_lon"],
                max_lat=kwargs["routing_region_max_lat"],
                max_lon=kwargs["routing_region_max_lon"],
            )
            reg_id = source.get("ROUTING_DEFAULT_REGION_ID", "default")
            prov_type = "osrm" if source.get("OSRM_BASE_URL") else "mock"
            kwargs["regions"] = (
                RegionConfig(
                    region_id=reg_id,
                    bounding_box=bbox,
                    provider_type=prov_type,
                    endpoint_url=source.get("OSRM_BASE_URL"),
                    dataset_id=source.get("ROUTING_DATASET_ID", "default"),
                    profile=source.get("ROUTING_PROFILE", "driving"),
                    max_snap_distance_meters=kwargs.get("routing_max_snap_distance_meters", 5000.0),
                ),
            )
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
        fb_proj = source.get("FIREBASE_PROJECT_ID") or source.get("GCLOUD_PROJECT") or source.get("GOOGLE_CLOUD_PROJECT")
        if fb_proj:
            kwargs["firebase_project_id"] = fb_proj.strip()
        fb_cred = source.get("FIREBASE_CREDENTIALS_PATH") or source.get("GOOGLE_APPLICATION_CREDENTIALS")
        if fb_cred:
            kwargs["firebase_credentials_path"] = fb_cred.strip()
        if "FIREBASE_CHECK_REVOKED" in source:
            kwargs["firebase_check_revoked"] = source["FIREBASE_CHECK_REVOKED"].lower() in ("true", "1", "yes")
        if "CORS_ALLOWED_ORIGINS" in source:
            raw_cors = source["CORS_ALLOWED_ORIGINS"].strip()
            if raw_cors:
                kwargs["cors_allowed_origins"] = tuple(
                    origin.strip() for origin in raw_cors.split(",") if origin.strip()
                )
        auth_type = source.get("AUTH_PROVIDER_TYPE") or source.get("AUTH_PROVIDER")
        if auth_type:
            kwargs["auth_provider_type"] = auth_type.strip().lower()
        return cls(**kwargs)
