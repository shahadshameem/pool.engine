"""Composite multi-region routing router conforming to RoadNetworkRoutingProvider."""

import logging
import time
from typing import Any, Mapping, Sequence

from engine.contracts.routing import (
    Coordinate,
    MatrixResult,
    OutOfRegionError,
    RegionConfig,
    RoadNetworkRoutingProvider,
    RouteGeometry,
)

logger = logging.getLogger("pool_engine.routing.multi_region")


class RegionalRoutingRouter(RoadNetworkRoutingProvider):
    """
    Composite routing router distributing spatial queries across isolated,
    region-specific routing providers while enforcing strict disjoint boundaries
    and rejecting unsupported cross-region journeys.
    """

    def __init__(
        self,
        regions: Sequence[RegionConfig],
        providers: Mapping[str, RoadNetworkRoutingProvider] | None = None,
    ) -> None:
        if not regions:
            raise ValueError("RegionalRoutingRouter requires at least one configured RegionConfig")

        self._regions: dict[str, RegionConfig] = {}
        for r in regions:
            if r.region_id in self._regions:
                raise ValueError(f"Duplicate region_id detected in configuration: '{r.region_id}'")
            self._regions[r.region_id] = r

        # Enforce strictly disjoint bounding boxes
        region_list = list(self._regions.values())
        for i in range(len(region_list)):
            for j in range(i + 1, len(region_list)):
                r1 = region_list[i]
                r2 = region_list[j]
                if r1.bounding_box.overlaps(r2.bounding_box):
                    raise ValueError(
                        f"Regional bounding boxes for '{r1.region_id}' and '{r2.region_id}' overlap: "
                        f"[{r1.bounding_box.min_lat}, {r1.bounding_box.min_lon}, {r1.bounding_box.max_lat}, {r1.bounding_box.max_lon}] "
                        f"and [{r2.bounding_box.min_lat}, {r2.bounding_box.min_lon}, {r2.bounding_box.max_lat}, {r2.bounding_box.max_lon}]"
                    )

        self._providers: dict[str, RoadNetworkRoutingProvider] = {}
        if providers is not None:
            for r_id in self._regions:
                if r_id not in providers:
                    raise ValueError(f"Missing routing provider for configured region '{r_id}'")
                self._providers[r_id] = providers[r_id]
        else:
            from engine.adapters.mock_routing import MockRoutingProvider
            from engine.adapters.osrm_routing import OsrmRoutingAdapter

            for r_id, cfg in self._regions.items():
                if cfg.provider_type == "mock":
                    self._providers[r_id] = MockRoutingProvider(bounding_box=cfg.bounding_box)
                elif cfg.provider_type == "osrm":
                    endpoint = cfg.endpoint_url or "http://127.0.0.1:5000"
                    self._providers[r_id] = OsrmRoutingAdapter(
                        base_url=endpoint,
                        bounding_box=cfg.bounding_box,
                        max_snap_distance_meters=cfg.max_snap_distance_meters,
                        timeout_seconds=cfg.timeout_seconds,
                        dataset_id=cfg.dataset_id,
                        profile=cfg.profile,
                        probe_coordinate=cfg.probe_coordinate,
                    )
                else:
                    raise ValueError(f"Unsupported provider_type '{cfg.provider_type}' for region '{r_id}'")

    @property
    def regions(self) -> dict[str, RegionConfig]:
        return dict(self._regions)

    @property
    def providers(self) -> dict[str, RoadNetworkRoutingProvider]:
        return dict(self._providers)

    def find_region_for_coordinate(self, coord: Coordinate) -> RegionConfig | None:
        """
        Locates the unique region containing the given coordinate.
        Because bounding boxes are strictly disjoint, at most one region matches.
        """
        for region in self._regions.values():
            if region.bounding_box.contains(coord):
                return region
        return None

    def get_provider(self, region_id: str) -> RoadNetworkRoutingProvider:
        """Returns the routing provider instance registered for the specified region."""
        if region_id not in self._providers:
            raise KeyError(f"No routing provider registered for region '{region_id}'")
        return self._providers[region_id]

    def validate_coordinate(self, coord: Coordinate, label: str = "Coordinate") -> None:
        """
        Validates that a coordinate falls inside at least one configured region,
        and delegates to that region's provider for snapping or local constraints.
        """
        region = self.find_region_for_coordinate(coord)
        if region is None:
            raise OutOfRegionError(
                f"{label} ({coord.latitude}, {coord.longitude}) falls outside all configured service regions"
            )
        self._providers[region.region_id].validate_coordinate(coord, label)

    def get_direct_leg(self, origin: Coordinate, destination: Coordinate) -> tuple[int, int]:
        """
        Routes a direct leg between origin and destination.
        Explicitly rejects cross-region journeys.
        """
        r_orig = self.find_region_for_coordinate(origin)
        if r_orig is None:
            raise OutOfRegionError(
                f"Origin coordinate ({origin.latitude}, {origin.longitude}) falls outside all configured service regions"
            )
        r_dest = self.find_region_for_coordinate(destination)
        if r_dest is None:
            raise OutOfRegionError(
                f"Destination coordinate ({destination.latitude}, {destination.longitude}) falls outside all configured service regions"
            )
        if r_orig.region_id != r_dest.region_id:
            raise OutOfRegionError(
                f"Cross-region routing between '{r_orig.region_id}' and '{r_dest.region_id}' is unsupported"
            )
        return self._providers[r_orig.region_id].get_direct_leg(origin, destination)

    def get_distance_matrix(
        self,
        origins: Sequence[Coordinate],
        destinations: Sequence[Coordinate],
    ) -> MatrixResult:
        """
        Computes pairwise road network distances and durations.
        All origins and destinations must reside within the same operational region.
        """
        if not origins or not destinations:
            return MatrixResult(distances_meters=[], durations_seconds=[])

        target_region: RegionConfig | None = None
        for idx, orig in enumerate(origins):
            r = self.find_region_for_coordinate(orig)
            if r is None:
                raise OutOfRegionError(
                    f"Origin[{idx}] ({orig.latitude}, {orig.longitude}) falls outside all configured service regions"
                )
            if target_region is None:
                target_region = r
            elif target_region.region_id != r.region_id:
                raise OutOfRegionError(
                    f"Cross-region distance matrix spanning '{target_region.region_id}' and '{r.region_id}' is unsupported"
                )

        assert target_region is not None
        for idx, dest in enumerate(destinations):
            r = self.find_region_for_coordinate(dest)
            if r is None:
                raise OutOfRegionError(
                    f"Destination[{idx}] ({dest.latitude}, {dest.longitude}) falls outside all configured service regions"
                )
            if target_region.region_id != r.region_id:
                raise OutOfRegionError(
                    f"Cross-region distance matrix spanning '{target_region.region_id}' and '{r.region_id}' is unsupported"
                )

        return self._providers[target_region.region_id].get_distance_matrix(origins, destinations)

    def get_route(self, waypoints: Sequence[Coordinate]) -> RouteGeometry:
        """
        Computes turn-by-turn road route connecting ordered waypoints.
        All waypoints must reside within the same operational region.
        """
        if not waypoints:
            return RouteGeometry(points=[], total_distance_meters=0, total_duration_seconds=0)

        target_region: RegionConfig | None = None
        for idx, wp in enumerate(waypoints):
            r = self.find_region_for_coordinate(wp)
            if r is None:
                raise OutOfRegionError(
                    f"Waypoint[{idx}] ({wp.latitude}, {wp.longitude}) falls outside all configured service regions"
                )
            if target_region is None:
                target_region = r
            elif target_region.region_id != r.region_id:
                raise OutOfRegionError(
                    f"Cross-region route spanning '{target_region.region_id}' and '{r.region_id}' is unsupported"
                )

        assert target_region is not None
        return self._providers[target_region.region_id].get_route(waypoints)

    def prefetch_matrix(
        self,
        origins: Sequence[Coordinate],
        destinations: Sequence[Coordinate] | None = None,
        deadline: float | None = None,
        reserved_headroom: float = 0.050,
    ) -> int:
        """
        Groups origins by region and delegates in-region prefetching to corresponding providers.
        Silently skips cross-region combinations without failing.
        """
        effective_destinations = destinations or origins
        # Partition origins by region
        region_origins: dict[str, list[Coordinate]] = {}
        for c in origins:
            r = self.find_region_for_coordinate(c)
            if r is not None:
                region_origins.setdefault(r.region_id, []).append(c)

        region_dests: dict[str, list[Coordinate]] = {}
        for c in effective_destinations:
            r = self.find_region_for_coordinate(c)
            if r is not None:
                region_dests.setdefault(r.region_id, []).append(c)

        total_cached = 0
        for r_id, r_origs in region_origins.items():
            if deadline is not None and time.monotonic() > deadline - reserved_headroom:
                break
            r_dsts = region_dests.get(r_id)
            if r_dsts:
                provider = self._providers[r_id]
                total_cached += provider.prefetch_matrix(
                    origins=r_origs,
                    destinations=r_dsts,
                    deadline=deadline,
                    reserved_headroom=reserved_headroom,
                )
        return total_cached

    def prefetch_matrices(
        self,
        groups: Sequence[Sequence[Coordinate]],
        deadline: float | None = None,
        reserved_headroom: float = 0.050,
    ) -> int:
        """
        Prefetches pairwise legs for candidate groups.
        Groups whose coordinates all belong to the same region are routed to that region's provider.
        Cross-region groups are safely pruned.
        """
        region_groups: dict[str, list[Sequence[Coordinate]]] = {}
        for group in groups:
            if not group:
                continue
            r_first = self.find_region_for_coordinate(group[0])
            if r_first is None:
                continue
            is_homogeneous = all(
                self.find_region_for_coordinate(c) is not None
                and self.find_region_for_coordinate(c).region_id == r_first.region_id  # type: ignore[union-attr]
                for c in group
            )
            if is_homogeneous:
                region_groups.setdefault(r_first.region_id, []).append(group)

        total = 0
        for r_id, r_grps in region_groups.items():
            if deadline is not None and time.monotonic() > deadline - reserved_headroom:
                break
            provider = self._providers[r_id]
            total += provider.prefetch_matrices(
                groups=r_grps,
                deadline=deadline,
                reserved_headroom=reserved_headroom,
            )
        return total

    def check_health(self) -> bool:
        """
        Returns True if all registered regional routing backends are reachable and healthy.
        If any region fails, returns False.
        """
        return all(p.check_health() for p in self._providers.values())

    def check_regions_health(self) -> dict[str, dict[str, Any]]:
        """
        Returns a detailed per-region health report.
        """
        report: dict[str, dict[str, Any]] = {}
        for r_id, cfg in self._regions.items():
            provider = self._providers[r_id]
            is_healthy = False
            try:
                is_healthy = provider.check_health()
            except Exception as err:
                logger.warning(f"Health check raised exception for region '{r_id}': {err}")
            report[r_id] = {
                "healthy": is_healthy,
                "provider_type": cfg.provider_type,
                "dataset_id": cfg.dataset_id,
                "endpoint_url": cfg.endpoint_url,
                "profile": cfg.profile,
            }
        return report

    def open(self) -> None:
        """Opens/initializes all underlying regional routing providers."""
        for p in self._providers.values():
            if hasattr(p, "open"):
                p.open()

    def close(self) -> None:
        """Closes all underlying regional routing providers."""
        for p in self._providers.values():
            if hasattr(p, "close"):
                try:
                    p.close()
                except Exception:
                    pass
            if hasattr(p, "transport") and hasattr(p.transport, "close"):
                try:
                    p.transport.close()
                except Exception:
                    pass
