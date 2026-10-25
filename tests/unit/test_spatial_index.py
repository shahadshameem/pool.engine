"""Unit tests for spatial candidate filtering, lower bounds, recall, and fallback (T022, T023, T024)."""

import math
import pytest
from typing import Sequence

from engine.contracts.routing import Coordinate, MatrixResult, RoadNetworkRoutingProvider, RouteGeometry
from engine.contracts.spatial import SpatialCandidate
from engine.spatial.lower_bounds import (
    compute_derived_bounding_box,
    haversine_distance_meters,
    is_in_bounding_box,
    is_insertion_detour_feasible,
    is_pickup_reachable,
    min_insertion_detour_meters,
    min_travel_time_seconds,
)
from engine.spatial.index import SpatialIndexCoordinator
from engine.adapters.h3_spatial import H3SpatialIndexAdapter


class CountingMockRoutingProvider(RoadNetworkRoutingProvider):
    """Mock router that counts get_direct_leg invocations to verify pruning."""
    def __init__(self) -> None:
        self.call_count = 0

    def get_distance_matrix(self, origins: Sequence[Coordinate], destinations: Sequence[Coordinate]) -> MatrixResult:
        return MatrixResult(distances_meters=[], durations_seconds=[])

    def get_route(self, waypoints: Sequence[Coordinate]) -> RouteGeometry:
        return RouteGeometry(points=list(waypoints), total_distance_meters=0, total_duration_seconds=0)

    def get_direct_leg(self, origin: Coordinate, destination: Coordinate) -> tuple[int, int]:
        self.call_count += 1
        return (1000, 100)


# ==============================================================================
# T022: Conservative Haversine Metric Lower-Bound Pruning Tests
# ==============================================================================

def test_haversine_known_distances() -> None:
    # Identical points
    c1 = Coordinate(latitude=40.7128, longitude=-74.0060)
    assert haversine_distance_meters(c1, c1) == 0.0

    # 1 degree of latitude on meridian is approx 111.19 km
    c_eq0 = Coordinate(latitude=0.0, longitude=0.0)
    c_eq1 = Coordinate(latitude=1.0, longitude=0.0)
    d = haversine_distance_meters(c_eq0, c_eq1)
    assert 111000.0 <= d <= 111300.0

    # NYC to JFK (approx 21km)
    jfk = Coordinate(latitude=40.6413, longitude=-73.7781)
    d_jfk = haversine_distance_meters(c1, jfk)
    assert 20000.0 <= d_jfk <= 23000.0


def test_min_travel_time_and_pickup_reachability() -> None:
    v_max = 33.333  # 120 km/h in m/s
    d = 10000.0  # 10 km
    t_min = min_travel_time_seconds(d, v_max_mps=v_max)
    assert round(t_min, 1) == 300.0  # 300 seconds

    # Available time = 360s (> 300s) -> Reachable
    assert is_pickup_reachable(d_haversine=d, delta_t_available=360.0, v_max_mps=v_max) is True

    # Available time = 250s (< 300s) -> Provably unreachable, safely pruned
    assert is_pickup_reachable(d_haversine=d, delta_t_available=250.0, v_max_mps=v_max) is False


def test_pruning_without_invoking_routing_api() -> None:
    router = CountingMockRoutingProvider()
    v_max = 33.333
    delta_t_available = 100.0  # max 100 seconds available

    # Pairings:
    # Candidate 1 is 5000m away -> min travel time = 5000 / 33.33 = 150s > 100s -> PRUNED
    # Candidate 2 is 1000m away -> min travel time = 1000 / 33.33 = 30s <= 100s -> KEPT
    c_origin = Coordinate(latitude=40.7128, longitude=-74.0060)
    c_far = Coordinate(latitude=40.7580, longitude=-74.0060)  # ~5km
    c_near = Coordinate(latitude=40.7200, longitude=-74.0060)  # ~0.8km

    d_far = haversine_distance_meters(c_origin, c_far)
    d_near = haversine_distance_meters(c_origin, c_near)

    assert is_pickup_reachable(d_far, delta_t_available, v_max) is False
    assert is_pickup_reachable(d_near, delta_t_available, v_max) is True

    # Only evaluate router on candidates that survive lower-bound pruning
    for c in [c_far, c_near]:
        d = haversine_distance_meters(c_origin, c)
        if is_pickup_reachable(d, delta_t_available, v_max):
            router.get_direct_leg(c_origin, c)

    # Exactly 1 call was made to the routing provider; the far candidate was pruned without API call
    assert router.call_count == 1


