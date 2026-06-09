"""Tests for stdlib.net.dns primitive (Phase 3.18.5)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.net_dns import NetDnsLookupPrimitive


@pytest.fixture
def net_dns() -> NetDnsLookupPrimitive:
    return NetDnsLookupPrimitive()


class TestNetDnsLookupPrimitive:
    """Tests for NetDnsLookupPrimitive.validate_args and execute."""

    def test_dns_lookup_valid_hostname(self, net_dns: NetDnsLookupPrimitive) -> None:
        """Resolving a well-known hostname returns addresses."""
        result = net_dns.execute({"hostname": "localhost"}, {})
        assert result.status == "success"
        assert result.data["hostname"] == "localhost"
        assert len(result.data["addresses"]) >= 1
        assert result.data["elapsed_ms"] >= 0

    def test_dns_lookup_nonexistent_hostname(self, net_dns: NetDnsLookupPrimitive) -> None:
        """A nonexistent hostname returns error."""
        result = net_dns.execute({"hostname": "nonexistent.invalid.tld"}, {})
        assert result.status == "error"

    def test_missing_hostname_raises_value_error(self, net_dns: NetDnsLookupPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'hostname' key"):
            net_dns.validate_args({})

    def test_empty_hostname_raises_value_error(self, net_dns: NetDnsLookupPrimitive) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            net_dns.validate_args({"hostname": ""})

    def test_hostname_not_string_raises_value_error(self, net_dns: NetDnsLookupPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            net_dns.validate_args({"hostname": 42})
