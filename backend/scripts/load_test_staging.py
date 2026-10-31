"""
Load-testing engine for Pool Engine Multi-Region Staging Deployment.
Simulates realistic passenger ride-request workloads with distinct regional
distributions, controlled invalid queries, and high-resolution latency tracking.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import random
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass


# Realistic Manhattan landmark coordinates
NYC_LANDMARKS = [
    {"name": "Times Square", "lat": 40.7580, "lon": -73.9855},
    {"name": "Wall Street", "lat": 40.7070, "lon": -74.0090},
    {"name": "Central Park South", "lat": 40.7660, "lon": -73.9770},
    {"name": "SoHo", "lat": 40.7233, "lon": -74.0030},
    {"name": "Columbia University", "lat": 40.8075, "lon": -73.9626},
    {"name": "Empire State Building", "lat": 40.7484, "lon": -73.9857},
    {"name": "Grand Central", "lat": 40.7527, "lon": -73.9772},
    {"name": "Chelsea Market", "lat": 40.7424, "lon": -74.0061},
    {"name": "Penn Station", "lat": 40.7505, "lon": -73.9934},
    {"name": "Battery Park", "lat": 40.7033, "lon": -74.0170},
]

# Realistic Kerala (Thiruvananthapuram pilot) landmark coordinates
KL_LANDMARKS = [
    {"name": "Secretariat", "lat": 8.5030, "lon": 76.9530},
    {"name": "Central Station", "lat": 8.4875, "lon": 76.9528},
    {"name": "Kovalam Beach", "lat": 8.4000, "lon": 76.9780},
    {"name": "Technopark Phase 1", "lat": 8.5560, "lon": 76.8820},
    {"name": "TRV Airport", "lat": 8.4821, "lon": 76.9199},
    {"name": "Kazhakkoottam", "lat": 8.5686, "lon": 76.8722},
    {"name": "East Fort", "lat": 8.4831, "lon": 76.9482},
    {"name": "Museum & Zoo", "lat": 8.5097, "lon": 76.9566},
    {"name": "Medical College", "lat": 8.5230, "lon": 76.9270},
    {"name": "Pattom", "lat": 8.5233, "lon": 76.9430},
]

# Controlled Out-of-Region / Invalid Coordinate Sets
INVALID_COORDINATES = [
    {"name": "Albany NY (Out of Manhattan)", "pickup": (42.6526, -73.7562), "drop": (40.7580, -73.9855)},
    {"name": "Kochi (Out of TVM Pilot)", "pickup": (9.9312, 76.2673), "drop": (8.5030, 76.9530)},
    {"name": "Cross-Region (NYC -> KL)", "pickup": (40.7580, -73.9855), "drop": (8.4875, 76.9528)},
    {"name": "Offshore Arabian Sea", "pickup": (8.4000, 76.2000), "drop": (8.5030, 76.9530)},
]


@dataclass
class RequestRecord:
    req_id: str
    region: str
    is_valid_route: bool
    status_code: int
    latency_ms: float
    distance_meters: float | None = None
    duration_seconds: float | None = None
    error: str | None = None


def generate_workload_item(idx: int, invalid_ratio: float = 0.10) -> tuple[dict, str, bool]:
    """Generates a request payload: ~45% Manhattan, ~45% Kerala, ~10% controlled invalid."""
    r = random.random()
    if r < invalid_ratio:
        item = random.choice(INVALID_COORDINATES)
        payload = {
            "request_id": f"load-inv-{idx:06d}",
            "user_id": f"user-inv-{idx:04d}",
            "pickup_location": {"latitude": item["pickup"][0], "longitude": item["pickup"][1]},
            "dropoff_location": {"latitude": item["drop"][0], "longitude": item["drop"][1]},
            "seat_count": 1,
            "earliest_pickup_time": 1700000000,
            "latest_dropoff_time": 1700003600,
        }
        return payload, "invalid_or_out_of_region", False

    # Split equally between NYC and Kerala
    if random.random() < 0.5:
        p1, p2 = random.sample(NYC_LANDMARKS, 2)
        payload = {
            "request_id": f"load-nyc-{idx:06d}",
            "user_id": f"user-nyc-{idx:04d}",
            "pickup_location": {"latitude": p1["lat"], "longitude": p1["lon"]},
            "dropoff_location": {"latitude": p2["lat"], "longitude": p2["lon"]},
            "seat_count": 1,
            "earliest_pickup_time": 1700000000,
            "latest_dropoff_time": 1700003600,
        }
        return payload, "us-nyc-manhattan", True
    else:
        p1, p2 = random.sample(KL_LANDMARKS, 2)
        payload = {
            "request_id": f"load-kl-{idx:06d}",
            "user_id": f"user-kl-{idx:04d}",
            "pickup_location": {"latitude": p1["lat"], "longitude": p1["lon"]},
            "dropoff_location": {"latitude": p2["lat"], "longitude": p2["lon"]},
            "seat_count": 1,
            "earliest_pickup_time": 1700000000,
            "latest_dropoff_time": 1700003600,
        }
        return payload, "in-kl-tvm", True


def execute_request(base_url: str, item: tuple[dict, str, bool], timeout: float = 3.0) -> RequestRecord:
    payload, region, is_valid = item
    url = f"{base_url}/v1/requests"
    req_body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_body,
        headers={"Content-Type": "application/json", "User-Agent": "PoolEngine-LoadTest/1.0"},
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            data = json.loads(resp.read().decode("utf-8"))
            return RequestRecord(
                req_id=payload["request_id"],
                region=region,
                is_valid_route=is_valid,
                status_code=resp.status,
                latency_ms=elapsed_ms,
                distance_meters=data.get("direct_distance_meters"),
                duration_seconds=data.get("direct_duration_seconds"),
            )
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        err_msg = exc.read().decode("utf-8", errors="replace")
        return RequestRecord(
            req_id=payload["request_id"],
            region=region,
            is_valid_route=is_valid,
            status_code=exc.code,
            latency_ms=elapsed_ms,
            error=err_msg[:200],
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return RequestRecord(
            req_id=payload["request_id"],
            region=region,
            is_valid_route=is_valid,
            status_code=0,
            latency_ms=elapsed_ms,
            error=str(exc)[:200],
        )


def run_workload(
    base_url: str,
    concurrency: int,
    total_requests: int,
    duration_seconds: float | None = None,
    invalid_ratio: float = 0.10,
    seed: int = 42,
) -> list[RequestRecord]:
    random.seed(seed)
    records: list[RequestRecord] = []
    start_time = time.perf_counter()

    print(
        f"Starting load test on {base_url} (concurrency={concurrency}, target_reqs={total_requests}, max_duration={duration_seconds}s)...",
        flush=True,
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        req_idx = 0
        futures = set()

        # Initial queue fill
        while len(futures) < concurrency and (req_idx < total_requests):
            req_idx += 1
            item = generate_workload_item(req_idx, invalid_ratio)
            futures.add(executor.submit(execute_request, base_url, item))

        while futures:
            done, futures = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
            for f in done:
                rec = f.result()
                records.append(rec)

            now = time.perf_counter()
            if duration_seconds and (now - start_time >= duration_seconds):
                # Drain remaining in-flight futures without submitting new ones
                break

            while len(futures) < concurrency and (req_idx < total_requests):
                if duration_seconds and (time.perf_counter() - start_time >= duration_seconds):
                    break
                req_idx += 1
                item = generate_workload_item(req_idx, invalid_ratio)
                futures.add(executor.submit(execute_request, base_url, item))

        # Wait for any remaining in-flight
        if futures:
            done, _ = concurrent.futures.wait(futures)
            for f in done:
                records.append(f.result())

    return records


def analyze_records(records: list[RequestRecord], elapsed_total_sec: float) -> dict[str, Any]:
    if not records:
        return {"total_requests": 0}

    valid_records = [r for r in records if r.is_valid_route and r.status_code in (200, 201)]
    rejected_records = [r for r in records if not r.is_valid_route and r.status_code in (400, 422)]
    error_records = [r for r in records if r.status_code >= 500 or r.status_code == 0]

    latencies_valid = [r.latency_ms for r in valid_records]
    latencies_rejected = [r.latency_ms for r in rejected_records]

    # Per-region valid records
    nyc_records = [r for r in valid_records if r.region == "us-nyc-manhattan"]
    kl_records = [r for r in valid_records if r.region == "in-kl-tvm"]

    status_dist = {}
    for r in records:
        status_dist[r.status_code] = status_dist.get(r.status_code, 0) + 1

    def stats(l: list[float]) -> dict[str, float]:
        if not l:
            return {"count": 0, "mean": 0, "p50": 0, "p95": 0, "p99": 0, "max": 0}
        s = sorted(l)
        return {
            "count": len(l),
            "mean": statistics.mean(l),
            "p50": statistics.median(l),
            "p95": s[min(int(len(s) * 0.95), len(s) - 1)],
            "p99": s[min(int(len(s) * 0.99), len(s) - 1)],
            "max": max(l),
        }

    return {
        "total_requests": len(records),
        "achieved_rps": len(records) / elapsed_total_sec if elapsed_total_sec > 0 else 0,
        "elapsed_seconds": elapsed_total_sec,
        "status_distribution": status_dist,
        "valid_routes_success_count": len(valid_records),
        "rejected_routes_count": len(rejected_records),
        "server_errors_or_timeouts": len(error_records),
        "error_rate_pct": (len(error_records) / len(records)) * 100.0,
        "latency_valid_routes_ms": stats(latencies_valid),
        "latency_rejected_routes_ms": stats(latencies_rejected),
        "regions": {
            "us-nyc-manhattan": {
                "valid_count": len(nyc_records),
                "latency_ms": stats([r.latency_ms for r in nyc_records]),
            },
            "in-kl-tvm": {
                "valid_count": len(kl_records),
                "latency_ms": stats([r.latency_ms for r in kl_records]),
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Pool Engine Staging Load Tester")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Staging base URL")
    parser.add_argument(
        "--profile",
        choices=["smoke", "normal", "burst", "diagnostic"],
        default="smoke",
        help="Workload profile to execute",
    )
    parser.add_argument("--concurrency", type=int, default=None, help="Override concurrency")
    parser.add_argument("--requests", type=int, default=None, help="Override total requests")
    parser.add_argument("--duration", type=float, default=None, help="Override duration in seconds")
    parser.add_argument("--output-json", type=str, default=None, help="Save raw metrics to JSON")

    args = parser.parse_args()

    # Configure defaults per profile
    if args.profile == "smoke":
        concurrency = args.concurrency or 2
        total_requests = args.requests or 40
        duration = args.duration or 10.0
    elif args.profile == "normal":
        concurrency = args.concurrency or 10
        total_requests = args.requests or 400
        duration = args.duration or 30.0
    elif args.profile == "burst":
        concurrency = args.concurrency or 25
        total_requests = args.requests or 750
        duration = args.duration or 30.0
    elif args.profile == "diagnostic":
        concurrency = args.concurrency or 50
        total_requests = args.requests or 1000
        duration = args.duration or 20.0

    print(f"\n=======================================================")
    print(f"  RUNNING LOAD TEST: PROFILE '{args.profile.upper()}'")
    print(f"  Target: {args.url} | Concurrency: {concurrency}")
    print(f"=======================================================")

    t0 = time.perf_counter()
    records = run_workload(
        base_url=args.url,
        concurrency=concurrency,
        total_requests=total_requests,
        duration_seconds=duration,
    )
    elapsed = time.perf_counter() - t0

    summary = analyze_records(records, elapsed)
    summary["profile"] = args.profile
    summary["concurrency"] = concurrency

    print(f"\n--- Load Test Results ({args.profile}) ---")
    print(f"Total Requests:     {summary['total_requests']}")
    print(f"Elapsed Time:       {summary['elapsed_seconds']:.2f} s")
    print(f"Achieved Rate:      {summary['achieved_rps']:.1f} req/s")
    print(f"Status Distribution: {summary['status_distribution']}")
    print(f"Error Rate:         {summary['error_rate_pct']:.2f}%")

    val_lat = summary["latency_valid_routes_ms"]
    print(f"\nValid Routes Latency (ms):")
    print(f"  Count: {val_lat['count']}")
    print(f"  Mean:  {val_lat['mean']:.2f} ms")
    print(f"  p50:   {val_lat['p50']:.2f} ms")
    print(f"  p95:   {val_lat['p95']:.2f} ms")
    print(f"  p99:   {val_lat['p99']:.2f} ms")
    print(f"  Max:   {val_lat['max']:.2f} ms")

    nyc_lat = summary["regions"]["us-nyc-manhattan"]["latency_ms"]
    kl_lat = summary["regions"]["in-kl-tvm"]["latency_ms"]
    print(f"\nRegional Breakdown:")
    print(f"  Manhattan: count={nyc_lat['count']}, p50={nyc_lat['p50']:.2f} ms, p95={nyc_lat['p95']:.2f} ms")
    print(f"  Kerala:    count={kl_lat['count']}, p50={kl_lat['p50']:.2f} ms, p95={kl_lat['p95']:.2f} ms")

    out_file = args.output_json or f"docs/load_test_{args.profile}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary metrics written to {out_file}")

    return 0 if summary["error_rate_pct"] == 0.0 else 1


if __name__ == "__main__":
    sys.exit(main())
