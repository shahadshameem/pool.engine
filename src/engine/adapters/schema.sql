-- Schema Migration 001: Persistent Storage Schema for Ride-Pooling Engine
-- Compatible with standard PostgreSQL 14+ and optional PostGIS extension.

-- Enable PostGIS if available (optional, caught gracefully if extension missing)
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS postgis;
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'PostGIS extension not available; using standard coordinate bounding.';
END
$$;

-- 1. Vehicles Table
CREATE TABLE IF NOT EXISTS vehicles (
    vehicle_id VARCHAR(128) PRIMARY KEY,
    driver_id VARCHAR(128) NOT NULL,
    total_seat_capacity INTEGER NOT NULL CHECK (total_seat_capacity >= 1 AND total_seat_capacity <= 50),
    luggage_capacity_units INTEGER NOT NULL DEFAULT 0 CHECK (luggage_capacity_units >= 0),
    current_latitude DOUBLE PRECISION NOT NULL CHECK (current_latitude >= -90.0 AND current_latitude <= 90.0),
    current_longitude DOUBLE PRECISION NOT NULL CHECK (current_longitude >= -180.0 AND current_longitude <= 180.0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vehicles_coords ON vehicles (current_latitude, current_longitude);

-- 2. Rides Table
CREATE TABLE IF NOT EXISTS rides (
    ride_id VARCHAR(128) PRIMARY KEY,
    vehicle_id VARCHAR(128) NOT NULL REFERENCES vehicles (vehicle_id),
    driver_id VARCHAR(128) NOT NULL,
    lifecycle_status VARCHAR(64) NOT NULL,
    scheduled_departure_time BIGINT NOT NULL,
    actual_departure_time BIGINT,
    active_passenger_count INTEGER NOT NULL DEFAULT 0 CHECK (active_passenger_count >= 0),
    total_vmt_meters INTEGER NOT NULL DEFAULT 0 CHECK (total_vmt_meters >= 0),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rides_status ON rides (lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_rides_vehicle ON rides (vehicle_id);

-- 3. Route Stops Table (ordered itinerary for each ride)
CREATE TABLE IF NOT EXISTS route_stops (
    stop_id VARCHAR(128) PRIMARY KEY,
    ride_id VARCHAR(128) NOT NULL REFERENCES rides (ride_id) ON DELETE CASCADE,
    stop_order INTEGER NOT NULL CHECK (stop_order >= 0),
    request_id VARCHAR(128) NOT NULL,
    stop_type VARCHAR(32) NOT NULL,
    latitude DOUBLE PRECISION NOT NULL CHECK (latitude >= -90.0 AND latitude <= 90.0),
    longitude DOUBLE PRECISION NOT NULL CHECK (longitude >= -180.0 AND longitude <= 180.0),
    passenger_delta INTEGER NOT NULL,
    scheduled_arrival_time BIGINT NOT NULL,
    promised_window_start BIGINT NOT NULL,
    promised_window_end BIGINT NOT NULL,
    actual_arrival_time BIGINT,
    dwell_duration_seconds INTEGER NOT NULL DEFAULT 0 CHECK (dwell_duration_seconds >= 0),
    dwell_start_time BIGINT,
    status VARCHAR(64) NOT NULL DEFAULT 'SCHEDULED',
    CONSTRAINT uq_ride_stop_order UNIQUE (ride_id, stop_order)
);

CREATE INDEX IF NOT EXISTS idx_route_stops_ride ON route_stops (ride_id, stop_order);
CREATE INDEX IF NOT EXISTS idx_route_stops_coords ON route_stops (latitude, longitude);

-- 4. Ride Requests Table
CREATE TABLE IF NOT EXISTS ride_requests (
    request_id VARCHAR(128) PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    pickup_latitude DOUBLE PRECISION NOT NULL CHECK (pickup_latitude >= -90.0 AND pickup_latitude <= 90.0),
    pickup_longitude DOUBLE PRECISION NOT NULL CHECK (pickup_longitude >= -180.0 AND pickup_longitude <= 180.0),
    dropoff_latitude DOUBLE PRECISION NOT NULL CHECK (dropoff_latitude >= -90.0 AND dropoff_latitude <= 90.0),
    dropoff_longitude DOUBLE PRECISION NOT NULL CHECK (dropoff_longitude >= -180.0 AND dropoff_longitude <= 180.0),
    seat_count INTEGER NOT NULL CHECK (seat_count >= 1),
    earliest_pickup_time BIGINT NOT NULL,
    latest_dropoff_time BIGINT NOT NULL,
    direct_distance_meters INTEGER NOT NULL DEFAULT 0 CHECK (direct_distance_meters >= 0),
    direct_duration_seconds INTEGER NOT NULL DEFAULT 0 CHECK (direct_duration_seconds >= 0),
    status VARCHAR(64) NOT NULL DEFAULT 'PENDING',
    matched_ride_id VARCHAR(128) REFERENCES rides (ride_id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ride_requests_status ON ride_requests (status);
CREATE INDEX IF NOT EXISTS idx_ride_requests_pickup ON ride_requests (pickup_latitude, pickup_longitude);

-- 5. Join Requests Table
CREATE TABLE IF NOT EXISTS join_requests (
    join_request_id VARCHAR(128) PRIMARY KEY,
    ride_id VARCHAR(128) NOT NULL REFERENCES rides (ride_id),
    request_id VARCHAR(128) NOT NULL REFERENCES ride_requests (request_id),
    user_id VARCHAR(128) NOT NULL,
    seat_count INTEGER NOT NULL CHECK (seat_count >= 1),
    submitted_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    status VARCHAR(64) NOT NULL DEFAULT 'PENDING',
    idempotency_token VARCHAR(256) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_join_requests_ride ON join_requests (ride_id, status);

-- 6. Seat Holds Table
CREATE TABLE IF NOT EXISTS seat_holds (
    join_request_id VARCHAR(128) PRIMARY KEY,
    ride_id VARCHAR(128) NOT NULL REFERENCES rides (ride_id) ON DELETE CASCADE,
    request_id VARCHAR(128) NOT NULL,
    seat_count INTEGER NOT NULL CHECK (seat_count >= 1),
    submitted_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    idempotency_token VARCHAR(256) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_seat_holds_ride_exp ON seat_holds (ride_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_seat_holds_expiry ON seat_holds (expires_at);

-- 7. Idempotency Records Table
CREATE TABLE IF NOT EXISTS idempotency_records (
    idempotency_token VARCHAR(256) PRIMARY KEY,
    record_type VARCHAR(64) NOT NULL,
    join_request_id VARCHAR(128) NOT NULL,
    request_id VARCHAR(128) NOT NULL,
    ride_id VARCHAR(128) NOT NULL,
    version INTEGER NOT NULL,
    created_at BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_idempotency_ride ON idempotency_records (ride_id);
