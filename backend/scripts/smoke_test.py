#!/usr/bin/env python3
"""
Smoke test suite for Pool Engine.

Verifies end-to-end service readiness, authentication boundaries,
vehicle registration, request submission, dispatch cycle execution,
and request cancellation.

Can run either against an in-process ASGI application instance or against
a live network target URL.
"""

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Mapping, Optional, Sequence

# Ensure src is on sys.path if invoked directly
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from engine.service.app import create_app
from engine.service.client import AsgiResponse, AsgiTestClient
from engine.service.security import sanitize_sensitive_strings

logger = logging.getLogger("smoke_test")


class SmokeTestFailure(Exception):
    """Raised when a smoke test check fails."""


class HttpResponse:
    def __init__(self, status_code: int, headers: dict[str, str], body: bytes) -> None:
        self.status_code = status_code
        self.headers = headers
        self.body = body

    def json(self) -> Any:
        if not self.body:
            return None
        return json.loads(self.body.decode("utf-8"))


class SmokeClient:
    """Unified client abstracting network HTTP vs in-process ASGI calls."""

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        timeout: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.is_in_process = (self.base_url.lower() in ("in-process", "inproc", ""))
        self._asgi_client: Optional[AsgiTestClient] = None

        if self.is_in_process:
            app = create_app()
            self._asgi_client = AsgiTestClient(app)

    def request(
        self,
        method: str,
        path: str,
        json_data: Any = None,
        auth_token: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> HttpResponse:
        req_headers: dict[str, str] = dict(headers or {})
        token = auth_token if auth_token is not None else self.api_key
        if token and "authorization" not in {k.lower(): v for k, v in req_headers.items()}:
            req_headers["Authorization"] = f"Bearer {token}"

        if self.is_in_process:
            assert self._asgi_client is not None
            resp = self._asgi_client.request(
                method=method,
                path=path,
                headers=req_headers,
                json_data=json_data,
            )
            return HttpResponse(
                status_code=resp.status_code,
                headers=resp.headers,
                body=resp.body,
            )
        else:
            url = f"{self.base_url}{path}"
            data_bytes: Optional[bytes] = None
            if json_data is not None:
                data_bytes = json.dumps(json_data).encode("utf-8")
                req_headers["Content-Type"] = "application/json"

            req = urllib.request.Request(
                url=url,
                data=data_bytes,
                headers=req_headers,
                method=method,
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    resp_headers = {k: v for k, v in resp.headers.items()}
                    return HttpResponse(
                        status_code=resp.status,
                        headers=resp_headers,
                        body=resp.read(),
                    )
            except urllib.error.HTTPError as he:
                resp_headers = {k: v for k, v in he.headers.items()}
                return HttpResponse(
                    status_code=he.code,
                    headers=resp_headers,
                    body=he.read(),
                )


def run_smoke_test(
    base_url: str = "in-process",
    api_key: Optional[str] = None,
    timeout: float = 5.0,
) -> int:
    """
    Execute end-to-end smoke test sequence.

    Returns:
        0 on success, 1 on failure.
    """
    start_time = time.monotonic()
    target_desc = "in-process ASGI app" if base_url in ("in-process", "") else base_url
    logger.info("Starting Pool Engine smoke test against %s...", target_desc)

    client = SmokeClient(base_url=base_url, api_key=api_key, timeout=timeout)

    try:
        # Step 1: Liveness probe
        step_start = time.monotonic()
        resp = client.request("GET", "/v1/health/liveness")
        if resp.status_code != 200:
            raise SmokeTestFailure(f"Liveness check failed with status {resp.status_code}: {resp.body.decode('utf-8')}")
        body = resp.json()
        if body.get("status") != "alive":
            raise SmokeTestFailure(f"Liveness status expected 'alive', got '{body.get('status')}'")
        logger.info("[PASS] Liveness probe OK (took %.3fs)", time.monotonic() - step_start)

        # Step 2: Readiness probe
        step_start = time.monotonic()
        resp = client.request("GET", "/v1/health/readiness")
        if resp.status_code != 200:
            raise SmokeTestFailure(f"Readiness check failed with status {resp.status_code}: {resp.body.decode('utf-8')}")
        body = resp.json()
        if not body.get("ready"):
            raise SmokeTestFailure(f"Readiness check reported not ready: {body}")
        logger.info("[PASS] Readiness probe OK (components=%s, took %.3fs)", body.get("components"), time.monotonic() - step_start)

        # Step 3: Auth boundaries (if api_key supplied)
        if api_key:
            step_start = time.monotonic()
            unauth_resp = client.request("GET", "/v1/requests/dummy-id", auth_token="")
            if unauth_resp.status_code != 401:
                raise SmokeTestFailure(f"Auth boundary failed: unauthenticated request returned {unauth_resp.status_code}, expected 401")

            badauth_resp = client.request("GET", "/v1/requests/dummy-id", auth_token="invalid-token-1234")
            if badauth_resp.status_code != 401:
                raise SmokeTestFailure(f"Auth boundary failed: invalid token returned {badauth_resp.status_code}, expected 401")
            logger.info("[PASS] Authentication boundary checks OK (took %.3fs)", time.monotonic() - step_start)

        # Step 4: Register vehicle
        step_start = time.monotonic()
        veh_id = f"smoke-veh-{uuid.uuid4().hex[:8]}"
        driver_id = f"smoke-drv-{uuid.uuid4().hex[:8]}"
        veh_payload = {
            "vehicle_id": veh_id,
            "driver_id": driver_id,
            "total_seat_capacity": 4,
            "luggage_capacity_units": 2,
            "current_location": {
                "latitude": 40.7580,
                "longitude": -73.9855,
            },
            "is_active": True,
        }
        resp = client.request("POST", "/v1/vehicles", json_data=veh_payload)
        if resp.status_code != 201:
            raise SmokeTestFailure(f"Vehicle registration failed ({resp.status_code}): {resp.body.decode('utf-8')}")
        v_data = resp.json()
        if v_data.get("vehicle_id") != veh_id:
            raise SmokeTestFailure(f"Vehicle ID mismatch: expected {veh_id}, got {v_data.get('vehicle_id')}")
        logger.info("[PASS] Vehicle registration OK (%s, took %.3fs)", veh_id, time.monotonic() - step_start)

        # Step 5: Submit ride request
        step_start = time.monotonic()
        req_id = f"smoke-req-{uuid.uuid4().hex[:8]}"
        req_payload = {
            "request_id": req_id,
            "user_id": f"smoke-user-{uuid.uuid4().hex[:8]}",
            "pickup_location": {
                "latitude": 40.7582,
                "longitude": -73.9850,
            },
            "dropoff_location": {
                "latitude": 40.7620,
                "longitude": -73.9800,
            },
            "seat_count": 1,
            "earliest_pickup_time": 1000,
            "latest_dropoff_time": 4000,
        }
        resp = client.request("POST", "/v1/requests", json_data=req_payload)
        if resp.status_code != 201:
            raise SmokeTestFailure(f"Request submission failed ({resp.status_code}): {resp.body.decode('utf-8')}")
        r_data = resp.json()
        if r_data.get("request_id") != req_id:
            raise SmokeTestFailure(f"Request ID mismatch: expected {req_id}, got {r_data.get('request_id')}")
        logger.info("[PASS] Ride request submission OK (%s, status=%s, took %.3fs)", req_id, r_data.get("status"), time.monotonic() - step_start)

        # Step 6: Query request state
        step_start = time.monotonic()
        resp = client.request("GET", f"/v1/requests/{req_id}")
        if resp.status_code != 200:
            raise SmokeTestFailure(f"Request retrieval failed ({resp.status_code}): {resp.body.decode('utf-8')}")
        logger.info("[PASS] Request state query OK (took %.3fs)", time.monotonic() - step_start)

        # Step 7: Run dispatch cycle
        step_start = time.monotonic()
        dispatch_payload = {
            "current_time": 1000,
            "deadline_seconds": 1.0,
        }
        resp = client.request("POST", "/v1/dispatch", json_data=dispatch_payload)
        if resp.status_code != 200:
            raise SmokeTestFailure(f"Dispatch run failed ({resp.status_code}): {resp.body.decode('utf-8')}")
        d_data = resp.json()
        assigned_cnt = len(d_data.get("committed_assignments", []))
        logger.info(
            "[PASS] Dispatch cycle OK (assignments=%d, duration=%.2fms, took %.3fs)",
            assigned_cnt,
            d_data.get("cycle_duration_ms", 0.0),
            time.monotonic() - step_start,
        )

        # Step 8: Cancel ride request
        step_start = time.monotonic()
        cancel_payload = {
            "reason": "Smoke test completed successfully",
            "idempotency_token": f"idemp-{uuid.uuid4().hex[:8]}",
        }
        resp = client.request("POST", f"/v1/requests/{req_id}/cancel", json_data=cancel_payload)
        if resp.status_code != 200:
            raise SmokeTestFailure(f"Request cancellation failed ({resp.status_code}): {resp.body.decode('utf-8')}")
        c_data = resp.json()
        if c_data.get("status") != "CANCELLED":
            raise SmokeTestFailure(f"Expected status CANCELLED, got {c_data.get('status')}")
        logger.info("[PASS] Request cancellation OK (status=%s, took %.3fs)", c_data.get("status"), time.monotonic() - step_start)

        total_elapsed = time.monotonic() - start_time
        logger.info("=== All smoke tests passed successfully in %.3fs ===", total_elapsed)
        return 0

    except SmokeTestFailure as stf:
        logger.error("[FAIL] Smoke test failed: %s", sanitize_sensitive_strings(str(stf)))
        return 1
    except Exception as exc:
        logger.error("[ERROR] Unexpected exception during smoke test: %s", sanitize_sensitive_strings(str(exc)))
        return 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entrypoint for Pool Engine smoke test."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Run end-to-end smoke test against Pool Engine."
    )
    parser.add_argument(
        "--base-url",
        dest="base_url",
        type=str,
        default="in-process",
        help="Target base URL (e.g. http://127.0.0.1:8000) or 'in-process' (default: in-process).",
    )
    parser.add_argument(
        "--api-key",
        dest="api_key",
        type=str,
        default=None,
        help="Optional API key for authenticated endpoints.",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout",
        type=float,
        default=5.0,
        help="Timeout in seconds per HTTP request (default: 5.0).",
    )

    args = parser.parse_args(argv)
    return run_smoke_test(
        base_url=args.base_url,
        api_key=args.api_key,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    sys.exit(main())
