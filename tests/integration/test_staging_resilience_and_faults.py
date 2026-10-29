"""
Phase 8E: Resilience & Fault Injection Verification Suite.

Tests graceful failure isolation, connection recovery, timeout handling,
and configuration fail-fast invariants without disturbing live services.
"""

from __future__ import annotations

import pytest
import time
from typing import Any

from engine.contracts.routing import (
    BoundingBox,
    Coordinate,
    OutOfRegionError,
    RegionConfig,
    RouteLookupError,
    RouteTimeoutError,
)
from engine.adapters.osrm_routing import OsrmRoutingAdapter, DefaultOsrmTransport
from engine.adapters.regional_router import RegionalRoutingRouter
from engine.adapters.postgres_storage import PostgresRideStorage
from engine.service.app import create_app
from engine.service.client import AsgiTestClient
from engine.service.service import PoolEngineService, build_service_from_env


C_NYC_1 = Coordinate(latitude=40.7580, longitude=-73.9855)
C_NYC_2 = Coordinate(latitude=40.7070, longitude=-74.0090)
C_KL_1 = Coordinate(latitude=8.5030, longitude=76.9530)
C_KL_2 = Coordinate(latitude=8.4875, longitude=76.9528)


# ---------------------------------------------------------------------------
# 1. Kerala OSRM Unavailable while Manhattan remains healthy
# ---------------------------------------------------------------------------
def test_resilience_kerala_offline_manhattan_healthy() -> None:
    regions = [
        RegionConfig(
            region_id="us-nyc-manhattan",
            bounding_box=BoundingBox(min_lat=40.69, min_lon=-74.05, max_lat=40.88, max_lon=-73.90),
            provider_type="osrm",
            endpoint_url="http://127.0.0.1:5000",
            probe_coordinate=C_NYC_1,
        ),
        RegionConfig(
            region_id="in-kl-tvm",
            bounding_box=BoundingBox(min_lat=8.18, min_lon=76.80, max_lat=8.65, max_lon=77.05),
            provider_type="osrm",
            endpoint_url="http://127.0.0.1:5998",  # Dead port
            probe_coordinate=C_KL_1,
        ),
    ]
    router = RegionalRoutingRouter(regions=regions)

    # Health reporting
    health = router.check_regions_health()
    assert health["us-nyc-manhattan"]["healthy"] is True
    assert health["in-kl-tvm"]["healthy"] is False

    # Manhattan requests route normally
    d, t = router.get_direct_leg(C_NYC_1, C_NYC_2)
    assert d > 7000

    # Kerala requests fail with controlled RouteLookupError or RouteTimeoutError
    with pytest.raises((RouteLookupError, RouteTimeoutError)):
        router.get_direct_leg(C_KL_1, C_KL_2)

    router.close()


# ---------------------------------------------------------------------------
# 2. Manhattan OSRM Unavailable while Kerala remains healthy
# ---------------------------------------------------------------------------
def test_resilience_manhattan_offline_kerala_healthy() -> None:
    regions = [
        RegionConfig(
            region_id="us-nyc-manhattan",
            bounding_box=BoundingBox(min_lat=40.69, min_lon=-74.05, max_lat=40.88, max_lon=-73.90),
            provider_type="osrm",
            endpoint_url="http://127.0.0.1:5997",  # Dead port
            probe_coordinate=C_NYC_1,
        ),
        RegionConfig(
            region_id="in-kl-tvm",
            bounding_box=BoundingBox(min_lat=8.18, min_lon=76.80, max_lat=8.65, max_lon=77.05),
            provider_type="osrm",
            endpoint_url="http://127.0.0.1:5001",
            probe_coordinate=C_KL_1,
        ),
    ]
    router = RegionalRoutingRouter(regions=regions)

    # Health reporting
    health = router.check_regions_health()
    assert health["us-nyc-manhattan"]["healthy"] is False
    assert health["in-kl-tvm"]["healthy"] is True

    # Kerala requests route normally
    d, t = router.get_direct_leg(C_KL_1, C_KL_2)
    assert d > 1500

    # Manhattan requests fail with controlled RouteLookupError or RouteTimeoutError
    with pytest.raises((RouteLookupError, RouteTimeoutError)):
        router.get_direct_leg(C_NYC_1, C_NYC_2)

    router.close()


