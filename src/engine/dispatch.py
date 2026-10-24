"""Unified Dispatch Engine entry point coordinating spatial filtering, routing, and optimization (T051)."""

from dataclasses import dataclass
import time
import uuid
from typing import Optional, Sequence

from engine.contracts.policy import DispatchPolicy, DispatchPolicyProvider
from engine.contracts.routing import Coordinate, RoadNetworkRoutingProvider
from engine.contracts.spatial import SpatialIndexProvider
from engine.contracts.storage import RideStorageProvider
from engine.domain.candidate import CandidateAssignment
from engine.domain.enums import (
    DispatchMode,
    RequestStatus,
    RideStatus,
    SearchStatus,
    StopStatus,
)
from engine.domain.models import MatchResult, Ride, RideRequest, Vehicle
from engine.optimization.set_packing import solve_set_packing_regret_k
from engine.routing.bundle_generator import generate_group_bundles
from engine.routing.insertion import generate_single_request_insertions
from engine.spatial.index import SpatialIndexCoordinator
from engine.spatial.lower_bounds import (
    DEFAULT_V_MAX_MPS,
    haversine_distance_meters,
)


class CandidateList(list[CandidateAssignment]):
    """
    List of candidate assignments annotated with search completeness and operating mode metadata.
    Provides standard list behavior with search diagnostics (dispatch_mode, search_status, is_approximated).
    """

    def __init__(
        self,
        candidates: Sequence[CandidateAssignment],
        dispatch_mode: DispatchMode = DispatchMode.BOUNDED,
        search_status: SearchStatus = SearchStatus.COMPLETE,
        is_approximated: bool = False,
    ) -> None:
        super().__init__(candidates)
        self.dispatch_mode = dispatch_mode
        self.search_status = search_status
        self.is_approximated = is_approximated


@dataclass(frozen=True)
class CandidateGenerationConfig:
    """
    Configuration parameters governing candidate discovery and pruning heuristics.

    Operating Modes:
        EXACT:
            Evaluates full physically reachable radius (v_max * max_pickup_delay_seconds)
            with zero arbitrary count caps on vehicles or requests. If the wall-clock deadline
            expires before complete evaluation, search_status is reported as INCOMPLETE_DEADLINE_EXPIRED.
        BOUNDED:
            Uses explicit, user-configured approximation limits (search radius, vehicles per request,
            requests per vehicle, bundle size). Reports search_status as APPROXIMATED and is_approximated=True.

    Attributes:
        mode: Operating mode (DispatchMode.EXACT or DispatchMode.BOUNDED).
        max_search_radius_meters: Maximum physical distance (meters) to search for candidate vehicles.
            In EXACT mode, this must be None (derived dynamically from physical reachability).
            In BOUNDED mode, limits the search horizon (e.g. 5000.0).
        max_vehicles_per_request: Maximum number of capable candidate vehicles to retain per request.
            In EXACT mode, this must be None (unconstrained).
            In BOUNDED mode, caps candidates per request.
        max_requests_per_vehicle: Maximum candidate requests to evaluate per vehicle.
            In EXACT mode, this must be None (unconstrained).
            In BOUNDED mode, caps requests prioritized by lower-bound detour.
        max_bundle_size: Maximum number of pooled requests in a single multi-passenger bundle (2, 3, or 4).
        exhaustive_fallback: In BOUNDED mode, if True and bounded search yields 0 capable candidates,
            falls back to expanding search radius up to the physical reachability bound.
        initial_search_radius_meters: Initial radius used in BOUNDED mode when exhaustive_fallback is enabled.
    """

    mode: DispatchMode = DispatchMode.BOUNDED
    max_search_radius_meters: Optional[float] = 5000.0
    max_vehicles_per_request: Optional[int] = 8
    max_requests_per_vehicle: Optional[int] = 3
    max_bundle_size: int = 2
    exhaustive_fallback: bool = True
    initial_search_radius_meters: float = 5000.0

    @classmethod
    def exact(cls, max_bundle_size: int = 2) -> "CandidateGenerationConfig":
        """Constructs an EXACT mode configuration with zero truncation limits."""
        return cls(
            mode=DispatchMode.EXACT,
            max_search_radius_meters=None,
            max_vehicles_per_request=None,
            max_requests_per_vehicle=None,
            max_bundle_size=max_bundle_size,
            exhaustive_fallback=False,
            initial_search_radius_meters=0.0,
        )

    @classmethod
    def bounded(
        cls,
        max_search_radius_meters: Optional[float] = 5000.0,
        max_vehicles_per_request: Optional[int] = 8,
        max_requests_per_vehicle: Optional[int] = 3,
        max_bundle_size: int = 2,
        exhaustive_fallback: bool = True,
        initial_search_radius_meters: float = 5000.0,
    ) -> "CandidateGenerationConfig":
        """Constructs a BOUNDED mode configuration with explicit approximation limits."""
        return cls(
            mode=DispatchMode.BOUNDED,
            max_search_radius_meters=max_search_radius_meters,
            max_vehicles_per_request=max_vehicles_per_request,
            max_requests_per_vehicle=max_requests_per_vehicle,
            max_bundle_size=max_bundle_size,
            exhaustive_fallback=exhaustive_fallback,
            initial_search_radius_meters=initial_search_radius_meters,
        )


