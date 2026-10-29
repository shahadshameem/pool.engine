"""
Native Windows / Staging Server Runner for Pool Engine.

Coordinates environment loading, dependency pre-flight verification,
and launches the Pool Engine ASGI service on 127.0.0.1:8000.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_REGIONS_CONFIG = "config/regions.json"
DEFAULT_PORT = 8000
DEFAULT_HOST = "127.0.0.1"


def check_tcp_port(host: str, port: int, timeout: float = 1.0) -> bool:
    """Verifies that a target TCP port is listening."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        sock.close()
        return True
    except (OSError, TimeoutError):
        return False


def check_http_endpoint(url: str, timeout: float = 2.0) -> tuple[bool, str]:
    """Probes an HTTP endpoint for 200 OK status."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PoolEngine-StagingProbe/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200, f"HTTP {resp.status}"
    except Exception as exc:
        return False, str(exc)


def run_preflight_checks(
    regions_file: str,
    db_url: str | None = None,
) -> bool:
    """Validates external dependencies prior to launching staging API."""
    print("--- Staging Dependency Pre-Flight Verification ---")
    all_ok = True

    # 1. Regions configuration
    if not os.path.exists(regions_file):
        print(f"FAIL: Regions config file '{regions_file}' does not exist.")
        return False

    with open(regions_file, "r", encoding="utf-8") as f:
        regions = json.load(f)

    print(f"PASS: Loaded regions configuration ({len(regions)} regions configured).")

    # 2. Check each regional OSRM backend
    for r in regions:
        r_id = r["region_id"]
        endpoint = r["endpoint_url"]
        probe_coord = r.get("probe_coordinate", {})
        lat = probe_coord.get("latitude")
        lon = probe_coord.get("longitude")

        if lat is not None and lon is not None:
            probe_url = f"{endpoint}/nearest/v1/driving/{lon:.6f},{lat:.6f}?number=1"
        else:
            probe_url = f"{endpoint}/v1/health"

        ok, msg = check_http_endpoint(probe_url)
        if ok:
            print(f"PASS: Regional OSRM '{r_id}' at {endpoint} is healthy.")
        else:
            print(f"FAIL: Regional OSRM '{r_id}' at {endpoint} probe failed: {msg}")
            all_ok = False

    # 3. Check PostgreSQL if configured
    if db_url:
        parsed_db = urllib.parse.urlsplit(db_url)
        db_host = parsed_db.hostname or "127.0.0.1"
        if db_host == "localhost":
            db_host = "127.0.0.1"
        db_port = parsed_db.port or 5432
        pg_ok = check_tcp_port(db_host, db_port)
        if pg_ok:
            print(f"PASS: PostgreSQL service at {db_host}:{db_port} is reachable.")
        else:
            print(f"FAIL: PostgreSQL service at {db_host}:{db_port} is unreachable.")
            all_ok = False

    return all_ok


def start_staging_service(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    regions_file: str = DEFAULT_REGIONS_CONFIG,
    db_url: str = "postgresql://postgres:postgres@127.0.0.1:5433/pool_engine_test",
) -> None:
    """Launches the Uvicorn ASGI server with staging configuration."""
    os.environ["ENVIRONMENT"] = "staging"
    os.environ["SERVICE_HOST"] = host
    os.environ["SERVICE_PORT"] = str(port)
    os.environ["ROUTING_REGIONS_FILE"] = regions_file
    os.environ["REQUIRE_REAL_ROUTING"] = "true"
    os.environ["STRICT_ROUTING_READINESS"] = "false"
    os.environ["DATABASE_URL"] = db_url
    os.environ["REQUIRE_PERSISTENT_STORAGE"] = "true"
    os.environ["AUTH_ENABLED"] = "false"
    os.environ["MASK_COORDINATES_IN_LOGS"] = "true"
    os.environ["ENABLE_TELEMETRY"] = "true"

    import uvicorn
    from engine.service.app import create_app
    from engine.service.service import build_service_from_env

    print(f"\nStarting Pool Engine Staging API on http://{host}:{port}...")
    app = create_app(build_service_from_env())
    uvicorn.run(app, host=host, port=port, log_level="info")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pool Engine Staging Environment Runner")
    parser.add_argument("--check-only", action="store_true", help="Run preflight checks only")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Host interface (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port (default: {DEFAULT_PORT})")
    parser.add_argument("--regions-file", default=DEFAULT_REGIONS_CONFIG, help="Path to regions JSON file")
    parser.add_argument(
        "--db-url",
        default="postgresql://postgres:postgres@127.0.0.1:5433/pool_engine_test",
        help="PostgreSQL connection string",
    )

    args = parser.parse_args()

    healthy = run_preflight_checks(args.regions_file, args.db_url)
    if args.check_only:
        return 0 if healthy else 1

    if not healthy:
        print("ERROR: Pre-flight checks failed. Aborting service launch.", file=sys.stderr)
        return 1

    try:
        start_staging_service(args.host, args.port, args.regions_file, args.db_url)
        return 0
    except KeyboardInterrupt:
        print("\nStaging service terminated by user.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
