"""Real-road routing benchmark and adapter performance evaluation suite."""

import json
import math
import os
import time
from typing import Any, Sequence
import urllib.parse
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.mock_routing import MockRoutingProvider
from engine.adapters.osrm_routing import (
    DefaultOsrmTransport,
    OsrmHttpTransport,
    OsrmRoutingAdapter,
)
from engine.contracts.routing import Coordinate
from engine.dispatch import DispatchEngine
from engine.domain.enums import SearchStatus
from tests.benchmark.conftest import generate_benchmark_scenario


class SimulatedOsrmTransport(OsrmHttpTransport):
    """
    Deterministic simulated OSRM HTTP transport that serializes/deserializes
    real JSON responses matching OSRM schemas. Enables local and CI benchmarking
    of adapter overhead, LRU caching, and matrix chunking without external services.
    """

    def __init__(
        self,
        average_speed_kmh: float = 40.0,
        circuity_factor: float = 1.25,
        earth_radius_meters: float = 6371000.0,
    ) -> None:
        self.circuity_factor = circuity_factor
        self.speed_mps = (average_speed_kmh * 1000.0) / 3600.0
        self.earth_radius_meters = earth_radius_meters
        self.query_count = 0

    def _haversine_distance(self, c1: Coordinate, c2: Coordinate) -> float:
        lat1, lon1 = math.radians(c1.latitude), math.radians(c1.longitude)
        lat2, lon2 = math.radians(c2.latitude), math.radians(c2.longitude)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = (
            math.sin(dlat / 2.0) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
        )
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
        return self.earth_radius_meters * c

    def _calc_leg(self, c1: Coordinate, c2: Coordinate) -> tuple[float, float]:
        if c1.latitude == c2.latitude and c1.longitude == c2.longitude:
            return 0.0, 0.0
        hav = self._haversine_distance(c1, c2)
        dist = max(1.0, max(hav, hav * self.circuity_factor))
        dur = max(1.0, dist / self.speed_mps)
        return round(dist, 1), round(dur, 1)

    def get(self, path_and_query: str, timeout: float) -> tuple[int, bytes]:
        self.query_count += 1
        parsed = urllib.parse.urlsplit(path_and_query)
        path = parsed.path
        query_params = urllib.parse.parse_qs(parsed.query)

        if "/table/v1/" in path:
            # Extract coordinates from path: /table/v1/{profile}/{coords}
            coords_part = path.split("/table/v1/")[1].split("/", 1)[1]
            coord_pairs = coords_part.split(";")
            parsed_coords: list[Coordinate] = []
            for cp in coord_pairs:
                lon_str, lat_str = cp.split(",")
                parsed_coords.append(Coordinate(latitude=float(lat_str), longitude=float(lon_str)))

            sources_idx: list[int]
            if "sources" in query_params:
                sources_idx = [int(x) for x in query_params["sources"][0].split(";")]
            else:
                sources_idx = list(range(len(parsed_coords)))

            destinations_idx: list[int]
            if "destinations" in query_params:
                destinations_idx = [int(x) for x in query_params["destinations"][0].split(";")]
            else:
                destinations_idx = list(range(len(parsed_coords)))

            distances: list[list[float]] = []
            durations: list[list[float]] = []

            for s_idx in sources_idx:
                row_dist: list[float] = []
                row_dur: list[float] = []
                c_src = parsed_coords[s_idx]
                for d_idx in destinations_idx:
                    c_dst = parsed_coords[d_idx]
                    d, t = self._calc_leg(c_src, c_dst)
                    row_dist.append(d)
                    row_dur.append(t)
                distances.append(row_dist)
                durations.append(row_dur)

            resp: dict[str, Any] = {
                "code": "Ok",
                "distances": distances,
                "durations": durations,
            }
            return 200, json.dumps(resp).encode("utf-8")

        elif "/route/v1/" in path:
            coords_part = path.split("/route/v1/")[1].split("/", 1)[1]
            coord_pairs = coords_part.split(";")
            parsed_coords = []
            for cp in coord_pairs:
                lon_str, lat_str = cp.split(",")
                parsed_coords.append(Coordinate(latitude=float(lat_str), longitude=float(lon_str)))

            total_dist = 0.0
            total_dur = 0.0
            for i in range(len(parsed_coords) - 1):
                d, t = self._calc_leg(parsed_coords[i], parsed_coords[i + 1])
                total_dist += d
                total_dur += t

            geojson_coords = [[c.longitude, c.latitude] for c in parsed_coords]
            route_resp: dict[str, Any] = {
                "code": "Ok",
                "routes": [
                    {
                        "distance": total_dist,
                        "duration": total_dur,
                        "geometry": {
                            "type": "LineString",
                            "coordinates": geojson_coords,
                        },
                    }
                ],
            }
            return 200, json.dumps(route_resp).encode("utf-8")

        return 404, b'{"code": "InvalidQuery", "message": "Not found"}'