def _sort_requests_by_active_detour(
    requests: Sequence[RideRequest],
    vehicle: Vehicle,
    active_ride: Ride,
) -> list[RideRequest]:
    """
    Sorts candidate requests ascending by lower-bound detour distance relative to
    the vehicle's current location and remaining scheduled/in-progress stops.
    """
    v_loc = Coordinate(vehicle.current_location.latitude, vehicle.current_location.longitude)
    active_stops = [
        s
        for s in active_ride.stops
        if s.status
        in (StopStatus.SCHEDULED, StopStatus.ARRIVED, StopStatus.IN_GRACE_PERIOD)
    ]

    if not active_stops:
        return sorted(
            requests,
            key=lambda r: haversine_distance_meters(
                v_loc, Coordinate(r.pickup_location.latitude, r.pickup_location.longitude)
            ),
        )

    coords = [v_loc] + [
        Coordinate(s.location.latitude, s.location.longitude) for s in active_stops
    ]

    def _req_detour_lower_bound(req: RideRequest) -> float:
        p = Coordinate(req.pickup_location.latitude, req.pickup_location.longitude)
        d = Coordinate(req.dropoff_location.latitude, req.dropoff_location.longitude)

        # Min detour to insert pickup P into any consecutive segment
        min_p_detour = float("inf")
        for i in range(len(coords) - 1):
            det = (
                haversine_distance_meters(coords[i], p)
                + haversine_distance_meters(p, coords[i + 1])
                - haversine_distance_meters(coords[i], coords[i + 1])
            )
            if det < min_p_detour:
                min_p_detour = det
        append_detour = haversine_distance_meters(coords[-1], p)
        if append_detour < min_p_detour:
            min_p_detour = append_detour

        direct_pd = haversine_distance_meters(p, d)
        return min_p_detour + direct_pd

    return sorted(requests, key=_req_detour_lower_bound)


