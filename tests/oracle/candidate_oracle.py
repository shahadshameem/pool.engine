"""
Independent, first-principles candidate-enumeration test oracle for ride-pooling.

This oracle independently enumerates all physically and temporally feasible candidate
assignments without importing or calling any production candidate generation functions
(such as generate_single_request_insertions or generate_group_bundles).
"""

from dataclasses import dataclass
import itertools
from typing import Optional, Sequence

from engine.contracts.policy import DispatchPolicy
from engine.contracts.routing import Coordinate, RoadNetworkRoutingProvider
from engine.domain.candidate import CandidateAssignment
from engine.domain.enums import RequestStatus, RideStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle


@dataclass(frozen=True)
class OracleCandidateSignature:
    """Canonical identifier and physical characteristics of a feasible candidate route."""
    vehicle_id: str
    request_ids: tuple[str, ...]
    ordered_stop_ids: tuple[str, ...]
    peak_occupancy: int
    total_vmt_meters: int

    @property
    def key(self) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
        return (self.vehicle_id, self.request_ids, self.ordered_stop_ids)


@dataclass(frozen=True)
class OracleComparisonResult:
    """Outcome of comparing production candidate generation against the first-principles oracle."""
    oracle_count: int
    production_count: int
    matching_count: int
    false_negatives: tuple[OracleCandidateSignature, ...]
    false_positives: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]
    recall_pct: float
    precision_pct: float

    @property
    def is_perfect_match(self) -> bool:
        return len(self.false_negatives) == 0 and len(self.false_positives) == 0


def _generate_oracle_request_stops(
    request: RideRequest,
    ride_id: str,
) -> tuple[RouteStop, RouteStop]:
    """Generates canonical RouteStop instances for an incoming request from first principles."""
    p_stop = RouteStop(
        stop_id=f"stop-p-{request.request_id}",
        ride_id=ride_id,
        request_id=request.request_id,
        stop_type=StopType.PICKUP,
        location=request.pickup_location,
        passenger_delta=+request.seat_count,
        scheduled_arrival_time=0,
        promised_window_start=request.earliest_pickup_time,
        promised_window_end=request.earliest_pickup_time,
        status=StopStatus.SCHEDULED,
    )
    d_stop = RouteStop(
        stop_id=f"stop-d-{request.request_id}",
        ride_id=ride_id,
        request_id=request.request_id,
        stop_type=StopType.DROPOFF,
        location=request.dropoff_location,
        passenger_delta=-request.seat_count,
        scheduled_arrival_time=0,
        promised_window_start=request.earliest_pickup_time,
        promised_window_end=request.latest_dropoff_time,
        status=StopStatus.SCHEDULED,
    )
    return p_stop, d_stop


def _generate_all_precedence_permutations(
    request_stop_pairs: Sequence[tuple[RouteStop, RouteStop]],
) -> list[list[RouteStop]]:
    """
    Recursively enumerates all valid orderings of 2*K stops such that for each pair (P, D),
    P strictly precedes D.
    """
    if not request_stop_pairs:
        return []

    sequences: list[list[RouteStop]] = [[request_stop_pairs[0][0], request_stop_pairs[0][1]]]

    for p_stop, d_stop in request_stop_pairs[1:]:
        next_sequences: list[list[RouteStop]] = []
        for seq in sequences:
            n = len(seq)
            for i in range(n + 1):
                for j in range(i + 1, n + 2):
                    new_seq = seq[:i] + [p_stop] + seq[i : j - 1] + [d_stop] + seq[j - 1 :]
                    next_sequences.append(new_seq)
        sequences = next_sequences

    return sequences


