"""Persistent PostgreSQL/PostGIS storage adapter implementing RideStorageProvider."""

import os
from pathlib import Path
from typing import Any, Optional, Sequence

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from engine.contracts.storage import (
    IdempotencyRecord,
    RideStorageProvider,
    SeatHold,
    StorageProviderError,
    VersionConflictError,
)
from engine.domain.enums import JoinStatus, RequestStatus, RideStatus, StopStatus, StopType
from engine.domain.models import GeoCoordinate, JoinRequest, Ride, RideRequest, RouteStop, Vehicle
from engine.routing.invariants import check_capacity_profile

_SCHEMA_FILE = Path(__file__).parent / "schema.sql"


class PostgresRideStorage(RideStorageProvider):
    """
    Persistent PostgreSQL & PostGIS implementation of RideStorageProvider.

    Guarantees:
    - Serializable and transactional row locking (SELECT ... FOR UPDATE).
    - Optimistic concurrency control (OCC) matching Ride.version.
    - Idempotency preservation via durable idempotency_records table.
    - Bounding-box spatial queries utilizing PostGIS or spatial coordinates index.
    - Multi-process and multi-container safety through database-level row serialization.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        connection: Optional[Connection[Any]] = None,
    ) -> None:
        self._dsn = dsn or os.environ.get("DATABASE_URL")
        self._external_conn = connection
        self._owned_conn: Optional[Connection[Any]] = None

    def _get_connection(self) -> Connection[Any]:
        if self._external_conn is not None:
            return self._external_conn
        if self._owned_conn is None or self._owned_conn.closed:
            if not self._dsn:
                raise StorageProviderError(
                    "PostgresRideStorage requires a DSN or active psycopg Connection, but none was provided."
                )
            self._owned_conn = psycopg.connect(self._dsn, autocommit=False)
        return self._owned_conn

    def close(self) -> None:
        """Closes the owned database connection if open."""
        if self._owned_conn is not None and not self._owned_conn.closed:
            self._owned_conn.close()

    def create_schema(self) -> None:
        """Executes DDL migrations from schema.sql to initialize tables and indexes."""
        if not _SCHEMA_FILE.exists():
            raise StorageProviderError(f"Schema file not found at {_SCHEMA_FILE}")
        sql = _SCHEMA_FILE.read_text(encoding="utf-8")
        conn = self._get_connection()
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()

    # -------------------------------------------------------------------------
    # Domain Mapping Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _row_to_vehicle(row: dict[str, Any]) -> Vehicle:
        return Vehicle(
            vehicle_id=row["vehicle_id"],
            driver_id=row["driver_id"],
            total_seat_capacity=row["total_seat_capacity"],
            luggage_capacity_units=row["luggage_capacity_units"],
            current_location=GeoCoordinate(
                latitude=row["current_latitude"],
                longitude=row["current_longitude"],
            ),
            is_active=row["is_active"],
        )

    @staticmethod
    def _row_to_route_stop(row: dict[str, Any]) -> RouteStop:
        return RouteStop(
            stop_id=row["stop_id"],
            ride_id=row["ride_id"],
            request_id=row["request_id"],
            stop_type=StopType(row["stop_type"]),
            location=GeoCoordinate(
                latitude=row["latitude"],
                longitude=row["longitude"],
            ),
            passenger_delta=row["passenger_delta"],
            scheduled_arrival_time=row["scheduled_arrival_time"],
            promised_window_start=row["promised_window_start"],
            promised_window_end=row["promised_window_end"],
            actual_arrival_time=row["actual_arrival_time"],
            dwell_duration_seconds=row["dwell_duration_seconds"],
            dwell_start_time=row["dwell_start_time"],
            status=StopStatus(row["status"]),
        )

    @classmethod
    def _row_to_ride(
        cls, ride_row: dict[str, Any], stop_rows: Sequence[dict[str, Any]]
    ) -> Ride:
        stops = tuple(cls._row_to_route_stop(s) for s in stop_rows)
        return Ride(
            ride_id=ride_row["ride_id"],
            vehicle_id=ride_row["vehicle_id"],
            driver_id=ride_row["driver_id"],
            lifecycle_status=RideStatus(ride_row["lifecycle_status"]),
            stops=stops,
            scheduled_departure_time=ride_row["scheduled_departure_time"],
            actual_departure_time=ride_row["actual_departure_time"],
            active_passenger_count=ride_row["active_passenger_count"],
            total_vmt_meters=ride_row["total_vmt_meters"],
            version=ride_row["version"],
        )

    @staticmethod
    def _row_to_request(row: dict[str, Any]) -> RideRequest:
        return RideRequest(
            request_id=row["request_id"],
            user_id=row["user_id"],
            pickup_location=GeoCoordinate(
                latitude=row["pickup_latitude"],
                longitude=row["pickup_longitude"],
            ),
            dropoff_location=GeoCoordinate(
                latitude=row["dropoff_latitude"],
                longitude=row["dropoff_longitude"],
            ),
            seat_count=row["seat_count"],
            earliest_pickup_time=row["earliest_pickup_time"],
            latest_dropoff_time=row["latest_dropoff_time"],
            direct_distance_meters=row["direct_distance_meters"],
            direct_duration_seconds=row["direct_duration_seconds"],
            status=RequestStatus(row["status"]),
            matched_ride_id=row["matched_ride_id"],
        )

    @staticmethod
    def _row_to_join_request(row: dict[str, Any]) -> JoinRequest:
        return JoinRequest(
            join_request_id=row["join_request_id"],
            ride_id=row["ride_id"],
            request_id=row["request_id"],
            user_id=row["user_id"],
            seat_count=row["seat_count"],
            submitted_at=row["submitted_at"],
            expires_at=row["expires_at"],
            status=JoinStatus(row["status"]),
            idempotency_token=row["idempotency_token"],
        )

    @staticmethod
    def _row_to_seat_hold(row: dict[str, Any]) -> SeatHold:
        return SeatHold(
            ride_id=row["ride_id"],
            request_id=row["request_id"],
            join_request_id=row["join_request_id"],
            seat_count=row["seat_count"],
            submitted_at=row["submitted_at"],
            expires_at=row["expires_at"],
            idempotency_token=row["idempotency_token"],
        )

    @staticmethod
    def _row_to_idempotency_record(row: dict[str, Any]) -> IdempotencyRecord:
        return IdempotencyRecord(
            token=row["idempotency_token"],
            record_type=row["record_type"],
            join_request_id=row["join_request_id"],
            request_id=row["request_id"],
            ride_id=row["ride_id"],
            version=row["version"],
            created_at=row["created_at"],
        )

    # -------------------------------------------------------------------------
    # Core Entity CRUD
    # -------------------------------------------------------------------------

    def get_ride(self, ride_id: str) -> Optional[Ride]:
        conn = self._get_connection()
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM rides WHERE ride_id = %s", (ride_id,))
            ride_row = cur.fetchone()
            if ride_row is None:
                return None

            cur.execute(
                "SELECT * FROM route_stops WHERE ride_id = %s ORDER BY stop_order ASC",
                (ride_id,),
            )
            stop_rows = cur.fetchall()
            return self._row_to_ride(ride_row, stop_rows)

    def save_ride(self, ride: Ride) -> None:
        conn = self._get_connection()
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO rides (
                        ride_id, vehicle_id, driver_id, lifecycle_status,
                        scheduled_departure_time, actual_departure_time,
                        active_passenger_count, total_vmt_meters, version, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (ride_id) DO UPDATE SET
                        vehicle_id = EXCLUDED.vehicle_id,
                        driver_id = EXCLUDED.driver_id,
                        lifecycle_status = EXCLUDED.lifecycle_status,
                        scheduled_departure_time = EXCLUDED.scheduled_departure_time,
                        actual_departure_time = EXCLUDED.actual_departure_time,
                        active_passenger_count = EXCLUDED.active_passenger_count,
                        total_vmt_meters = EXCLUDED.total_vmt_meters,
                        version = EXCLUDED.version,
                        updated_at = NOW()
                    """,
                    (
                        ride.ride_id,
                        ride.vehicle_id,
                        ride.driver_id,
                        ride.lifecycle_status.value,
                        ride.scheduled_departure_time,
                        ride.actual_departure_time,
                        ride.active_passenger_count,
                        ride.total_vmt_meters,
                        ride.version,
                    ),
                )

                # Replace route stops atomically
                cur.execute("DELETE FROM route_stops WHERE ride_id = %s", (ride.ride_id,))
                for idx, stop in enumerate(ride.stops):
                    cur.execute(
                        """
                        INSERT INTO route_stops (
                            stop_id, ride_id, stop_order, request_id, stop_type,
                            latitude, longitude, passenger_delta,
                            scheduled_arrival_time, promised_window_start, promised_window_end,
                            actual_arrival_time, dwell_duration_seconds, dwell_start_time, status
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            stop.stop_id,
                            stop.ride_id,
                            idx,
                            stop.request_id,
                            stop.stop_type.value,
                            stop.location.latitude,
                            stop.location.longitude,
                            stop.passenger_delta,
                            stop.scheduled_arrival_time,
                            stop.promised_window_start,
                            stop.promised_window_end,
                            stop.actual_arrival_time,
                            stop.dwell_duration_seconds,
                            stop.dwell_start_time,
                            stop.status.value,
                        ),
                    )

    def get_vehicle(self, vehicle_id: str) -> Optional[Vehicle]:
        conn = self._get_connection()
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM vehicles WHERE vehicle_id = %s", (vehicle_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_vehicle(row)

    def save_vehicle(self, vehicle: Vehicle) -> None:
        conn = self._get_connection()
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO vehicles (
                        vehicle_id, driver_id, total_seat_capacity, luggage_capacity_units,
                        current_latitude, current_longitude, is_active, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (vehicle_id) DO UPDATE SET
                        driver_id = EXCLUDED.driver_id,
                        total_seat_capacity = EXCLUDED.total_seat_capacity,
                        luggage_capacity_units = EXCLUDED.luggage_capacity_units,
                        current_latitude = EXCLUDED.current_latitude,
                        current_longitude = EXCLUDED.current_longitude,
                        is_active = EXCLUDED.is_active,
                        updated_at = NOW()
                    """,
                    (
                        vehicle.vehicle_id,
                        vehicle.driver_id,
                        vehicle.total_seat_capacity,
                        vehicle.luggage_capacity_units,
                        vehicle.current_location.latitude,
                        vehicle.current_location.longitude,
                        vehicle.is_active,
                    ),
                )

    def get_request(self, request_id: str) -> Optional[RideRequest]:
        conn = self._get_connection()
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM ride_requests WHERE request_id = %s", (request_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_request(row)

    def save_request(self, request: RideRequest) -> None:
        conn = self._get_connection()
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ride_requests (
                        request_id, user_id, pickup_latitude, pickup_longitude,
                        dropoff_latitude, dropoff_longitude, seat_count,
                        earliest_pickup_time, latest_dropoff_time,
                        direct_distance_meters, direct_duration_seconds,
                        status, matched_ride_id, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (request_id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        pickup_latitude = EXCLUDED.pickup_latitude,
                        pickup_longitude = EXCLUDED.pickup_longitude,
                        dropoff_latitude = EXCLUDED.dropoff_latitude,
                        dropoff_longitude = EXCLUDED.dropoff_longitude,
                        seat_count = EXCLUDED.seat_count,
                        earliest_pickup_time = EXCLUDED.earliest_pickup_time,
                        latest_dropoff_time = EXCLUDED.latest_dropoff_time,
                        direct_distance_meters = EXCLUDED.direct_distance_meters,
                        direct_duration_seconds = EXCLUDED.direct_duration_seconds,
                        status = EXCLUDED.status,
                        matched_ride_id = EXCLUDED.matched_ride_id,
                        updated_at = NOW()
                    """,
                    (
                        request.request_id,
                        request.user_id,
                        request.pickup_location.latitude,
                        request.pickup_location.longitude,
                        request.dropoff_location.latitude,
                        request.dropoff_location.longitude,
                        request.seat_count,
                        request.earliest_pickup_time,
                        request.latest_dropoff_time,
                        request.direct_distance_meters,
                        request.direct_duration_seconds,
                        request.status.value,
                        request.matched_ride_id,
                    ),
                )

    def get_join_request(self, join_request_id: str) -> Optional[JoinRequest]:
        conn = self._get_connection()
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM join_requests WHERE join_request_id = %s", (join_request_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_join_request(row)

    def save_join_request(self, join_request: JoinRequest) -> None:
        conn = self._get_connection()
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO join_requests (
                        join_request_id, ride_id, request_id, user_id,
                        seat_count, submitted_at, expires_at, status, idempotency_token, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (join_request_id) DO UPDATE SET
                        ride_id = EXCLUDED.ride_id,
                        request_id = EXCLUDED.request_id,
                        user_id = EXCLUDED.user_id,
                        seat_count = EXCLUDED.seat_count,
                        submitted_at = EXCLUDED.submitted_at,
                        expires_at = EXCLUDED.expires_at,
                        status = EXCLUDED.status,
                        idempotency_token = EXCLUDED.idempotency_token,
                        updated_at = NOW()
                    """,
                    (
                        join_request.join_request_id,
                        join_request.ride_id,
                        join_request.request_id,
                        join_request.user_id,
                        join_request.seat_count,
                        join_request.submitted_at,
                        join_request.expires_at,
                        join_request.status.value,
                        join_request.idempotency_token,
                    ),
                )

    # -------------------------------------------------------------------------
    # Spatial Bounding Box Search
    # -------------------------------------------------------------------------

    def get_active_rides_in_bounding_box(
        self,
        min_lat: float,
        min_lon: float,
        max_lat: float,
        max_lon: float,
    ) -> Sequence[Ride]:
        conn = self._get_connection()
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT DISTINCT r.ride_id
                FROM rides r
                JOIN vehicles v ON r.vehicle_id = v.vehicle_id
                LEFT JOIN route_stops s ON r.ride_id = s.ride_id
                WHERE r.lifecycle_status IN (%s, %s)
                  AND (
                    (v.current_latitude BETWEEN %s AND %s AND v.current_longitude BETWEEN %s AND %s)
                    OR
                    (s.latitude BETWEEN %s AND %s AND s.longitude BETWEEN %s AND %s)
                  )
                ORDER BY r.ride_id
                """,
                (
                    RideStatus.SCHEDULED.value,
                    RideStatus.ACTIVE.value,
                    min_lat,
                    max_lat,
                    min_lon,
                    max_lon,
                    min_lat,
                    max_lat,
                    min_lon,
                    max_lon,
                ),
            )
            ride_ids = [row["ride_id"] for row in cur.fetchall()]

        rides: list[Ride] = []
        for r_id in ride_ids:
            r = self.get_ride(r_id)
            if r is not None:
                rides.append(r)
        return rides

    # -------------------------------------------------------------------------
    # Transactional Concurrency Control & Seat Holds
    # -------------------------------------------------------------------------

    def acquire_seat_hold_atomic(
        self,
        ride_id: str,
        request_id: str,
        join_request_id: str,
        seat_count: int,
        submitted_at: int,
        expires_at: int,
        expected_version: int,
        idempotency_token: str,
    ) -> bool:
        conn = self._get_connection()
        with conn.transaction():
            with conn.cursor(row_factory=dict_row) as cur:
                # 1. Replay Safety: check if token already recorded
                cur.execute(
                    "SELECT * FROM idempotency_records WHERE idempotency_token = %s",
                    (idempotency_token,),
                )
                rec = cur.fetchone()
                if rec is not None:
                    if (
                        rec["join_request_id"] == join_request_id
                        and rec["request_id"] == request_id
                        and rec["ride_id"] == ride_id
                    ):
                        cur.execute(
                            "SELECT * FROM seat_holds WHERE join_request_id = %s",
                            (join_request_id,),
                        )
                        hold = cur.fetchone()
                        if hold is not None:
                            if submitted_at <= hold["expires_at"]:
                                return True
                            else:
                                cur.execute(
                                    "DELETE FROM seat_holds WHERE join_request_id = %s",
                                    (join_request_id,),
                                )
                                return False
                        return False
                    return False

                # 2. Lock Ride Row (SELECT ... FOR UPDATE) and verify OCC version
                cur.execute(
                    """
                    SELECT version, vehicle_id, active_passenger_count, lifecycle_status
                    FROM rides
                    WHERE ride_id = %s
                    FOR UPDATE
                    """,
                    (ride_id,),
                )
                ride_row = cur.fetchone()
                if ride_row is None:
                    return False

                if ride_row["version"] != expected_version:
                    return False

                # 3. Read Vehicle Capacity
                cur.execute(
                    "SELECT total_seat_capacity FROM vehicles WHERE vehicle_id = %s",
                    (ride_row["vehicle_id"],),
                )
                veh_row = cur.fetchone()
                capacity = veh_row["total_seat_capacity"] if veh_row else 4

                # 4. Compute Current Peak Occupancy across route stops
                cur.execute(
                    """
                    SELECT passenger_delta FROM route_stops
                    WHERE ride_id = %s
                    ORDER BY stop_order ASC
                    """,
                    (ride_id,),
                )
                stop_rows = cur.fetchall()
                current_occ = ride_row["active_passenger_count"]
                peak_occ = current_occ
                for s in stop_rows:
                    current_occ += s["passenger_delta"]
                    if current_occ > peak_occ:
                        peak_occ = current_occ

                # 5. Lock and Sum Active Seat Holds for this Ride
                cur.execute(
                    """
                    SELECT join_request_id, seat_count, expires_at
                    FROM seat_holds
                    WHERE ride_id = %s
                    FOR UPDATE
                    """,
                    (ride_id,),
                )
                existing_holds = cur.fetchall()
                active_held_seats = 0
                for h in existing_holds:
                    if h["join_request_id"] != join_request_id:
                        if submitted_at <= h["expires_at"]:
                            active_held_seats += h["seat_count"]
                        else:
                            # Auto-clean expired hold observed during transaction
                            cur.execute(
                                "DELETE FROM seat_holds WHERE join_request_id = %s",
                                (h["join_request_id"],),
                            )

                # 6. Strict Capacity Check
                if peak_occ + active_held_seats + seat_count > capacity:
                    return False

                # 7. Persist Hold
                cur.execute(
                    """
                    INSERT INTO seat_holds (
                        join_request_id, ride_id, request_id, seat_count,
                        submitted_at, expires_at, idempotency_token
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (join_request_id) DO UPDATE SET
                        seat_count = EXCLUDED.seat_count,
                        submitted_at = EXCLUDED.submitted_at,
                        expires_at = EXCLUDED.expires_at,
                        idempotency_token = EXCLUDED.idempotency_token
                    """,
                    (
                        join_request_id,
                        ride_id,
                        request_id,
                        seat_count,
                        submitted_at,
                        expires_at,
                        idempotency_token,
                    ),
                )

                # 8. Increment Ride Version on Mutation
                new_version = ride_row["version"] + 1
                cur.execute(
                    "UPDATE rides SET version = %s, updated_at = NOW() WHERE ride_id = %s",
                    (new_version, ride_id),
                )

                # 9. Record Idempotency Record
                cur.execute(
                    """
                    INSERT INTO idempotency_records (
                        idempotency_token, record_type, join_request_id,
                        request_id, ride_id, version, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (idempotency_token) DO UPDATE SET
                        record_type = EXCLUDED.record_type,
                        version = EXCLUDED.version
                    """,
                    (
                        idempotency_token,
                        "hold",
                        join_request_id,
                        request_id,
                        ride_id,
                        new_version,
                        submitted_at,
                    ),
                )
                return True

    def reserve_seats_atomic(
        self,
        ride_id: str,
        request_id: str,
        join_request_id: str,
        seat_count: int,
        expected_version: int,
        idempotency_token: str,
        new_stops: Optional[Sequence[RouteStop]] = None,
        current_time: Optional[int] = None,
    ) -> bool:
        conn = self._get_connection()
        with conn.transaction():
            with conn.cursor(row_factory=dict_row) as cur:
                # 1. Idempotency Check
                cur.execute(
                    "SELECT * FROM idempotency_records WHERE idempotency_token = %s",
                    (idempotency_token,),
                )
                rec = cur.fetchone()
                if rec is not None:
                    if rec["record_type"] == "reservation":
                        if (
                            rec["join_request_id"] == join_request_id
                            and rec["request_id"] == request_id
                            and rec["ride_id"] == ride_id
                        ):
                            return True
                        return False
                    elif (
                        rec["join_request_id"] != join_request_id
                        or rec["request_id"] != request_id
                        or rec["ride_id"] != ride_id
                    ):
                        return False

                # 2. Lock Ride Row and verify OCC version
                cur.execute(
                    """
                    SELECT version, vehicle_id, active_passenger_count, lifecycle_status
                    FROM rides
                    WHERE ride_id = %s
                    FOR UPDATE
                    """,
                    (ride_id,),
                )
                ride_row = cur.fetchone()
                if ride_row is None:
                    return False
                if ride_row["version"] != expected_version:
                    return False

                # 3. Check and Lock Seat Hold
                cur.execute(
                    """
                    SELECT seat_count, submitted_at, expires_at
                    FROM seat_holds
                    WHERE join_request_id = %s
                    FOR UPDATE
                    """,
                    (join_request_id,),
                )
                hold_row = cur.fetchone()
                if hold_row is None:
                    return False

                now = current_time if current_time is not None else hold_row["submitted_at"]
                if now > hold_row["expires_at"]:
                    cur.execute(
                        "DELETE FROM seat_holds WHERE join_request_id = %s",
                        (join_request_id,),
                    )
                    return False

                # 4. Double Revalidation of Capacity
                cur.execute(
                    "SELECT total_seat_capacity FROM vehicles WHERE vehicle_id = %s",
                    (ride_row["vehicle_id"],),
                )
                veh_row = cur.fetchone()
                capacity = veh_row["total_seat_capacity"] if veh_row else 4

                if new_stops is not None:
                    if not check_capacity_profile(
                        new_stops, capacity, ride_row["active_passenger_count"]
                    ):
                        cur.execute(
                            "DELETE FROM seat_holds WHERE join_request_id = %s",
                            (join_request_id,),
                        )
                        return False
                else:
                    cur.execute(
                        """
                        SELECT passenger_delta FROM route_stops
                        WHERE ride_id = %s
                        ORDER BY stop_order ASC
                        """,
                        (ride_id,),
                    )
                    curr_occ = ride_row["active_passenger_count"]
                    peak_occ = curr_occ
                    for stop_item in cur.fetchall():
                        curr_occ += stop_item["passenger_delta"]
                        if curr_occ > peak_occ:
                            peak_occ = curr_occ
                    if peak_occ + seat_count > capacity:
                        cur.execute(
                            "DELETE FROM seat_holds WHERE join_request_id = %s",
                            (join_request_id,),
                        )
                        return False

                # 5. Atomic Promotion: remove hold, update stops, increment version
                cur.execute("DELETE FROM seat_holds WHERE join_request_id = %s", (join_request_id,))

                if new_stops is not None:
                    cur.execute("DELETE FROM route_stops WHERE ride_id = %s", (ride_id,))
                    for idx, route_stop in enumerate(new_stops):
                        cur.execute(
                            """
                            INSERT INTO route_stops (
                                stop_id, ride_id, stop_order, request_id, stop_type,
                                latitude, longitude, passenger_delta,
                                scheduled_arrival_time, promised_window_start, promised_window_end,
                                actual_arrival_time, dwell_duration_seconds, dwell_start_time, status
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                route_stop.stop_id,
                                route_stop.ride_id,
                                idx,
                                route_stop.request_id,
                                route_stop.stop_type.value,
                                route_stop.location.latitude,
                                route_stop.location.longitude,
                                route_stop.passenger_delta,
                                route_stop.scheduled_arrival_time,
                                route_stop.promised_window_start,
                                route_stop.promised_window_end,
                                route_stop.actual_arrival_time,
                                route_stop.dwell_duration_seconds,
                                route_stop.dwell_start_time,
                                route_stop.status.value,
                            ),
                        )

                new_version = ride_row["version"] + 1
                cur.execute(
                    "UPDATE rides SET version = %s, updated_at = NOW() WHERE ride_id = %s",
                    (new_version, ride_id),
                )

                # 6. Record Reservation Idempotency Token
                cur.execute(
                    """
                    INSERT INTO idempotency_records (
                        idempotency_token, record_type, join_request_id,
                        request_id, ride_id, version, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (idempotency_token) DO UPDATE SET
                        record_type = EXCLUDED.record_type,
                        version = EXCLUDED.version
                    """,
                    (
                        idempotency_token,
                        "reservation",
                        join_request_id,
                        request_id,
                        ride_id,
                        new_version,
                        now,
                    ),
                )
                return True

    def release_seats_atomic(
        self,
        ride_id: str,
        join_request_id: str,
        request_id: Optional[str] = None,
        seat_count: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> bool:
        conn = self._get_connection()
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM seat_holds WHERE join_request_id = %s",
                    (join_request_id,),
                )
                return cur.rowcount > 0

    def get_active_seat_holds(
        self,
        ride_id: str,
        current_time: Optional[int] = None,
    ) -> Sequence[SeatHold]:
        conn = self._get_connection()
        with conn.cursor(row_factory=dict_row) as cur:
            if current_time is not None:
                cur.execute(
                    """
                    SELECT * FROM seat_holds
                    WHERE ride_id = %s AND %s <= expires_at
                    ORDER BY submitted_at ASC
                    """,
                    (ride_id, current_time),
                )
            else:
                cur.execute(
                    "SELECT * FROM seat_holds WHERE ride_id = %s ORDER BY submitted_at ASC",
                    (ride_id,),
                )
            return [self._row_to_seat_hold(row) for row in cur.fetchall()]

    def sweep_expired_holds(self, current_time: int) -> Sequence[str]:
        conn = self._get_connection()
        with conn.transaction():
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT join_request_id FROM seat_holds
                    WHERE %s > expires_at
                    FOR UPDATE
                    """,
                    (current_time,),
                )
                expired_ids = [row["join_request_id"] for row in cur.fetchall()]
                if expired_ids:
                    cur.execute(
                        "DELETE FROM seat_holds WHERE %s > expires_at",
                        (current_time,),
                    )
                return expired_ids

    def get_idempotency_record(self, idempotency_token: str) -> Optional[IdempotencyRecord]:
        conn = self._get_connection()
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM idempotency_records WHERE idempotency_token = %s",
                (idempotency_token,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_idempotency_record(row)
