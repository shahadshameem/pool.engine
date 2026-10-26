"""Unified Dispatch Engine entry point coordinating spatial filtering, routing, and optimization (T051)."""

from dataclasses import dataclass
import math
import operator
import time
import uuid
from typing import Optional, Sequence

from engine.contracts.policy import DispatchPolicy, DispatchPolicyProvider
from engine.contracts.routing import (
    Coordinate,
    RoadNetworkRoutingProvider,
    RoutingProviderError,
)
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
from engine.routing.insertion import (
    generate_active_ride_insertions,
    generate_single_request_insertions,
)
from engine.spatial.index import SpatialIndexCoordinator
from engine.spatial.lower_bounds import (
    DEFAULT_EARTH_RADIUS_METERS,
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
        routing_errors_count: int = 0,
    ) -> None:
        super().__init__(candidates)
        self.dispatch_mode = dispatch_mode
        self.search_status = search_status
        self.is_approximated = is_approximated
        self.routing_errors_count = routing_errors_count


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
        max_requests_per_vehicle: Maximum candidate requests to evaluate for multi-passenger pooling per vehicle.
            In EXACT mode, this must be None (unconstrained).
            In BOUNDED mode, caps pooled requests prioritized by lower-bound detour.
        max_single_requests_per_vehicle: Maximum candidate requests to evaluate for single-passenger service per vehicle.
            In EXACT mode, this must be None (unconstrained).
            In BOUNDED mode, caps single-passenger evaluation without combinatorial explosion (default 6).
        max_bundle_size: Maximum number of pooled requests in a single multi-passenger bundle (2, 3, or 4).
        exhaustive_fallback: In BOUNDED mode, if True and bounded search yields 0 capable candidates,
            falls back to expanding search radius up to the physical reachability bound.
        initial_search_radius_meters: Initial radius used in BOUNDED mode when exhaustive_fallback is enabled.
        propagate_routing_errors: If True, raises RoutingProviderError on routing failure rather than isolating.
    """

    mode: DispatchMode = DispatchMode.BOUNDED
    max_search_radius_meters: Optional[float] = 5000.0
    max_vehicles_per_request: Optional[int] = 8
    max_candidate_vehicles: Optional[int] = 32
    max_requests_per_vehicle: Optional[int] = 3
    max_single_requests_per_vehicle: Optional[int] = 6
    max_bundle_size: int = 2
    exhaustive_fallback: bool = True
    initial_search_radius_meters: float = 5000.0
    propagate_routing_errors: bool = False
    spatial_partitioning: bool = True
    num_partitions: Optional[int] = None
    max_candidate_vehicles_per_partition: Optional[int] = 13
    boundary_buffer_meters: float = 600.0
    aging_weight_mps: float = 15.0

    @classmethod
    def exact(
        cls,
        max_bundle_size: int = 2,
        propagate_routing_errors: bool = False,
    ) -> "CandidateGenerationConfig":
        """Constructs an EXACT mode configuration with zero truncation limits."""
        return cls(
            mode=DispatchMode.EXACT,
            max_search_radius_meters=None,
            max_vehicles_per_request=None,
            max_candidate_vehicles=None,
            max_requests_per_vehicle=None,
            max_single_requests_per_vehicle=None,
            max_bundle_size=max_bundle_size,
            exhaustive_fallback=False,
            initial_search_radius_meters=0.0,
            propagate_routing_errors=propagate_routing_errors,
            spatial_partitioning=False,
            num_partitions=None,
            max_candidate_vehicles_per_partition=None,
            aging_weight_mps=0.0,
        )

    @classmethod
    def bounded(
        cls,
        max_search_radius_meters: Optional[float] = 5000.0,
        max_vehicles_per_request: Optional[int] = 8,
        max_candidate_vehicles: Optional[int] = 32,
        max_requests_per_vehicle: Optional[int] = 3,
        max_single_requests_per_vehicle: Optional[int] = 6,
        max_bundle_size: int = 2,
        exhaustive_fallback: bool = True,
        initial_search_radius_meters: float = 5000.0,
        propagate_routing_errors: bool = False,
        spatial_partitioning: bool = True,
        num_partitions: Optional[int] = None,
        max_candidate_vehicles_per_partition: Optional[int] = 13,
        boundary_buffer_meters: float = 600.0,
        aging_weight_mps: float = 15.0,
    ) -> "CandidateGenerationConfig":
        """Constructs a BOUNDED mode configuration with explicit approximation limits."""
        return cls(
            mode=DispatchMode.BOUNDED,
            max_search_radius_meters=max_search_radius_meters,
            max_vehicles_per_request=max_vehicles_per_request,
            max_candidate_vehicles=max_candidate_vehicles,
            max_requests_per_vehicle=max_requests_per_vehicle,
            max_single_requests_per_vehicle=max_single_requests_per_vehicle,
            max_bundle_size=max_bundle_size,
            exhaustive_fallback=exhaustive_fallback,
            initial_search_radius_meters=initial_search_radius_meters,
            propagate_routing_errors=propagate_routing_errors,
            spatial_partitioning=spatial_partitioning,
            num_partitions=num_partitions,
            max_candidate_vehicles_per_partition=max_candidate_vehicles_per_partition,
            boundary_buffer_meters=boundary_buffer_meters,
            aging_weight_mps=aging_weight_mps,
        )


def _sort_requests_by_active_detour(
    requests: Sequence[RideRequest],
    vehicle: Vehicle,
    active_ride: Ride,
    req_pickup_coords: dict[str, Coordinate] | None = None,
    req_pickup_rad: dict[str, tuple[float, float, float]] | None = None,
    current_time: Optional[int] = None,
    aging_weight_mps: float = 0.0,
) -> list[RideRequest]:
    """
    Sorts candidate requests ascending by lower-bound detour distance relative to
    the vehicle's current location and remaining scheduled/in-progress stops.
    Incorporates starvation-aware aging credit when current_time and aging_weight_mps > 0.
    """
    v_loc = Coordinate(vehicle.current_location.latitude, vehicle.current_location.longitude)
    active_stops = [
        s
        for s in active_ride.stops
        if s.status
        in (StopStatus.SCHEDULED, StopStatus.ARRIVED, StopStatus.IN_GRACE_PERIOD)
    ]

    v_lat_rad = math.radians(vehicle.current_location.latitude)
    v_lon_rad = math.radians(vehicle.current_location.longitude)
    v_cos_lat = math.cos(v_lat_rad)
    v_rad = (v_lat_rad, v_lon_rad, v_cos_lat)

    def _fast_hav(r1: tuple[float, float, float], r2: tuple[float, float, float]) -> float:
        dlat = r2[0] - r1[0]
        dlon = r2[1] - r1[1]
        sin_half_dlat = math.sin(dlat * 0.5)
        sin_half_dlon = math.sin(dlon * 0.5)
        a = sin_half_dlat * sin_half_dlat + r1[2] * r2[2] * sin_half_dlon * sin_half_dlon
        return (2.0 * DEFAULT_EARTH_RADIUS_METERS) * math.asin(math.sqrt(min(1.0, a)))

    def _get_p_rad(req: RideRequest) -> tuple[float, float, float]:
        if req_pickup_rad is not None and req.request_id in req_pickup_rad:
            return req_pickup_rad[req.request_id]
        p_lat = math.radians(req.pickup_location.latitude)
        p_lon = math.radians(req.pickup_location.longitude)
        return (p_lat, p_lon, math.cos(p_lat))

    if not active_stops:
        if current_time is not None and aging_weight_mps > 0.0:
            return sorted(
                requests,
                key=lambda r: (
                    _fast_hav(v_rad, _get_p_rad(r))
                    - aging_weight_mps * max(0, current_time - r.earliest_pickup_time)
                ),
            )
        return sorted(requests, key=lambda r: _fast_hav(v_rad, _get_p_rad(r)))

    coords_rad = [v_rad] + [
        (
            math.radians(s.location.latitude),
            math.radians(s.location.longitude),
            math.cos(math.radians(s.location.latitude)),
        )
        for s in active_stops
    ]
    segment_lengths = [
        _fast_hav(coords_rad[i], coords_rad[i + 1])
        for i in range(len(coords_rad) - 1)
    ]

    def _req_detour_lower_bound(req: RideRequest) -> float:
        p = _get_p_rad(req)

        # Min detour to insert pickup P into any consecutive segment
        min_p_detour = float("inf")
        for i in range(len(coords_rad) - 1):
            det = (
                _fast_hav(coords_rad[i], p)
                + _fast_hav(p, coords_rad[i + 1])
                - segment_lengths[i]
            )
            if det < min_p_detour:
                min_p_detour = det
        append_detour = _fast_hav(coords_rad[-1], p)
        if append_detour < min_p_detour:
            min_p_detour = append_detour

        direct_pd = float(req.direct_distance_meters)
        base_detour = min_p_detour + direct_pd
        if current_time is not None and aging_weight_mps > 0.0:
            aging_credit = aging_weight_mps * float(max(0, current_time - req.earliest_pickup_time))
            return base_detour - aging_credit
        return base_detour

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
                max_single_requests_per_vehicle=effective_config.max_single_requests_per_vehicle,
                max_bundle_size=max_bundle_size,
                exhaustive_fallback=effective_config.exhaustive_fallback,
                initial_search_radius_meters=effective_config.initial_search_radius_meters,
                propagate_routing_errors=effective_config.propagate_routing_errors,
            )

        # Normalize config for exact mode
        if effective_config.mode == DispatchMode.EXACT:
            effective_config = CandidateGenerationConfig.exact(
                max_bundle_size=effective_config.max_bundle_size,
                propagate_routing_errors=effective_config.propagate_routing_errors,
            )
            is_approximated = False
            search_status = SearchStatus.COMPLETE
        else:
            is_approximated = bool(
                effective_config.max_search_radius_meters is not None
                or effective_config.max_vehicles_per_request is not None
                or effective_config.max_requests_per_vehicle is not None
                or effective_config.max_single_requests_per_vehicle is not None
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

        nearby_requests_by_vehicle: dict[str, list[tuple[float, RideRequest]]] = {
            v.vehicle_id: [] for v in eligible_vehicles
        }

        # Precompute pickup coordinates and radians for all pending requests once
        req_pickup_coords: dict[str, Coordinate] = {
            req.request_id: Coordinate(
                latitude=req.pickup_location.latitude,
                longitude=req.pickup_location.longitude,
            )
            for req in pending_requests
        }
        req_pickup_rad: dict[str, tuple[float, float, float]] = {
            req.request_id: (
                math.radians(req.pickup_location.latitude),
                math.radians(req.pickup_location.longitude),
                math.cos(math.radians(req.pickup_location.latitude)),
            )
            for req in pending_requests
        }

        # Precompute capable vehicle sets by required seat count once per batch
        capable_vehs_by_seats: dict[int, set[str]] = {
            s: {v.vehicle_id for v in eligible_vehicles if v.total_seat_capacity >= s}
            for s in set(r.seat_count for r in pending_requests)
        }

        # Exact vs Bounded spatial search configuration
        if effective_config.mode == DispatchMode.EXACT:
            for req in pending_requests:
                if time.monotonic() > effective_deadline - reserved_headroom:
                    search_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
                    is_approximated = True
                    break

                pickup_coord = req_pickup_coords[req.request_id]
                cap_filter = capable_vehs_by_seats[req.seat_count].__contains__
                # Exact mode: examine full physically reachable radius with no candidate limit
                capable = spatial_coord.find_candidates_within_radius(
                    target=pickup_coord,
                    max_radius_meters=r_reach,
                    min_candidates=1,
                    max_candidates=None,
                    entity_filter=cap_filter,
                )
                for sc in capable:
                    nearby_requests_by_vehicle[sc.entity_id].append((sc.haversine_distance_meters, req))
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

                pickup_coord = req_pickup_coords[req.request_id]

                if (
                    effective_config.exhaustive_fallback
                    and search_radius > effective_config.initial_search_radius_meters
                    and effective_config.initial_search_radius_meters > 0
                ):
                    probe_radius = effective_config.initial_search_radius_meters
                else:
                    probe_radius = search_radius

                cap_filter = capable_vehs_by_seats[req.seat_count].__contains__

                capable = list(
                    spatial_coord.find_candidates_within_radius(
                        target=pickup_coord,
                        max_radius_meters=probe_radius,
                        min_candidates=1,
                        max_candidates=effective_config.max_vehicles_per_request,
                        entity_filter=cap_filter,
                    )
                )

                # Bounded fallback if 0 capable vehicles found in initial probe
                if not capable and effective_config.exhaustive_fallback and probe_radius < r_reach:
                    capable = list(
                        spatial_coord.find_candidates_within_radius(
                            target=pickup_coord,
                            max_radius_meters=r_reach,
                            min_candidates=1,
                            max_candidates=effective_config.max_vehicles_per_request,
                            entity_filter=cap_filter,
                        )
                    )

                if effective_config.max_vehicles_per_request is not None:
                    capable = capable[: effective_config.max_vehicles_per_request]

                for sc in capable:
                    nearby_requests_by_vehicle[sc.entity_id].append((sc.haversine_distance_meters, req))

        candidates: list[CandidateAssignment] = []
        shared_leg_cache: dict[tuple[str, str], tuple[int, int] | None] = {}
        shared_routing_errors: list[RoutingProviderError] = []

        # Stage 3 Pre-pass: Prioritize candidate vehicles by closest candidate pickup distance
        candidate_vehicles_with_min_dist: list[tuple[float, Vehicle, list[tuple[float, RideRequest]]]] = []
        for veh_id, nearby_reqs in nearby_requests_by_vehicle.items():
            if not nearby_reqs:
                continue
            if effective_config.aging_weight_mps > 0.0:
                min_d = min(
                    pair[0]
                    - effective_config.aging_weight_mps
                    * max(0, current_time - pair[1].earliest_pickup_time)
                    for pair in nearby_reqs
                )
            else:
                min_d = min(d for d, _ in nearby_reqs)
            candidate_vehicles_with_min_dist.append((min_d, vehicles_by_id[veh_id], nearby_reqs))

        candidate_vehicles_with_min_dist.sort(key=operator.itemgetter(0))

        # Candidate vehicle truncation in bounded mode
        if (
            effective_config.mode != DispatchMode.EXACT
            and effective_config.max_candidate_vehicles is not None
        ):
            candidate_vehicles_with_min_dist = candidate_vehicles_with_min_dist[
                : effective_config.max_candidate_vehicles
            ]

        vehicle_eval_plan: list[tuple[Vehicle, Ride | None, list[RideRequest], list[Coordinate]]] = []
        waypoint_groups_to_prefetch: list[list[Coordinate]] = []

        for _, veh, nearby_reqs in candidate_vehicles_with_min_dist:
            active_ride = rides_by_vehicle.get(veh.vehicle_id)
            if active_ride is not None:
                plain_reqs = [r for _, r in nearby_reqs]
                sorted_reqs = _sort_requests_by_active_detour(
                    plain_reqs,
                    veh,
                    active_ride,
                    req_pickup_coords=req_pickup_coords,
                    req_pickup_rad=req_pickup_rad,
                    current_time=current_time,
                    aging_weight_mps=effective_config.aging_weight_mps,
                )
            else:
                if effective_config.aging_weight_mps > 0.0:
                    sorted_reqs = [
                        r
                        for _, r in sorted(
                            nearby_reqs,
                            key=lambda pair: (
                                pair[0]
                                - effective_config.aging_weight_mps
                                * max(0, current_time - pair[1].earliest_pickup_time)
                            ),
                        )
                    ]
                else:
                    sorted_reqs = [r for _, r in sorted(nearby_reqs, key=operator.itemgetter(0))]

            # Request slicing: strictly controlled by explicit configuration
            if effective_config.mode == DispatchMode.EXACT:
                eval_reqs = sorted_reqs
            else:
                single_cap = effective_config.max_single_requests_per_vehicle
                bundle_cap = effective_config.max_requests_per_vehicle
                effective_eval_cap = (
                    max(single_cap or 0, bundle_cap or 0)
                    if (single_cap is not None or bundle_cap is not None)
                    else None
                )
                eval_reqs = sorted_reqs[:effective_eval_cap] if effective_eval_cap is not None else sorted_reqs

            if not eval_reqs:
                continue

            v_wps = [Coordinate(veh.current_location.latitude, veh.current_location.longitude)]
            if active_ride is not None:
                v_wps.extend([
                    Coordinate(s.location.latitude, s.location.longitude)
                    for s in active_ride.stops
                    if s.status in (StopStatus.SCHEDULED, StopStatus.ARRIVED, StopStatus.IN_GRACE_PERIOD)
                ])
            for r in eval_reqs:
                v_wps.append(Coordinate(r.pickup_location.latitude, r.pickup_location.longitude))
                v_wps.append(Coordinate(r.dropoff_location.latitude, r.dropoff_location.longitude))

            vehicle_eval_plan.append((veh, active_ride, eval_reqs, v_wps))
            waypoint_groups_to_prefetch.append(v_wps)

        # Launch asynchronous pipelined prefetch if supported by routing provider
        prefetch_handle = self.routing_provider.start_prefetch_matrices(
            groups=waypoint_groups_to_prefetch,
            deadline=effective_deadline,
            reserved_headroom=reserved_headroom,
        )

        # Synchronous prefetch fallback if pipelining is not supported
        if (
            prefetch_handle is None
            and (
                type(self.routing_provider).prefetch_matrices is not RoadNetworkRoutingProvider.prefetch_matrices
                or type(self.routing_provider).prefetch_matrix is not RoadNetworkRoutingProvider.prefetch_matrix
            )
            and waypoint_groups_to_prefetch
        ):
            prefetch_headroom = reserved_headroom + 0.050
            self.routing_provider.prefetch_matrices(
                groups=waypoint_groups_to_prefetch,
                deadline=effective_deadline,
                reserved_headroom=prefetch_headroom,
            )

        try:
            # Stage 3 & 4: Route Insertion & Group Bundling
            for idx, (veh, active_ride, eval_reqs, v_wps) in enumerate(vehicle_eval_plan):
                if time.monotonic() > effective_deadline - reserved_headroom:
                    search_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
                    is_approximated = True
                    break

                # If pipelined prefetch is active, wait for this specific vehicle's group
                if prefetch_handle is not None:
                    rem_budget = max(0.001, (effective_deadline - reserved_headroom) - time.monotonic())
                    try:
                        prefetch_handle.wait_group(idx, timeout=rem_budget)
                    except TimeoutError:
                        search_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
                        is_approximated = True
                        break
                    except Exception:
                        pass

                if time.monotonic() > effective_deadline - reserved_headroom:
                    search_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
                    is_approximated = True
                    break

                max_bundle_reqs = (
                    effective_config.max_requests_per_vehicle
                    if effective_config.mode != DispatchMode.EXACT
                    else None
                )

                # Defensive per-vehicle fallback prefetch (instant O(1) no-op if already cached)
                if (
                    prefetch_handle is None
                    and type(self.routing_provider).prefetch_matrix is not RoadNetworkRoutingProvider.prefetch_matrix
                    and eval_reqs
                ):
                    self.routing_provider.prefetch_matrix(
                        origins=v_wps,
                        destinations=v_wps,
                        deadline=effective_deadline,
                        reserved_headroom=reserved_headroom,
                    )

                if active_ride is not None:
                    ins_cands = generate_active_ride_insertions(
                        active_ride=active_ride,
                        requests=eval_reqs,
                        vehicle=veh,
                        router=self.routing_provider,
                        policy=policy,
                        current_time=current_time,
                        max_bundle_size=effective_config.max_bundle_size,
                        deadline=effective_deadline,
                        reserved_headroom=reserved_headroom,
                        max_bundle_requests=max_bundle_reqs,
                        shared_leg_cache=shared_leg_cache,
                        shared_routing_errors=shared_routing_errors,
                        propagate_routing_errors=effective_config.propagate_routing_errors,
                    )
                    candidates.extend(ins_cands)
                    if time.monotonic() > effective_deadline - reserved_headroom:
                        search_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
                        is_approximated = True
                        break
                else:
                    bundle_cands = generate_group_bundles(
                        requests=eval_reqs,
                        vehicle=veh,
                        router=self.routing_provider,
                        policy=policy,
                        current_time=current_time,
                        max_bundle_size=effective_config.max_bundle_size,
                        deadline=effective_deadline,
                        reserved_headroom=reserved_headroom,
                        max_bundle_requests=max_bundle_reqs,
                        shared_leg_cache=shared_leg_cache,
                        shared_routing_errors=shared_routing_errors,
                        propagate_routing_errors=effective_config.propagate_routing_errors,
                    )
                    candidates.extend(bundle_cands)
                    if time.monotonic() > effective_deadline - reserved_headroom:
                        search_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
                        is_approximated = True
                        break
        finally:
            if prefetch_handle is not None:
                prefetch_handle.cancel()

        if shared_routing_errors and search_status != SearchStatus.INCOMPLETE_DEADLINE_EXPIRED:
            if effective_config.mode == DispatchMode.EXACT:
                search_status = SearchStatus.INCOMPLETE_ROUTING_ERROR
                is_approximated = True
            else:
                is_approximated = True

        return CandidateList(
            candidates=candidates,
            dispatch_mode=effective_config.mode,
            search_status=search_status,
            is_approximated=is_approximated,
            routing_errors_count=len(shared_routing_errors),
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

        # Validate and deduplicate requests and vehicles by canonical entity ID
        requests_by_id: dict[str, RideRequest] = {}
        for r in requests:
            if r.status != RequestStatus.PENDING:
                continue
            if r.request_id in requests_by_id:
                existing_r = requests_by_id[r.request_id]
                if r != existing_r:
                    raise ValueError(
                        f"Conflicting duplicate request detected for request_id '{r.request_id}'"
                    )
                continue
            requests_by_id[r.request_id] = r

        vehicles_by_id: dict[str, Vehicle] = {}
        for v in vehicles:
            if not v.is_active:
                continue
            if v.vehicle_id in vehicles_by_id:
                existing_v = vehicles_by_id[v.vehicle_id]
                if v != existing_v:
                    raise ValueError(
                        f"Conflicting duplicate vehicle detected for vehicle_id '{v.vehicle_id}'"
                    )
                continue
            vehicles_by_id[v.vehicle_id] = v

        pending_requests = list(requests_by_id.values())
        eligible_vehicles = list(vehicles_by_id.values())
        all_req_ids = tuple(sorted(requests_by_id.keys()))

        # Stage 1: Fast Input Validation
        if not pending_requests or not eligible_vehicles:
            solve_duration = (time.monotonic() - start_monotonic) * 1000.0
            return MatchResult(
                match_id=f"match-{uuid.uuid4()}",
                batch_id=effective_batch_id,
                solver_timestamp=current_time,
                selected_assignments=(),
                unassigned_request_ids=all_req_ids,
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
                unassigned_request_ids=all_req_ids,
                total_vmt_savings_meters=0,
                solve_duration_ms=solve_duration,
                dispatch_mode=effective_config.mode,
                search_status=SearchStatus.INCOMPLETE_DEADLINE_EXPIRED,
                is_approximated=True,
            )

        # Stage 2: Spatial Partitioning for larger fleets in Bounded Mode
        if (
            effective_config.mode != DispatchMode.EXACT
            and effective_config.spatial_partitioning
            and len(eligible_vehicles) > 32
        ):
            return self._dispatch_partitioned_batch(
                pending_requests=pending_requests,
                eligible_vehicles=eligible_vehicles,
                active_rides=active_rides,
                current_time=current_time,
                effective_batch_id=effective_batch_id,
                effective_deadline=effective_deadline,
                reserved_headroom=reserved_headroom,
                effective_config=effective_config,
                all_req_ids=all_req_ids,
                start_monotonic=start_monotonic,
                max_bundle_size=max_bundle_size,
            )

        # Stage 2, 3, 4: Candidate Generation
        # Reserve headroom for set packing solver (headroom + 15ms)
        cand_headroom = reserved_headroom + 0.015
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
        # Reserve 25ms headroom for Stage 6 validation and serialization
        solver_reserved_headroom = min(reserved_headroom, 0.025)
        solver_result = solve_set_packing_regret_k(
            candidates=candidates,
            all_request_ids=all_req_ids,
            deadline=effective_deadline,
            reserved_headroom=solver_reserved_headroom,
        )

        solve_duration_ms = (time.monotonic() - start_monotonic) * 1000.0

        if solver_result.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED:
            effective_search_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
            effective_is_approximated = True
        elif candidates.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED:
            effective_search_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
            effective_is_approximated = True
        elif time.monotonic() >= effective_deadline:
            effective_search_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
            effective_is_approximated = True
        elif candidates.search_status == SearchStatus.INCOMPLETE_ROUTING_ERROR:
            effective_search_status = SearchStatus.INCOMPLETE_ROUTING_ERROR
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
            routing_errors_count=candidates.routing_errors_count,
        )

        return match_result

    def _dispatch_partitioned_batch(
        self,
        pending_requests: list[RideRequest],
        eligible_vehicles: list[Vehicle],
        active_rides: Sequence[Ride],
        current_time: int,
        effective_batch_id: str,
        effective_deadline: float,
        reserved_headroom: float,
        effective_config: CandidateGenerationConfig,
        all_req_ids: tuple[str, ...],
        start_monotonic: float,
        max_bundle_size: Optional[int] = None,
    ) -> MatchResult:
        """
        Executes a spatially partitioned dispatch cycle for regional fleets:
        1. Partitions requests and vehicles into K regional sectors along the principal spatial axis.
        2. Assigns vehicles strictly to their home sector (disjoint vehicle ownership).
        3. Buffers boundary requests within boundary_buffer_meters to adjacent sectors.
        4. Launches unified concurrent matrix prefetch across all sector waypoint groups.
        5. Evaluates candidate insertions and group bundles per sector.
        6. Resolves conflicts globally via unified set-packing regret-K solver, guaranteeing zero
           duplicate assignments, zero double-booked seats, and atomic commit semantics.
        """
        n_veh = len(eligible_vehicles)
        if effective_config.num_partitions is not None:
            num_partitions = effective_config.num_partitions
        elif n_veh <= 60:
            num_partitions = 2
        else:
            num_partitions = 3

        cand_veh_limit_default = effective_config.max_candidate_vehicles_per_partition or 13
        total_cand_limit = (
            effective_config.max_candidate_vehicles
            if effective_config.max_candidate_vehicles is not None
            else (cand_veh_limit_default * num_partitions)
        )
        buffer_m = effective_config.boundary_buffer_meters
        buffer_deg = buffer_m / 111000.0

        # Determine partition boundaries along the active spatial extent
        all_lats = [r.pickup_location.latitude for r in pending_requests] + [
            v.current_location.latitude for v in eligible_vehicles
        ]
        min_lat = min(all_lats)
        max_lat = max(all_lats)
        lat_span = max_lat - min_lat
        if lat_span > 1e-5:
            split_lats = [
                min_lat + lat_span * (i / num_partitions)
                for i in range(1, num_partitions)
            ]
        else:
            split_lats = []

        def get_home_sector(lat: float) -> int:
            for s_idx, split_lat in enumerate(split_lats):
                if lat < split_lat:
                    return s_idx
            return len(split_lats)

        # Vehicle assignment: strictly disjoint home sector ownership
        vehs_by_sector: list[list[Vehicle]] = [[] for _ in range(num_partitions)]
        for v in eligible_vehicles:
            vehs_by_sector[get_home_sector(v.current_location.latitude)].append(v)

        # Request assignment: home sector + adjacent sectors if within boundary buffer
        reqs_by_sector: list[list[RideRequest]] = [[] for _ in range(num_partitions)]
        for r in pending_requests:
            p_lat = r.pickup_location.latitude
            home_sec = get_home_sector(p_lat)
            reqs_by_sector[home_sec].append(r)

            if home_sec > 0 and abs(p_lat - split_lats[home_sec - 1]) <= buffer_deg:
                reqs_by_sector[home_sec - 1].append(r)
            if home_sec < num_partitions - 1 and abs(p_lat - split_lats[home_sec]) <= buffer_deg:
                reqs_by_sector[home_sec + 1].append(r)

        total_reqs = sum(len(reqs) for reqs in reqs_by_sector)
        rides_by_veh = {r.vehicle_id: r for r in active_rides}
        policy = self.policy_provider.get_policy()

        # Build candidate evaluation plans across all sectors
        all_eval_plans: list[tuple[Vehicle, Ride | None, list[RideRequest], list[Coordinate]]] = []
        all_waypoint_groups: list[list[Coordinate]] = []

        max_single_cap = (
            min(4, effective_config.max_single_requests_per_vehicle)
            if effective_config.max_single_requests_per_vehicle is not None
            else 4
        )

        for sec in range(num_partitions):
            sec_reqs = reqs_by_sector[sec]
            sec_vehs = vehs_by_sector[sec]
            if not sec_reqs or not sec_vehs:
                continue

            # Demand-proportional candidate vehicle limit across sectors
            if total_reqs > 0:
                prop_limit = round(total_cand_limit * (len(sec_reqs) / total_reqs))
                sec_cand_limit = max(8, min(20, prop_limit))
            else:
                sec_cand_limit = cand_veh_limit_default

            # Query nearby vehicles within this sector
            coord = SpatialIndexCoordinator(self.spatial_index)
            coord.index_entities([
                (v.vehicle_id, Coordinate(v.current_location.latitude, v.current_location.longitude))
                for v in sec_vehs
            ])

            nearby: dict[str, list[tuple[float, RideRequest]]] = {v.vehicle_id: [] for v in sec_vehs}
            for r in sec_reqs:
                cands = coord.find_candidates_within_radius(
                    Coordinate(r.pickup_location.latitude, r.pickup_location.longitude),
                    effective_config.max_search_radius_meters or 5000.0,
                    1,
                    effective_config.max_vehicles_per_request or 8,
                )
                for c in cands:
                    nearby[c.entity_id].append((c.haversine_distance_meters, r))

            if effective_config.aging_weight_mps > 0.0:
                cand_vehs = [
                    (
                        min(
                            pair[0]
                            - effective_config.aging_weight_mps
                            * max(0, current_time - pair[1].earliest_pickup_time)
                            for pair in req_list
                        ),
                        v,
                        req_list,
                    )
                    for v in sec_vehs
                    if (req_list := nearby.get(v.vehicle_id))
                ]
            else:
                cand_vehs = [
                    (min(d for d, _ in req_list), v, req_list)
                    for v in sec_vehs
                    if (req_list := nearby.get(v.vehicle_id))
                ]
            cand_vehs.sort(key=operator.itemgetter(0))
            cand_vehs = cand_vehs[:sec_cand_limit]

            for _, veh, nearby_reqs in cand_vehs:
                active_ride = rides_by_veh.get(veh.vehicle_id)
                if active_ride is not None:
                    plain_reqs = [r for _, r in nearby_reqs]
                    sorted_reqs = _sort_requests_by_active_detour(
                        plain_reqs,
                        veh,
                        active_ride,
                        current_time=current_time,
                        aging_weight_mps=effective_config.aging_weight_mps,
                    )
                else:
                    if effective_config.aging_weight_mps > 0.0:
                        sorted_reqs = [
                            r
                            for _, r in sorted(
                                nearby_reqs,
                                key=lambda pair: (
                                    pair[0]
                                    - effective_config.aging_weight_mps
                                    * max(0, current_time - pair[1].earliest_pickup_time)
                                ),
                            )
                        ]
                    else:
                        sorted_reqs = [r for _, r in sorted(nearby_reqs, key=operator.itemgetter(0))]
                eval_reqs = sorted_reqs[:max_single_cap]
                if not eval_reqs:
                    continue

                v_wps = [Coordinate(veh.current_location.latitude, veh.current_location.longitude)]
                if active_ride is not None:
                    v_wps.extend([
                        Coordinate(s.location.latitude, s.location.longitude)
                        for s in active_ride.stops
                        if s.status in (StopStatus.SCHEDULED, StopStatus.ARRIVED, StopStatus.IN_GRACE_PERIOD)
                    ])
                for r in eval_reqs:
                    v_wps.append(Coordinate(r.pickup_location.latitude, r.pickup_location.longitude))
                    v_wps.append(Coordinate(r.dropoff_location.latitude, r.dropoff_location.longitude))

                all_eval_plans.append((veh, active_ride, eval_reqs, v_wps))
                all_waypoint_groups.append(v_wps)

        # Launch unified concurrent prefetch across all sector groups
        prefetch_handle = self.routing_provider.start_prefetch_matrices(
            groups=all_waypoint_groups,
            deadline=effective_deadline,
            reserved_headroom=reserved_headroom,
        )

        all_candidates: list[CandidateAssignment] = []
        search_status = SearchStatus.APPROXIMATED
        is_approximated = True
        shared_leg_cache: dict[tuple[str, str], tuple[int, int] | None] = {}
        shared_routing_errors: list[RoutingProviderError] = []

        try:
            for idx, (veh, active_ride, eval_reqs, v_wps) in enumerate(all_eval_plans):
                if time.monotonic() > effective_deadline - reserved_headroom:
                    search_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
                    break

                if prefetch_handle is not None:
                    rem_budget = max(0.001, (effective_deadline - reserved_headroom) - time.monotonic())
                    try:
                        prefetch_handle.wait_group(idx, timeout=rem_budget)
                    except TimeoutError:
                        search_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
                        break
                    except Exception:
                        pass

                if time.monotonic() > effective_deadline - reserved_headroom:
                    search_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
                    break

                effective_bundle_size = (
                    max_bundle_size
                    if max_bundle_size is not None
                    else effective_config.max_bundle_size
                )
                max_bundle_reqs = effective_config.max_requests_per_vehicle

                if active_ride is not None:
                    ins_cands = generate_active_ride_insertions(
                        active_ride=active_ride,
                        requests=eval_reqs,
                        vehicle=veh,
                        router=self.routing_provider,
                        policy=policy,
                        current_time=current_time,
                        max_bundle_size=effective_bundle_size,
                        deadline=effective_deadline,
                        reserved_headroom=reserved_headroom,
                        max_bundle_requests=max_bundle_reqs,
                        shared_leg_cache=shared_leg_cache,
                        shared_routing_errors=shared_routing_errors,
                        propagate_routing_errors=effective_config.propagate_routing_errors,
                    )
                    all_candidates.extend(ins_cands)
                else:
                    bundle_cands = generate_group_bundles(
                        requests=eval_reqs,
                        vehicle=veh,
                        router=self.routing_provider,
                        policy=policy,
                        current_time=current_time,
                        max_bundle_size=effective_bundle_size,
                        deadline=effective_deadline,
                        reserved_headroom=reserved_headroom,
                        max_bundle_requests=max_bundle_reqs,
                        shared_leg_cache=shared_leg_cache,
                        shared_routing_errors=shared_routing_errors,
                        propagate_routing_errors=effective_config.propagate_routing_errors,
                    )
                    all_candidates.extend(bundle_cands)
        finally:
            if prefetch_handle is not None:
                prefetch_handle.cancel()

        # Global Set-Packing Conflict Resolution across all partition candidates
        solver_reserved_headroom = min(reserved_headroom, 0.025)
        solver_result = solve_set_packing_regret_k(
            candidates=all_candidates,
            all_request_ids=all_req_ids,
            deadline=effective_deadline,
            reserved_headroom=solver_reserved_headroom,
        )

        solve_duration_ms = (time.monotonic() - start_monotonic) * 1000.0

        if solver_result.search_status == SearchStatus.INCOMPLETE_DEADLINE_EXPIRED:
            search_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
        elif time.monotonic() >= effective_deadline:
            search_status = SearchStatus.INCOMPLETE_DEADLINE_EXPIRED
        elif shared_routing_errors and effective_config.mode == DispatchMode.EXACT:
            search_status = SearchStatus.INCOMPLETE_ROUTING_ERROR

        return MatchResult(
            match_id=f"match-{uuid.uuid4()}",
            batch_id=effective_batch_id,
            solver_timestamp=current_time,
            selected_assignments=solver_result.selected_assignments,
            unassigned_request_ids=solver_result.unassigned_request_ids,
            total_vmt_savings_meters=solver_result.total_vmt_savings_meters,
            solve_duration_ms=round(solve_duration_ms, 2),
            dispatch_mode=effective_config.mode,
            search_status=search_status,
            is_approximated=is_approximated,
            routing_errors_count=len(shared_routing_errors),
        )