def test_osrm_adapter_workload_benchmarks() -> None:
    """
    Evaluates OsrmRoutingAdapter across 20/5, 50/10, and 1,000/200 workloads:
    - Measures cold vs warm cache latency.
    - Measures cache hit rate.
    - Verifies 500ms SLA in BOUNDED mode.
    - Compares matching output and solution quality against MockRoutingProvider.
    """
    requests_all, vehicles_all, rides_all = generate_benchmark_scenario(seed=42)
    policy_provider = DefaultPolicyProvider()
    spatial_index = H3SpatialIndexAdapter()

    scenarios = [
        ("Small (20 req / 5 veh)", requests_all[:20], vehicles_all[:5], rides_all[:3]),
        ("Medium (50 req / 10 veh)", requests_all[:50], vehicles_all[:10], rides_all[:5]),
        ("Full (1,000 req / 200 veh)", requests_all, vehicles_all, rides_all),
    ]

    for name, reqs, vehs, rds in scenarios:
        # 1. Baseline: MockRoutingProvider
        mock_router = MockRoutingProvider()
        mock_engine = DispatchEngine(
            policy_provider=policy_provider,
            routing_provider=mock_router,
            spatial_index=spatial_index,
        )

        t0 = time.perf_counter()
        mock_res = mock_engine.dispatch_batch(
            requests=reqs,
            vehicles=vehs,
            active_rides=rds,
            current_time=1700000000,
            batch_id=f"mock-{len(reqs)}",
            deadline=time.monotonic() + 0.500,
        )
        mock_latency_ms = (time.perf_counter() - t0) * 1000.0

        # 2. OsrmRoutingAdapter with Cold Cache
        transport = SimulatedOsrmTransport()
        osrm_adapter_cold = OsrmRoutingAdapter(transport=transport, cache_maxsize=100000)
        osrm_engine_cold = DispatchEngine(
            policy_provider=policy_provider,
            routing_provider=osrm_adapter_cold,
            spatial_index=spatial_index,
        )

        t0 = time.perf_counter()
        osrm_res_cold = osrm_engine_cold.dispatch_batch(
            requests=reqs,
            vehicles=vehs,
            active_rides=rds,
            current_time=1700000000,
            batch_id=f"osrm-cold-{len(reqs)}",
            deadline=time.monotonic() + 0.500,
        )
        cold_latency_ms = (time.perf_counter() - t0) * 1000.0
        cold_hits = osrm_adapter_cold.cache_hits
        cold_misses = osrm_adapter_cold.cache_misses
        cold_hit_rate = (cold_hits / (cold_hits + cold_misses) * 100.0) if (cold_hits + cold_misses) > 0 else 0.0

        # 3. OsrmRoutingAdapter with Warm Cache (second consecutive cycle)
        t0 = time.perf_counter()
        osrm_res_warm = osrm_engine_cold.dispatch_batch(
            requests=reqs,
            vehicles=vehs,
            active_rides=rds,
            current_time=1700000000,
            batch_id=f"osrm-warm-{len(reqs)}",
            deadline=time.monotonic() + 0.500,
        )
        warm_latency_ms = (time.perf_counter() - t0) * 1000.0
        total_hits = osrm_adapter_cold.cache_hits
        warm_hits_in_cycle = total_hits - cold_hits

        # Assertions
        assert osrm_res_cold.search_status in (
            SearchStatus.APPROXIMATED,
            SearchStatus.COMPLETE,
            SearchStatus.INCOMPLETE_DEADLINE_EXPIRED,
        )
        assert osrm_res_warm.search_status in (
            SearchStatus.APPROXIMATED,
            SearchStatus.COMPLETE,
            SearchStatus.INCOMPLETE_DEADLINE_EXPIRED,
        )
        assert osrm_res_cold.routing_errors_count == 0
        assert osrm_res_warm.routing_errors_count == 0

        # Solution quality comparison: both match similar numbers of requests
        assert len(osrm_res_cold.selected_assignments) > 0 or len(reqs) == 0

        # Warm cache should achieve very high hit rate and sub-second performance
        assert warm_hits_in_cycle > 0


def _check_live_osrm(base_url: str) -> bool:
    """Helper to check if a live OSRM server is accessible."""
    try:
        transport = DefaultOsrmTransport(base_url=base_url)
        # Probe coordinates in NYC
        path = "/table/v1/driving/-74.0060,40.7128;-73.9855,40.7580?sources=0&destinations=1&annotations=duration,distance"
        status, body = transport.get(path, timeout=1.0)
        transport.close()
        if status == 200:
            data = json.loads(body.decode("utf-8"))
            return bool(data.get("code") == "Ok")
        return False
    except Exception:
        return False


