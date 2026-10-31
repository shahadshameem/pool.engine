"""Unit tests for regional routing correctness, coordinate invariants, and boundary validation (Phase 3)."""

import math
from typing import Any
import pytest

from engine.contracts.routing import (
    BoundingBox,
    Coordinate,
    InvalidCoordinateError,
    InvalidRouteDataError,
    MatrixResult,
    OutOfRegionError,
    RoadNetworkRoutingProvider,
    RouteGeometry,
    RouteLookupError,
    RouteTimeoutError,
    RoutingProviderError,
    validate_route_leg,
)
from engine.adapters.osrm_routing import (
    DefaultOsrmTransport,
    OsrmHttpTransport,
    OsrmRoutingAdapter,
)
from engine.service.config import ServiceConfig
from engine.service.service import build_service_from_env


class FakeOsrmTransport(OsrmHttpTransport):
    """Controllable fake HTTP transport for unit testing."""

    def __init__(self) -> None:
        self.responses: dict[str, tuple[int, bytes]] = {}
        self.call_history: list[str] = []

    def set_response(self, path_and_query: str, status_code: int, data: str | bytes) -> None:
        body = data.encode("utf-8") if isinstance(data, str) else data
        self.responses[path_and_query] = (status_code, body)

    def get(self, path_and_query: str, timeout: float) -> tuple[int, bytes]:
        self.call_history.append(path_and_query)
        if path_and_query in self.responses:
            return self.responses[path_and_query]
        for pattern, resp in self.responses.items():
            if pattern in path_and_query:
                return resp
        return 404, b'{"code":"InvalidQuery","message":"Not found in fake"}'


# ===========================================================================
# 1. Coordinate Invariants & Validation
# ===========================================================================

def test_coordinate_valid_extremes() -> None:
    c_eq = Coordinate(latitude=0.0, longitude=0.0)
    assert c_eq.latitude == 0.0
    assert c_eq.longitude == 0.0

    c_north_pole = Coordinate(latitude=90.0, longitude=0.0)
    assert c_north_pole.latitude == 90.0

    c_south_pole = Coordinate(latitude=-90.0, longitude=0.0)
    assert c_south_pole.latitude == -90.0

    c_date_line_east = Coordinate(latitude=0.0, longitude=180.0)
    assert c_date_line_east.longitude == 180.0

    c_date_line_west = Coordinate(latitude=0.0, longitude=-180.0)
    assert c_date_line_west.longitude == -180.0


def test_coordinate_precision_rounding() -> None:
    c = Coordinate(latitude=40.7588961234, longitude=-73.9851308765)
    assert c.latitude == 40.758896
    assert c.longitude == -73.985131


@pytest.mark.parametrize("invalid_lat", [90.000001, -90.000001, 100.0, -120.0])
def test_coordinate_invalid_latitude_raises(invalid_lat: float) -> None:
    with pytest.raises(InvalidCoordinateError, match=r"Latitude must be between -90\.0 and 90\.0"):
        Coordinate(latitude=invalid_lat, longitude=0.0)


@pytest.mark.parametrize("invalid_lon", [180.000001, -180.000001, 200.0, -360.0])
def test_coordinate_invalid_longitude_raises(invalid_lon: float) -> None:
    with pytest.raises(InvalidCoordinateError, match=r"Longitude must be between -180\.0 and 180\.0"):
        Coordinate(latitude=0.0, longitude=invalid_lon)


@pytest.mark.parametrize("nan_val", [float("nan"), float("inf"), float("-inf")])
def test_coordinate_nan_inf_rejected(nan_val: float) -> None:
    with pytest.raises(InvalidCoordinateError, match=r"finite number"):
        Coordinate(latitude=nan_val, longitude=0.0)

    with pytest.raises(InvalidCoordinateError, match=r"finite number"):
        Coordinate(latitude=0.0, longitude=nan_val)


def test_coordinate_boolean_rejected() -> None:
    with pytest.raises(InvalidCoordinateError, match=r"boolean"):
        Coordinate(latitude=True, longitude=0.0)  # type: ignore[arg-type]

    with pytest.raises(InvalidCoordinateError, match=r"boolean"):
        Coordinate(latitude=0.0, longitude=False)  # type: ignore[arg-type]


# ===========================================================================
# 2. BoundingBox Contract & Regional Checks
# ===========================================================================