def _evaluate_candidate_feasibility(
    vehicle_loc: Coordinate,
    stops: Sequence[RouteStop],
    initial_passengers: int,
    capacity: int,
    eval_requests: Sequence[RideRequest],
    active_ride: Optional[Ride],
    router: RoadNetworkRoutingProvider,
    policy: DispatchPolicy,
    current_time: int,
) -> Optional[tuple[int, int]]:
    """
    Independently verifies physical and temporal invariants:
    1. Precedence: Pickup before dropoff for all requests.
    2. Capacity conservation: Occupancy in [0, capacity] across all legs.
    3. Pickup delay limit: Arrival at pickup <= earliest_pickup + max_pickup_delay.
    4. Detour limits: Additional in-vehicle duration <= min((alpha-1)*direct, C).
    5. Active ride promise windows: Future dropoffs arrive <= promised_window_end.

    Returns (peak_occupancy, total_vmt_meters) if feasible, or None if infeasible.
    """
    # 1. First-principles Precedence Invariant
    seen_pickups: set[str] = set()
    for s in stops:
        if s.stop_type == StopType.PICKUP:
            seen_pickups.add(s.request_id)
        elif s.stop_type == StopType.DROPOFF:
            # Dropoff must have a preceding pickup in the candidate route or be an onboard passenger from active ride
            if s.request_id not in seen_pickups:
                if active_ride is None:
                    return None
                existing_pickups = {
                    st.request_id for st in active_ride.stops if st.stop_type == StopType.PICKUP
                }
                if s.request_id in existing_pickups:
                    return None
                existing_dropoff_ids = {
                    st.request_id for st in active_ride.stops if st.stop_type == StopType.DROPOFF
                }
                if s.request_id not in existing_dropoff_ids:
                    return None

    # 2. First-principles Capacity Profile Invariant
    curr_occ = initial_passengers
    peak_occ = curr_occ
    if curr_occ > capacity or curr_occ < 0:
        return None

    for s in stops:
        curr_occ += s.passenger_delta
        if curr_occ < 0 or curr_occ > capacity:
            return None
        if curr_occ > peak_occ:
            peak_occ = curr_occ

    # 3. First-principles Routing & Travel Times
    waypoints = [vehicle_loc] + [
        Coordinate(latitude=s.location.latitude, longitude=s.location.longitude)
        for s in stops
    ]

    current_clock = current_time
    total_vmt = 0
    arrival_times: dict[str, int] = {}

    for idx, s in enumerate(stops):
        leg_dist, leg_dur = router.get_direct_leg(waypoints[idx], waypoints[idx + 1])
        total_vmt += leg_dist
        current_clock += leg_dur
        arrival_times[s.stop_id] = current_clock
        current_clock += s.dwell_duration_seconds

    # 4. First-principles Temporal Bounds for New Requests
    for req in eval_requests:
        p_id = f"stop-p-{req.request_id}"
        d_id = f"stop-d-{req.request_id}"
        if p_id not in arrival_times or d_id not in arrival_times:
            return None

        p_time = arrival_times[p_id]
        d_time = arrival_times[d_id]

        # Pickup delay
        if p_time - req.earliest_pickup_time > policy.max_pickup_delay_seconds:
            return None
        if p_time < 0:
            return None

        # In-vehicle detour
        in_veh_dur = max(0, d_time - p_time)
        detour = max(0, in_veh_dur - req.direct_duration_seconds)
        max_detour = min(
            (policy.detour_relative_multiplier - 1.0) * float(req.direct_duration_seconds),
            float(policy.detour_absolute_cap_seconds),
        )
        if detour > (max_detour + 1e-6):
            return None

    # 5. First-principles Temporal Bounds for Existing Active Stops
    if active_ride is not None:
        existing_stop_ids = {st.stop_id for st in active_ride.stops}
        for s in stops:
            if s.stop_id in existing_stop_ids and s.stop_type == StopType.DROPOFF and s.stop_id in arrival_times:
                arr = arrival_times[s.stop_id]
                if arr > s.promised_window_end:
                    return None

                p_match = next(
                    (st for st in active_ride.stops if st.request_id == s.request_id and st.stop_type == StopType.PICKUP),
                    None,
                )
                if p_match is not None:
                    p_time = arrival_times.get(
                        p_match.stop_id,
                        p_match.actual_arrival_time or p_match.scheduled_arrival_time,
                    )
                    orig_p = p_match.actual_arrival_time or p_match.scheduled_arrival_time
                    orig_dur = max(0, s.scheduled_arrival_time - orig_p)
                    if orig_dur > 0:
                        act_dur = max(0, arr - p_time)
                        det = max(0, act_dur - orig_dur)
                        max_det = min(
                            (policy.detour_relative_multiplier - 1.0) * float(orig_dur),
                            float(policy.detour_absolute_cap_seconds),
                        )
                        if det > (max_det + 1e-6):
                            return None

    return peak_occ, total_vmt


