"""Unit tests for multi-region routing contracts, configuration, and routing router (Phase 5)."""

import pytest

from engine.adapters.mock_routing import MockRoutingProvider
from engine.contracts.routing import (
    BoundingBox,
    Coordinate,
    InvalidCoordinateError,
    OutOfRegionError,
    RoadNetworkRoutingProvider,
    RouteLookupError,
    RouteTimeoutError,
    RoutingProviderError,
)

# Test regions
NYC_BBOX = BoundingBox(
    min_lat=40.6900,
    min_lon=-74.0500,
    max_lat=40.8800,
    max_lon=-73.9000,
)
KERALA_BBOX = BoundingBox(
    min_lat=8.1800,
    min_lon=76.8000,
    max_lat=12.8000,
    max_lon=77.5000,
)

NYC_TIMES_SQUARE = Coordinate(latitude=40.7580, longitude=-73.9855)
NYC_WALL_STREET = Coordinate(latitude=40.7070, longitude=-74.0090)
KERALA_TVM_ORIGIN = Coordinate(latitude=8.5469, longitude=76.9054)
KERALA_TVM_DEST = Coordinate(latitude=8.4875, longitude=76.9528)
LONDON_COORD = Coordinate(latitude=51.5074, longitude=-0.1278)


# ===========================================================================
# 1. BoundingBox Overlap & Disjoint Validation
# ===========================================================================

def test_bounding_box_overlaps_disjoint() -> None:
    """Disjoint bounding boxes do not overlap."""
    assert not NYC_BBOX.overlaps(KERALA_BBOX)
    assert not KERALA_BBOX.overlaps(NYC_BBOX)


def test_bounding_box_overlaps_overlapping() -> None:
    """Overlapping bounding boxes return True."""
    box1 = BoundingBox(min_lat=40.0, min_lon=-74.0, max_lat=41.0, max_lon=-73.0)
    box2 = BoundingBox(min_lat=40.5, min_lon=-73.5, max_lat=41.5, max_lon=-72.5)
    assert box1.overlaps(box2)
    assert box2.overlaps(box1)


def test_bounding_box_overlaps_contained() -> None:
    """Fully contained bounding box returns True."""
    box_outer = BoundingBox(min_lat=40.0, min_lon=-75.0, max_lat=42.0, max_lon=-72.0)
    box_inner = BoundingBox(min_lat=40.5, min_lon=-74.0, max_lat=41.5, max_lon=-73.0)
    assert box_outer.overlaps(box_inner)
    assert box_inner.overlaps(box_outer)


# ===========================================================================
# 2. RegionConfig Contract & Validation
# ===========================================================================

def test_region_config_valid() -> None:
    """Valid RegionConfig initializes successfully."""
    from engine.contracts.routing import RegionConfig

    cfg = RegionConfig(
        region_id="us-nyc-manhattan",
        bounding_box=NYC_BBOX,
        provider_type="mock",
        dataset_id="nyc-2026",
    )
    assert cfg.region_id == "us-nyc-manhattan"
    assert cfg.dataset_id == "nyc-2026"
    assert cfg.profile == "driving"


def test_region_config_rejects_invalid_region_id() -> None:
    """RegionConfig rejects invalid or empty region identifiers."""
    from engine.contracts.routing import RegionConfig

    with pytest.raises(ValueError, match="region_id"):
        RegionConfig(
            region_id="",
            bounding_box=NYC_BBOX,
        )

    with pytest.raises(ValueError, match="region_id"):
        RegionConfig(
            region_id="invalid id with spaces!",
            bounding_box=NYC_BBOX,
        )


def test_region_config_rejects_probe_coordinate_outside_bounds() -> None:
    """RegionConfig rejects probe coordinates that fall outside the region bounding box."""
    from engine.contracts.routing import RegionConfig

    with pytest.raises(ValueError, match="probe_coordinate"):
        RegionConfig(
            region_id="us-nyc-manhattan",
            bounding_box=NYC_BBOX,
            probe_coordinate=KERALA_TVM_ORIGIN,
        )


# ===========================================================================
# 3. RegionalRoutingRouter Multi-Region Architecture
# ===========================================================================

