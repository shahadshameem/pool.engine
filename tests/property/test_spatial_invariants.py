"""Property-based invariant tests for spatial lower bounds and bounding box recall (T025)."""

import math
from hypothesis import given, strategies as st

from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.routing import Coordinate
from engine.spatial.lower_bounds import (
    compute_derived_bounding_box,
    haversine_distance_meters,
    is_in_bounding_box,
)


@st.composite
def random_wgs84_coordinate(draw: st.DrawFn) -> Coordinate:
    lat = draw(st.floats(min_value=-85.0, max_value=85.0))
    lon = draw(st.floats(min_value=-180.0, max_value=180.0))
    return Coordinate(latitude=lat, longitude=lon)


@given(c1=random_wgs84_coordinate(), c2=random_wgs84_coordinate())
def test_property_haversine_bounds_road_distance_from_below(c1: Coordinate, c2: Coordinate) -> None:
    """
    Asserts that great-circle Haversine distance is strictly <= road network distance
    under any physical road circuity (circuity_factor >= 1.0).
    """
    router = MockRoutingProvider(circuity_factor=1.2)
    d_haversine = haversine_distance_meters(c1, c2)
    d_road, _ = router.get_direct_leg(c1, c2)

    # Great-circle is the geodesic: d_haversine <= d_road
    assert d_haversine <= float(d_road) + 1e-4


@given(
    center=random_wgs84_coordinate(),
    radius_meters=st.floats(min_value=100.0, max_value=50000.0),
    bearing_rad=st.floats(min_value=0.0, max_value=2 * math.pi),
    fraction=st.floats(min_value=0.0, max_value=0.999),
)
def test_property_derived_bbox_guarantees_100_percent_containment(
    center: Coordinate,
    radius_meters: float,
    bearing_rad: float,
    fraction: float,
) -> None:
    """
    Mathematically verifies that every point within Haversine distance R is provably
    contained inside the derived bounding box BBox(center, R).
    """
    # Generate point at distance = fraction * radius_meters in direction bearing_rad
    dist = fraction * radius_meters
    R_earth = 6371000.0
    angular_dist = dist / R_earth

    lat1 = math.radians(center.latitude)
    lon1 = math.radians(center.longitude)

    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular_dist)
        + math.cos(lat1) * math.sin(angular_dist) * math.cos(bearing_rad)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing_rad) * math.sin(angular_dist) * math.cos(lat1),
        math.cos(angular_dist) - math.sin(lat1) * math.sin(lat2),
    )
    # Normalize lon2 to [-pi, pi]
    lon2 = (lon2 + math.pi) % (2 * math.pi) - math.pi

    target_pt = Coordinate(latitude=math.degrees(lat2), longitude=math.degrees(lon2))

    # Verify actual Haversine distance <= radius_meters
    actual_d = haversine_distance_meters(center, target_pt)
    assert actual_d <= radius_meters + 1e-3

    # Verify point is 100% inside derived BBox
    bbox = compute_derived_bounding_box(center, radius_meters)
    assert is_in_bounding_box(target_pt, bbox) is True
