"""Deterministic benchmark scenario generator for 1,000 requests and 200 vehicles (T052)."""

import random
from typing import Sequence
import pytest

from engine.adapters.default_policy import DefaultPolicyProvider
from engine.adapters.h3_spatial import H3SpatialIndexAdapter
from engine.adapters.mock_routing import MockRoutingProvider
from engine.domain.enums import RequestStatus, RideStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, Ride, RideRequest, RouteStop, Vehicle

# 10 km x 10 km urban bounding box (NYC Midtown/Downtown area)
MIN_LAT = 40.7000
MAX_LAT = 40.7900
MIN_LON = -74.0200
MAX_LON = -73.9000

HOTSPOTS = [
    (40.7128, -74.0060),  # Downtown / Financial District
    (40.7580, -73.9855),  # Midtown / Times Square
    (40.7829, -73.9654),  # Upper East / Transit Hub
]


def generate_benchmark_scenario(
    seed: int = 42,
    base_time: int = 1700000000,
) -> tuple[list[RideRequest], list[Vehicle], list[Ride]]:
    """
    Generates a reproducible benchmark scenario with fixed PRNG seed=42:
    - 1,000 active requests (60% clustered near 3 hotspots, 40% uniform;
      party sizes 70% 1-seat, 20% 2-seat, 10% 3-4 seat;
      trip durations 40% short, 40% medium, 20% long)
    - 200 active vehicles (80% 4-passenger, 20% 6-passenger; 50% idle, 50% active)
    """
    rng = random.Random(seed)

    def _sample_point(clustered: bool = False) -> GeoCoordinate:
        if clustered:
            center_lat, center_lon = rng.choice(HOTSPOTS)
            lat = rng.gauss(center_lat, 0.005)
            lon = rng.gauss(center_lon, 0.005)
        else:
            lat = rng.uniform(MIN_LAT, MAX_LAT)
            lon = rng.uniform(MIN_LON, MAX_LON)
        lat = max(MIN_LAT, min(MAX_LAT, lat))
        lon = max(MIN_LON, min(MAX_LON, lon))
        return GeoCoordinate(latitude=round(lat, 6), longitude=round(lon, 6))

    requests: list[RideRequest] = []

    # 1,000 requests
    for i in range(1000):
        is_clustered = (i < 600)  # 60% clustered, 40% uniform
        pickup = _sample_point(clustered=is_clustered)
        dropoff = _sample_point(clustered=False)

        # Party sizes: 70% 1-seat, 20% 2-seat, 10% 3-4 seat
        if i < 700:
            seats = 1
        elif i < 900:
            seats = 2
        elif i < 950:
            seats = 3
        else:
            seats = 4

        # Trip durations: 40% short (<600s), 40% medium (600-1800s), 20% long (1800-3600s)
        if i < 400:
            duration = rng.randint(300, 550)
        elif i < 800:
            duration = rng.randint(650, 1500)
        else:
            duration = rng.randint(1850, 3200)

        # Distance approximated at 40 km/h (11.11 m/s)
        distance = int(duration * 11.11)

        req = RideRequest(
            request_id=f"req-bench-{i:04d}",
            user_id=f"user-bench-{i:04d}",
            pickup_location=pickup,
            dropoff_location=dropoff,
            seat_count=seats,
            earliest_pickup_time=base_time + rng.randint(0, 300),
            latest_dropoff_time=base_time + duration + 1200,
            direct_distance_meters=distance,
            direct_duration_seconds=duration,
            status=RequestStatus.PENDING,
        )
        requests.append(req)

    # 200 vehicles (80% 4-seat, 20% 6-seat; 50% idle, 50% active)
    vehicles: list[Vehicle] = []
    rides: list[Ride] = []

    for v_idx in range(200):
        veh_id = f"veh-bench-{v_idx:03d}"
        capacity = 4 if v_idx < 160 else 6
        loc = _sample_point(clustered=(v_idx < 100))

        vehicle = Vehicle(
            vehicle_id=veh_id,
            driver_id=f"drv-bench-{v_idx:03d}",
            total_seat_capacity=capacity,
            current_location=loc,
            is_active=True,
        )
        vehicles.append(vehicle)

        # 50% active (vehicles 100 to 199 have active rides with 1 onboard passenger)
        if v_idx >= 100:
            p_onboard = _sample_point()
            d_onboard = _sample_point()
            req_onboard_id = f"req-onboard-{v_idx}"

            stop_p = RouteStop(
                stop_id=f"stop-p-{req_onboard_id}",
                ride_id=f"ride-bench-{v_idx:03d}",
                request_id=req_onboard_id,
                stop_type=StopType.PICKUP,
                location=p_onboard,
                passenger_delta=+1,
                scheduled_arrival_time=base_time - 300,
                promised_window_start=base_time - 600,
                promised_window_end=base_time,
                actual_arrival_time=base_time - 300,
                status=StopStatus.COMPLETED,
            )
            stop_d = RouteStop(
                stop_id=f"stop-d-{req_onboard_id}",
                ride_id=f"ride-bench-{v_idx:03d}",
                request_id=req_onboard_id,
                stop_type=StopType.DROPOFF,
                location=d_onboard,
                passenger_delta=-1,
                scheduled_arrival_time=base_time + 600,
                promised_window_start=base_time - 600,
                promised_window_end=base_time + 1200,
                status=StopStatus.SCHEDULED,
            )

            ride = Ride(
                ride_id=f"ride-bench-{v_idx:03d}",
                vehicle_id=veh_id,
                driver_id=vehicle.driver_id,
                lifecycle_status=RideStatus.ACTIVE,
                stops=(stop_p, stop_d),
                scheduled_departure_time=base_time - 300,
                actual_departure_time=base_time - 300,
                active_passenger_count=1,
                total_vmt_meters=3000,
                version=1,
            )
            rides.append(ride)

    return requests, vehicles, rides


@pytest.fixture
def benchmark_scenario_data() -> tuple[list[RideRequest], list[Vehicle], list[Ride]]:
    return generate_benchmark_scenario(seed=42)


@pytest.fixture
def in_memory_router() -> MockRoutingProvider:
    return MockRoutingProvider(average_speed_kmh=40.0)


@pytest.fixture
def policy_provider() -> DefaultPolicyProvider:
    return DefaultPolicyProvider()


@pytest.fixture
def spatial_index() -> H3SpatialIndexAdapter:
    return H3SpatialIndexAdapter(resolution=8)