def test_bounding_box_valid_construction() -> None:
    bbox = BoundingBox(min_lat=40.70, min_lon=-74.05, max_lat=40.85, max_lon=-73.90)
    assert bbox.min_lat == 40.70
    assert bbox.min_lon == -74.05
    assert bbox.max_lat == 40.85
    assert bbox.max_lon == -73.90

    # Inside
    assert bbox.contains(Coordinate(latitude=40.75, longitude=-73.98)) is True
    # On boundary
    assert bbox.contains(Coordinate(latitude=40.70, longitude=-74.00)) is True
    assert bbox.contains(Coordinate(latitude=40.85, longitude=-73.90)) is True
    # Outside north
    assert bbox.contains(Coordinate(latitude=40.86, longitude=-73.98)) is False
    # Outside south
    assert bbox.contains(Coordinate(latitude=40.69, longitude=-73.98)) is False
    # Outside east
    assert bbox.contains(Coordinate(latitude=40.75, longitude=-73.89)) is False
    # Outside west
    assert bbox.contains(Coordinate(latitude=40.75, longitude=-74.06)) is False


def test_bounding_box_invalid_invariants() -> None:
    with pytest.raises(InvalidCoordinateError, match=r"min_lat.*cannot exceed.*max_lat"):
        BoundingBox(min_lat=41.0, min_lon=-74.0, max_lat=40.0, max_lon=-73.0)

    with pytest.raises(InvalidCoordinateError, match=r"min_lon.*cannot exceed.*max_lon"):
        BoundingBox(min_lat=40.0, min_lon=-73.0, max_lat=41.0, max_lon=-74.0)

    with pytest.raises(InvalidCoordinateError, match=r"finite number"):
        BoundingBox(min_lat=float("nan"), min_lon=-74.0, max_lat=41.0, max_lon=-73.0)


def test_bounding_box_validate_method() -> None:
    bbox = BoundingBox(min_lat=40.70, min_lon=-74.05, max_lat=40.85, max_lon=-73.90)
    c_inside = Coordinate(latitude=40.75, longitude=-73.98)
    bbox.validate(c_inside, label="Pickup")  # Should not raise

    c_outside = Coordinate(latitude=8.5469, longitude=76.9054)  # Kerala
    with pytest.raises(OutOfRegionError, match=r"Pickup \(8\.5469, 76\.9054\) falls outside regional bounding box"):
        bbox.validate(c_outside, label="Pickup")


def test_bounding_box_from_env() -> None:
    env = {
        "ROUTING_REGION_MIN_LAT": "40.70",
        "ROUTING_REGION_MIN_LON": "-74.05",
        "ROUTING_REGION_MAX_LAT": "40.85",
        "ROUTING_REGION_MAX_LON": "-73.90",
    }
    bbox = BoundingBox.from_env(env)
    assert bbox is not None
    assert bbox.min_lat == 40.70
    assert bbox.max_lon == -73.90

    # None if unset
    assert BoundingBox.from_env({}) is None

    # Error if partially configured
    with pytest.raises(ValueError, match=r"Incomplete regional bounding box configuration"):
        BoundingBox.from_env({"ROUTING_REGION_MIN_LAT": "40.70"})


# ===========================================================================
# 3. OsrmRoutingAdapter Regional & Snapping Rejection
# ===========================================================================

def test_osrm_rejects_out_of_bounding_box_without_network_call() -> None:
    transport = FakeOsrmTransport()
    bbox = BoundingBox(min_lat=40.70, min_lon=-74.05, max_lat=40.85, max_lon=-73.90)
    adapter = OsrmRoutingAdapter(transport=transport, bounding_box=bbox)

    c_kerala_origin = Coordinate(latitude=8.5469, longitude=76.9054)
    c_kerala_dest = Coordinate(latitude=8.4875, longitude=76.9528)

    with pytest.raises(OutOfRegionError, match=r"Origin.*outside regional bounding box"):
        adapter.get_direct_leg(c_kerala_origin, c_kerala_dest)

    # Crucial assertion: adapter must fail-fast without sending any request to transport
    assert len(transport.call_history) == 0


def test_osrm_rejects_snapping_distance_exceeding_threshold() -> None:
    transport = FakeOsrmTransport()
    # Snapping threshold 5000m (5km)
    adapter = OsrmRoutingAdapter(transport=transport, max_snap_distance_meters=5000.0)

    # Origin and destination inside coordinate range, but OSRM snaps 15,678km away
    c1 = Coordinate(latitude=8.5469, longitude=76.9054)
    c2 = Coordinate(latitude=8.4875, longitude=76.9528)

    # Simulate OSRM 200 OK response with massive snap distance
    osrm_response = {
        "code": "Ok",
        "sources": [
            {
                "name": "Catalpa Avenue",
                "location": [-73.891301, 40.705059],
                "distance": 15678813.9,
                "hint": "AAA",
            }
        ],
        "destinations": [
            {
                "name": "Catalpa Avenue",
                "location": [-73.891301, 40.705059],
                "distance": 15690888.8,
                "hint": "AAA",
            }
        ],
        "distances": [[0.0]],
        "durations": [[0.0]],
    }
    transport.set_response("/table/v1/", 200, json_dump(osrm_response))

    with pytest.raises(OutOfRegionError, match=r"snapped 15678813\.9m away.*exceeding maximum allowed snapping distance"):
        adapter.get_direct_leg(c1, c2)


