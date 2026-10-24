"""Contract for dispatch policy and operational configuration."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class InvalidPolicyError(Exception):
    """Raised when policy parameters or weights fail validation."""
    pass


@dataclass(frozen=True)
class DispatchPolicy:
    """Operational constraints, detour tolerances, timers, and multi-objective weights."""

    # Invariant Thresholds
    detour_relative_multiplier: float = 1.30
    detour_absolute_cap_seconds: int = 900          # 15 minutes
    max_pickup_delay_seconds: int = 600             # 10 minutes

    # Lifecycle Timers
    boarding_grace_period_seconds: int = 180        # 3 minutes
    scheduled_departure_grace_seconds: int = 600    # 10 minutes
    join_request_expiry_seconds: int = 300          # 5 minutes
    scheduled_activation_lead_seconds: int = 1800   # 30 minutes
    stop_arrival_dwell_seconds: int = 15            # 15 seconds

    # Multi-Objective Weights (Normalized, sum == 1.0)
    weight_vmt_reduction: float = 0.40
    weight_passenger_detour: float = 0.30
    weight_passenger_wait: float = 0.20
    weight_driver_idle: float = 0.10

    def validate(self) -> None:
        """
        Validates all parameter ranges and objective weights.
        Raises InvalidPolicyError or ValueError if parameters fall outside valid bounds.
        """
        if not (1.00 <= self.detour_relative_multiplier <= 3.00):
            raise ValueError(f"detour_relative_multiplier {self.detour_relative_multiplier} out of range [1.0, 3.0]")
        if not (60 <= self.detour_absolute_cap_seconds <= 7200):
            raise ValueError(f"detour_absolute_cap_seconds {self.detour_absolute_cap_seconds} out of range [60, 7200]")
        if not (0 <= self.max_pickup_delay_seconds <= 3600):
            raise ValueError(f"max_pickup_delay_seconds {self.max_pickup_delay_seconds} out of range [0, 3600]")
        if not (30 <= self.boarding_grace_period_seconds <= 900):
            raise ValueError(f"boarding_grace_period_seconds {self.boarding_grace_period_seconds} out of range [30, 900]")
        if not (60 <= self.scheduled_departure_grace_seconds <= 1800):
            raise ValueError(f"scheduled_departure_grace_seconds {self.scheduled_departure_grace_seconds} out of range [60, 1800]")
        if not (30 <= self.join_request_expiry_seconds <= 1800):
            raise ValueError(f"join_request_expiry_seconds {self.join_request_expiry_seconds} out of range [30, 1800]")
        if not (300 <= self.scheduled_activation_lead_seconds <= 7200):
            raise ValueError(f"scheduled_activation_lead_seconds {self.scheduled_activation_lead_seconds} out of range [300, 7200]")
        if not (0 <= self.stop_arrival_dwell_seconds <= 120):
            raise ValueError(f"stop_arrival_dwell_seconds {self.stop_arrival_dwell_seconds} out of range [0, 120]")

        weights = [
            self.weight_vmt_reduction,
            self.weight_passenger_detour,
            self.weight_passenger_wait,
            self.weight_driver_idle,
        ]
        if any(w < 0.0 for w in weights):
            raise ValueError("All objective weights must be non-negative (>= 0.0)")
        total_w = sum(weights)
        if total_w <= 0.0:
            raise ValueError("Sum of objective weights must be positive (> 0.0)")
        if abs(total_w - 1.0) > 1e-6:
            raise ValueError(f"Objective weights must sum to 1.0 within 1e-6 tolerance (current sum: {total_w:.6f})")


class DispatchPolicyProvider(ABC):
    """Supplies operational policy and scoring configuration to matching engines."""

    @abstractmethod
    def get_policy(self, zone_id: str | None = None) -> DispatchPolicy:
        """Returns the active, validated DispatchPolicy for an operational zone."""
        pass

    @abstractmethod
    def update_policy(self, new_policy: DispatchPolicy, zone_id: str | None = None) -> None:
        """
        Validates and applies a new policy dynamically.
        Active onboard rides maintain their booking-time promise windows.
        """
        pass
