"""
Reproducible scenario generation, correctness validation, and benchmark metrics for the playground.
"""

import math
import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from engine.domain.enums import StopType
from engine.domain.models import GeoCoordinate, RideRequest, RouteStop, Vehicle
from engine.routing.invariants import check_capacity_profile, check_precedence

HOTSPOTS: dict[str, tuple[float, float]] = {
    "Downtown / Financial District": (40.7128, -74.0060),
    "Midtown / Times Square": (40.7580, -73.9855),
    "Uptown / Central Park North": (40.7829, -73.9654),
}


@dataclass(frozen=True)
class ScenarioEntitySet:
    """A generated, reproducible set of requests and vehicles."""
    seed: int
    requests: tuple[dict[str, Any], ...]
    vehicles: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class CorrectnessAudit:
    """Outcome of validating algorithmic invariants on a set of dispatch assignments."""
    all_passed: bool
    precedence_passed: bool
    capacity_passed: bool
    uniqueness_passed: bool
    total_assignments_checked: int
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class BenchmarkStatistics:
    """Statistical summary across multiple benchmark runs."""
    total_runs: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    min_ms: float
    mean_ms: float
    runs_over_450ms: int
    runs_over_500ms: int
    durations_ms: tuple[float, ...]


@dataclass(frozen=True)
class ExperimentResult:
    """Comprehensive outcome of a multi-run playground experiment."""
    workload_name: str
    num_requests: int
    num_vehicles: int
    num_runs: int
    seed: int
    routing_backend: str
    statistics: BenchmarkStatistics
    correctness: CorrectnessAudit
    average_matched_requests: float
    average_unassigned_requests: float
    match_rate_pct: float
    average_vmt_savings_meters: float
    active_vehicle_utilization_pct: float
    raw_runs: tuple[dict[str, Any], ...]


def generate_scenario(
    num_requests: int,
    num_vehicles: int,
    seed: int = 42,
    base_time: int = 1700000000,
) -> ScenarioEntitySet:
    """
    Generates a reproducible set of vehicles and ride requests based on Manhattan hotspots.
    Guarantees bit-for-bit repeatability across identical seeds.
    """
    rng = random.Random(seed)
    hotspot_keys = list(HOTSPOTS.keys())

    # 1. Generate Vehicles
    vehicles: list[dict[str, Any]] = []
    for v_idx in range(num_vehicles):
        veh_id = f"veh-{seed}-{v_idx:04d}"
        hub = rng.choice(hotspot_keys)
        c_lat, c_lon = HOTSPOTS[hub]
        v_lat = max(40.7000, min(40.7900, rng.gauss(c_lat, 0.007)))
        v_lon = max(-74.0200, min(-73.9000, rng.gauss(c_lon, 0.007)))
        cap = 4 if v_idx < int(0.80 * num_vehicles) else 6
        vehicles.append({
            "vehicle_id": veh_id,
            "driver_id": f"drv-{v_idx:04d}",
            "total_seat_capacity": cap,
            "latitude": round(v_lat, 6),
            "longitude": round(v_lon, 6),
            "is_active": True,
            "luggage_capacity_units": 2,
        })

    # 2. Generate Requests
    requests: list[dict[str, Any]] = []
    for r_idx in range(num_requests):
        req_id = f"req-{seed}-{r_idx:04d}"
        r_val = rng.random()
        if r_val < 0.50:
            hub = "Midtown / Times Square"
        elif r_val < 0.80:
            hub = "Downtown / Financial District"
        else:
            hub = "Uptown / Central Park North"

        c_lat, c_lon = HOTSPOTS[hub]
        p_lat = max(40.7000, min(40.7900, rng.gauss(c_lat, 0.006)))
        p_lon = max(-74.0200, min(-73.9000, rng.gauss(c_lon, 0.006)))

        d_hub = rng.choice(hotspot_keys)
        d_lat_c, d_lon_c = HOTSPOTS[d_hub]
        d_lat = max(40.7000, min(40.7900, rng.gauss(d_lat_c, 0.008)))
        d_lon = max(-74.0200, min(-73.9000, rng.gauss(d_lon_c, 0.008)))

        duration = rng.randint(300, 1200)
        distance = int(duration * 11.11)

        r_seats = rng.random()
        seats = 1 if r_seats < 0.75 else (2 if r_seats < 0.92 else 3)

        requests.append({
            "request_id": req_id,
            "user_id": f"user-{req_id}",
            "pickup_lat": round(p_lat, 6),
            "pickup_lon": round(p_lon, 6),
            "dropoff_lat": round(d_lat, 6),
            "dropoff_lon": round(d_lon, 6),
            "seat_count": seats,
            "earliest_pickup_time": base_time,
            "latest_dropoff_time": base_time + duration + 900,
            "direct_distance_meters": distance,
            "direct_duration_seconds": duration,
        })

    return ScenarioEntitySet(
        seed=seed,
        requests=tuple(requests),
        vehicles=tuple(vehicles),
    )