class DispatchEngine:
    """
    Unified high-level dispatch facade for the provider-independent ride-pooling engine.
    Orchestrates spatial candidate discovery, feasible route insertions, group bundling,
    and fleet-wide set packing optimization under a single monotonic wall-clock deadline.
    """

    def __init__(
        self,
        policy_provider: DispatchPolicyProvider,
        routing_provider: RoadNetworkRoutingProvider,
        spatial_index: SpatialIndexProvider,
        storage: Optional[RideStorageProvider] = None,
        config: Optional[CandidateGenerationConfig] = None,
    ) -> None:
        self.policy_provider = policy_provider
        self.routing_provider = routing_provider
        self.spatial_index = spatial_index
        self.storage = storage
        self.config = config or CandidateGenerationConfig.bounded()

    def generate_candidates(
        self,
        requests: Sequence[RideRequest],
        vehicles: Sequence[Vehicle],
        active_rides: Sequence[Ride],
        current_time: int,
        config: Optional[CandidateGenerationConfig] = None,
        deadline: Optional[float] = None,
        reserved_headroom: float = 0.050,
        max_bundle_size: Optional[int] = None,
    ) -> CandidateList:
        """
        Discovers and generates all feasible candidate assignments (both single insertions
        and group trip bundles) across eligible vehicles and requests.
        Returns a CandidateList providing candidates and search status diagnostics.
        """
        start_monotonic = time.monotonic()
        effective_deadline = (
            deadline if deadline is not None else start_monotonic + 10.0
        )
        effective_config = config or self.config
        if (
            max_bundle_size is not None
            and max_bundle_size != effective_config.max_bundle_size
        ):
            effective_config = CandidateGenerationConfig(
                mode=effective_config.mode,
                max_search_radius_meters=effective_config.max_search_radius_meters,
                max_vehicles_per_request=effective_config.max_vehicles_per_request,
                max_requests_per_vehicle=effective_config.max_requests_per_vehicle,
                max_bundle_size=max_bundle_size,
                exhaustive_fallback=effective_config.exhaustive_fallback,
                initial_search_radius_meters=effective_config.initial_search_radius_meters,
            )

        # Normalize config for exact mode
        if effective_config.mode == DispatchMode.EXACT:
            effective_config = CandidateGenerationConfig.exact(
                max_bundle_size=effective_config.max_bundle_size
            )
            is_approximated = False
            search_status = SearchStatus.COMPLETE
        else:
            is_approximated = bool(
                effective_config.max_search_radius_meters is not None
                or effective_config.max_vehicles_per_request is not None
                or effective_config.max_requests_per_vehicle is not None
            )
            search_status = (
                SearchStatus.APPROXIMATED if is_approximated else SearchStatus.COMPLETE
            )

        pending_requests = [r for r in requests if r.status == RequestStatus.PENDING]
        eligible_vehicles = [v for v in vehicles if v.is_active]

        if not pending_requests or not eligible_vehicles:
            return CandidateList(
                candidates=[],
                dispatch_mode=effective_config.mode,
                search_status=SearchStatus.COMPLETE,
                is_approximated=False,
            )

        if time.monotonic() > effective_deadline - reserved_headroom:
            return CandidateList(
                candidates=[],
                dispatch_mode=effective_config.mode,
                search_status=SearchStatus.INCOMPLETE_DEADLINE_EXPIRED,
                is_approximated=True,
            )

        policy = self.policy_provider.get_policy()
        r_reach = DEFAULT_V_MAX_MPS * float(policy.max_pickup_delay_seconds)

        rides_by_vehicle: dict[str, Ride] = {
            r.vehicle_id: r
            for r in active_rides
            if r.lifecycle_status in (RideStatus.ACTIVE, RideStatus.SCHEDULED)
        }
        vehicles_by_id = {v.vehicle_id: v for v in eligible_vehicles}

        # Stage 2: Spatial Indexing & Candidate Discovery
        spatial_coord = SpatialIndexCoordinator(self.spatial_index)
        vehicle_entities = [
            (
                v.vehicle_id,
                Coordinate(
                    latitude=v.current_location.latitude,
                    longitude=v.current_location.longitude,
                ),
            )
            for v in eligible_vehicles
        ]
        spatial_coord.index_entities(vehicle_entities)

        nearby_requests_by_vehicle: dict[str, list[RideRequest]] = {
            v.vehicle_id: [] for v in eligible_vehicles
        }

        # Exact vs Bounded spatial search configuration
        if effective_config.mode == DispatchMode.EXACT:
            for req in pending_requests:
                if time.monotonic() > effective_deadline - reserved_headroom:
                    search_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
                    is_approximated = True
                    break

                pickup_coord = Coordinate(
                    latitude=req.pickup_location.latitude,
                    longitude=req.pickup_location.longitude,
                )
                # Exact mode: examine full physically reachable radius with no candidate limit
                spatial_candidates = spatial_coord.find_candidates_within_radius(
                    target=pickup_coord,
                    max_radius_meters=r_reach,
                    min_candidates=1,
                    max_candidates=None,
                )
                capable = [
                    sc
                    for sc in spatial_candidates
                    if sc.entity_id in vehicles_by_id
                    and vehicles_by_id[sc.entity_id].total_seat_capacity
                    >= req.seat_count
                ]
                for sc in capable:
                    nearby_requests_by_vehicle[sc.entity_id].append(req)
        else:
            # Bounded mode: use configured radius and candidate count
            search_radius = (
                effective_config.max_search_radius_meters
                if effective_config.max_search_radius_meters is not None
                else r_reach
            )

            for req in pending_requests:
                if time.monotonic() > effective_deadline - reserved_headroom:
                    search_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
                    is_approximated = True
                    break

                pickup_coord = Coordinate(
                    latitude=req.pickup_location.latitude,
                    longitude=req.pickup_location.longitude,
                )

                if (
                    effective_config.exhaustive_fallback
                    and search_radius > effective_config.initial_search_radius_meters
                    and effective_config.initial_search_radius_meters > 0
                ):
                    probe_radius = effective_config.initial_search_radius_meters
                else:
                    probe_radius = search_radius

                spatial_candidates = spatial_coord.find_candidates_within_radius(
                    target=pickup_coord,
                    max_radius_meters=probe_radius,
                    min_candidates=1,
                    max_candidates=effective_config.max_vehicles_per_request,
                )
                capable = [
                    sc
                    for sc in spatial_candidates
                    if sc.entity_id in vehicles_by_id
                    and vehicles_by_id[sc.entity_id].total_seat_capacity
                    >= req.seat_count
                ]

                # Bounded fallback if 0 capable vehicles found in initial probe
                if not capable and effective_config.exhaustive_fallback and probe_radius < r_reach:
                    spatial_candidates = spatial_coord.find_candidates_within_radius(
                        target=pickup_coord,
                        max_radius_meters=r_reach,
                        min_candidates=1,
                        max_candidates=effective_config.max_vehicles_per_request,
                    )
                    capable = [
                        sc
                        for sc in spatial_candidates
                        if sc.entity_id in vehicles_by_id
                        and vehicles_by_id[sc.entity_id].total_seat_capacity
                        >= req.seat_count
                    ]

                if effective_config.max_vehicles_per_request is not None:
                    capable = capable[: effective_config.max_vehicles_per_request]

                for sc in capable:
                    nearby_requests_by_vehicle[sc.entity_id].append(req)

        candidates: list[CandidateAssignment] = []

        # Stage 3 & 4: Route Insertion & Group Bundling
        for veh_id, nearby_reqs in nearby_requests_by_vehicle.items():
            if time.monotonic() > effective_deadline - reserved_headroom:
                search_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
                is_approximated = True
                break

            if not nearby_reqs:
                continue

            veh = vehicles_by_id[veh_id]
            active_ride = rides_by_vehicle.get(veh_id)
            v_loc = Coordinate(
                latitude=veh.current_location.latitude,
                longitude=veh.current_location.longitude,
            )

            if active_ride is not None:
                sorted_reqs = _sort_requests_by_active_detour(
                    nearby_reqs, veh, active_ride
                )
            else:
                sorted_reqs = sorted(
                    nearby_reqs,
                    key=lambda r: haversine_distance_meters(
                        v_loc,
                        Coordinate(
                            latitude=r.pickup_location.latitude,
                            longitude=r.pickup_location.longitude,
                        ),
                    ),
                )

            # Request slicing: strictly controlled by explicit configuration
            if effective_config.mode == DispatchMode.EXACT:
                eval_reqs = sorted_reqs
            elif effective_config.max_requests_per_vehicle is not None:
                eval_reqs = sorted_reqs[: effective_config.max_requests_per_vehicle]
            else:
                eval_reqs = sorted_reqs

            if active_ride is not None:
                for req in eval_reqs:
                    if time.monotonic() > effective_deadline - reserved_headroom:
                        search_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
                        is_approximated = True
                        break
                    ins_cands = generate_single_request_insertions(
                        active_ride=active_ride,
                        request=req,
                        vehicle=veh,
                        router=self.routing_provider,
                        policy=policy,
                        current_time=current_time,
                    )
                    candidates.extend(ins_cands)
            else:
                bundle_cands = generate_group_bundles(
                    requests=eval_reqs,
                    vehicle=veh,
                    router=self.routing_provider,
                    policy=policy,
                    current_time=current_time,
                    max_bundle_size=effective_config.max_bundle_size,
                )
                candidates.extend(bundle_cands)

        return CandidateList(
            candidates=candidates,
            dispatch_mode=effective_config.mode,
            search_status=search_status,
            is_approximated=is_approximated,
        )

    def dispatch_batch(
        self,
        requests: Sequence[RideRequest],
        vehicles: Sequence[Vehicle],
        active_rides: Sequence[Ride],
        current_time: int,
        batch_id: Optional[str] = None,
        deadline: Optional[float] = None,
        reserved_headroom: float = 0.050,
        max_bundle_size: Optional[int] = None,
        config: Optional[CandidateGenerationConfig] = None,
    ) -> MatchResult:
        """
        Executes an end-to-end batch dispatch optimization cycle.
        Governed by a monotonic wall-clock deadline (default 500ms SLA).
        Guarantees safe fallback: if timed out or interrupted, unassigned requests
        are cleanly returned with zero state corruption.
        """
        start_monotonic = time.monotonic()
        effective_deadline = (
            deadline if deadline is not None else start_monotonic + 0.500
        )
        effective_batch_id = batch_id or f"batch-{uuid.uuid4()}"
        effective_config = config or self.config

        pending_requests = [r for r in requests if r.status == RequestStatus.PENDING]
        eligible_vehicles = [v for v in vehicles if v.is_active]
        all_req_ids = [r.request_id for r in pending_requests]

        # Stage 1: Fast Input Validation
        if not pending_requests or not eligible_vehicles:
            solve_duration = (time.monotonic() - start_monotonic) * 1000.0
            return MatchResult(
                match_id=f"match-{uuid.uuid4()}",
                batch_id=effective_batch_id,
                solver_timestamp=current_time,
                selected_assignments=(),
                unassigned_request_ids=tuple(all_req_ids),
                total_vmt_savings_meters=0,
                solve_duration_ms=solve_duration,
                dispatch_mode=effective_config.mode,
                search_status=SearchStatus.COMPLETE,
                is_approximated=False,
            )

        # Monotonic interrupt check before candidate discovery
        if time.monotonic() > effective_deadline - reserved_headroom:
            solve_duration = (time.monotonic() - start_monotonic) * 1000.0
            return MatchResult(
                match_id=f"match-{uuid.uuid4()}",
                batch_id=effective_batch_id,
                solver_timestamp=current_time,
                selected_assignments=(),
                unassigned_request_ids=tuple(all_req_ids),
                total_vmt_savings_meters=0,
                solve_duration_ms=solve_duration,
                dispatch_mode=effective_config.mode,
                search_status=SearchStatus.INCOMPLETE_DEADLINE_EXPIRED,
                is_approximated=True,
            )

        # Stage 2, 3, 4: Candidate Generation
        # Reserve headroom for set packing solver (headroom + 50ms)
        cand_headroom = reserved_headroom + 0.050
        candidates = self.generate_candidates(
            requests=pending_requests,
            vehicles=eligible_vehicles,
            active_rides=active_rides,
            current_time=current_time,
            config=effective_config,
            deadline=effective_deadline,
            reserved_headroom=cand_headroom,
            max_bundle_size=max_bundle_size,
        )

        effective_search_status = candidates.search_status
        effective_is_approximated = candidates.is_approximated
        effective_dispatch_mode = candidates.dispatch_mode

        # Stage 5: Fleet Assignment Solver (Regret-K Heuristic)
        solver_result = solve_set_packing_regret_k(
            candidates=candidates,
            all_request_ids=all_req_ids,
            deadline=effective_deadline,
            reserved_headroom=reserved_headroom,
        )

        solve_duration_ms = (time.monotonic() - start_monotonic) * 1000.0

        if (
            time.monotonic() >= effective_deadline - reserved_headroom
            or candidates.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
        ):
            effective_search_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
            effective_is_approximated = True

        # Stage 6: Canonical MatchResult Serialization
        match_result = MatchResult(
            match_id=f"match-{uuid.uuid4()}",
            batch_id=effective_batch_id,
            solver_timestamp=current_time,
            selected_assignments=solver_result.selected_assignments,
            unassigned_request_ids=solver_result.unassigned_request_ids,
            total_vmt_savings_meters=solver_result.total_vmt_savings_meters,
            solve_duration_ms=round(solve_duration_ms, 2),
            dispatch_mode=effective_dispatch_mode,
            search_status=effective_search_status,
            is_approximated=effective_is_approximated,
        )

        return match_result
