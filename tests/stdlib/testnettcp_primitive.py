"""Tests for stdlib.net.tcp primitive (Phase 3.18.5)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.net_tcp import NetTcpCheckPrimitive


@pytest.fixture
def net_tcp() -> NetTcpCheckPrimitive:
    return NetTcpCheckPrimitive()


class TestNetTcpCheckPrimitive:
    """Tests for NetTcpCheckPrimitive.validate_args and execute."""

    def test_tcp_closed_port(self, net_tcp: NetTcpCheckPrimitive) -> None:
        """Checking a port with no listener returns open=False."""
        result = net_tcp.execute({"host": "127.0.0.1", "port": 19999}, {})
        assert result.status == "success"
        assert result.data["open"] is False
        assert result.data["host"] == "127.0.0.1"
        assert result.data["port"] == 19999
        assert result.data["elapsed_ms"] >= 0

    def test_missing_host_raises_value_error(self, net_tcp: NetTcpCheckPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'host' key"):
            net_tcp.validate_args({"port": 80})

    def test_missing_port_raises_value_error(self, net_tcp: NetTcpCheckPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'port' key"):
            net_tcp.validate_args({"host": "127.0.0.1"})

    def test_empty_host_raises_value_error(self, net_tcp: NetTcpCheckPrimitive) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            net_tcp.validate_args({"host": "", "port": 80})

    def test_invalid_port_type_raises_value_error(self, net_tcp: NetTcpCheckPrimitive) -> None:
        with pytest.raises(ValueError, match="must be an integer"):
            net_tcp.validate_args({"host": "127.0.0.1", "port": "80"})

    def test_port_out_of_range_raises_value_error(self, net_tcp: NetTcpCheckPrimitive) -> None:
        with pytest.raises(ValueError, match="must be between"):
            net_tcp.validate_args({"host": "127.0.0.1", "port": 99999})

    def test_negative_timeout_raises_value_error(self, net_tcp: NetTcpCheckPrimitive) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            net_tcp.validate_args({"host": "127.0.0.1", "port": 80, "timeout": -1})
