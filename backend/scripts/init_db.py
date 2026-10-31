#!/usr/bin/env python3
"""Database initialization and schema verification script for Pool Engine."""

import argparse
import logging
import os
import re
import sys
from typing import Optional, Sequence

import psycopg

# Ensure src is on sys.path if invoked directly
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from engine.adapters.postgres_storage import PostgresRideStorage
from engine.contracts.storage import StorageProviderError
from engine.service.security import sanitize_sensitive_strings

logger = logging.getLogger("init_db")

EXPECTED_TABLES = [
    "vehicles",
    "rides",
    "route_stops",
    "ride_requests",
    "join_requests",
    "seat_holds",
    "idempotency_records",
]


def sanitize_dsn(dsn: Optional[str]) -> str:
    """Mask credentials in a database connection string for safe logging."""
    if not dsn:
        return "<none>"
    # Pattern to match :password@ in URIs
    masked = re.sub(r":([^/@:]+)@", ":***@", dsn)
    return sanitize_sensitive_strings(masked)


def verify_tables_exist(conn: psycopg.Connection) -> tuple[bool, list[str]]:
    """Check whether all expected pool engine tables exist in the public schema."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            """
        )
        existing = {row[0] for row in cur.fetchall()}

    missing = [t for t in EXPECTED_TABLES if t not in existing]
    return len(missing) == 0, missing


def run_init_db(
    dsn: Optional[str] = None,
    check_only: bool = False,
    timeout: float = 10.0,
) -> int:
    """
    Initialize or verify the PostgreSQL schema for Pool Engine.

    Returns:
        0 on success, non-zero on failure.
    """
    effective_dsn = dsn or os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_DSN")
    if not effective_dsn:
        logger.error(
            "No database DSN provided. Specify via --dsn or DATABASE_URL/POSTGRES_DSN."
        )
        return 1

    sanitized = sanitize_dsn(effective_dsn)
    logger.info("Connecting to PostgreSQL at %s (timeout=%.1fs)...", sanitized, timeout)

    try:
        conn = psycopg.connect(
            effective_dsn,
            connect_timeout=int(timeout),
            autocommit=True,
        )
    except Exception as exc:
        logger.error("Failed to connect to database: %s", sanitize_sensitive_strings(str(exc)))
        return 1

    try:
        if check_only:
            logger.info("Running schema verification (check-only mode)...")
            ok, missing = verify_tables_exist(conn)
            if not ok:
                logger.error("Schema check failed. Missing expected tables: %s", missing)
                return 1
            logger.info("Schema check succeeded. All expected tables are present: %s", EXPECTED_TABLES)
            return 0

        logger.info("Applying database schema DDL migrations...")
        storage = PostgresRideStorage(connection=conn)
        storage.create_schema()

        ok, missing = verify_tables_exist(conn)
        if not ok:
            logger.error("Schema initialization completed but missing tables: %s", missing)
            return 1

        logger.info("Database schema initialized and verified successfully.")
        return 0
    except StorageProviderError as spe:
        logger.error("Storage error during schema operations: %s", sanitize_sensitive_strings(str(spe)))
        return 1
    except Exception as exc:
        logger.error("Unexpected error during schema operations: %s", sanitize_sensitive_strings(str(exc)))
        return 1
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entrypoint for database initialization."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Initialize or verify PostgreSQL schema for Pool Engine."
    )
    parser.add_argument(
        "--dsn",
        dest="dsn",
        type=str,
        default=None,
        help="PostgreSQL connection URI (defaults to DATABASE_URL or POSTGRES_DSN env var).",
    )
    parser.add_argument(
        "--check-only",
        dest="check_only",
        action="store_true",
        help="Check that tables exist without applying migrations or DDL.",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout",
        type=float,
        default=10.0,
        help="Connection timeout in seconds (default: 10.0).",
    )

    args = parser.parse_args(argv)
    return run_init_db(
        dsn=args.dsn,
        check_only=args.check_only,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    sys.exit(main())