def verify_correctness(
    committed_assignments: Sequence[Any],
    vehicles_by_id: Mapping[str, Any],
) -> CorrectnessAudit:
    """
    Validates physical and contractual invariants on dispatch assignments:
    1. Precedence: Pickup precedes dropoff for every passenger.
    2. Capacity: Cumulative occupancy never exceeds vehicle seat capacity.
    3. Uniqueness: No request ID is assigned to multiple vehicles in the same cycle.
    """
    issues: list[str] = []
    seen_request_ids: set[str] = set()
    precedence_ok = True
    capacity_ok = True
    uniqueness_ok = True

    for asgn in committed_assignments:
        veh_id = asgn.get("vehicle_id") if isinstance(asgn, dict) else getattr(asgn, "vehicle_id", "")
        req_ids = asgn.get("request_ids", ()) if isinstance(asgn, dict) else getattr(asgn, "request_ids", ())
        stops_raw = asgn.get("stops", ()) if isinstance(asgn, dict) else getattr(asgn, "stops", ())

        # Check Uniqueness
        for rid in req_ids:
            if rid in seen_request_ids:
                issues.append(f"Request '{rid}' assigned multiple times across vehicles.")
                uniqueness_ok = False
            seen_request_ids.add(rid)

        # Convert stops to RouteStop domain models if needed
        parsed_stops: list[RouteStop] = []
        for s in stops_raw:
            if isinstance(s, RouteStop):
                parsed_stops.append(s)
            elif isinstance(s, dict):
                loc = s.get("location", {})
                lat = loc.get("latitude", 0.0) if isinstance(loc, dict) else getattr(loc, "latitude", 0.0)
                lon = loc.get("longitude", 0.0) if isinstance(loc, dict) else getattr(loc, "longitude", 0.0)
                parsed_stops.append(
                    RouteStop(
                        stop_id=s.get("stop_id", "s"),
                        ride_id=s.get("ride_id", "r"),
                        request_id=s.get("request_id", "req"),
                        stop_type=StopType(s.get("stop_type", "PICKUP")),
                        location=GeoCoordinate(latitude=lat, longitude=lon),
                        passenger_delta=s.get("passenger_delta", 0),
                        scheduled_arrival_time=s.get("scheduled_arrival_time", 0),
                        promised_window_start=s.get("promised_window_start", 0),
                        promised_window_end=s.get("promised_window_end", 0),
                    )
                )

        if parsed_stops:
            # Check Precedence
            if not check_precedence(parsed_stops):
                precedence_ok = False
                issues.append(f"Vehicle '{veh_id}': Stop precedence violated (dropoff before pickup).")

            # Check Capacity Profile
            veh_id_str = str(veh_id)
            veh_info = vehicles_by_id.get(veh_id_str)
            cap: int = 4
            if veh_info:
                raw_cap = veh_info.get("total_seat_capacity") if isinstance(veh_info, dict) else getattr(veh_info, "total_seat_capacity", 4)
                if isinstance(raw_cap, int):
                    cap = raw_cap
            if not check_capacity_profile(parsed_stops, capacity=cap):
                capacity_ok = False
                issues.append(f"Vehicle '{veh_id}': Vehicle capacity ({cap}) exceeded along route.")

    all_passed = precedence_ok and capacity_ok and uniqueness_ok
    return CorrectnessAudit(
        all_passed=all_passed,
        precedence_passed=precedence_ok,
        capacity_passed=capacity_ok,
        uniqueness_passed=uniqueness_ok,
        total_assignments_checked=len(committed_assignments),
        issues=tuple(issues),
    )


