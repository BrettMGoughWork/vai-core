"""Tests for stdlib.net.post primitive (Phase 3.18.5)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.net_post import NetHttpPostPrimitive


@pytest.fixture
def net_post() -> NetHttpPostPrimitive:
    return NetHttpPostPrimitive()


class TestNetHttpPostPrimitive:
    """Tests for NetHttpPostPrimitive.validate_args and execute."""

    def test_post_json(self, net_post: NetHttpPostPrimitive) -> None:
        """POST with JSON body to httpbin."""
        result = net_post.execute(
            {"url": "https://httpbin.org/post", "json": {"key": "value"}},
            {},
        )
        assert result.status == "success"
        assert result.data["status_code"] == 200
        assert "key" in result.data["body"]

    def test_post_data(self, net_post: NetHttpPostPrimitive) -> None:
        """POST with raw data body."""
        result = net_post.execute(
            {"url": "https://httpbin.org/post", "data": "raw body"},
            {},
        )
        assert result.status == "success"
        assert result.data["status_code"] == 200

    def test_post_500_returns_success(self, net_post: NetHttpPostPrimitive) -> None:
        """Even 500 is a successful HTTP response (status in data)."""
        result = net_post.execute(
            {"url": "https://httpbin.org/status/500", "json": {}},
            {},
        )
        assert result.status == "success"
        assert result.data["status_code"] == 500

    def test_post_invalid_url_returns_error(self, net_post: NetHttpPostPrimitive) -> None:
        result = net_post.execute({"url": "not-a-valid-url", "json": {}}, {})
        assert result.status == "error"

    def test_missing_url_raises_value_error(self, net_post: NetHttpPostPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'url' key"):
            net_post.validate_args({})

    def test_empty_url_raises_value_error(self, net_post: NetHttpPostPrimitive) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            net_post.validate_args({"url": ""})

    def test_invalid_json_raises_value_error(self, net_post: NetHttpPostPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a dict"):
            net_post.validate_args({"url": "https://example.com", "json": "not dict"})

    def test_both_json_and_data_raises_value_error(self, net_post: NetHttpPostPrimitive) -> None:
        with pytest.raises(ValueError, match="cannot specify both"):
            net_post.validate_args({"url": "https://example.com", "json": {}, "data": "x"})

    def test_negative_timeout_raises_value_error(self, net_post: NetHttpPostPrimitive) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            net_post.validate_args({"url": "https://example.com", "timeout": -1})
