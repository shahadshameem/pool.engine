"""Unit tests for staging runner preflight checks and dynamic database URL parsing."""

from unittest.mock import patch
import pytest

from scripts.run_staging_server import run_preflight_checks, check_tcp_port


def test_staging_preflight_dynamic_db_url_parsing() -> None:
    """Verifies that run_preflight_checks parses arbitrary host and port combinations."""
    with patch("scripts.run_staging_server.check_tcp_port") as mock_tcp:
        with patch("scripts.run_staging_server.check_http_endpoint") as mock_http:
            mock_tcp.return_value = True
            mock_http.return_value = (True, "HTTP 200")

            # 1. Standard port 5432 with localhost
            ok = run_preflight_checks(
                regions_file="config/regions.json",
                db_url="postgresql://user:pass@localhost:5432/test_db",
            )
            assert ok is True
            # Verified that check_tcp_port was called with 127.0.0.1 (normalized from localhost) and 5432
            mock_tcp.assert_called_with("127.0.0.1", 5432)

            # 2. Custom host and port
            mock_tcp.reset_mock()
            ok = run_preflight_checks(
                regions_file="config/regions.json",
                db_url="postgresql://user:pass@10.0.0.5:5439/test_db",
            )
            assert ok is True
            mock_tcp.assert_called_with("10.0.0.5", 5439)


def test_staging_preflight_fails_fast_on_unreachable_db() -> None:
    """Verifies that an unreachable database triggers a clean preflight failure."""
    with patch("scripts.run_staging_server.check_tcp_port") as mock_tcp:
        with patch("scripts.run_staging_server.check_http_endpoint") as mock_http:
            mock_tcp.return_value = False
            mock_http.return_value = (True, "HTTP 200")

            ok = run_preflight_checks(
                regions_file="config/regions.json",
                db_url="postgresql://user:pass@127.0.0.1:5432/non_existent_db",
            )
            assert ok is False