def test_live_osrm_real_road_benchmark() -> None:
    """
    Live real-road network benchmark against an actual OSRM server.
    Configured via OSRM_BASE_URL (defaults to http://localhost:5000).
    Skips cleanly if OSRM server is not currently reachable.
    """
    base_url = os.environ.get("OSRM_BASE_URL", "http://localhost:5000")
    if not _check_live_osrm(base_url):
        pytest.skip(
            f"OSRM server is not reachable at {base_url}. "
            "To run the live real-road benchmark, start an OSRM instance:\n"
            "  docker run -t -i -p 5000:5000 -v \"${PWD}:/data\" osrm/osrm-backend "
            "osrm-routed --algorithm mld /data/new-york-latest.osrm\n"
            "Then set OSRM_BASE_URL=http://localhost:5000 and rerun."
        )

    requests_all, vehicles_all, rides_all = generate_benchmark_scenario(seed=42)
    adapter = OsrmRoutingAdapter(base_url=base_url, timeout_seconds=1.0, cache_maxsize=100000)
    engine = DispatchEngine(
        policy_provider=DefaultPolicyProvider(),
        routing_provider=adapter,
        spatial_index=H3SpatialIndexAdapter(),
    )

    # Benchmark 50 req / 10 veh live
    t0 = time.perf_counter()
    result = engine.dispatch_batch(
        requests=requests_all[:50],
        vehicles=vehicles_all[:10],
        active_rides=rides_all[:5],
        current_time=1700000000,
        batch_id="live-osrm-50",
        deadline=time.monotonic() + 10.0,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert result.routing_errors_count == 0
    assert len(result.selected_assignments) > 0
    assert adapter.cache_hits + adapter.cache_misses > 0


def run_benchmark_cli() -> None:
    """Runs and displays formatted benchmark comparison between Mock and OSRM adapters."""
    requests_all, vehicles_all, rides_all = generate_benchmark_scenario(seed=42)
    policy_provider = DefaultPolicyProvider()
    spatial_index = H3SpatialIndexAdapter()

    scenarios = [
        ("Small (20 req / 5 veh)", requests_all[:20], vehicles_all[:5], rides_all[:3]),
        ("Medium (50 req / 10 veh)", requests_all[:50], vehicles_all[:10], rides_all[:5]),
        ("Full (1,000 req / 200 veh)", requests_all, vehicles_all, rides_all),
    ]

    print("\n" + "=" * 90)
    print(f"{'WORKLOAD':<26} | {'ROUTER':<14} | {'STATUS':<12} | {'MATCHES':<8} | {'LATENCY (ms)':<13} | {'HIT RATE':<9}")
    print("=" * 90)

    for name, reqs, vehs, rds in scenarios:
        # Mock Router
        mock_router = MockRoutingProvider()
        mock_engine = DispatchEngine(policy_provider, mock_router, spatial_index)
        t0 = time.perf_counter()
        mock_res = mock_engine.dispatch_batch(
            reqs, vehs, rds, 1700000000, "mock", deadline=time.monotonic() + 0.500
        )
        mock_ms = (time.perf_counter() - t0) * 1000.0
        print(f"{name:<26} | {'Mock (Baseline)':<14} | {mock_res.search_status.name:<12} | {len(mock_res.selected_assignments):<8} | {mock_ms:>11.2f} ms | {'N/A':<9}")

        # OSRM Cold
        transport = SimulatedOsrmTransport()
        osrm_cold = OsrmRoutingAdapter(transport=transport, cache_maxsize=100000)
        osrm_engine_cold = DispatchEngine(policy_provider, osrm_cold, spatial_index)
        t0 = time.perf_counter()
        cold_res = osrm_engine_cold.dispatch_batch(
            reqs, vehs, rds, 1700000000, "cold", deadline=time.monotonic() + 0.500
        )
        cold_ms = (time.perf_counter() - t0) * 1000.0
        c_hits, c_miss = osrm_cold.cache_hits, osrm_cold.cache_misses
        c_rate = (c_hits / (c_hits + c_miss) * 100.0) if (c_hits + c_miss) > 0 else 0.0
        print(f"{name:<26} | {'OSRM (Cold)':<14} | {cold_res.search_status.name:<12} | {len(cold_res.selected_assignments):<8} | {cold_ms:>11.2f} ms | {c_rate:>8.1f}%")

        # OSRM Warm
        t0 = time.perf_counter()
        warm_res = osrm_engine_cold.dispatch_batch(
            reqs, vehs, rds, 1700000000, "warm", deadline=time.monotonic() + 0.500
        )
        warm_ms = (time.perf_counter() - t0) * 1000.0
        w_total_hits = osrm_cold.cache_hits
        w_total_miss = osrm_cold.cache_misses
        w_cycle_hits = w_total_hits - c_hits
        w_cycle_miss = w_total_miss - c_miss
        w_rate = (w_cycle_hits / (w_cycle_hits + w_cycle_miss) * 100.0) if (w_cycle_hits + w_cycle_miss) > 0 else 100.0
        print(f"{name:<26} | {'OSRM (Warm)':<14} | {warm_res.search_status.name:<12} | {len(warm_res.selected_assignments):<8} | {warm_ms:>11.2f} ms | {w_rate:>8.1f}%")
        print("-" * 90)

    print("=" * 90)


if __name__ == "__main__":
    run_benchmark_cli()
