"""Tests for stdlib.net.get primitive (Phase 3.18.5)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.net_get import NetHttpGetPrimitive


@pytest.fixture
def net_get() -> NetHttpGetPrimitive:
    return NetHttpGetPrimitive()


class TestNetHttpGetPrimitive:
    """Tests for NetHttpGetPrimitive.validate_args and execute."""

    def test_get_success(self, net_get: NetHttpGetPrimitive) -> None:
        """A GET to httpbin returns 200."""
        result = net_get.execute({"url": "https://httpbin.org/get"}, {})
        assert result.status == "success"
        assert result.data["status_code"] == 200
        assert result.data["elapsed_ms"] >= 0

    def test_get_with_headers(self, net_get: NetHttpGetPrimitive) -> None:
        """Custom headers are sent."""
        result = net_get.execute(
            {"url": "https://httpbin.org/get", "headers": {"X-Test": "hello"}},
            {},
        )
        assert result.status == "success"
        assert "X-Test" in result.data["body"]

    def test_get_404_returns_success(self, net_get: NetHttpGetPrimitive) -> None:
        """Even 404 is a successful HTTP response (status in data)."""
        result = net_get.execute({"url": "https://httpbin.org/status/404"}, {})
        assert result.status == "success"
        assert result.data["status_code"] == 404

    def test_get_invalid_url_returns_error(self, net_get: NetHttpGetPrimitive) -> None:
        """A clearly invalid URL returns error status."""
        result = net_get.execute({"url": "not-a-valid-url"}, {})
        assert result.status == "error"

    def test_missing_url_raises_value_error(self, net_get: NetHttpGetPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'url' key"):
            net_get.validate_args({})

    def test_empty_url_raises_value_error(self, net_get: NetHttpGetPrimitive) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            net_get.validate_args({"url": ""})

    def test_url_not_string_raises_value_error(self, net_get: NetHttpGetPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            net_get.validate_args({"url": 42})

    def test_negative_timeout_raises_value_error(self, net_get: NetHttpGetPrimitive) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            net_get.validate_args({"url": "https://example.com", "timeout": -1})

    def test_headers_not_dict_raises_value_error(self, net_get: NetHttpGetPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a dict"):
            net_get.validate_args({"url": "https://example.com", "headers": "bad"})
