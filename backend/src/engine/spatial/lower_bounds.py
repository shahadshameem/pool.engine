"""Conservative metric lower-bound math and derived bounding box geometry."""

import math
from engine.contracts.routing import Coordinate

DEFAULT_EARTH_RADIUS_METERS = 6371000.0
DEFAULT_V_MAX_MPS = 33.333  # 120 km/h in meters per second


def haversine_distance_meters(
    c1: Coordinate,
    c2: Coordinate,
    earth_radius_meters: float = DEFAULT_EARTH_RADIUS_METERS,
) -> float:
    """Computes great-circle distance in meters between two WGS84 coordinates."""
    lat1, lon1 = math.radians(c1.latitude), math.radians(c1.longitude)
    lat2, lon2 = math.radians(c2.latitude), math.radians(c2.longitude)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return earth_radius_meters * c


def min_travel_time_seconds(
    d_haversine: float,
    v_max_mps: float = DEFAULT_V_MAX_MPS,
) -> float:
    """
    Computes absolute physical minimum road travel time across any road network.
    TravelTime >= d_haversine / v_max.
    """
    return d_haversine / v_max_mps


def is_pickup_reachable(
    d_haversine: float,
    delta_t_available: float,
    v_max_mps: float = DEFAULT_V_MAX_MPS,
) -> bool:
    """
    Pruning Rule 1: A candidate is pruned if d_haversine / v_max > delta_t_available.
    Returns True if reachable (or within tolerance), False if provably unreachable.
    """
    if delta_t_available <= 0.0:
        return d_haversine <= 0.0
    t_min = min_travel_time_seconds(d_haversine, v_max_mps)
    return t_min <= (delta_t_available + 1e-6)


def min_insertion_detour_meters(
    origin: Coordinate,
    insertion: Coordinate,
    destination: Coordinate,
    road_distance_orig_dest: float,
) -> float:
    """
    Pruning Rule 2: Minimum road distance added by inserting a stop between origin and destination.
    Delta_d_min = max(0, d_haversine(origin, insertion) + d_haversine(insertion, dest) - d_road(orig, dest)).
    """
    d_in = haversine_distance_meters(origin, insertion)
    d_out = haversine_distance_meters(insertion, destination)
    return max(0.0, (d_in + d_out) - road_distance_orig_dest)


def is_insertion_detour_feasible(
    min_detour_meters: float,
    detour_slack_seconds: float,
    v_max_mps: float = DEFAULT_V_MAX_MPS,
) -> bool:
    """
    Returns False if minimum insertion detour travel time exceeds available detour slack.
    """
    if detour_slack_seconds < 0.0:
        return False
    min_time_added = min_travel_time_seconds(min_detour_meters, v_max_mps)
    return min_time_added <= (detour_slack_seconds + 1e-6)


def compute_derived_bounding_box(
    center: Coordinate,
    radius_meters: float,
    earth_radius_meters: float = DEFAULT_EARTH_RADIUS_METERS,
) -> tuple[float, float, float, float]:
    """
    Computes derived bounding box [min_lat, min_lon, max_lat, max_lon] in degrees.
    Guarantees 100% complete coverage of all points within radius_meters.
    Delta_phi = Delta_sigma, Delta_lambda = Delta_sigma / cos(phi_max_abs).
    """
    phi0 = math.radians(center.latitude)
    lambda0 = math.radians(center.longitude)
    delta_sigma = radius_meters / earth_radius_meters

    # Polar boundary condition: near North/South pole
    if abs(phi0) + delta_sigma >= (math.pi / 2.0 - 1e-6):
        min_lat = max(-90.0, math.degrees(phi0 - delta_sigma))
        max_lat = min(90.0, math.degrees(phi0 + delta_sigma))
        return (min_lat, -180.0, max_lat, 180.0)

    phi_max_abs = min(
        math.pi / 2.0 - 1e-6,
        max(abs(phi0 - delta_sigma), abs(phi0 + delta_sigma)),
    )
    delta_phi = delta_sigma
    cos_phi = math.cos(phi_max_abs)
    delta_lambda = delta_sigma / cos_phi if cos_phi > 0.0 else math.pi

    min_lat = max(-90.0, math.degrees(phi0 - delta_phi))
    max_lat = min(90.0, math.degrees(phi0 + delta_phi))
    min_lon = math.degrees(lambda0 - delta_lambda)
    max_lon = math.degrees(lambda0 + delta_lambda)

    return (min_lat, min_lon, max_lat, max_lon)


def is_in_bounding_box(
    point: Coordinate,
    bbox: tuple[float, float, float, float],
) -> bool:
    """
    Verifies whether point (latitude, longitude) lies within bounding box,
    supporting antimeridian crossing and spherical longitude wrap-around.
    """
    min_lat, min_lon, max_lat, max_lon = bbox
    # Allow 1e-9 float margin
    if not ((min_lat - 1e-9) <= point.latitude <= (max_lat + 1e-9)):
        return False

    lon = point.longitude
    # If longitude range spans full circle (>= 360 degrees)
    if (max_lon - min_lon) >= 360.0:
        return True

    # Antimeridian wrap: min_lon < -180
    if min_lon < -180.0:
        wrapped_min = min_lon + 360.0
        return ((-180.0 - 1e-9) <= lon <= (max_lon + 1e-9)) or ((wrapped_min - 1e-9) <= lon <= (180.0 + 1e-9))

    # Antimeridian wrap: max_lon > 180
    if max_lon > 180.0:
        wrapped_max = max_lon - 360.0
        return ((min_lon - 1e-9) <= lon <= (180.0 + 1e-9)) or ((-180.0 - 1e-9) <= lon <= (wrapped_max + 1e-9))

    return ((min_lon - 1e-9) <= lon <= (max_lon + 1e-9))
