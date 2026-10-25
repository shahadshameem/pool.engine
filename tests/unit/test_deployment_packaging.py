"""Unit tests for Phase 2.5 deployment packaging, environment configuration, and verification tools."""

import os
from typing import Generator
from unittest.mock import MagicMock, patch
import pytest

from engine.adapters.in_memory_storage import InMemoryRideStorage
from engine.adapters.mock_routing import MockRoutingProvider
from engine.adapters.osrm_routing import OsrmRoutingAdapter
from engine.adapters.postgres_storage import PostgresRideStorage
from engine.service.app import create_app
from engine.service.client import AsgiTestClient
from engine.service.config import ServiceConfig
from engine.service.security import (
    ApiKeyAuthProvider,
    NoOpAuthProvider,
    build_auth_provider_from_env,
)
from engine.service.service import PoolEngineService, build_service_from_env
from scripts.init_db import sanitize_dsn, verify_tables_exist
from scripts.smoke_test import run_smoke_test


def test_service_config_from_env_defaults() -> None:
    with patch.dict(os.environ, {}, clear=True):
        cfg = ServiceConfig.from_env()
        assert cfg.environment == "development"
        assert cfg.require_auth is False
        assert cfg.max_request_body_bytes == 1_048_576
        assert cfg.shutdown_timeout_seconds == 5.0
        assert cfg.mask_coordinates_in_logs is True


def test_service_config_from_env_custom() -> None:
    env = {
        "ENVIRONMENT": "staging",
        "AUTH_ENABLED": "true",
        "MAX_REQUEST_BODY_BYTES": "2097152",
        "SHUTDOWN_TIMEOUT_SECONDS": "12.5",
        "STRICT_ROUTING_READINESS": "true",
        "MASK_COORDINATES_IN_LOGS": "false",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = ServiceConfig.from_env()
        assert cfg.environment == "staging"
        assert cfg.require_auth is True
        assert cfg.max_request_body_bytes == 2097152
        assert cfg.shutdown_timeout_seconds == 12.5
        assert cfg.strict_routing_readiness is True
        assert cfg.mask_coordinates_in_logs is False


def test_service_config_production_guard() -> None:
    env = {
        "ENVIRONMENT": "production",
        "REQUIRE_AUTH": "false",
    }
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValueError, match="Production environment requires authentication"):
            ServiceConfig.from_env()

    # Allowed with explicit opt-out
    env["ALLOW_UNAUTHENTICATED_IN_PRODUCTION"] = "true"
    with patch.dict(os.environ, env, clear=True):
        cfg = ServiceConfig.from_env()
        assert cfg.environment == "production"
        assert cfg.allow_unauthenticated_in_production is True


def test_build_auth_provider_from_env_comma_delimited() -> None:
    env = {
        "API_KEYS": "admin_key:admin,reader_key:read",
    }
    provider = build_auth_provider_from_env(env)
    assert isinstance(provider, ApiKeyAuthProvider)
    # Verify authentication
    admin_ctx = provider.authenticate({}, {"authorization": "Bearer admin_key"})
    assert admin_ctx.authenticated is True
    assert "admin" in admin_ctx.roles

    reader_ctx = provider.authenticate({}, {"authorization": "Bearer reader_key"})
    assert reader_ctx.authenticated is True
    assert "read" in reader_ctx.roles

    # Verify invalid key
    invalid_ctx = provider.authenticate({}, {"authorization": "Bearer invalid_key"})
    assert invalid_ctx.authenticated is False


def test_build_auth_provider_from_env_json() -> None:
    env = {
        "API_KEYS": '{"custom-token": ["custom-subject", ["admin", "write"]]}',
    }
    provider = build_auth_provider_from_env(env)
    assert isinstance(provider, ApiKeyAuthProvider)
    ctx = provider.authenticate({}, {"authorization": "Bearer custom-token"})
    assert ctx.authenticated is True
    assert ctx.subject_id == "custom-subject"
    assert "write" in ctx.roles


def test_build_auth_provider_from_env_empty() -> None:
    provider = build_auth_provider_from_env({"API_KEYS": ""})
    assert isinstance(provider, NoOpAuthProvider)


def test_build_service_from_env_in_memory() -> None:
    env = {
        "DATABASE_URL": "",
        "OSRM_BASE_URL": "",
    }
    svc = build_service_from_env(env)
    assert isinstance(svc, PoolEngineService)
    assert isinstance(svc.storage, InMemoryRideStorage)
    assert isinstance(svc.router, MockRoutingProvider)


def test_build_service_from_env_postgres_and_osrm() -> None:
    env = {
        "DATABASE_URL": "postgresql://test:test@localhost:5432/test_db",
        "OSRM_BASE_URL": "http://127.0.0.1:5000",
        "ROUTING_TIMEOUT_SECONDS": "0.40",
    }
    svc = build_service_from_env(env)
    assert isinstance(svc, PoolEngineService)
    assert isinstance(svc.storage, PostgresRideStorage)
    assert isinstance(svc.router, OsrmRoutingAdapter)
    assert svc.router.timeout_seconds == 0.40


def test_create_app_zero_arguments() -> None:
    """Verifies that create_app() can be invoked without arguments as an ASGI factory."""
    with patch.dict(os.environ, {"DATABASE_URL": "", "OSRM_BASE_URL": ""}, clear=True):
        app = create_app()
        client = AsgiTestClient(app)
        resp = client.get("/v1/health/liveness")
        assert resp.status_code == 200
        assert resp.json()["status"] == "alive"


def test_sanitize_dsn_masks_password() -> None:
    dsn = "postgresql://myuser:supersecretpassword@db.prod.internal:5432/pool_db"
    sanitized = sanitize_dsn(dsn)
    assert "supersecretpassword" not in sanitized
    assert "myuser:***@db.prod.internal" in sanitized

    assert sanitize_dsn(None) == "<none>"
    assert sanitize_dsn("") == "<none>"


def test_smoke_test_in_process_success() -> None:
    """End-to-end verification of smoke test execution in-process."""
    with patch.dict(os.environ, {"DATABASE_URL": "", "OSRM_BASE_URL": "", "REQUIRE_AUTH": "false"}, clear=True):
        exit_code = run_smoke_test(base_url="in-process")
        assert exit_code == 0


def test_smoke_test_with_auth_success() -> None:
    """End-to-end verification of smoke test with API key auth."""
    env = {
        "DATABASE_URL": "",
        "OSRM_BASE_URL": "",
        "REQUIRE_AUTH": "true",
        "API_KEYS": "test-key-1:admin",
    }
    with patch.dict(os.environ, env, clear=True):
        exit_code = run_smoke_test(base_url="in-process", api_key="test-key-1")
        assert exit_code == 0


def test_smoke_test_detects_unauthorized_failure() -> None:
    """Smoke test should fail if server requires auth but no valid key is provided."""
    env = {
        "DATABASE_URL": "",
        "OSRM_BASE_URL": "",
        "REQUIRE_AUTH": "true",
        "API_KEYS": "test-key-1:admin",
    }
    with patch.dict(os.environ, env, clear=True):
        # Passing wrong or missing key should trigger failure exit code 1
        exit_code = run_smoke_test(base_url="in-process", api_key=None)
        assert exit_code == 1