def test_osrm_accepts_valid_snapping_within_threshold() -> None:
    transport = FakeOsrmTransport()
    adapter = OsrmRoutingAdapter(transport=transport, max_snap_distance_meters=5000.0)

    c1 = Coordinate(latitude=40.7580, longitude=-73.9855)
    c2 = Coordinate(latitude=40.7070, longitude=-74.0090)

    # Snapping 2.0 meters away (valid road match)
    osrm_response = {
        "code": "Ok",
        "sources": [{"location": [-73.9855, 40.7580], "distance": 1.2, "name": "7th Ave"}],
        "destinations": [{"location": [-74.0090, 40.7070], "distance": 2.5, "name": "Wall St"}],
        "distances": [[9400.0]],
        "durations": [[900.0]],
    }
    transport.set_response("/table/v1/", 200, json_dump(osrm_response))

    dist, dur = adapter.get_direct_leg(c1, c2)
    assert dist == 9400
    assert dur == 900


def test_osrm_distance_matrix_rejects_out_of_region() -> None:
    transport = FakeOsrmTransport()
    bbox = BoundingBox(min_lat=40.70, min_lon=-74.05, max_lat=40.85, max_lon=-73.90)
    adapter = OsrmRoutingAdapter(transport=transport, bounding_box=bbox)

    c_valid = Coordinate(latitude=40.75, longitude=-73.98)
    c_kerala = Coordinate(latitude=8.5469, longitude=76.9054)

    with pytest.raises(OutOfRegionError, match=r"outside regional bounding box"):
        adapter.get_distance_matrix([c_valid], [c_kerala])

    assert len(transport.call_history) == 0


def test_osrm_distance_matrix_rejects_extreme_snapping() -> None:
    transport = FakeOsrmTransport()
    adapter = OsrmRoutingAdapter(transport=transport, max_snap_distance_meters=5000.0)

    c1 = Coordinate(latitude=40.7580, longitude=-73.9855)
    c2 = Coordinate(latitude=42.6526, longitude=-73.7562)  # Albany

    # Albany snaps 206km away
    osrm_response = {
        "code": "Ok",
        "sources": [{"location": [-73.9855, 40.7580], "distance": 1.5, "name": "7th Ave"}],
        "destinations": [{"location": [-73.9615, 40.7987], "distance": 206621.1, "name": "Manhattan Ave"}],
        "distances": [[6100.0]],
        "durations": [[650.0]],
    }
    transport.set_response("/table/v1/", 200, json_dump(osrm_response))

    with pytest.raises(OutOfRegionError, match=r"snapped 206621\.1m away"):
        adapter.get_distance_matrix([c1], [c2])


def test_osrm_get_route_rejects_snapping_violation() -> None:
    transport = FakeOsrmTransport()
    adapter = OsrmRoutingAdapter(transport=transport, max_snap_distance_meters=5000.0)

    c1 = Coordinate(latitude=40.7580, longitude=-73.9855)
    c2 = Coordinate(latitude=8.4875, longitude=76.9528)

    route_response = {
        "code": "Ok",
        "waypoints": [
            {"location": [-73.9855, 40.7580], "distance": 1.0, "name": "7th Ave"},
            {"location": [-73.8913, 40.7051], "distance": 15690888.0, "name": "Catalpa Ave"},
        ],
        "routes": [
            {
                "distance": 12000.0,
                "duration": 1100.0,
                "geometry": {
                    "coordinates": [[-73.9855, 40.7580], [-73.8913, 40.7051]]
                },
            }
        ],
    }
    transport.set_response("/route/v1/", 200, json_dump(route_response))

    with pytest.raises(OutOfRegionError, match=r"Waypoint.*snapped 15690888\.0m away"):
        adapter.get_route([c1, c2])