def test_min_insertion_detour_bounds() -> None:
    v_max = 33.333
    # Existing leg A -> B on a straight meridian
    cA = Coordinate(latitude=40.7000, longitude=-74.0000)
    cB = Coordinate(latitude=40.8000, longitude=-74.0000)
    d_road_AB = haversine_distance_meters(cA, cB)

    # Candidate P is far to the east
    cP = Coordinate(latitude=40.7500, longitude=-73.8000)
    min_detour = min_insertion_detour_meters(origin=cA, insertion=cP, destination=cB, road_distance_orig_dest=d_road_AB)
    assert min_detour > 0.0

    # If detour slack is only 60s, but min detour takes 300s, must be pruned
    assert is_insertion_detour_feasible(min_detour_meters=min_detour, detour_slack_seconds=60.0, v_max_mps=v_max) is False


# ==============================================================================
# T023: Exhaustive Baseline Spatial Recall Tests (N=50, 100, 200)
# ==============================================================================

@pytest.mark.parametrize("n_entities", [50, 100, 200])
def test_exhaustive_candidate_recall(n_entities: int) -> None:
    """
    Evaluates candidate discovery against brute-force all-pairs search on fixtures (N=50, 100, 200).
    Asserts 100% candidate recall of all physically feasible pairings.
    """
    adapter = H3SpatialIndexAdapter(resolution=8)
    coordinator = SpatialIndexCoordinator(spatial_provider=adapter)

    # Generate synthetic entity grid in 10km x 10km area around Manhattan (lat ~40.70 to 40.80, lon ~-74.05 to -73.95)
    entities: list[tuple[str, Coordinate]] = []
    base_lat, base_lon = 40.7128, -74.0060
    step = 0.08 / math.sqrt(n_entities)

    count = 0
    cols = int(math.ceil(math.sqrt(n_entities)))
    for r in range(cols):
        for c in range(cols):
            if count >= n_entities:
                break
            lat = base_lat - 0.04 + r * step
            lon = base_lon - 0.04 + c * step
            entities.append((f"veh-{count}", Coordinate(latitude=lat, longitude=lon)))
            count += 1

    coordinator.index_entities(entities)

    # Target pickup location in the center
    target = Coordinate(latitude=base_lat, longitude=base_lon)
    max_radius_meters = 3500.0  # 3.5 km search radius

    # 1. Exhaustive brute-force all-pairs ground truth
    exhaustive_feasible = coordinator.exhaustive_search(target=target, max_radius_meters=max_radius_meters)
    exhaustive_ids = {c.entity_id for c in exhaustive_feasible}
    assert len(exhaustive_ids) > 0, "Fixture must contain feasible candidates"

    # 2. Run spatial indexing discovery
    discovered = coordinator.find_candidates_within_radius(target=target, max_radius_meters=max_radius_meters)
    discovered_ids = {c.entity_id for c in discovered}

    # 3. Assert 100% recall: every feasible entity in exhaustive ground truth MUST be discovered
    missing = exhaustive_ids - discovered_ids
    assert len(missing) == 0, f"Spatial indexing dropped feasible candidates: {missing}"
    assert exhaustive_ids.issubset(discovered_ids)


# Alias matching quickstart validation guide
test_spatial_candidate_recall = test_exhaustive_candidate_recall



# ==============================================================================
# T024: Bounding-Box Edge-Case and Fallback Tests
# ==============================================================================

def test_derived_bounding_box_formula() -> None:
    center = Coordinate(latitude=40.7128, longitude=-74.0060)
    radius_meters = 5000.0  # 5 km

    min_lat, min_lon, max_lat, max_lon = compute_derived_bounding_box(center, radius_meters)

    # Must contain center
    assert min_lat < center.latitude < max_lat
    assert min_lon < center.longitude < max_lon

    # Points strictly within radius must be inside BBox
    p_inside = Coordinate(latitude=40.7200, longitude=-74.0060)
    assert haversine_distance_meters(center, p_inside) < radius_meters
    assert is_in_bounding_box(p_inside, (min_lat, min_lon, max_lat, max_lon)) is True


def test_bounding_box_antimeridian_wrap() -> None:
    # Target near +180 longitude (e.g. 179.99 degrees)
    center = Coordinate(latitude=10.0, longitude=179.99)
    radius_meters = 20000.0  # 20 km spans across +180 / -180 line

    bbox = compute_derived_bounding_box(center, radius_meters)
    min_lat, min_lon, max_lat, max_lon = bbox

    # Point slightly across the antimeridian at -179.99
    p_across = Coordinate(latitude=10.0, longitude=-179.99)
    d = haversine_distance_meters(center, p_across)
    assert d < radius_meters

    # Point must be recognized as contained in the antimeridian-wrapped bounding box
    assert is_in_bounding_box(p_across, bbox) is True