# ---------------------------------------------------------------------------
# 3. API Process Restart & Recovery
# ---------------------------------------------------------------------------
def test_resilience_api_service_restart_recovery() -> None:
    env = {
        "ROUTING_REGIONS_FILE": "config/regions.json",
        "REQUIRE_REAL_ROUTING": "true",
        "DATABASE_URL": "postgresql://postgres:postgres@127.0.0.1:5433/pool_engine_test",
        "REQUIRE_PERSISTENT_STORAGE": "true",
    }
    s1 = build_service_from_env(env)
    c1 = AsgiTestClient(create_app(s1))
    r1 = c1.get("/v1/health/readiness")
    assert r1.status_code == 200
    s1.close()

    # Recreate service (simulating clean restart)
    s2 = build_service_from_env(env)
    c2 = AsgiTestClient(create_app(s2))
    r2 = c2.get("/v1/health/readiness")
    assert r2.status_code == 200
    assert r2.json()["ready"] is True
    s2.close()


# ---------------------------------------------------------------------------
# 4. OSRM Connection Drop & Transparent Recovery
# ---------------------------------------------------------------------------
def test_resilience_osrm_connection_drop_and_recovery() -> None:
    adapter = OsrmRoutingAdapter(base_url="http://127.0.0.1:5001")
    d1, t1 = adapter.get_direct_leg(C_KL_1, C_KL_2)

    # Abruptly close transport pool
    if isinstance(adapter.transport, DefaultOsrmTransport):
        adapter.transport.close()

    # Next query transparently reconnects and succeeds
    d2, t2 = adapter.get_direct_leg(C_KL_1, C_KL_2)
    assert d1 == d2
    assert t1 == t2
    adapter.close()


# ---------------------------------------------------------------------------
# 5. Delayed Backend Responses or Connection Timeouts
# ---------------------------------------------------------------------------
def test_resilience_delayed_response_timeout_handling() -> None:
    from engine.adapters.osrm_routing import OsrmHttpTransport

    class SimTimeoutTransport(OsrmHttpTransport):
        def get(self, path_and_query: str, timeout: float) -> tuple[int, bytes]:
            raise TimeoutError("Simulated socket read timeout")

    timeout_adapter = OsrmRoutingAdapter(transport=SimTimeoutTransport())
    with pytest.raises(RouteTimeoutError, match=r"timed out"):
        timeout_adapter.get_direct_leg(C_KL_1, C_KL_2)
    timeout_adapter.close()


# ---------------------------------------------------------------------------
# 6. Database Connection Failure & Credential Sanitization
# ---------------------------------------------------------------------------
def test_resilience_database_failure_sanitizes_credentials() -> None:
    from engine.contracts.storage import StorageProviderError

    bad_url = "postgresql://secret_user:super_secret_pw@127.0.0.1:5996/nonexistent"
    try:
        storage = PostgresRideStorage(dsn=bad_url, min_pool_size=1, max_pool_size=2)
        storage.open()
        storage.get_active_rides(limit=1)
        storage.close()
    except Exception as exc:
        err_text = str(exc)
        # Ensure password is not leaked in plain text exception
        assert "super_secret_pw" not in err_text


# ---------------------------------------------------------------------------
# 7. Malformed Configuration Fails Fast at Startup
# ---------------------------------------------------------------------------
def test_resilience_malformed_configuration_fails_fast() -> None:
    # 7.1 Inverted bounding box
    with pytest.raises(ValueError, match=r"cannot exceed max_lat"):
        BoundingBox(min_lat=45.0, min_lon=-74.0, max_lat=40.0, max_lon=-73.0)

    # 7.2 Overlapping bounding boxes between regions
    r1 = RegionConfig(
        region_id="r1",
        bounding_box=BoundingBox(min_lat=40.0, min_lon=-74.0, max_lat=41.0, max_lon=-73.0),
        provider_type="osrm",
        endpoint_url="http://127.0.0.1:5000",
    )
    r2 = RegionConfig(
        region_id="r2",
        bounding_box=BoundingBox(min_lat=40.5, min_lon=-73.5, max_lat=41.5, max_lon=-72.5),  # Overlaps r1
        provider_type="osrm",
        endpoint_url="http://127.0.0.1:5001",
    )
    with pytest.raises(ValueError, match=r"overlap"):
        RegionalRoutingRouter(regions=[r1, r2])


# ---------------------------------------------------------------------------
# 8. Graceful Shutdown Closes Resources Cleanly
# ---------------------------------------------------------------------------
def test_resilience_graceful_shutdown() -> None:
    env = {
        "ROUTING_REGIONS_FILE": "config/regions.json",
        "REQUIRE_REAL_ROUTING": "true",
        "DATABASE_URL": "postgresql://postgres:postgres@127.0.0.1:5433/pool_engine_test",
        "REQUIRE_PERSISTENT_STORAGE": "true",
    }
    service = build_service_from_env(env)
    assert service.router is not None
    assert service.storage is not None

    # Perform a request before shutdown
    resp = service.check_readiness()
    assert resp["ready"] is True

    # Shutdown
    service.close()