def test_osrm_prefetch_matrix_skips_out_of_region_safely() -> None:
    transport = FakeOsrmTransport()
    bbox = BoundingBox(min_lat=40.70, min_lon=-74.05, max_lat=40.85, max_lon=-73.90)
    adapter = OsrmRoutingAdapter(transport=transport, bounding_box=bbox)

    c_valid1 = Coordinate(latitude=40.75, longitude=-73.98)
    c_valid2 = Coordinate(latitude=40.74, longitude=-73.99)
    c_kerala = Coordinate(latitude=8.5469, longitude=76.9054)

    # Prefetch matrix must never raise an unhandled exception for out-of-region coordinates
    cached = adapter.prefetch_matrix(origins=[c_valid1, c_kerala], destinations=[c_valid2])
    # Kerala coord should be excluded from caching
    assert isinstance(cached, int)


# ===========================================================================
# 4. Service Config & Environment Construction
# ===========================================================================

def test_service_config_regional_bounding_box() -> None:
    env = {
        "ROUTING_REGION_MIN_LAT": "40.70",
        "ROUTING_REGION_MIN_LON": "-74.05",
        "ROUTING_REGION_MAX_LAT": "40.85",
        "ROUTING_REGION_MAX_LON": "-73.90",
        "ROUTING_MAX_SNAP_DISTANCE_METERS": "3000",
    }
    config = ServiceConfig.from_env(env)
    assert config.routing_region_min_lat == 40.70
    assert config.routing_region_min_lon == -74.05
    assert config.routing_region_max_lat == 40.85
    assert config.routing_region_max_lon == -73.90
    assert config.routing_max_snap_distance_meters == 3000.0


def test_build_service_strict_real_routing_prohibits_silent_mock_fallback() -> None:
    # REQUIRE_REAL_ROUTING=true without OSRM_BASE_URL must fail fast
    env = {"REQUIRE_REAL_ROUTING": "true"}
    with pytest.raises(ValueError, match=r"Real road network routing is required.*OSRM_BASE_URL is not set"):
        build_service_from_env(env)


def test_build_service_strict_real_routing_fails_if_osrm_unhealthy() -> None:
    # Point to an unresolvable port
    env = {
        "REQUIRE_REAL_ROUTING": "true",
        "OSRM_BASE_URL": "http://127.0.0.1:59999",  # unreachable port
        "ROUTING_TIMEOUT_SECONDS": "0.1",
    }
    with pytest.raises(RoutingProviderError, match=r"OSRM service.*unreachable or unhealthy"):
        build_service_from_env(env)


# ===========================================================================
# 5. Phase 4 Audit: Malformed Waypoints, Direct Config, and API Guardrails
# ===========================================================================

@pytest.mark.parametrize(
    "bad_snap_dist",
    [True, False, float("nan"), float("inf"), float("-inf"), -1.0, -100.0, "non-numeric"],
)
def test_osrm_rejects_malformed_waypoint_distance(bad_snap_dist: Any) -> None:
    transport = FakeOsrmTransport()
    adapter = OsrmRoutingAdapter(transport=transport)
    c1 = Coordinate(latitude=40.7580, longitude=-73.9855)
    c2 = Coordinate(latitude=40.7070, longitude=-74.0090)

    osrm_response = {
        "code": "Ok",
        "sources": [{"location": [-73.9855, 40.7580], "distance": bad_snap_dist, "name": "7th Ave"}],
        "destinations": [{"location": [-74.0090, 40.7070], "distance": 1.0, "name": "Wall St"}],
        "distances": [[1000.0]],
        "durations": [[100.0]],
    }
    transport.set_response("/table/v1/", 200, json_dump(osrm_response))

    with pytest.raises(InvalidRouteDataError):
        adapter.get_direct_leg(c1, c2)


def test_osrm_rejects_malformed_waypoint_location() -> None:
    transport = FakeOsrmTransport()
    bbox = BoundingBox(min_lat=40.70, min_lon=-74.05, max_lat=40.85, max_lon=-73.90)
    adapter = OsrmRoutingAdapter(transport=transport, bounding_box=bbox)
    c1 = Coordinate(latitude=40.7580, longitude=-73.9855)
    c2 = Coordinate(latitude=40.7070, longitude=-74.0090)

    # Waypoint with malformed location (lat > 90)
    osrm_response = {
        "code": "Ok",
        "sources": [{"location": [-73.9855, 120.0], "distance": 5.0, "name": "Bad Lat"}],
        "destinations": [{"location": [-74.0090, 40.7070], "distance": 1.0, "name": "Wall St"}],
        "distances": [[1000.0]],
        "durations": [[100.0]],
    }
    transport.set_response("/table/v1/", 200, json_dump(osrm_response))

    with pytest.raises(InvalidRouteDataError):
        adapter.get_direct_leg(c1, c2)


