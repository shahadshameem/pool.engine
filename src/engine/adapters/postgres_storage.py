"""Persistent PostgreSQL/PostGIS storage adapter implementing RideStorageProvider."""

import os
from pathlib import Path
import time
from typing import Any, Optional, Sequence

from collections.abc import Generator
from contextlib import contextmanager

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
import psycopg_pool
from psycopg_pool import ConnectionPool, PoolTimeout

from engine.contracts.storage import (
    AssignmentCommitResult,
    CancellationCommitResult,
    IdempotencyRecord,
    RideStorageProvider,
    SeatHold,
    StorageProviderError,
    VersionConflictError,
)
from engine.domain.candidate import CandidateAssignment
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
        min_size: int = 2,
        max_size: int = 10,
        timeout: float = 5.0,
        max_idle: float = 300.0,
        check_connection: bool = True,
    ) -> None:
        self._dsn = dsn or os.environ.get("DATABASE_URL")
        self._external_conn = connection
        self._direct_conn: Optional[Connection[Any]] = None
        self._pool: Optional[ConnectionPool] = None

        # Bounded pool configurations with environment variable overrides
        self._min_size = int(os.environ.get("PG_POOL_MIN_SIZE", min_size))
        self._max_size = int(os.environ.get("PG_POOL_MAX_SIZE", max_size))
        self._timeout = float(os.environ.get("PG_POOL_TIMEOUT", timeout))
        self._max_idle = float(os.environ.get("PG_POOL_MAX_IDLE", max_idle))
        self._check_connection = check_connection

    def open(self) -> None:
        """
        Pre-warms and initializes the owned connection pool.
        Idempotent; no-op if using an external connection or if pool is already open.
        """
        if self._external_conn is not None:
            return
        self._get_pool()

    def _get_pool(self) -> ConnectionPool:
        """Returns the active bounded ConnectionPool, opening it lazily if necessary."""
        if self._external_conn is not None:
            raise StorageProviderError("Cannot open connection pool when an external connection is injected.")
        if not self._dsn:
            raise StorageProviderError(
                "PostgresRideStorage requires a DSN or active psycopg Connection, but none was provided."
            )
        if self._pool is None or self._pool.closed:
            check_fn = ConnectionPool.check_connection if self._check_connection else None
            try:
                self._pool = ConnectionPool(
                    conninfo=self._dsn,
                    min_size=self._min_size,
                    max_size=self._max_size,
                    timeout=self._timeout,
                    max_idle=self._max_idle,
                    check=check_fn,
                    kwargs={"autocommit": True},
                    open=True,
                )
            except Exception as exc:
                raise StorageProviderError(
                    f"Failed to initialize PostgreSQL connection pool: {exc}"
                ) from exc
        return self._pool

    @contextmanager
    def connection(self) -> Generator[Connection[Any], None, None]:
        """
        Context manager acquiring and returning a database connection.
        If an external connection was injected, yields that connection without checkout or closing.
        Otherwise, checks out a connection from the bounded ConnectionPool and returns it safely.
        """
        if self._external_conn is not None:
            yield self._external_conn
            return

        pool = self._get_pool()
        try:
            with pool.connection(timeout=self._timeout) as conn:
                yield conn
        except PoolTimeout as exc:
            raise StorageProviderError(
                f"Database connection pool exhausted (timeout={self._timeout}s): {exc}"
            ) from exc

    def _get_connection(self) -> Connection[Any]:
        """
        Direct connection accessor retained for backward compatibility with integration test fixtures.
        Production and repository operations MUST use the `with self.connection() as conn:` context manager.
        """
        if self._external_conn is not None:
            return self._external_conn
        if not self._dsn:
            raise StorageProviderError(
                "PostgresRideStorage requires a DSN or active psycopg Connection, but none was provided."
            )
        if self._direct_conn is None or self._direct_conn.closed or self._direct_conn.broken:
            if self._direct_conn is not None:
                try:
                    self._direct_conn.close()
                except Exception:
                    pass
            self._direct_conn = psycopg.connect(self._dsn, autocommit=True)
        return self._direct_conn

    def close(self) -> None:
        """
        Closes the owned database connection pool and direct connection if open.
        Never closes externally injected connections.
        """
        if self._direct_conn is not None and not self._direct_conn.closed:
            try:
                self._direct_conn.close()
            except Exception:
                pass
            self._direct_conn = None

        if self._pool is not None and not self._pool.closed:
            try:
                self._pool.close()
            except Exception:
                pass
            self._pool = None

    def get_pool_stats(self) -> Optional[dict[str, Any]]:
        """Returns statistics from the underlying ConnectionPool if active."""
        if self._pool is not None and not self._pool.closed:
            return self._pool.get_stats()
        return None

    def init_db(self) -> None:
        """Alias for create_schema() initializing all tables, constraints, and indexes."""
        self.create_schema()

    def create_schema(self) -> None:
        """Executes DDL migrations from schema.sql to initialize tables and indexes."""
        if not _SCHEMA_FILE.exists():
            raise StorageProviderError(f"Schema file not found at {_SCHEMA_FILE}")
        sql = _SCHEMA_FILE.read_text(encoding="utf-8")
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
            if not conn.autocommit:
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
        origin_loc = None
        if ride_row.get("origin_latitude") is not None and ride_row.get("origin_longitude") is not None:
            origin_loc = GeoCoordinate(latitude=ride_row["origin_latitude"], longitude=ride_row["origin_longitude"])
        dest_loc = None
        if ride_row.get("destination_latitude") is not None and ride_row.get("destination_longitude") is not None:
            dest_loc = GeoCoordinate(latitude=ride_row["destination_latitude"], longitude=ride_row["destination_longitude"])
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
            origin_location=origin_loc,
            destination_location=dest_loc,
            max_detour_seconds=ride_row.get("max_detour_seconds"),
            direct_duration_seconds=ride_row.get("direct_duration_seconds"),
            direct_distance_meters=ride_row.get("direct_distance_meters"),
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
            host_accepted=bool(row.get("host_accepted", False)),
            traveller_accepted=bool(row.get("traveller_accepted", False)),
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

    def _get_ride_with_conn(self, ride_id: str, conn: Connection[Any]) -> Optional[Ride]:
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

    def get_ride(self, ride_id: str, conn: Optional[Connection[Any]] = None) -> Optional[Ride]:
        if conn is not None:
            return self._get_ride_with_conn(ride_id, conn)
        with self.connection() as c:
            return self._get_ride_with_conn(ride_id, c)

    def save_ride(self, ride: Ride) -> None:
        with self.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO rides (
                            ride_id, vehicle_id, driver_id, lifecycle_status,
                            scheduled_departure_time, actual_departure_time,
                            active_passenger_count, total_vmt_meters, version,
                            origin_latitude, origin_longitude,
                            destination_latitude, destination_longitude,
                            max_detour_seconds, direct_duration_seconds, direct_distance_meters,
                            updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (ride_id) DO UPDATE SET
                            vehicle_id = EXCLUDED.vehicle_id,
                            driver_id = EXCLUDED.driver_id,
                            lifecycle_status = EXCLUDED.lifecycle_status,
                            scheduled_departure_time = EXCLUDED.scheduled_departure_time,
                            actual_departure_time = EXCLUDED.actual_departure_time,
                            active_passenger_count = EXCLUDED.active_passenger_count,
                            total_vmt_meters = EXCLUDED.total_vmt_meters,
                            version = EXCLUDED.version,
                            origin_latitude = EXCLUDED.origin_latitude,
                            origin_longitude = EXCLUDED.origin_longitude,
                            destination_latitude = EXCLUDED.destination_latitude,
                            destination_longitude = EXCLUDED.destination_longitude,
                            max_detour_seconds = EXCLUDED.max_detour_seconds,
                            direct_duration_seconds = EXCLUDED.direct_duration_seconds,
                            direct_distance_meters = EXCLUDED.direct_distance_meters,
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
                            ride.origin_location.latitude if ride.origin_location else None,
                            ride.origin_location.longitude if ride.origin_location else None,
                            ride.destination_location.latitude if ride.destination_location else None,
                            ride.destination_location.longitude if ride.destination_location else None,
                            ride.max_detour_seconds,
                            ride.direct_duration_seconds,
                            ride.direct_distance_meters,
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
        with self.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM vehicles WHERE vehicle_id = %s", (vehicle_id,))
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_vehicle(row)

    def save_vehicle(self, vehicle: Vehicle) -> None:
        with self.connection() as conn:
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

    def _get_request_with_conn(self, request_id: str, conn: Connection[Any]) -> Optional[RideRequest]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM ride_requests WHERE request_id = %s", (request_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_request(row)

    def get_request(self, request_id: str, conn: Optional[Connection[Any]] = None) -> Optional[RideRequest]:
        if conn is not None:
            return self._get_request_with_conn(request_id, conn)
        with self.connection() as c:
            return self._get_request_with_conn(request_id, c)

    def save_request(self, request: RideRequest) -> None:
        with self.connection() as conn:
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
        with self.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM join_requests WHERE join_request_id = %s", (join_request_id,))
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_join_request(row)

    def save_join_request(self, join_request: JoinRequest) -> None:
        with self.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO join_requests (
                            join_request_id, ride_id, request_id, user_id,
                            seat_count, submitted_at, expires_at, status, idempotency_token,
                            host_accepted, traveller_accepted, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (join_request_id) DO UPDATE SET
                            ride_id = EXCLUDED.ride_id,
                            request_id = EXCLUDED.request_id,
                            user_id = EXCLUDED.user_id,
                            seat_count = EXCLUDED.seat_count,
                            submitted_at = EXCLUDED.submitted_at,
                            expires_at = EXCLUDED.expires_at,
                            status = EXCLUDED.status,
                            idempotency_token = EXCLUDED.idempotency_token,
                            host_accepted = join_requests.host_accepted OR EXCLUDED.host_accepted,
                            traveller_accepted = join_requests.traveller_accepted OR EXCLUDED.traveller_accepted,
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
                            join_request.host_accepted,
                            join_request.traveller_accepted,
                        ),
                    )

    def record_proposal_acceptance(
        self,
        join_request_id: str,
        is_host: bool,
        is_traveller: bool,
    ) -> Optional[tuple[bool, bool]]:
        with self.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE join_requests
                        SET host_accepted = join_requests.host_accepted OR %s,
                            traveller_accepted = join_requests.traveller_accepted OR %s,
                            updated_at = NOW()
                        WHERE join_request_id = %s
                        RETURNING host_accepted, traveller_accepted;
                        """,
                        (is_host, is_traveller, join_request_id),
                    )
                    row = cur.fetchone()
                    if row is None:
                        return None
                    return bool(row[0]), bool(row[1])

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
        with self.connection() as conn:
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
                r = self._get_ride_with_conn(r_id, conn)
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
        with self.connection() as conn:
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
        with self.connection() as conn:
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
        with self.connection() as conn:
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
        with self.connection() as conn:
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
        with self.connection() as conn:
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
        with self.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM idempotency_records WHERE idempotency_token = %s",
                    (idempotency_token,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_idempotency_record(row)

    def get_pending_requests(self, limit: Optional[int] = None) -> Sequence[RideRequest]:
        with self.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                if limit is not None:
                    cur.execute(
                        "SELECT * FROM ride_requests WHERE status = %s ORDER BY earliest_pickup_time ASC LIMIT %s",
                        (RequestStatus.PENDING.value, limit),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM ride_requests WHERE status = %s ORDER BY earliest_pickup_time ASC",
                        (RequestStatus.PENDING.value,),
                    )
                return [self._row_to_request(row) for row in cur.fetchall()]

    def get_active_vehicles(self, limit: Optional[int] = None) -> Sequence[Vehicle]:
        with self.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                if limit is not None:
                    cur.execute(
                        "SELECT * FROM vehicles WHERE is_active = TRUE ORDER BY vehicle_id ASC LIMIT %s",
                        (limit,),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM vehicles WHERE is_active = TRUE ORDER BY vehicle_id ASC"
                    )
                return [self._row_to_vehicle(row) for row in cur.fetchall()]

    def get_active_rides(self, limit: Optional[int] = None) -> Sequence[Ride]:
        with self.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                if limit is not None:
                    cur.execute(
                        """
                        SELECT ride_id FROM rides
                        WHERE lifecycle_status IN (%s, %s)
                        ORDER BY scheduled_departure_time ASC
                        LIMIT %s
                        """,
                        (RideStatus.SCHEDULED.value, RideStatus.ACTIVE.value, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT ride_id FROM rides
                        WHERE lifecycle_status IN (%s, %s)
                        ORDER BY scheduled_departure_time ASC
                        """,
                        (RideStatus.SCHEDULED.value, RideStatus.ACTIVE.value),
                    )
                ride_ids = [row["ride_id"] for row in cur.fetchall()]

            rides: list[Ride] = []
            for r_id in ride_ids:
                r = self._get_ride_with_conn(r_id, conn)
                if r is not None:
                    rides.append(r)
            return rides

    def commit_dispatch_assignment_atomic(
        self,
        assignment: CandidateAssignment,
        idempotency_token: str,
        current_time: int,
        expected_ride_version: Optional[int] = None,
        new_ride_id: Optional[str] = None,
    ) -> AssignmentCommitResult:
        with self.connection() as conn:
            with conn.transaction():
                with conn.cursor(row_factory=dict_row) as cur:
                    # 1. Idempotency Check
                    cur.execute(
                        "SELECT * FROM idempotency_records WHERE idempotency_token = %s FOR UPDATE",
                        (idempotency_token,),
                    )
                    rec = cur.fetchone()
                    if rec is not None:
                        if rec["record_type"] == "dispatch_assignment":
                            if rec["join_request_id"] == assignment.candidate_id:
                                committed_ride = self._get_ride_with_conn(rec["ride_id"], conn)
                                return AssignmentCommitResult(
                                    success=True,
                                    candidate_id=assignment.candidate_id,
                                    ride_id=rec["ride_id"],
                                    ride=committed_ride,
                                    committed_request_ids=assignment.request_ids,
                                )
                            return AssignmentCommitResult(
                                success=False,
                                candidate_id=assignment.candidate_id,
                                rejection_reason="IDEMPOTENCY_CONFLICT",
                            )
                        return AssignmentCommitResult(
                            success=False,
                            candidate_id=assignment.candidate_id,
                            rejection_reason="IDEMPOTENCY_CONFLICT",
                        )

                    # 2. Check and lock vehicle
                    cur.execute(
                        "SELECT * FROM vehicles WHERE vehicle_id = %s FOR UPDATE",
                        (assignment.vehicle_id,),
                    )
                    veh_row = cur.fetchone()
                    if veh_row is None or not veh_row["is_active"]:
                        return AssignmentCommitResult(
                            success=False,
                            candidate_id=assignment.candidate_id,
                            rejection_reason="VEHICLE_NOT_AVAILABLE",
                        )
                    vehicle_capacity = veh_row["total_seat_capacity"]
                    driver_id = veh_row["driver_id"]

                    # 3. Case A: New Ride (idle vehicle)
                    if assignment.existing_ride_id is None:
                        cur.execute(
                            """
                            SELECT ride_id FROM rides
                            WHERE vehicle_id = %s AND lifecycle_status IN (%s, %s)
                            FOR UPDATE
                            """,
                            (assignment.vehicle_id, RideStatus.SCHEDULED.value, RideStatus.ACTIVE.value),
                        )
                        if cur.fetchone() is not None:
                            return AssignmentCommitResult(
                                success=False,
                                candidate_id=assignment.candidate_id,
                                rejection_reason="VEHICLE_BUSY",
                            )

                        # Lock and verify all requests are PENDING
                        if not assignment.request_ids:
                            return AssignmentCommitResult(
                                success=False,
                                candidate_id=assignment.candidate_id,
                                rejection_reason="NO_REQUESTS",
                            )
                        cur.execute(
                            "SELECT request_id, status FROM ride_requests WHERE request_id = ANY(%s) FOR UPDATE",
                            (list(assignment.request_ids),),
                        )
                        rows = cur.fetchall()
                        if len(rows) != len(assignment.request_ids) or any(
                            r["status"] != RequestStatus.PENDING.value for r in rows
                        ):
                            return AssignmentCommitResult(
                                success=False,
                                candidate_id=assignment.candidate_id,
                                rejection_reason="REQUEST_NOT_PENDING",
                            )

                        # Check capacity profile
                        if not check_capacity_profile(assignment.ordered_stops, vehicle_capacity, 0):
                            return AssignmentCommitResult(
                                success=False,
                                candidate_id=assignment.candidate_id,
                                rejection_reason="CAPACITY_EXCEEDED",
                            )

                        effective_ride_id = new_ride_id or f"ride-{assignment.candidate_id}"
                        dep_time = (
                            assignment.ordered_stops[0].scheduled_arrival_time
                            if assignment.ordered_stops
                            else current_time
                        )

                        # Insert new ride
                        cur.execute(
                            """
                            INSERT INTO rides (
                                ride_id, vehicle_id, driver_id, lifecycle_status,
                                scheduled_departure_time, active_passenger_count, total_vmt_meters, version
                            ) VALUES (%s, %s, %s, %s, %s, 0, %s, 1)
                            """,
                            (
                                effective_ride_id,
                                assignment.vehicle_id,
                                driver_id,
                                RideStatus.SCHEDULED.value,
                                dep_time,
                                assignment.vmt_meters,
                            ),
                        )

                        # Insert route stops
                        for idx, stop in enumerate(assignment.ordered_stops):
                            cur.execute(
                                """
                                INSERT INTO route_stops (
                                    stop_id, ride_id, stop_order, request_id, stop_type,
                                    latitude, longitude, passenger_delta, scheduled_arrival_time,
                                    promised_window_start, promised_window_end, dwell_duration_seconds, status
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    stop.stop_id,
                                    effective_ride_id,
                                    idx,
                                    stop.request_id,
                                    stop.stop_type.value,
                                    stop.location.latitude,
                                    stop.location.longitude,
                                    stop.passenger_delta,
                                    stop.scheduled_arrival_time,
                                    stop.promised_window_start,
                                    stop.promised_window_end,
                                    stop.dwell_duration_seconds,
                                    stop.status.value,
                                ),
                            )

                        # Update ride requests
                        cur.execute(
                            """
                            UPDATE ride_requests
                            SET status = %s, matched_ride_id = %s, updated_at = NOW()
                            WHERE request_id = ANY(%s)
                            """,
                            (RequestStatus.MATCHED.value, effective_ride_id, list(assignment.request_ids)),
                        )

                        # Insert idempotency record
                        cur.execute(
                            """
                            INSERT INTO idempotency_records (
                                idempotency_token, record_type, join_request_id, request_id, ride_id, version, created_at
                            ) VALUES (%s, 'dispatch_assignment', %s, %s, %s, 1, %s)
                            """,
                            (
                                idempotency_token,
                                assignment.candidate_id,
                                assignment.request_ids[0],
                                effective_ride_id,
                                current_time,
                            ),
                        )

                        new_ride = self._get_ride_with_conn(effective_ride_id, conn)
                        return AssignmentCommitResult(
                            success=True,
                            candidate_id=assignment.candidate_id,
                            ride_id=effective_ride_id,
                            ride=new_ride,
                            committed_request_ids=assignment.request_ids,
                        )

                    # 4. Case B: Active Ride Insertion
                    cur.execute(
                        """
                        SELECT version, active_passenger_count, lifecycle_status
                        FROM rides
                        WHERE ride_id = %s
                        FOR UPDATE
                        """,
                        (assignment.existing_ride_id,),
                    )
                    ride_row = cur.fetchone()
                    if ride_row is None or ride_row["lifecycle_status"] not in (
                        RideStatus.SCHEDULED.value,
                        RideStatus.ACTIVE.value,
                    ):
                        return AssignmentCommitResult(
                            success=False,
                            candidate_id=assignment.candidate_id,
                            rejection_reason="RIDE_NOT_ACTIVE",
                        )

                    if expected_ride_version is not None and ride_row["version"] != expected_ride_version:
                        return AssignmentCommitResult(
                            success=False,
                            candidate_id=assignment.candidate_id,
                            rejection_reason="VERSION_CONFLICT",
                        )

                    # Check capacity profile
                    if not check_capacity_profile(
                        assignment.ordered_stops, vehicle_capacity, ride_row["active_passenger_count"]
                    ):
                        return AssignmentCommitResult(
                            success=False,
                            candidate_id=assignment.candidate_id,
                            rejection_reason="CAPACITY_EXCEEDED",
                        )

                    # Determine newly added requests
                    cur.execute(
                        "SELECT DISTINCT request_id FROM route_stops WHERE ride_id = %s",
                        (assignment.existing_ride_id,),
                    )
                    existing_req_ids = {r["request_id"] for r in cur.fetchall()}
                    if not assignment.request_ids or any(r_id in existing_req_ids for r_id in assignment.request_ids):
                        return AssignmentCommitResult(
                            success=False,
                            candidate_id=assignment.candidate_id,
                            rejection_reason="REQUEST_NOT_PENDING",
                        )

                    cur.execute(
                        "SELECT request_id, status FROM ride_requests WHERE request_id = ANY(%s) FOR UPDATE",
                        (list(assignment.request_ids),),
                    )
                    rows = cur.fetchall()
                    if len(rows) != len(assignment.request_ids) or any(
                        r["status"] != RequestStatus.PENDING.value for r in rows
                    ):
                        return AssignmentCommitResult(
                            success=False,
                            candidate_id=assignment.candidate_id,
                            rejection_reason="REQUEST_NOT_PENDING",
                        )

                    # Replace route stops
                    cur.execute("DELETE FROM route_stops WHERE ride_id = %s", (assignment.existing_ride_id,))
                    for idx, stop in enumerate(assignment.ordered_stops):
                        cur.execute(
                            """
                            INSERT INTO route_stops (
                                stop_id, ride_id, stop_order, request_id, stop_type,
                                latitude, longitude, passenger_delta, scheduled_arrival_time,
                                promised_window_start, promised_window_end, dwell_duration_seconds, status
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                stop.stop_id,
                                assignment.existing_ride_id,
                                idx,
                                stop.request_id,
                                stop.stop_type.value,
                                stop.location.latitude,
                                stop.location.longitude,
                                stop.passenger_delta,
                                stop.scheduled_arrival_time,
                                stop.promised_window_start,
                                stop.promised_window_end,
                                stop.dwell_duration_seconds,
                                stop.status.value,
                            ),
                        )

                    # Update ride
                    new_version = ride_row["version"] + 1
                    cur.execute(
                        """
                        UPDATE rides
                        SET total_vmt_meters = %s, version = %s, updated_at = NOW()
                        WHERE ride_id = %s
                        """,
                        (assignment.vmt_meters, new_version, assignment.existing_ride_id),
                    )

                    # Update newly added requests
                    newly_added_req_ids: list[str] = list(assignment.request_ids)
                    if newly_added_req_ids:
                        cur.execute(
                            """
                            UPDATE ride_requests
                            SET status = %s, matched_ride_id = %s, updated_at = NOW()
                            WHERE request_id = ANY(%s)
                            """,
                            (RequestStatus.MATCHED.value, assignment.existing_ride_id, newly_added_req_ids),
                        )

                    # Insert idempotency record
                    cur.execute(
                        """
                        INSERT INTO idempotency_records (
                            idempotency_token, record_type, join_request_id, request_id, ride_id, version, created_at
                        ) VALUES (%s, 'dispatch_assignment', %s, %s, %s, %s, %s)
                        """,
                        (
                            idempotency_token,
                            assignment.candidate_id,
                            assignment.request_ids[0] if assignment.request_ids else "",
                            assignment.existing_ride_id,
                            new_version,
                            current_time,
                        ),
                    )

                    updated_ride = self._get_ride_with_conn(assignment.existing_ride_id, conn)
                    return AssignmentCommitResult(
                        success=True,
                        candidate_id=assignment.candidate_id,
                        ride_id=assignment.existing_ride_id,
                        ride=updated_ride,
                        committed_request_ids=assignment.request_ids,
                    )

    def cancel_assigned_request_atomic(
        self,
        ride_id: str,
        request_id: str,
        expected_ride_version: int,
        updated_stops: Sequence[RouteStop],
        new_total_vmt_meters: int,
        idempotency_token: Optional[str] = None,
        new_ride_status: Optional[RideStatus] = None,
    ) -> CancellationCommitResult:
        """
        Atomically cancels an assigned request and commits the re-optimized ride itinerary in a single transaction.
        Uses SELECT ... FOR UPDATE on both the ride and request rows.
        """
        with self.connection() as conn:
            with conn.transaction():
                with conn.cursor(row_factory=dict_row) as cur:
                    # 1. Idempotency Check
                    if idempotency_token is not None:
                        cur.execute(
                            "SELECT * FROM idempotency_records WHERE idempotency_token = %s",
                            (idempotency_token,),
                        )
                        rec = cur.fetchone()
                        if rec is not None:
                            if (
                                rec["record_type"] == "cancellation"
                                and rec["request_id"] == request_id
                                and rec["ride_id"] == ride_id
                            ):
                                cur_ride = self._get_ride_with_conn(ride_id, conn)
                                cur_req = self._get_request_with_conn(request_id, conn)
                                return CancellationCommitResult(
                                    success=True,
                                    request_id=request_id,
                                    ride_id=ride_id,
                                    ride=cur_ride,
                                    request=cur_req,
                                )
                            return CancellationCommitResult(
                                success=False,
                                request_id=request_id,
                                ride_id=ride_id,
                                rejection_reason="IDEMPOTENCY_CONFLICT",
                            )

                    # 2. Lock Ride Row (SELECT ... FOR UPDATE) and verify OCC version
                    cur.execute(
                        """
                        SELECT version, lifecycle_status, total_vmt_meters
                        FROM rides
                        WHERE ride_id = %s
                        FOR UPDATE
                        """,
                        (ride_id,),
                    )
                    ride_row = cur.fetchone()
                    if ride_row is None:
                        return CancellationCommitResult(
                            success=False,
                            request_id=request_id,
                            ride_id=ride_id,
                            rejection_reason="RIDE_NOT_FOUND",
                        )

                    if ride_row["version"] != expected_ride_version:
                        return CancellationCommitResult(
                            success=False,
                            request_id=request_id,
                            ride_id=ride_id,
                            rejection_reason="VERSION_CONFLICT",
                        )

                    # 3. Lock Request Row
                    cur.execute(
                        """
                        SELECT request_id, status, matched_ride_id
                        FROM ride_requests
                        WHERE request_id = %s
                        FOR UPDATE
                        """,
                        (request_id,),
                    )
                    req_row = cur.fetchone()
                    if req_row is None:
                        return CancellationCommitResult(
                            success=False,
                            request_id=request_id,
                            ride_id=ride_id,
                            rejection_reason="REQUEST_NOT_FOUND",
                        )

                    if req_row["status"] == RequestStatus.CANCELLED.value:
                        # Idempotent replay
                        cur_ride = self._get_ride_with_conn(ride_id, conn)
                        cur_req = self._get_request_with_conn(request_id, conn)
                        return CancellationCommitResult(
                            success=True,
                            request_id=request_id,
                            ride_id=ride_id,
                            ride=cur_ride,
                            request=cur_req,
                        )

                    if req_row["status"] != RequestStatus.MATCHED.value or req_row["matched_ride_id"] != ride_id:
                        return CancellationCommitResult(
                            success=False,
                            request_id=request_id,
                            ride_id=ride_id,
                            rejection_reason="REQUEST_NOT_MATCHED",
                        )

                    # 4. Check route stops for passenger boarding
                    cur.execute(
                        """
                        SELECT stop_type, status
                        FROM route_stops
                        WHERE ride_id = %s AND request_id = %s
                        FOR UPDATE
                        """,
                        (ride_id, request_id),
                    )
                    stop_rows = cur.fetchall()
                    for s in stop_rows:
                        if s["stop_type"] == StopType.PICKUP.value and s["status"] == StopStatus.COMPLETED.value:
                            return CancellationCommitResult(
                                success=False,
                                request_id=request_id,
                                ride_id=ride_id,
                                rejection_reason="PASSENGER_ALREADY_BOARDED",
                            )

                    # 5. Delete existing route stops and insert updated_stops
                    cur.execute("DELETE FROM route_stops WHERE ride_id = %s", (ride_id,))
                    for idx, stop in enumerate(updated_stops):
                        cur.execute(
                            """
                            INSERT INTO route_stops (
                                stop_id, ride_id, stop_order, request_id, stop_type,
                                latitude, longitude, passenger_delta, scheduled_arrival_time,
                                promised_window_start, promised_window_end, dwell_duration_seconds, status
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                stop.stop_id,
                                ride_id,
                                idx,
                                stop.request_id,
                                stop.stop_type.value,
                                stop.location.latitude,
                                stop.location.longitude,
                                stop.passenger_delta,
                                stop.scheduled_arrival_time,
                                stop.promised_window_start,
                                stop.promised_window_end,
                                stop.dwell_duration_seconds,
                                stop.status.value,
                            ),
                        )

                    # 6. Update Ride version and VMT
                    new_version = ride_row["version"] + 1
                    eff_status = (
                        new_ride_status.value
                        if new_ride_status is not None
                        else ride_row["lifecycle_status"]
                    )
                    cur.execute(
                        """
                        UPDATE rides
                        SET total_vmt_meters = %s, version = %s, lifecycle_status = %s, updated_at = NOW()
                        WHERE ride_id = %s
                        """,
                        (new_total_vmt_meters, new_version, eff_status, ride_id),
                    )

                    # 7. Update Request to CANCELLED
                    cur.execute(
                        """
                        UPDATE ride_requests
                        SET status = %s, updated_at = NOW()
                        WHERE request_id = %s
                        """,
                        (RequestStatus.CANCELLED.value, request_id),
                    )

                    # 8. Record Idempotency if token provided
                    if idempotency_token is not None:
                        cur.execute(
                            """
                            INSERT INTO idempotency_records (
                                idempotency_token, record_type, join_request_id, request_id, ride_id, version, created_at
                            ) VALUES (%s, 'cancellation', '', %s, %s, %s, %s)
                            """,
                            (idempotency_token, request_id, ride_id, new_version, int(time.time())),
                        )

                    # Return updated ride and request snapshots
                    updated_ride = self._get_ride_with_conn(ride_id, conn)
                    updated_req = self._get_request_with_conn(request_id, conn)
                    return CancellationCommitResult(
                        success=True,
                        request_id=request_id,
                        ride_id=ride_id,
                        ride=updated_ride,
                        request=updated_req,
                    )