def test_regional_routing_router_rejects_overlapping_regions() -> None:
    """RegionalRoutingRouter fails fast if configured with overlapping regions."""
    from engine.contracts.routing import RegionConfig
    from engine.adapters.regional_router import RegionalRoutingRouter

    cfg1 = RegionConfig(region_id="region-1", bounding_box=NYC_BBOX, provider_type="mock")
    overlapping_bbox = BoundingBox(min_lat=40.7000, min_lon=-74.0000, max_lat=40.9000, max_lon=-73.8000)
    cfg2 = RegionConfig(region_id="region-2", bounding_box=overlapping_bbox, provider_type="mock")

    with pytest.raises(ValueError, match="overlap"):
        RegionalRoutingRouter(regions=[cfg1, cfg2])


def test_regional_routing_router_routes_independent_regions() -> None:
    """RegionalRoutingRouter routes queries to appropriate region provider."""
    from engine.contracts.routing import RegionConfig
    from engine.adapters.regional_router import RegionalRoutingRouter

    cfg_nyc = RegionConfig(
        region_id="us-nyc-manhattan",
        bounding_box=NYC_BBOX,
        provider_type="mock",
        dataset_id="nyc-mock",
    )
    cfg_kl = RegionConfig(
        region_id="in-kl-tvm",
        bounding_box=KERALA_BBOX,
        provider_type="mock",
        dataset_id="kl-mock",
    )

    provider_nyc = MockRoutingProvider(average_speed_kmh=30.0, bounding_box=NYC_BBOX)
    provider_kl = MockRoutingProvider(average_speed_kmh=60.0, bounding_box=KERALA_BBOX)

    router = RegionalRoutingRouter(
        regions=[cfg_nyc, cfg_kl],
        providers={"us-nyc-manhattan": provider_nyc, "in-kl-tvm": provider_kl},
    )

    # In-region NYC routing
    dist_nyc, dur_nyc = router.get_direct_leg(NYC_TIMES_SQUARE, NYC_WALL_STREET)
    assert dist_nyc > 0
    assert dur_nyc > 0

    # In-region Kerala routing
    dist_kl, dur_kl = router.get_direct_leg(KERALA_TVM_ORIGIN, KERALA_TVM_DEST)
    assert dist_kl > 0
    assert dur_kl > 0

    # Faster speed in Kerala provider produces lower duration per unit distance
    assert (dur_kl / dist_kl) < (dur_nyc / dist_nyc)


def test_regional_routing_router_rejects_out_of_region() -> None:
    """RegionalRoutingRouter rejects coordinates outside all configured regions."""
    from engine.contracts.routing import RegionConfig
    from engine.adapters.regional_router import RegionalRoutingRouter

    cfg_nyc = RegionConfig(region_id="us-nyc-manhattan", bounding_box=NYC_BBOX, provider_type="mock")
    router = RegionalRoutingRouter(
        regions=[cfg_nyc],
        providers={"us-nyc-manhattan": MockRoutingProvider(bounding_box=NYC_BBOX)},
    )

    # Coordinate in London outside NYC
    with pytest.raises(OutOfRegionError, match="outside all configured service regions"):
        router.validate_coordinate(LONDON_COORD)

    with pytest.raises(OutOfRegionError, match="outside all configured service regions"):
        router.get_direct_leg(NYC_TIMES_SQUARE, LONDON_COORD)


def test_regional_routing_router_rejects_cross_region_journey() -> None:
    """RegionalRoutingRouter explicitly rejects cross-region journeys."""
    from engine.contracts.routing import RegionConfig
    from engine.adapters.regional_router import RegionalRoutingRouter

    cfg_nyc = RegionConfig(region_id="us-nyc-manhattan", bounding_box=NYC_BBOX, provider_type="mock")
    cfg_kl = RegionConfig(region_id="in-kl-tvm", bounding_box=KERALA_BBOX, provider_type="mock")

    router = RegionalRoutingRouter(
        regions=[cfg_nyc, cfg_kl],
        providers={
            "us-nyc-manhattan": MockRoutingProvider(bounding_box=NYC_BBOX),
            "in-kl-tvm": MockRoutingProvider(bounding_box=KERALA_BBOX),
        },
    )

    # Pickup in NYC, Dropoff in Kerala
    with pytest.raises(OutOfRegionError, match="Cross-region routing between 'us-nyc-manhattan' and 'in-kl-tvm' is unsupported"):
        router.get_direct_leg(NYC_TIMES_SQUARE, KERALA_TVM_DEST)