def test_service_config_direct_instantiation_validates_bounding_box() -> None:
    # Partial bounding box must raise ValueError
    with pytest.raises(ValueError, match=r"Incomplete regional bounding box"):
        ServiceConfig(routing_region_min_lat=40.0, routing_region_max_lat=41.0)

    # Inverted bounding box must raise ValueError
    with pytest.raises(ValueError, match=r"min_lat.*cannot exceed.*max_lat"):
        ServiceConfig(
            routing_region_min_lat=41.0,
            routing_region_min_lon=-74.0,
            routing_region_max_lat=40.0,
            routing_region_max_lon=-73.0,
        )


def test_create_request_validates_coordinates_when_distance_duration_provided() -> None:
    """Confirms that client-provided direct distance/duration cannot bypass regional validation."""
    from engine.adapters.in_memory_storage import InMemoryRideStorage
    from engine.adapters.mock_routing import MockRoutingProvider
    from engine.adapters.h3_spatial import H3SpatialIndexAdapter
    from engine.adapters.default_policy import DefaultPolicyProvider
    from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator
    from engine.service.errors import OutOfRegionServiceError
    from engine.service.schemas import CreateRideRequestInput
    from engine.service.service import PoolEngineService
    from engine.domain.models import GeoCoordinate

    bbox = BoundingBox(min_lat=40.70, min_lon=-74.05, max_lat=40.85, max_lon=-73.90)
    router = MockRoutingProvider(bounding_box=bbox)
    storage = InMemoryRideStorage()
    service = PoolEngineService(
        storage=storage,
        orchestrator=DispatchOrchestrator(
            storage=storage,
            policy_provider=DefaultPolicyProvider(),
            routing_provider=router,
            spatial_index=H3SpatialIndexAdapter(),
        ),
        router=router,
    )

    # Pre-supplying direct distance/duration for a Kerala coordinate
    input_data = CreateRideRequestInput(
        request_id="req-bypass-test",
        user_id="user-1",
        pickup_location=GeoCoordinate(latitude=8.5469, longitude=76.9054),
        dropoff_location=GeoCoordinate(latitude=8.4875, longitude=76.9528),
        seat_count=1,
        earliest_pickup_time=1000,
        latest_dropoff_time=2000,
        direct_distance_meters=2000,
        direct_duration_seconds=300,
    )

    with pytest.raises(OutOfRegionServiceError, match=r"operational service region"):
        service.create_request(input_data)


def test_register_vehicle_and_update_location_validates_regional_boundaries() -> None:
    from engine.adapters.in_memory_storage import InMemoryRideStorage
    from engine.adapters.mock_routing import MockRoutingProvider
    from engine.adapters.h3_spatial import H3SpatialIndexAdapter
    from engine.adapters.default_policy import DefaultPolicyProvider
    from engine.orchestration.dispatch_orchestrator import DispatchOrchestrator
    from engine.service.errors import OutOfRegionServiceError
    from engine.service.schemas import RegisterVehicleInput
    from engine.service.service import PoolEngineService
    from engine.domain.models import GeoCoordinate

    bbox = BoundingBox(min_lat=40.70, min_lon=-74.05, max_lat=40.85, max_lon=-73.90)
    router = MockRoutingProvider(bounding_box=bbox)
    storage = InMemoryRideStorage()
    service = PoolEngineService(
        storage=storage,
        orchestrator=DispatchOrchestrator(
            storage=storage,
            policy_provider=DefaultPolicyProvider(),
            routing_provider=router,
            spatial_index=H3SpatialIndexAdapter(),
        ),
        router=router,
    )

    # Out-of-region vehicle registration
    with pytest.raises(OutOfRegionServiceError, match=r"operational service region"):
        service.register_vehicle(
            RegisterVehicleInput(
                vehicle_id="veh-kerala-1",
                driver_id="driver-1",
                total_seat_capacity=4,
                current_location=GeoCoordinate(latitude=8.5469, longitude=76.9054),
            )
        )

    # Register in-region vehicle
    veh = service.register_vehicle(
        RegisterVehicleInput(
            vehicle_id="veh-manhattan-1",
            driver_id="driver-1",
            total_seat_capacity=4,
            current_location=GeoCoordinate(latitude=40.7580, longitude=-73.9855),
        )
    )
    assert veh.vehicle_id == "veh-manhattan-1"

    # Out-of-region location update
    with pytest.raises(OutOfRegionServiceError, match=r"operational service region"):
        service.update_vehicle_location(
            vehicle_id="veh-manhattan-1",
            location=GeoCoordinate(latitude=8.5469, longitude=76.9054),
        )


def json_dump(obj: Any) -> str:
    import json
    return json.dumps(obj)
