#!/usr/bin/env python3
"""Automated local staging database setup script for Pool Engine.

Creates 'pool_engine_staging' and 'pool_engine_test' databases,
applies the full schema to 'pool_engine_staging', and configures
the local non-committed .env.staging file.
"""

import argparse
import getpass
import logging
import os
import sys
import urllib.parse
from typing import Optional

import psycopg

# Ensure src is on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from engine.service.security import sanitize_sensitive_strings
from scripts.init_db import EXPECTED_TABLES, run_init_db, sanitize_dsn

logger = logging.getLogger("setup_staging_databases")


def create_databases_if_missing(
    host: str,
    port: int,
    user: str,
    password: str,
    db_names: list[str],
) -> bool:
    """Connect to the default maintenance database ('postgres') and create target databases."""
    admin_dsn = f"postgresql://{urllib.parse.quote(user)}:{urllib.parse.quote(password)}@{host}:{port}/postgres"
    sanitized_admin = sanitize_dsn(admin_dsn)
    logger.info("Connecting to PostgreSQL maintenance database at %s...", sanitized_admin)

    try:
        conn = psycopg.connect(admin_dsn, connect_timeout=5, autocommit=True)
    except Exception as exc:
        logger.error("Failed to connect to PostgreSQL maintenance database: %s", sanitize_sensitive_strings(str(exc)))
        return False

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT datname FROM pg_database WHERE datistemplate = false;")
            existing_dbs = {row[0] for row in cur.fetchall()}

            for db_name in db_names:
                if db_name in existing_dbs:
                    logger.info("Database '%s' already exists.", db_name)
                else:
                    logger.info("Creating database '%s'...", db_name)
                    # Database name cannot be parameterized with %s in CREATE DATABASE
                    # so validate identifier safety
                    if not db_name.replace("_", "").isalnum():
                        raise ValueError(f"Invalid database name: {db_name}")
                    cur.execute(f'CREATE DATABASE "{db_name}";')
                    logger.info("Database '%s' created successfully.", db_name)
        return True
    except Exception as exc:
        logger.error("Error creating databases: %s", sanitize_sensitive_strings(str(exc)))
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def configure_local_env_staging(
    staging_dsn: str,
    test_dsn: str,
) -> None:
    """Create or update .env.staging from .env.staging.example with the real local DSNs."""
    staging_env_path = os.path.join(PROJECT_ROOT, ".env.staging")
    staging_example_path = os.path.join(PROJECT_ROOT, ".env.staging.example")

    if not os.path.exists(staging_env_path) and os.path.exists(staging_example_path):
        with open(staging_example_path, "r", encoding="utf-8") as f:
            template = f.read()
    elif os.path.exists(staging_env_path):
        with open(staging_env_path, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        template = ""

    # Replace or add DATABASE_URL and TEST_DATABASE_URL
    lines = template.splitlines()
    new_lines = []
    has_db = False
    has_test_db = False
    has_persistent = False

    for line in lines:
        if line.startswith("DATABASE_URL="):
            new_lines.append(f"DATABASE_URL={staging_dsn}")
            has_db = True
        elif line.startswith("TEST_DATABASE_URL="):
            new_lines.append(f"TEST_DATABASE_URL={test_dsn}")
            has_test_db = True
        elif line.startswith("REQUIRE_PERSISTENT_STORAGE="):
            new_lines.append("REQUIRE_PERSISTENT_STORAGE=true")
            has_persistent = True
        else:
            new_lines.append(line)

    if not has_db:
        new_lines.append(f"DATABASE_URL={staging_dsn}")
    if not has_test_db:
        new_lines.append(f"TEST_DATABASE_URL={test_dsn}")
    if not has_persistent:
        new_lines.append("REQUIRE_PERSISTENT_STORAGE=true")

    with open(staging_env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")

    logger.info("Updated git-ignored .env.staging with configured local PostgreSQL endpoints.")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Pool Engine Staging Database Setup")
    parser.add_argument("--host", default="127.0.0.1", help="PostgreSQL host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5432, help="PostgreSQL port (default: 5432)")
    parser.add_argument("--user", default="postgres", help="PostgreSQL superuser (default: postgres)")
    parser.add_argument("--password", default=None, help="PostgreSQL password (omit to prompt securely or use PGPASSWORD)")

    args = parser.parse_args()

    password = args.password or os.environ.get("PGPASSWORD")
    if not password:
        if sys.stdin.isatty():
            password = getpass.getpass(f"Enter PostgreSQL password for user '{args.user}': ")
        else:
            logger.error("No password supplied via --password, PGPASSWORD, or interactive stdin.")
            return 1

    target_dbs = ["pool_engine_staging", "pool_engine_test"]
    if not create_databases_if_missing(args.host, args.port, args.user, password, target_dbs):
        return 1

    staging_dsn = f"postgresql://{urllib.parse.quote(args.user)}:{urllib.parse.quote(password)}@{args.host}:{args.port}/pool_engine_staging"
    test_dsn = f"postgresql://{urllib.parse.quote(args.user)}:{urllib.parse.quote(password)}@{args.host}:{args.port}/pool_engine_test"

    logger.info("Initializing schema in pool_engine_staging...")
    init_res = run_init_db(dsn=staging_dsn, check_only=False)
    if init_res != 0:
        logger.error("Failed to apply schema migrations to pool_engine_staging.")
        return 1

    logger.info("Verifying schema in pool_engine_staging (check-only)...")
    check_res = run_init_db(dsn=staging_dsn, check_only=True)
    if check_res != 0:
        logger.error("Schema verification failed on pool_engine_staging.")
        return 1

    configure_local_env_staging(staging_dsn, test_dsn)
    logger.info("Staging and test database setup completed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
