"""
Reproducible compilation and verification utility for Kerala OSRM road network graphs.

Usage:
    # 1. Check graph status or probe running Kerala OSRM instance:
    uv run python scripts/prepare_kerala_graph.py --verify-only --port 5001

    # 2. Compile an approved Kerala OSM extract into an OSRM Contraction Hierarchies (CH) graph:
    uv run python scripts/prepare_kerala_graph.py --osm-path path/to/kerala.osm.pbf

    # 3. Compile with SHA256 integrity verification:
    uv run python scripts/prepare_kerala_graph.py --osm-path path/to/kerala.osm.pbf --checksum <sha256>

Note: Per project safety guidelines, this script strictly DOES NOT perform automatic
downloads of external map data. An approved dataset must be placed locally.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_TOOLCHAIN_DIR = Path(
    os.environ.get("LOCALAPPDATA", "C:\\Users\\shaha\\AppData\\Local")
) / "osrm_portable" / "osrm-v26.10.0-win32-x64-Release"

DEFAULT_OUTPUT_DIR = Path(
    os.environ.get("LOCALAPPDATA", "C:\\Users\\shaha\\AppData\\Local")
) / "osrm_portable"

# Central Thiruvananthapuram (Secretariat / Central Station)
KERALA_PROBE_LAT = 8.5241
KERALA_PROBE_LON = 76.9366


def compute_sha256(file_path: Path) -> str:
    """Computes SHA256 digest of a local file in 64KB chunks."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify_osrm_service(port: int = 5001, timeout: float = 2.0) -> bool:
    """Probes the OSRM /nearest endpoint on the target port to verify road graph readiness."""
    url = f"http://127.0.0.1:{port}/nearest/v1/driving/{KERALA_PROBE_LON:.6f},{KERALA_PROBE_LAT:.6f}?number=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PoolEngine-HealthProbe/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode("utf-8"))
                if body.get("code") == "Ok" and body.get("waypoints"):
                    print(f"PASS: Kerala OSRM service on port {port} is healthy and responsive.")
                    print(f"      Nearest snapped waypoint: {body['waypoints'][0].get('name') or 'Unnamed road'}")
                    return True
    except Exception as exc:
        print(f"FAIL: Unable to reach Kerala OSRM service on port {port}: {exc}")
    return False


def compile_graph(
    osm_path: Path,
    output_dir: Path,
    toolchain_dir: Path,
    profile_path: Path,
    expected_checksum: str | None = None,
) -> Path:
    """Executes osrm-extract and osrm-contract to build an OSRM CH graph."""
    if not osm_path.exists():
        raise FileNotFoundError(f"Input OSM file not found: {osm_path}")

    if expected_checksum:
        print(f"Verifying SHA256 checksum for {osm_path}...")
        actual_checksum = compute_sha256(osm_path)
        if actual_checksum.lower() != expected_checksum.lower():
            raise ValueError(
                f"Checksum mismatch for {osm_path}!\n"
                f"  Expected: {expected_checksum}\n"
                f"  Actual:   {actual_checksum}"
            )
        print("Checksum verified successfully.")

    extract_exe = toolchain_dir / "osrm-extract.exe"
    contract_exe = toolchain_dir / "osrm-contract.exe"

    if not extract_exe.exists():
        raise FileNotFoundError(f"osrm-extract executable not found at: {extract_exe}")
    if not contract_exe.exists():
        raise FileNotFoundError(f"osrm-contract executable not found at: {contract_exe}")
    if not profile_path.exists():
        raise FileNotFoundError(f"Lua routing profile not found at: {profile_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    target_base = output_dir / "kerala.osrm"

    print("\n--- Step 1: Running osrm-extract ---")
    extract_cmd = [
        str(extract_exe),
        "-p",
        str(profile_path),
        str(osm_path),
    ]
    print(f"Executing: {' '.join(extract_cmd)}")
    res = subprocess.run(extract_cmd, cwd=str(output_dir), check=False)
    if res.returncode != 0:
        raise RuntimeError(f"osrm-extract failed with exit code {res.returncode}")

    print("\n--- Step 2: Running osrm-contract ---")
    contract_cmd = [
        str(contract_exe),
        str(target_base),
    ]
    print(f"Executing: {' '.join(contract_cmd)}")
    res = subprocess.run(contract_cmd, cwd=str(output_dir), check=False)
    if res.returncode != 0:
        raise RuntimeError(f"osrm-contract failed with exit code {res.returncode}")

    hsgr_path = output_dir / "kerala.osrm.hsgr"
    if not hsgr_path.exists():
        raise RuntimeError(f"Compiled graph hierarchy file missing: {hsgr_path}")

    print(f"\nSUCCESS: Kerala OSRM graph successfully compiled at {target_base}")
    print(f"Run the following daemon to serve Kerala routing on port 5001:")
    print(f'  & "{toolchain_dir / "osrm-routed.exe"}" -a CH -p 5001 -t 4 "{target_base}"')
    return target_base


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile and verify Kerala OSRM road network graphs for Pool Engine."
    )
    parser.add_argument(
        "--osm-path",
        type=Path,
        default=None,
        help="Path to approved local Kerala .osm.pbf or .osm extract.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for compiled graph artifacts (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--toolchain-dir",
        type=Path,
        default=DEFAULT_TOOLCHAIN_DIR,
        help=f"Directory containing OSRM binaries (default: {DEFAULT_TOOLCHAIN_DIR})",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=None,
        help="Path to Lua profile (default: toolchain_dir/profiles/car.lua)",
    )
    parser.add_argument(
        "--checksum",
        type=str,
        default=None,
        help="Expected SHA256 checksum for the input OSM dataset.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5001,
        help="OSRM HTTP port to probe or serve (default: 5001)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only probe the running OSRM instance without compiling.",
    )

    args = parser.parse_args()

    if args.verify_only:
        is_healthy = verify_osrm_service(port=args.port)
        return 0 if is_healthy else 1

    if args.osm_path is None:
        print("ERROR: --osm-path argument is required for graph compilation.")
        print("\nNotice: Map data downloads require explicit user authorization.")
        print("Approved dataset specification for Kerala:")
        print("  - Source: Geofabrik Southern India (southern-zone-latest.osm.pbf) or BBBike Thiruvananthapuram")
        print("  - License: OpenStreetMap contributors (ODbL)")
        print("  - Target path: C:\\Users\\shaha\\AppData\\Local\\osrm_portable\\kerala.osm.pbf")
        print(f"\nTo check current service status on port {args.port}, run with --verify-only.")
        return 1

    profile_path = args.profile or (args.toolchain_dir / "profiles" / "car.lua")

    try:
        compile_graph(
            osm_path=args.osm_path,
            output_dir=args.output_dir,
            toolchain_dir=args.toolchain_dir,
            profile_path=profile_path,
            expected_checksum=args.checksum,
        )
        return 0
    except Exception as exc:
        print(f"Compilation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