def test_regional_routing_router_distance_matrix_cross_region_rejected() -> None:
    """RegionalRoutingRouter rejects distance matrix queries spanning multiple regions."""
    from engine.contracts.routing import RegionConfig
    from engine.adapters.regional_router import RegionalRoutingRouter

    cfg_nyc = RegionConfig(region_id="us-nyc-manhattan", bounding_box=NYC_BBOX, provider_type="mock")
    cfg_kl = RegionConfig(region_id="in-kl-tvm", bounding_box=KERALA_BBOX, provider_type="mock")

    router = RegionalRoutingRouter(
        regions=[cfg_nyc, cfg_kl],
        providers={
            "us-nyc-manhattan": MockRoutingProvider(bounding_box=NYC_BBOX),
            "in-kl-tvm": MockRoutingProvider(bounding_box=KERALA_BBOX),
        },
    )

    with pytest.raises(OutOfRegionError, match="Cross-region"):
        router.get_distance_matrix(
            origins=[NYC_TIMES_SQUARE, KERALA_TVM_ORIGIN],
            destinations=[NYC_WALL_STREET, KERALA_TVM_DEST],
        )


def test_regional_routing_router_health_reporting() -> None:
    """RegionalRoutingRouter provides comprehensive per-region and aggregate health."""
    from engine.contracts.routing import RegionConfig
    from engine.adapters.regional_router import RegionalRoutingRouter

    class FailingRoutingProvider(MockRoutingProvider):
        def check_health(self) -> bool:
            return False

    cfg_nyc = RegionConfig(region_id="us-nyc-manhattan", bounding_box=NYC_BBOX, provider_type="mock", endpoint_url="http://127.0.0.1:5000")
    cfg_kl = RegionConfig(region_id="in-kl-tvm", bounding_box=KERALA_BBOX, provider_type="mock", endpoint_url="http://127.0.0.1:5001")

    p_nyc = MockRoutingProvider(bounding_box=NYC_BBOX)
    p_kl = FailingRoutingProvider(bounding_box=KERALA_BBOX)

    router = RegionalRoutingRouter(
        regions=[cfg_nyc, cfg_kl],
        providers={"us-nyc-manhattan": p_nyc, "in-kl-tvm": p_kl},
    )

    # Overall health is False because Kerala provider is failing
    assert router.check_health() is False

    health_report = router.check_regions_health()
    assert health_report["us-nyc-manhattan"]["healthy"] is True
    assert health_report["us-nyc-manhattan"]["provider_type"] == "mock"
    assert health_report["in-kl-tvm"]["healthy"] is False


def test_osrm_cache_key_dataset_and_profile_isolation() -> None:
    """Verifies that routing caches incorporate dataset identity and profile to prevent cross-dataset leakage."""
    from engine.adapters.osrm_routing import OsrmRoutingAdapter

    adapter1 = OsrmRoutingAdapter(dataset_id="manhattan-2026-v1", profile="driving")
    adapter2 = OsrmRoutingAdapter(dataset_id="manhattan-2026-v2", profile="driving")
    adapter3 = OsrmRoutingAdapter(dataset_id="manhattan-2026-v1", profile="cycling")

    k1 = adapter1._cache_key(NYC_TIMES_SQUARE, NYC_WALL_STREET)
    k2 = adapter2._cache_key(NYC_TIMES_SQUARE, NYC_WALL_STREET)
    k3 = adapter3._cache_key(NYC_TIMES_SQUARE, NYC_WALL_STREET)

    assert k1 != k2
    assert k1 != k3
    assert k2 != k3
    assert k1[0] == "manhattan-2026-v1"
    assert k1[1] == "driving"
    assert k2[0] == "manhattan-2026-v2"
    assert k3[1] == "cycling"
