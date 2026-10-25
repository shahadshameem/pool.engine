"""Operational observability, structured logging, and metrics hooks for the pool engine."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


logger = logging.getLogger("pool_engine.telemetry")


def mask_coordinate(lat: float, lon: float, precision: int = 2) -> tuple[float, float]:
    """
    Coarsens geographic coordinates to fuzz exact user location in telemetry logs.
    Satisfies Constitution Principle VIII (Location Sanitization).
    precision=2 corresponds to approximately ~1.1 km accuracy at the equator.
    """
    return round(lat, precision), round(lon, precision)


class EngineTelemetryProvider(ABC):
    """Abstract telemetry and observability provider for tracking operational health and dispatch metrics."""

    @abstractmethod
    def record_dispatch_cycle(
        self,
        cycle_id: str,
        duration_ms: float,
        search_status: str,
        committed_count: int,
        rejected_count: int,
        unassigned_count: int,
        routing_errors: int,
        vmt_savings: int,
    ) -> None:
        """Records metrics for an end-to-end dispatch optimization cycle."""
        pass

    @abstractmethod
    def record_routing_failure(self, provider: str, reason: str) -> None:
        """Records an external road routing failure or timeout."""
        pass

    @abstractmethod
    def record_conflict(self, conflict_type: str, resource_id: str) -> None:
        """Records optimistic concurrency or idempotency conflict."""
        pass

    @abstractmethod
    def record_cancellation(self, request_id: str, ride_id: Optional[str], was_matched: bool) -> None:
        """Records ride request cancellation."""
        pass

    @abstractmethod
    def record_idempotency_hit(self, token: str, operation: str) -> None:
        """Records duplicate idempotent submission replay."""
        pass

    @abstractmethod
    def record_api_request(self, method: str, path: str, status_code: int, duration_ms: float) -> None:
        """Records HTTP request invocation metrics."""
        pass


class StructuredLoggerTelemetry(EngineTelemetryProvider):
    """Emits structured, privacy-preserving audit logs via Python's standard logging facility."""

    def __init__(self, log_level: int = logging.INFO) -> None:
        self.logger = logger
        self.log_level = log_level

    def record_dispatch_cycle(
        self,
        cycle_id: str,
        duration_ms: float,
        search_status: str,
        committed_count: int,
        rejected_count: int,
        unassigned_count: int,
        routing_errors: int,
        vmt_savings: int,
    ) -> None:
        self.logger.log(
            self.log_level,
            "dispatch_cycle_completed",
            extra={
                "event": "dispatch_cycle",
                "cycle_id": cycle_id,
                "duration_ms": duration_ms,
                "search_status": search_status,
                "committed_assignments": committed_count,
                "rejected_assignments": rejected_count,
                "unassigned_requests": unassigned_count,
                "routing_errors": routing_errors,
                "vmt_savings_meters": vmt_savings,
            },
        )

    def record_routing_failure(self, provider: str, reason: str) -> None:
        self.logger.warning(
            "routing_failure_recorded",
            extra={"event": "routing_failure", "provider": provider, "reason": reason},
        )

    def record_conflict(self, conflict_type: str, resource_id: str) -> None:
        self.logger.info(
            "concurrency_conflict_recorded",
            extra={"event": "concurrency_conflict", "type": conflict_type, "resource_id": resource_id},
        )

    def record_cancellation(self, request_id: str, ride_id: Optional[str], was_matched: bool) -> None:
        self.logger.info(
            "cancellation_recorded",
            extra={"event": "cancellation", "request_id": request_id, "ride_id": ride_id, "was_matched": was_matched},
        )

    def record_idempotency_hit(self, token: str, operation: str) -> None:
        self.logger.info(
            "idempotency_replay_recorded",
            extra={"event": "idempotency_replay", "token": token[:8] + "...", "operation": operation},
        )

    def record_api_request(self, method: str, path: str, status_code: int, duration_ms: float) -> None:
        self.logger.log(
            self.log_level,
            "http_request_handled",
            extra={
                "event": "http_request",
                "method": method,
                "path": path,
                "status_code": status_code,
                "duration_ms": duration_ms,
            },
        )


@dataclass
class InMemoryTelemetry(EngineTelemetryProvider):
    """In-memory telemetry collector for automated tests and operational inspection."""

    dispatch_cycles: list[dict[str, Any]]
    routing_failures: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    cancellations: list[dict[str, Any]]
    idempotency_hits: list[dict[str, Any]]
    api_requests: list[dict[str, Any]]

    def __init__(self) -> None:
        self.dispatch_cycles = []
        self.routing_failures = []
        self.conflicts = []
        self.cancellations = []
        self.idempotency_hits = []
        self.api_requests = []

    def record_dispatch_cycle(
        self,
        cycle_id: str,
        duration_ms: float,
        search_status: str,
        committed_count: int,
        rejected_count: int,
        unassigned_count: int,
        routing_errors: int,
        vmt_savings: int,
    ) -> None:
        self.dispatch_cycles.append(
            {
                "cycle_id": cycle_id,
                "duration_ms": duration_ms,
                "search_status": search_status,
                "committed_count": committed_count,
                "rejected_count": rejected_count,
                "unassigned_count": unassigned_count,
                "routing_errors": routing_errors,
                "vmt_savings": vmt_savings,
            }
        )

    def record_routing_failure(self, provider: str, reason: str) -> None:
        self.routing_failures.append({"provider": provider, "reason": reason})

    def record_conflict(self, conflict_type: str, resource_id: str) -> None:
        self.conflicts.append({"conflict_type": conflict_type, "resource_id": resource_id})

    def record_cancellation(self, request_id: str, ride_id: Optional[str], was_matched: bool) -> None:
        self.cancellations.append(
            {"request_id": request_id, "ride_id": ride_id, "was_matched": was_matched}
        )

    def record_idempotency_hit(self, token: str, operation: str) -> None:
        self.idempotency_hits.append({"token": token, "operation": operation})

    def record_api_request(self, method: str, path: str, status_code: int, duration_ms: float) -> None:
        self.api_requests.append(
            {
                "method": method,
                "path": path,
                "status_code": status_code,
                "duration_ms": duration_ms,
            }
        )
