"""Candidate hyperedge assignment structures."""

from pydantic import BaseModel, ConfigDict, Field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.domain.models import RouteStop


class ScoreBreakdown(BaseModel):
    """Itemized multi-objective utility components."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    vmt_savings_ratio: float = Field(default=0.0, ge=0.0, le=1.0, description="Normalized VMT reduction ratio S_vmt")
    detour_penalty_ratio: float = Field(default=0.0, ge=0.0, le=1.0, description="Normalized passenger detour penalty P_detour")
    wait_penalty_ratio: float = Field(default=0.0, ge=0.0, le=1.0, description="Normalized passenger wait time penalty P_wait")
    driver_idle_penalty_ratio: float = Field(default=0.0, ge=0.0, le=1.0, description="Normalized driver idle time penalty P_idle")


class CandidateAssignment(BaseModel):
    """Represents a candidate assignment bundle mapping requests to a vehicle route."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    vehicle_id: str
    existing_ride_id: str | None = None
    request_ids: tuple[str, ...]
    ordered_stops: tuple["RouteStop", ...]
    peak_seat_load: int = Field(ge=0)
    vmt_meters: int = Field(ge=0)
    objective_value: float
    normalized_score: float = Field(ge=0.0, le=1.0)
    score_breakdown: ScoreBreakdown