class IndependentCandidateOracle:
    """
    First-principles test oracle for ride-pooling candidate enumeration.
    Operates without importing or delegating to production routing permutation generators.
    """

    def __init__(
        self,
        router: RoadNetworkRoutingProvider,
        policy: DispatchPolicy,
        max_bundle_size: int = 2,
    ) -> None:
        self.router = router
        self.policy = policy
        self.max_bundle_size = max_bundle_size

    def enumerate_feasible_candidates(
        self,
        requests: Sequence[RideRequest],
        vehicles: Sequence[Vehicle],
        active_rides: Sequence[Ride],
        current_time: int,
    ) -> list[OracleCandidateSignature]:
        """
        Independently enumerates all feasible candidate signatures across eligible vehicles
        and pending requests.
        """
        pending_requests = [r for r in requests if r.status == RequestStatus.PENDING]
        eligible_vehicles = [v for v in vehicles if v.is_active]

        rides_by_veh = {
            r.vehicle_id: r
            for r in active_rides
            if r.lifecycle_status in (RideStatus.ACTIVE, RideStatus.SCHEDULED)
        }

        candidates: list[OracleCandidateSignature] = []

        for veh in eligible_vehicles:
            v_loc = Coordinate(
                latitude=veh.current_location.latitude,
                longitude=veh.current_location.longitude,
            )
            active_ride = rides_by_veh.get(veh.vehicle_id)

            if active_ride is not None:
                # Active ride: evaluate single-request insertions
                future_stops = [
                    s for s in active_ride.stops
                    if s.status in (StopStatus.SCHEDULED, StopStatus.ARRIVED, StopStatus.IN_GRACE_PERIOD)
                ]
                n = len(future_stops)
                t_start = current_time if current_time is not None else active_ride.scheduled_departure_time

                for req in pending_requests:
                    if req.seat_count > veh.total_seat_capacity:
                        continue

                    p_stop, d_stop = _generate_oracle_request_stops(req, active_ride.ride_id)

                    for i in range(n + 1):
                        for j in range(i + 1, n + 2):
                            candidate_stops = (
                                future_stops[:i]
                                + [p_stop]
                                + future_stops[i : j - 1]
                                + [d_stop]
                                + future_stops[j - 1 :]
                            )

                            eval_res = _evaluate_candidate_feasibility(
                                vehicle_loc=v_loc,
                                stops=candidate_stops,
                                initial_passengers=active_ride.active_passenger_count,
                                capacity=veh.total_seat_capacity,
                                eval_requests=[req],
                                active_ride=active_ride,
                                router=self.router,
                                policy=self.policy,
                                current_time=t_start,
                            )
                            if eval_res is not None:
                                peak_occ, total_vmt = eval_res
                                sig = OracleCandidateSignature(
                                    vehicle_id=veh.vehicle_id,
                                    request_ids=(req.request_id,),
                                    ordered_stop_ids=tuple(s.stop_id for s in candidate_stops),
                                    peak_occupancy=peak_occ,
                                    total_vmt_meters=total_vmt,
                                )
                                candidates.append(sig)
            else:
                # Idle vehicle: evaluate multi-passenger group bundles up to max_bundle_size
                capable_requests = [
                    r for r in pending_requests if r.seat_count <= veh.total_seat_capacity
                ]
                for bundle_size in range(1, min(self.max_bundle_size, len(capable_requests)) + 1):
                    for req_subset in itertools.combinations(capable_requests, bundle_size):
                        req_pairs = [_generate_oracle_request_stops(r, "ride-new") for r in req_subset]
                        valid_orderings = _generate_all_precedence_permutations(req_pairs)

                        sorted_req_ids = tuple(sorted(r.request_id for r in req_subset))

                        for stop_seq in valid_orderings:
                            eval_res = _evaluate_candidate_feasibility(
                                vehicle_loc=v_loc,
                                stops=stop_seq,
                                initial_passengers=0,
                                capacity=veh.total_seat_capacity,
                                eval_requests=req_subset,
                                active_ride=None,
                                router=self.router,
                                policy=self.policy,
                                current_time=current_time,
                            )
                            if eval_res is not None:
                                peak_occ, total_vmt = eval_res
                                sig = OracleCandidateSignature(
                                    vehicle_id=veh.vehicle_id,
                                    request_ids=sorted_req_ids,
                                    ordered_stop_ids=tuple(s.stop_id for s in stop_seq),
                                    peak_occupancy=peak_occ,
                                    total_vmt_meters=total_vmt,
                                )
                                candidates.append(sig)

        return candidates

    def compare(
        self,
        production_candidates: Sequence[CandidateAssignment],
        oracle_candidates: Sequence[OracleCandidateSignature],
    ) -> OracleComparisonResult:
        """
        Compares production candidate set against oracle results using canonical signatures.
        """
        oracle_map = {c.key: c for c in oracle_candidates}
        prod_map = {
            (c.vehicle_id, tuple(sorted(c.request_ids)), tuple(s.stop_id for s in c.ordered_stops)): c
            for c in production_candidates
        }

        matches = set(oracle_map.keys()) & set(prod_map.keys())
        false_negatives = tuple(oracle_map[k] for k in oracle_map.keys() - prod_map.keys())
        false_positives = tuple(k for k in prod_map.keys() - oracle_map.keys())

        oracle_count = len(oracle_map)
        prod_count = len(prod_map)
        recall = (len(matches) / oracle_count * 100.0) if oracle_count > 0 else 100.0
        precision = (len(matches) / prod_count * 100.0) if prod_count > 0 else 100.0

        return OracleComparisonResult(
            oracle_count=oracle_count,
            production_count=prod_count,
            matching_count=len(matches),
            false_negatives=false_negatives,
            false_positives=false_positives,
            recall_pct=round(recall, 2),
            precision_pct=round(precision, 2),
        )