def calculate_benchmark_stats(durations_ms: Sequence[float]) -> BenchmarkStatistics:
    """Computes exact percentiles, max, min, mean, and SLA cutoffs for latency distributions."""
    if not durations_ms:
        return BenchmarkStatistics(
            total_runs=0,
            p50_ms=0.0,
            p95_ms=0.0,
            p99_ms=0.0,
            max_ms=0.0,
            min_ms=0.0,
            mean_ms=0.0,
            runs_over_450ms=0,
            runs_over_500ms=0,
            durations_ms=(),
        )

    sorted_d = sorted(durations_ms)
    n = len(sorted_d)

    def percentile(p: float) -> float:
        if n == 1:
            return sorted_d[0]
        k = (n - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_d[int(k)]
        d0 = sorted_d[f] * (c - k)
        d1 = sorted_d[c] * (k - f)
        return round(d0 + d1, 2)

    p50 = percentile(50.0)
    p95 = percentile(95.0)
    p99 = percentile(99.0)
    max_ms = round(sorted_d[-1], 2)
    min_ms = round(sorted_d[0], 2)
    mean_ms = round(statistics.mean(sorted_d), 2)

    over_450 = sum(1 for d in sorted_d if d > 450.0)
    over_500 = sum(1 for d in sorted_d if d > 500.0)

    return BenchmarkStatistics(
        total_runs=n,
        p50_ms=p50,
        p95_ms=p95,
        p99_ms=p99,
        max_ms=max_ms,
        min_ms=min_ms,
        mean_ms=mean_ms,
        runs_over_450ms=over_450,
        runs_over_500ms=over_500,
        durations_ms=tuple(round(d, 2) for d in durations_ms),
    )


def run_experiment(
    num_requests: int,
    num_vehicles: int,
    num_runs: int = 5,
    seed: int = 42,
    use_osrm: bool = False,
    osrm_url: str = "http://127.0.0.1:5000",
    deadline_seconds: float = 0.500,
    progress_callback: Optional[Any] = None,
) -> ExperimentResult:
    """
    Executes a multi-run controlled benchmark experiment.

    Guarantees:
    - Pure timing isolation: entity generation and storage seeding occur BEFORE timing starts.
    - Zero destructive mutations on persistent databases (uses isolated in-memory storage).
    - Validates capacity, precedence, and uniqueness invariants on each run.
    """
    from engine.adapters.default_policy import DefaultPolicyProvider
    from engine.adapters.h3_spatial import H3SpatialIndexAdapter
    from engine.adapters.in_memory_storage import InMemoryRideStorage
    from engine.adapters.mock_routing import MockRoutingProvider
    from engine.adapters.osrm_routing import OsrmRoutingAdapter
    from engine.domain.enums import RequestStatus
    from engine.orchestration.dispatch_orchestrator import (
        DispatchOrchestrator,
        OrchestrationConfig,
    )

    routing_label = "OSRM Road Network (Manhattan)" if use_osrm else "Mock Routing (Euclidean Grid)"
    durations: list[float] = []
    matched_counts: list[int] = []
    unassigned_counts: list[int] = []
    vmt_savings_list: list[int] = []
    assigned_vehicles_count_list: list[int] = []
    all_issues: list[str] = []
    raw_runs: list[dict[str, Any]] = []

    # Share router across runs to emulate warmed connection pool if OSRM is chosen
    router = (
        OsrmRoutingAdapter(base_url=osrm_url, timeout_seconds=deadline_seconds)
        if use_osrm
        else MockRoutingProvider()
    )

    try:
        for run_idx in range(num_runs):
            # Deterministic seed per run to exercise variance while remaining reproducible
            run_seed = seed + (run_idx * 101)
            scenario = generate_scenario(num_requests, num_vehicles, seed=run_seed)

            # Setup clean in-memory state (UNTIMED)
            storage = InMemoryRideStorage()
            spatial = H3SpatialIndexAdapter()
            policy = DefaultPolicyProvider()
            orchestrator = DispatchOrchestrator(
                storage=storage,
                policy_provider=policy,
                routing_provider=router,
                spatial_index=spatial,
                config=OrchestrationConfig(deadline_seconds=deadline_seconds),
            )

            vehicles_by_id: dict[str, Any] = {}
            for v_data in scenario.vehicles:
                veh = Vehicle(
                    vehicle_id=v_data["vehicle_id"],
                    driver_id=v_data["driver_id"],
                    total_seat_capacity=v_data["total_seat_capacity"],
                    current_location=GeoCoordinate(
                        latitude=v_data["latitude"],
                        longitude=v_data["longitude"],
                    ),
                    is_active=v_data["is_active"],
                )
                storage.save_vehicle(veh)
                vehicles_by_id[veh.vehicle_id] = v_data

            for r_data in scenario.requests:
                req = RideRequest(
                    request_id=r_data["request_id"],
                    user_id=r_data["user_id"],
                    pickup_location=GeoCoordinate(
                        latitude=r_data["pickup_lat"],
                        longitude=r_data["pickup_lon"],
                    ),
                    dropoff_location=GeoCoordinate(
                        latitude=r_data["dropoff_lat"],
                        longitude=r_data["dropoff_lon"],
                    ),
                    seat_count=r_data["seat_count"],
                    earliest_pickup_time=r_data["earliest_pickup_time"],
                    latest_dropoff_time=r_data["latest_dropoff_time"],
                    direct_distance_meters=r_data["direct_distance_meters"],
                    direct_duration_seconds=r_data["direct_duration_seconds"],
                    status=RequestStatus.PENDING,
                )
                storage.save_request(req)

            # TIMED SECTION: Strictly the dispatch solver execution
            t_start = time.perf_counter()
            res = orchestrator.dispatch_cycle(
                current_time=1700000000,
                cycle_id=f"exp-{run_seed}",
                idempotency_token=f"idemp-{run_seed}",
                deadline=time.monotonic() + deadline_seconds,
            )
            t_end = time.perf_counter()
            duration_ms = (t_end - t_start) * 1000.0

            # Validate correctness invariants
            audit = verify_correctness(res.committed_assignments, vehicles_by_id)
            if not audit.all_passed:
                all_issues.extend(audit.issues)

            matched_reqs = sum(len(a.request_ids) for a in res.committed_assignments)
            assigned_vehs = len({a.vehicle_id for a in res.committed_assignments})

            durations.append(duration_ms)
            matched_counts.append(matched_reqs)
            unassigned_counts.append(len(res.unassigned_request_ids))
            vmt_savings_list.append(res.total_vmt_savings_meters)
            assigned_vehicles_count_list.append(assigned_vehs)

            raw_runs.append({
                "run_index": run_idx + 1,
                "seed": run_seed,
                "duration_ms": round(duration_ms, 2),
                "search_status": res.search_status.value,
                "matched_requests": matched_reqs,
                "unassigned_requests": len(res.unassigned_request_ids),
                "assigned_vehicles": assigned_vehs,
                "vmt_savings_meters": res.total_vmt_savings_meters,
                "correctness_passed": audit.all_passed,
            })

            if progress_callback:
                progress_callback(run_idx + 1, num_runs, duration_ms)

    finally:
        if hasattr(router, "close"):
            try:
                router.close()
            except Exception:
                pass

    stats = calculate_benchmark_stats(durations)
    avg_matched = float(statistics.mean(matched_counts)) if matched_counts else 0.0
    avg_unassigned = float(statistics.mean(unassigned_counts)) if unassigned_counts else 0.0
    avg_vmt = float(statistics.mean(vmt_savings_list)) if vmt_savings_list else 0.0
    avg_assigned_vehs = float(statistics.mean(assigned_vehicles_count_list)) if assigned_vehicles_count_list else 0.0
    utilization_pct = round((avg_assigned_vehs / max(1, num_vehicles)) * 100.0, 1)
    match_rate_pct = round((avg_matched / max(1, num_requests)) * 100.0, 1)

    overall_audit = CorrectnessAudit(
        all_passed=len(all_issues) == 0,
        precedence_passed=not any("precedence" in s.lower() for s in all_issues),
        capacity_passed=not any("capacity" in s.lower() for s in all_issues),
        uniqueness_passed=not any("multiple times" in s.lower() for s in all_issues),
        total_assignments_checked=sum(len(r.get("matched_requests", [])) if isinstance(r.get("matched_requests"), list) else 1 for r in raw_runs),
        issues=tuple(all_issues),
    )

    workload_label = f"Workload ({num_requests} reqs / {num_vehicles} vehs)"
    return ExperimentResult(
        workload_name=workload_label,
        num_requests=num_requests,
        num_vehicles=num_vehicles,
        num_runs=num_runs,
        seed=seed,
        routing_backend=routing_label,
        statistics=stats,
        correctness=overall_audit,
        average_matched_requests=round(avg_matched, 1),
        average_unassigned_requests=round(avg_unassigned, 1),
        match_rate_pct=match_rate_pct,
        average_vmt_savings_meters=round(avg_vmt, 1),
        active_vehicle_utilization_pct=utilization_pct,
        raw_runs=tuple(raw_runs),
    )
