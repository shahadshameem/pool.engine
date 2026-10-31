"""
Developer API client for executing requests against the Pool Engine service.

Supports both:
1. Live HTTP API Service (e.g., http://127.0.0.1:8000)
2. In-Process ASGI Application (zero external daemon requirement)
"""

import json
import time
import urllib.error
import urllib.request
from typing import Any, Mapping, Optional, Sequence

from engine.service.app import create_app
from engine.service.client import AsgiTestClient
from engine.service.service import PoolEngineService, build_service_from_env


class PlaygroundClient:
    """Unified client for interacting with the Pool Engine service."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        service: Optional[PoolEngineService] = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self.api_key = api_key
        self.timeout = timeout
        self._in_process_service = service
        self._asgi_client: Optional[AsgiTestClient] = None

        if not self.base_url:
            # In-process mode
            eff_service = service or build_service_from_env()
            self._in_process_service = eff_service
            app = create_app(service=eff_service)
            self._asgi_client = AsgiTestClient(app)

    @property
    def is_in_process(self) -> bool:
        return self.base_url is None

    def request(
        self,
        method: str,
        path: str,
        json_data: Any = None,
        headers: Optional[dict[str, str]] = None,
    ) -> tuple[int, Any]:
        """Sends an HTTP request and returns (status_code, json_body)."""
        req_headers: dict[str, str] = dict(headers or {})
        if self.api_key and "authorization" not in {k.lower(): v for k, v in req_headers.items()}:
            req_headers["Authorization"] = f"Bearer {self.api_key}"

        if self._asgi_client is not None:
            resp = self._asgi_client.request(
                method=method,
                path=path,
                json_data=json_data,
                headers=req_headers,
            )
            data = resp.json() if resp.body else None
            return resp.status_code, data

        assert self.base_url is not None
        url = f"{self.base_url}{path}"
        data_bytes: Optional[bytes] = None
        if json_data is not None:
            data_bytes = json.dumps(json_data).encode("utf-8")
            req_headers["Content-Type"] = "application/json"

        req = urllib.request.Request(
            url=url,
            data=data_bytes,
            headers=req_headers,
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read()
                data = json.loads(body.decode("utf-8")) if body else None
                return resp.status, data
        except urllib.error.HTTPError as he:
            body = he.read()
            data = json.loads(body.decode("utf-8")) if body else None
            return he.code, data
        except Exception as exc:
            return 503, {"error": {"code": "CONNECTION_ERROR", "message": str(exc)}}

    def get_health(self) -> dict[str, Any]:
        """Queries /v1/health/readiness to verify DB and Routing state."""
        code, data = self.request("GET", "/v1/health/readiness")
        if code == 200 and isinstance(data, dict):
            return data
        elif isinstance(data, dict):
            return data
        return {"ready": False, "status": "unreachable", "components": {}}

    def register_vehicle(
        self,
        vehicle_id: str,
        driver_id: str,
        total_seat_capacity: int,
        latitude: float,
        longitude: float,
        is_active: bool = True,
        luggage_capacity_units: int = 0,
    ) -> tuple[int, Any]:
        payload = {
            "vehicle_id": vehicle_id,
            "driver_id": driver_id,
            "total_seat_capacity": total_seat_capacity,
            "current_location": {"latitude": latitude, "longitude": longitude},
            "is_active": is_active,
            "luggage_capacity_units": luggage_capacity_units,
        }
        return self.request("POST", "/v1/vehicles", json_data=payload)

    def submit_ride_request(
        self,
        user_id: str,
        pickup_lat: float,
        pickup_lon: float,
        dropoff_lat: float,
        dropoff_lon: float,
        seat_count: int = 1,
        earliest_pickup_time: Optional[int] = None,
        latest_dropoff_time: Optional[int] = None,
        request_id: Optional[str] = None,
        direct_distance_meters: Optional[int] = None,
        direct_duration_seconds: Optional[int] = None,
    ) -> tuple[int, Any]:
        now = int(time.time())
        p_time = earliest_pickup_time if earliest_pickup_time is not None else now
        # Default generous dropoff window (now + 1 hour) if not specified
        d_time = latest_dropoff_time if latest_dropoff_time is not None else p_time + 3600

        payload: dict[str, Any] = {
            "user_id": user_id,
            "pickup_location": {"latitude": pickup_lat, "longitude": pickup_lon},
            "dropoff_location": {"latitude": dropoff_lat, "longitude": dropoff_lon},
            "seat_count": seat_count,
            "earliest_pickup_time": p_time,
            "latest_dropoff_time": d_time,
        }
        if request_id:
            payload["request_id"] = request_id
        if direct_distance_meters is not None:
            payload["direct_distance_meters"] = direct_distance_meters
        if direct_duration_seconds is not None:
            payload["direct_duration_seconds"] = direct_duration_seconds

        return self.request("POST", "/v1/requests", json_data=payload)

    def run_dispatch(
        self,
        current_time: Optional[int] = None,
        deadline_seconds: float = 0.500,
        cycle_id: Optional[str] = None,
        idempotency_token: Optional[str] = None,
    ) -> tuple[int, Any]:
        eff_time = current_time if current_time is not None else int(time.time())
        payload = {
            "current_time": eff_time,
            "deadline_seconds": deadline_seconds,
            "cycle_id": cycle_id,
            "idempotency_token": idempotency_token,
        }
        headers = {}
        if idempotency_token:
            headers["Idempotency-Key"] = idempotency_token
        return self.request("POST", "/v1/dispatch", json_data=payload, headers=headers)

    def get_vehicle(self, vehicle_id: str) -> tuple[int, Any]:
        return self.request("GET", f"/v1/vehicles/{vehicle_id}")

    def get_request(self, request_id: str) -> tuple[int, Any]:
        return self.request("GET", f"/v1/requests/{request_id}")

    def get_ride(self, ride_id: str) -> tuple[int, Any]:
        return self.request("GET", f"/v1/rides/{ride_id}")

    def cancel_request(
        self,
        request_id: str,
        reason: Optional[str] = None,
    ) -> tuple[int, Any]:
        payload = {"reason": reason} if reason else {}
        return self.request("POST", f"/v1/requests/{request_id}/cancel", json_data=payload)

    def register_host_ride(
        self,
        driver_id: str,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
        scheduled_departure_time: int,
        available_seats: int = 3,
        max_detour_seconds: int = 600,
        vehicle_id: Optional[str] = None,
    ) -> tuple[int, Any]:
        payload = {
            "driver_id": driver_id,
            "origin": {"latitude": origin_lat, "longitude": origin_lon},
            "destination": {"latitude": dest_lat, "longitude": dest_lon},
            "scheduled_departure_time": scheduled_departure_time,
            "available_seats": available_seats,
            "max_detour_seconds": max_detour_seconds,
        }
        if vehicle_id:
            payload["vehicle_id"] = vehicle_id
        return self.request("POST", "/v1/host-rides", json_data=payload)

    def get_host_ride(self, ride_id: str) -> tuple[int, Any]:
        return self.request("GET", f"/v1/host-rides/{ride_id}")

    def match_host_ride(self, ride_id: str, request_id: Optional[str] = None) -> tuple[int, Any]:
        payload = {"request_id": request_id} if request_id else {}
        return self.request("POST", f"/v1/host-rides/{ride_id}/match", json_data=payload)

    def create_proposal(
        self,
        ride_id: str,
        request_id: str,
        seat_count: int = 1,
        current_time: Optional[int] = None,
    ) -> tuple[int, Any]:
        payload = {
            "ride_id": ride_id,
            "request_id": request_id,
            "seat_count": seat_count,
        }
        return self.request("POST", "/v1/proposals", json_data=payload)

    def accept_proposal(
        self,
        proposal_id: str,
        user_id: Optional[str] = None,
        role: Optional[str] = None,
        current_time: Optional[int] = None,
    ) -> tuple[int, Any]:
        payload: dict[str, Any] = {}
        if user_id:
            payload["user_id"] = user_id
        if role:
            payload["role"] = role
        if current_time is not None:
            payload["current_time"] = current_time
        return self.request("POST", f"/v1/proposals/{proposal_id}/accept", json_data=payload)

    def update_vehicle_progress(
        self,
        vehicle_id: str,
        latitude: float,
        longitude: float,
        ride_id: Optional[str] = None,
        completed_stop_ids: Optional[Sequence[str]] = None,
        current_time: Optional[int] = None,
    ) -> tuple[int, Any]:
        payload: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "notes": "Simulated progress marker (not live GPS tracking)",
        }
        if ride_id:
            payload["ride_id"] = ride_id
        if completed_stop_ids:
            payload["completed_stop_ids"] = list(completed_stop_ids)
        if current_time is not None:
            payload["current_time"] = current_time
        return self.request("POST", f"/v1/vehicles/{vehicle_id}/location", json_data=payload)

    def evaluate_en_route_join(
        self,
        ride_id: str,
        request_id: str,
        current_time: Optional[int] = None,
    ) -> tuple[int, Any]:
        payload: dict[str, Any] = {"request_id": request_id}
        if current_time is not None:
            payload["current_time"] = current_time
        return self.request("POST", f"/v1/rides/{ride_id}/en-route-join", json_data=payload)

    def get_proposal(
        self,
        proposal_id: str,
        user_id: Optional[str] = None,
    ) -> tuple[int, Any]:
        headers = {"X-User-Id": user_id} if user_id else None
        return self.request("GET", f"/v1/proposals/{proposal_id}", headers=headers)

    def decline_proposal(
        self,
        proposal_id: str,
        user_id: Optional[str] = None,
        role: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> tuple[int, Any]:
        payload: dict[str, Any] = {}
        if user_id:
            payload["user_id"] = user_id
        if role:
            payload["role"] = role
        if reason:
            payload["reason"] = reason
        return self.request("POST", f"/v1/proposals/{proposal_id}/decline", json_data=payload)

    def update_vehicle_status(
        self,
        vehicle_id: str,
        is_active: bool,
    ) -> tuple[int, Any]:
        return self.request("PATCH", f"/v1/vehicles/{vehicle_id}/status", json_data={"is_active": is_active})

    def list_active_rides(self, limit: int = 50) -> list[dict[str, Any]]:
        """Returns active/scheduled rides directly from storage if in-process, or empty list."""
        if self._in_process_service and hasattr(self._in_process_service, "storage"):
            rides = self._in_process_service.storage.get_active_rides(limit=limit)
            return [
                {
                    "ride_id": r.ride_id,
                    "driver_id": r.driver_id,
                    "vehicle_id": r.vehicle_id,
                    "status": r.lifecycle_status.value,
                    "active_passengers": r.active_passenger_count,
                    "stops_count": len(r.stops),
                    "is_host_ride": r.is_host_ride,
                    "origin": (
                        {"latitude": r.origin_location.latitude, "longitude": r.origin_location.longitude}
                        if r.origin_location else None
                    ),
                    "destination": (
                        {"latitude": r.destination_location.latitude, "longitude": r.destination_location.longitude}
                        if r.destination_location else None
                    ),
                    "max_detour_seconds": r.max_detour_seconds,
                    "total_vmt_meters": r.total_vmt_meters,
                    "scheduled_departure_time": r.scheduled_departure_time,
                }
                for r in rides
            ]
        return []

    def list_active_vehicles(self, limit: int = 50) -> list[dict[str, Any]]:
        """Returns active vehicles directly from storage if in-process, or empty list."""
        if self._in_process_service and hasattr(self._in_process_service, "storage"):
            vehs = self._in_process_service.storage.get_active_vehicles(limit=limit)
            return [
                {
                    "vehicle_id": v.vehicle_id,
                    "driver_id": v.driver_id,
                    "total_seat_capacity": v.total_seat_capacity,
                    "current_location": {
                        "latitude": v.current_location.latitude,
                        "longitude": v.current_location.longitude,
                    },
                    "is_active": v.is_active,
                }
                for v in vehs
            ]
        return []

    def list_pending_requests(self, limit: int = 50) -> list[dict[str, Any]]:
        """Returns pending requests directly from storage if in-process, or empty list."""
        if self._in_process_service and hasattr(self._in_process_service, "storage"):
            reqs = self._in_process_service.storage.get_pending_requests(limit=limit)
            return [
                {
                    "request_id": req.request_id,
                    "user_id": req.user_id,
                    "seat_count": req.seat_count,
                    "pickup": {
                        "latitude": req.pickup_location.latitude,
                        "longitude": req.pickup_location.longitude,
                    },
                    "dropoff": {
                        "latitude": req.dropoff_location.latitude,
                        "longitude": req.dropoff_location.longitude,
                    },
                    "earliest_pickup_time": req.earliest_pickup_time,
                    "latest_dropoff_time": req.latest_dropoff_time,
                    "status": req.status.value,
                }
                for req in reqs
            ]
        return []