def test_polar_latitude_boundary_fallback() -> None:
    # Near North Pole (86 degrees latitude > 85 deg threshold)
    adapter = H3SpatialIndexAdapter(resolution=8)
    coordinator = SpatialIndexCoordinator(spatial_provider=adapter)

    p_pole = Coordinate(latitude=86.0, longitude=0.0)
    p_near = Coordinate(latitude=86.01, longitude=0.0)
    coordinator.index_entities([("veh-polar", p_near)])

    # Should trigger polar fallback safely without error
    candidates = coordinator.find_candidates_within_radius(target=p_pole, max_radius_meters=5000.0)
    assert len(candidates) == 1
    assert candidates[0].entity_id == "veh-polar"


def test_provider_exception_triggers_safe_fallback() -> None:
    class FailingSpatialAdapter(H3SpatialIndexAdapter):
        def find_nearest_candidates(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("Discrete spatial index corruption simulation")

    failing_adapter = FailingSpatialAdapter()
    coordinator = SpatialIndexCoordinator(spatial_provider=failing_adapter)

    loc1 = Coordinate(latitude=40.7128, longitude=-74.0060)
    loc2 = Coordinate(latitude=40.7150, longitude=-74.0040)
    coordinator.index_entities([("veh-fallback", loc2)])

    # Exception in provider must trigger automatic exhaustive BBox fallback
    candidates = coordinator.find_candidates_within_radius(target=loc1, max_radius_meters=3000.0)
    assert len(candidates) == 1
    assert candidates[0].entity_id == "veh-fallback"


def test_antimeridian_search_at_179_degrees_spanning_boundary() -> None:
    """
    Priority 2: Target at +179.0 longitude with search radius of 150 km,
    which crosses the +/-180 antimeridian line.
    Must discover candidates both on the +179 side and the -179 side across the boundary.
    """
    adapter = H3SpatialIndexAdapter(resolution=8)
    coordinator = SpatialIndexCoordinator(spatial_provider=adapter)

    target = Coordinate(latitude=0.0, longitude=179.0)
    radius_m = 150000.0  # 150 km

    # Candidate 1: longitude 179.5 (~55.6 km away, inside)
    c1 = Coordinate(latitude=0.0, longitude=179.5)
    # Candidate 2: longitude -179.8 (~133.4 km away across the antimeridian, inside)
    c2 = Coordinate(latitude=0.0, longitude=-179.8)
    # Candidate 3: longitude -177.0 (> 400 km away across the antimeridian, outside)
    c3 = Coordinate(latitude=0.0, longitude=-177.0)

    coordinator.index_entities([
        ("veh-pos", c1),
        ("veh-across", c2),
        ("veh-far", c3),
    ])

    results = coordinator.find_candidates_within_radius(target=target, max_radius_meters=radius_m)
    found_ids = {c.entity_id for c in results}

    assert "veh-pos" in found_ids, "Candidate on positive side must be discovered"
    assert "veh-across" in found_ids, "Candidate across antimeridian must be discovered"
    assert "veh-far" not in found_ids, "Candidate outside radius must not be discovered"


def test_antimeridian_pure_python_fallback_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Priority 2: Verify antimeridian recall under pure-Python discrete grid fallback mode
    where native H3 C-extension is unavailable.
    """
    import engine.adapters.h3_spatial as h3_module
    monkeypatch.setattr(h3_module, "_H3_MODULE", None)

    adapter = H3SpatialIndexAdapter(resolution=8)
    coordinator = SpatialIndexCoordinator(spatial_provider=adapter)

    target = Coordinate(latitude=10.0, longitude=179.1)
    radius_m = 130000.0  # 130 km

    # Within 130 km across antimeridian
    c_across = Coordinate(latitude=10.0, longitude=-179.9)
    d = haversine_distance_meters(target, c_across)
    assert d < radius_m

    coordinator.index_entities([
        ("veh-grid-across", c_across),
        ("veh-local-1", Coordinate(latitude=10.05, longitude=179.15)),
        ("veh-local-2", Coordinate(latitude=10.08, longitude=179.20)),
    ])

    results = coordinator.find_candidates_within_radius(target=target, max_radius_meters=radius_m)
    found_ids = {c.entity_id for c in results}
    assert "veh-grid-across" in found_ids, "Pure-Python fallback must not drop antimeridian candidate"


def test_h3_traversal_failure_triggers_exhaustive_fallback_and_retains_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Fix 1 Regression Test: When H3 ring/disk traversal fails (e.g. pentagon/distortion error),
    H3SpatialIndexAdapter must not silently return set() and omit reachable candidates.
    It must propagate an exception so SpatialIndexCoordinator invokes exhaustive fallback.
    """
    adapter = H3SpatialIndexAdapter(resolution=8)
    coordinator = SpatialIndexCoordinator(spatial_provider=adapter)

    target = Coordinate(latitude=40.7128, longitude=-74.0060)
    radius_m = 3000.0

    # Entity 1: very close to target (~100m, ring 0)
    c_close = Coordinate(latitude=40.7135, longitude=-74.0060)
    # Entity 2: ~1,500m north (in an outer ring)
    c_outer = Coordinate(latitude=40.7263, longitude=-74.0060)

    coordinator.index_entities([
        ("veh-close", c_close),
        ("veh-outer", c_outer),
    ])

    # Simulate H3 native module failure on outer rings:
    # When grid_ring and grid_disk raise an error for k >= 1
    import engine.adapters.h3_spatial as h3_module

    class FailingH3Mock:
        def latlng_to_cell(self, lat: float, lng: float, res: int) -> str:
            return "882a100d2bffff"

        def grid_ring(self, cell: str, k: int) -> list[str]:
            if k == 0:
                return [cell]
            raise RuntimeError(f"H3 pentagon error at k={k}")

        def grid_disk(self, cell: str, k: int) -> list[str]:
            if k == 0:
                return [cell]
            raise RuntimeError(f"H3 grid disk failed at k={k}")

    monkeypatch.setattr(h3_module, "_H3_MODULE", FailingH3Mock())

    # 1. Calling adapter directly MUST propagate the traversal error (not silently return partial candidates)
    with pytest.raises(RuntimeError, match="H3 grid disk failed"):
        adapter.find_nearest_candidates(target=target, max_radius_meters=radius_m, min_candidates=1)

    # 2. Calling through coordinator MUST catch the error and invoke exhaustive fallback,
    # finding BOTH close and outer candidates without silent omission
    candidates = coordinator.find_candidates_within_radius(
        target=target,
        max_radius_meters=radius_m,
        min_candidates=1,
    )
    found_ids = {c.entity_id for c in candidates}
    assert "veh-close" in found_ids
    assert "veh-outer" in found_ids, "Outer candidate must not be silently omitted when H3 ring fails"


def test_entity_filter_skips_ineligible_entities_during_ring_expansion() -> None:
    """
    Unit test for entity_filter support in SpatialIndexProvider and Coordinator.
    Verifies that entities failing entity_filter are excluded from candidate counts,
    allowing ring expansion to continue until the requested number of eligible entities is discovered.
    """
    adapter = H3SpatialIndexAdapter(resolution=8)
    coordinator = SpatialIndexCoordinator(spatial_provider=adapter)

    target = Coordinate(latitude=40.7100, longitude=-74.0000)

    # 4 close entities (100m - 400m away) that will be rejected by filter
    ineligible = [
        (f"ent-ineligible-{i}", Coordinate(latitude=40.7100 + i * 0.001, longitude=-74.0000))
        for i in range(1, 5)
    ]
    # 2 further entities (1,000m - 1,200m away) that will be accepted by filter
    eligible = [
        ("ent-eligible-1", Coordinate(latitude=40.7100 + 0.009, longitude=-74.0000)),
        ("ent-eligible-2", Coordinate(latitude=40.7100 + 0.011, longitude=-74.0000)),
    ]

    coordinator.index_entities(ineligible + eligible)

    # Filter accepting only entities starting with 'ent-eligible'
    is_eligible = lambda eid: eid.startswith("ent-eligible")

    # Adapter level
    cands_adapter = adapter.find_nearest_candidates(
        target=target,
        max_radius_meters=5000.0,
        min_candidates=1,
        max_candidates=2,
        entity_filter=is_eligible,
    )
    found_adapter_ids = [c.entity_id for c in cands_adapter]
    assert found_adapter_ids == ["ent-eligible-1", "ent-eligible-2"]

    # Coordinator level
    cands_coord = coordinator.find_candidates_within_radius(
        target=target,
        max_radius_meters=5000.0,
        min_candidates=1,
        max_candidates=2,
        entity_filter=is_eligible,
    )
    found_coord_ids = [c.entity_id for c in cands_coord]
    assert found_coord_ids == ["ent-eligible-1", "ent-eligible-2"]

