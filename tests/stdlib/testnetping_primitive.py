"""Tests for stdlib.net.ping primitive (Phase 3.18.5)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.net_ping import NetPingPrimitive


@pytest.fixture
def net_ping() -> NetPingPrimitive:
    return NetPingPrimitive()


class TestNetPingPrimitive:
    """Tests for NetPingPrimitive.validate_args and execute."""

    def test_ping_loopback_success(self, net_ping: NetPingPrimitive) -> None:
        """Pinging 127.0.0.1:9999 should fail (no listener) but return success status."""
        result = net_ping.execute({"host": "127.0.0.1", "port": 9999}, {})
        assert result.status == "success"
        assert result.data["reachable"] is False
        assert result.data["host"] == "127.0.0.1"
        assert result.data["port"] == 9999
        assert result.data["elapsed_ms"] >= 0

    def test_missing_host_raises_value_error(self, net_ping: NetPingPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'host' key"):
            net_ping.validate_args({"port": 80})

    def test_missing_port_raises_value_error(self, net_ping: NetPingPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'port' key"):
            net_ping.validate_args({"host": "127.0.0.1"})

    def test_empty_host_raises_value_error(self, net_ping: NetPingPrimitive) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            net_ping.validate_args({"host": "", "port": 80})

    def test_invalid_port_type_raises_value_error(self, net_ping: NetPingPrimitive) -> None:
        with pytest.raises(ValueError, match="must be an integer"):
            net_ping.validate_args({"host": "127.0.0.1", "port": "80"})

    def test_port_out_of_range_raises_value_error(self, net_ping: NetPingPrimitive) -> None:
        with pytest.raises(ValueError, match="must be between"):
            net_ping.validate_args({"host": "127.0.0.1", "port": 99999})

    def test_negative_timeout_raises_value_error(self, net_ping: NetPingPrimitive) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            net_ping.validate_args({"host": "127.0.0.1", "port": 80, "timeout": -1})
