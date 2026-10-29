"""Unit tests for bounded PostgreSQL ConnectionPool lifecycle, configuration, and safety."""

import os
from unittest.mock import MagicMock
import pytest

from engine.adapters.postgres_storage import PostgresRideStorage
from engine.contracts.storage import StorageProviderError


def test_pool_configuration_defaults_and_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies default pool parameters and environment variable overrides."""
    # 1. Defaults
    storage_default = PostgresRideStorage(dsn="postgresql://user:pass@localhost:5432/db")
    assert storage_default._min_size == 2
    assert storage_default._max_size == 10
    assert storage_default._timeout == 5.0
    assert storage_default._max_idle == 300.0
    assert storage_default._check_connection is True

    # 2. Environment variable overrides
    monkeypatch.setenv("PG_POOL_MIN_SIZE", "4")
    monkeypatch.setenv("PG_POOL_MAX_SIZE", "25")
    monkeypatch.setenv("PG_POOL_TIMEOUT", "10.5")
    monkeypatch.setenv("PG_POOL_MAX_IDLE", "600.0")

    storage_custom = PostgresRideStorage(dsn="postgresql://user:pass@localhost:5432/db")
    assert storage_custom._min_size == 4
    assert storage_custom._max_size == 25
    assert storage_custom._timeout == 10.5
    assert storage_custom._max_idle == 600.0


def test_external_connection_injected_never_closed() -> None:
    """Verifies that an externally injected connection is used directly and NEVER closed."""
    mock_conn = MagicMock()
    mock_conn.closed = False

    storage = PostgresRideStorage(connection=mock_conn)

    # Context manager yields external connection
    with storage.connection() as conn:
        assert conn is mock_conn

    # Legacy accessor returns external connection
    assert storage._get_connection() is mock_conn

    # Calling close() must NOT close external connection
    storage.close()
    assert mock_conn.close.call_count == 0, "storage.close() must never close an externally injected connection"


def test_external_connection_cannot_open_pool() -> None:
    """Verifies that calling _get_pool() with an external connection raises StorageProviderError."""
    mock_conn = MagicMock()
    storage = PostgresRideStorage(connection=mock_conn)
    with pytest.raises(StorageProviderError, match="Cannot open connection pool when an external connection is injected"):
        storage._get_pool()


def test_missing_dsn_and_connection_raises_storage_provider_error() -> None:
    """Verifies that attempting connection acquisition without DSN or connection raises StorageProviderError."""
    storage = PostgresRideStorage(dsn=None, connection=None)

    with pytest.raises(StorageProviderError, match="requires a DSN or active psycopg Connection"):
        storage._get_pool()

    with pytest.raises(StorageProviderError, match="requires a DSN or active psycopg Connection"):
        storage._get_connection()

    with pytest.raises(StorageProviderError, match="requires a DSN or active psycopg Connection"):
        with storage.connection():
            pass


def test_pool_stats_when_pool_closed_or_uninitialized() -> None:
    """Verifies that get_pool_stats() returns None when pool is not open."""
    storage = PostgresRideStorage(dsn="postgresql://user:pass@localhost:5432/db")
    assert storage.get_pool_stats() is None

    storage.close()
    assert storage.get_pool_stats() is None


def test_pool_close_idempotency() -> None:
    """Verifies that storage.close() can be called repeatedly without raising exceptions."""
    storage = PostgresRideStorage(dsn="postgresql://user:pass@localhost:5432/db")
    storage.close()
    storage.close()
    assert storage._pool is None
    assert storage._direct_conn is None
