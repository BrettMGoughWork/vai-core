"""
Tests for the domain policy interpreter (PHASE 3.12.3).

Covers:
- Default policy (no policy file, empty policy, missing domain)
- Domain extraction from URLs (normal, no-scheme, IPv4, IPv6, invalid)
- Deny / allow=false → immediate block
- Preferred mode resolution
- Forbidden modes filtering
- Rate limit propagation
- Merged fields (partial entries)
- Convenience properties (is_denied, has_preference, etc.)
- Invalid/malformed mode values
"""

from __future__ import annotations

import pytest

from src.capabilities.primitives.fetch.domain_policy import (
    DomainPolicy,
    _extract_domain,
    _normalise_forbidden_modes,
    _normalise_preferred_mode,
    interpret_domain_policy,
)

# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------


class TestDomainPolicySmoke:
    """Basic sanity — the function exists and returns the expected shape."""

    def test_returns_domain_policy(self):
        result = interpret_domain_policy("https://example.com")
        assert isinstance(result, DomainPolicy)

    def test_has_required_fields(self):
        result = interpret_domain_policy("https://example.com")
        assert result.domain == "example.com"
        assert isinstance(result.allow, bool)
        assert isinstance(result.deny, bool)
        assert isinstance(result.rate_limit_ms, int)
        assert result.preferred_mode is None or isinstance(result.preferred_mode, str)
        assert isinstance(result.forbidden_modes, tuple)
        assert isinstance(result.reasoning, str)

    def test_is_frozen(self):
        result = interpret_domain_policy("https://example.com")
        with pytest.raises(Exception):
            result.allow = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Default policy (no policy file / empty / missing domain)
# ---------------------------------------------------------------------------


class TestDefaultPolicy:
    """When no policy file is supplied, return defaults for every domain."""

    def test_no_policy_dict_returns_defaults(self):
        result = interpret_domain_policy("https://example.com")
        assert result.allow is True
        assert result.deny is False
        assert result.rate_limit_ms == 0
        assert result.preferred_mode is None
        assert result.forbidden_modes == ()

    def test_none_policy_dict_returns_defaults(self):
        result = interpret_domain_policy("https://example.com", domain_policy=None)
        assert result.allow is True

    def test_empty_policy_dict_returns_defaults(self):
        result = interpret_domain_policy("https://example.com", domain_policy={})
        assert result.allow is True

    def test_missing_domain_in_policy_returns_defaults(self):
        policy = {"other.com": {"allow": False}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.allow is True
        assert result.reasoning == "no policy entry for example.com → defaults"


# ---------------------------------------------------------------------------
# Domain extraction
# ---------------------------------------------------------------------------


class TestDomainExtraction:
    """The domain is extracted correctly from a variety of URL shapes."""

    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://example.com", "example.com"),
            ("http://www.example.com/path?q=1", "www.example.com"),
            ("https://sub.domain.co.uk/page", "sub.domain.co.uk"),
            ("http://example.com:8080/api", "example.com"),
            ("https://192.168.1.1/admin", "192.168.1.1"),
            ("https://[::1]/path", "::1"),  # IPv6
            ("https://[2001:db8::1]:443/path", "2001:db8::1"),  # IPv6 with port
        ],
    )
    def test_extracts_domain(self, url, expected):
        result = interpret_domain_policy(url)
        assert result.domain == expected

    def test_no_scheme_adds_http(self):
        result = interpret_domain_policy("example.com/path")
        assert result.domain == "example.com"

    def test_domain_is_lowercased(self):
        result = interpret_domain_policy("https://EXAMPLE.COM/Path")
        assert result.domain == "example.com"

    def test_empty_url_returns_empty_domain(self):
        result = interpret_domain_policy("")
        assert result.domain == ""

    def test_invalid_url_returns_defaults(self):
        result = interpret_domain_policy("not a url at all !!!")
        assert result.allow is True  # Still safe — defaults apply

    def test_trailing_slash_only(self):
        result = interpret_domain_policy("https://example.com/")
        assert result.domain == "example.com"

    def test_mailto_url(self):
        """mailto: URLs have no hostname."""
        result = interpret_domain_policy("mailto:user@example.com")
        assert result.domain == ""


# ---------------------------------------------------------------------------
# Deny / allow=false
# ---------------------------------------------------------------------------


class TestDeny:
    """Deny or allow=false must block the domain immediately."""

    def test_deny_true_blocks(self):
        policy = {"evil.com": {"deny": True}}
        result = interpret_domain_policy("https://evil.com", domain_policy=policy)
        assert result.allow is False
        assert result.deny is True
        assert result.is_denied is True

    def test_allow_false_blocks(self):
        policy = {"evil.com": {"allow": False}}
        result = interpret_domain_policy("https://evil.com", domain_policy=policy)
        assert result.allow is False
        assert result.deny is True
        assert result.is_denied is True

    def test_both_allow_false_and_deny_true(self):
        policy = {"evil.com": {"allow": False, "deny": True}}
        result = interpret_domain_policy("https://evil.com", domain_policy=policy)
        assert result.allow is False
        assert result.deny is True

    def test_deny_false_allowed(self):
        policy = {"example.com": {"deny": False}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.allow is True

    def test_deny_reasoning(self):
        policy = {"evil.com": {"deny": True}}
        result = interpret_domain_policy("https://evil.com", domain_policy=policy)
        assert "denied" in result.reasoning.lower()

    def test_deny_domain_is_exact_match(self):
        """Subdomains do not inherit the parent domain's deny."""
        policy = {"evil.com": {"deny": True}}
        result = interpret_domain_policy("https://sub.evil.com", domain_policy=policy)
        assert result.allow is True  # sub.evil.com ≠ evil.com


# ---------------------------------------------------------------------------
# Preferred mode
# ---------------------------------------------------------------------------


class TestPreferredMode:
    """preferred_mode is returned as a hint."""

    def test_preferred_mode_present(self):
        policy = {"example.com": {"preferred_mode": "http_hardened"}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.preferred_mode == "http_hardened"

    def test_preferred_mode_in_reasoning(self):
        policy = {"example.com": {"preferred_mode": "http_stealth"}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert "preferred=http_stealth" in result.reasoning

    def test_invalid_preferred_mode_ignored(self):
        policy = {"example.com": {"preferred_mode": "http_best_effort"}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.preferred_mode is None

    def test_null_preferred_mode_returns_none(self):
        policy = {"example.com": {"preferred_mode": None}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.preferred_mode is None

    def test_nonexistent_preferred_mode(self):
        policy = {"example.com": {"preferred_mode": "some_random_thing"}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.preferred_mode is None


# ---------------------------------------------------------------------------
# Forbidden modes
# ---------------------------------------------------------------------------


class TestForbiddenModes:
    """forbidden_modes are filtered and returned."""

    def test_single_forbidden_mode(self):
        policy = {"example.com": {"forbidden_modes": ["http_simple"]}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.forbidden_modes == ("http_simple",)

    def test_multiple_forbidden_modes(self):
        policy = {
            "example.com": {
                "forbidden_modes": ["http_simple", "http_hardened"]
            }
        }
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.forbidden_modes == ("http_simple", "http_hardened")

    def test_forbidden_in_reasoning(self):
        policy = {"example.com": {"forbidden_modes": ["http_simple"]}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert "forbidden" in result.reasoning

    def test_invalid_forbidden_modes_filtered_out(self):
        policy = {
            "example.com": {
                "forbidden_modes": ["http_simple", "bogus", "also_bogus"]
            }
        }
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.forbidden_modes == ("http_simple",)

    def test_all_invalid_forbidden_modes(self):
        policy = {"example.com": {"forbidden_modes": ["bogus1", "bogus2"]}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.forbidden_modes == ()

    def test_forbidden_modes_not_a_list(self):
        policy = {"example.com": {"forbidden_modes": "http_simple"}}  # not a list
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.forbidden_modes == ()


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------


class TestRateLimit:
    """rate_limit_ms propagates to the output."""

    def test_rate_limit_propagates(self):
        policy = {"example.com": {"rate_limit_ms": 2000}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.rate_limit_ms == 2000

    def test_rate_limit_zero_by_default(self):
        result = interpret_domain_policy("https://example.com")
        assert result.rate_limit_ms == 0

    def test_rate_limit_in_reasoning(self):
        policy = {"example.com": {"rate_limit_ms": 500}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert "rate_limit=500ms" in result.reasoning

    def test_rate_limit_string_coerced_to_int(self):
        policy = {"example.com": {"rate_limit_ms": "100"}}  # type: ignore[dict-item]
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.rate_limit_ms == 100


# ---------------------------------------------------------------------------
# Merged fields (partial entries)
# ---------------------------------------------------------------------------


class TestMergedEntries:
    """When only some fields are present, defaults fill the rest."""

    def test_partial_entry_only_preferred(self):
        policy = {"example.com": {"preferred_mode": "http_stealth"}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.allow is True
        assert result.rate_limit_ms == 0
        assert result.forbidden_modes == ()

    def test_partial_entry_only_rate_limit(self):
        policy = {"example.com": {"rate_limit_ms": 1000}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.allow is True
        assert result.preferred_mode is None

    def test_full_entry(self):
        policy = {
            "example.com": {
                "allow": True,
                "deny": False,
                "rate_limit_ms": 500,
                "preferred_mode": "http_hardened",
                "forbidden_modes": ["http_simple"],
                "notes": "test domain",
            }
        }
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.allow is True
        assert result.rate_limit_ms == 500
        assert result.preferred_mode == "http_hardened"
        assert result.forbidden_modes == ("http_simple",)

    def test_unknown_keys_ignored(self):
        """Extra keys in the policy entry should not affect output."""
        policy = {"example.com": {"some_future_field": 42}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.allow is True  # Not affected by unknown key


# ---------------------------------------------------------------------------
# Convenience properties
# ---------------------------------------------------------------------------


class TestConvenienceProperties:
    """DomainPolicy exposes boolean flags for common checks."""

    def test_is_denied(self):
        policy = {"evil.com": {"deny": True}}
        result = interpret_domain_policy("https://evil.com", domain_policy=policy)
        assert result.is_denied is True

    def test_is_not_denied(self):
        result = interpret_domain_policy("https://example.com")
        assert result.is_denied is False

    def test_has_preference_true(self):
        policy = {"example.com": {"preferred_mode": "http_hardened"}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.has_preference is True

    def test_has_preference_false(self):
        result = interpret_domain_policy("https://example.com")
        assert result.has_preference is False

    def test_has_forbidden_true(self):
        policy = {"example.com": {"forbidden_modes": ["http_simple"]}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.has_forbidden is True

    def test_has_forbidden_false(self):
        result = interpret_domain_policy("https://example.com")
        assert result.has_forbidden is False

    def test_is_rate_limited_true(self):
        policy = {"example.com": {"rate_limit_ms": 1000}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.is_rate_limited is True

    def test_is_rate_limited_false(self):
        result = interpret_domain_policy("https://example.com")
        assert result.is_rate_limited is False


# ---------------------------------------------------------------------------
# Unit tests for internal helpers
# ---------------------------------------------------------------------------


class TestExtractDomainUnit:
    """Direct tests for _extract_domain."""

    def test_standard_url(self):
        assert _extract_domain("https://example.com/path") == "example.com"

    def test_no_scheme(self):
        assert _extract_domain("example.com") == "example.com"

    def test_empty_string(self):
        assert _extract_domain("") == ""

    def test_none(self):
        assert _extract_domain(None) == ""  # type: ignore[arg-type]

    def test_non_string(self):
        assert _extract_domain(123) == ""  # type: ignore[arg-type]

    def test_ipv4(self):
        assert _extract_domain("https://192.168.1.1:8080/path") == "192.168.1.1"

    def test_ipv6(self):
        assert _extract_domain("https://[::1]/path") == "::1"

    def test_lowercase(self):
        assert _extract_domain("https://EXAMPLE.COM") == "example.com"


class TestNormalisePreferredMode:
    """Direct tests for _normalise_preferred_mode."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("http_simple", "http_simple"),
            ("http_hardened", "http_hardened"),
            ("http_headless_browser", "http_headless_browser"),
            ("http_stealth", "http_stealth"),
            ("bogus", None),
            (None, None),
            (42, None),
            ([], None),
            ({}, None),
        ],
    )
    def test_normalisation(self, raw, expected):
        assert _normalise_preferred_mode(raw) == expected


class TestNormaliseForbiddenModes:
    """Direct tests for _normalise_forbidden_modes."""

    def test_filters_invalid(self):
        result = _normalise_forbidden_modes(["http_simple", "bogus", "http_stealth"])
        assert result == ("http_simple", "http_stealth")

    def test_not_a_list(self):
        result = _normalise_forbidden_modes("http_simple")
        assert result == ()

    def test_none(self):
        result = _normalise_forbidden_modes(None)
        assert result == ()

    def test_empty_list(self):
        result = _normalise_forbidden_modes([])
        assert result == ()

    def test_tuple(self):
        result = _normalise_forbidden_modes(("http_simple", "http_hardened"))
        assert result == ("http_simple", "http_hardened")


# ---------------------------------------------------------------------------
# Data class properties
# ---------------------------------------------------------------------------


class TestDataClass:
    """Verify DomainPolicy is well-formed."""

    def test_repr(self):
        result = interpret_domain_policy("https://example.com")
        r = repr(result)
        assert "example.com" in r

    def test_eq(self):
        a = interpret_domain_policy("https://example.com")
        b = interpret_domain_policy("https://example.com")
        assert a == b

    def test_not_eq_different_domain(self):
        a = interpret_domain_policy("https://example.com")
        b = interpret_domain_policy("https://other.com")
        assert a != b

    def test_hashable(self):
        result = interpret_domain_policy("https://example.com")
        assert hash(result) is not None
        s = {result}
        assert len(s) == 1


# ---------------------------------------------------------------------------
# Multiple domains in policy
# ---------------------------------------------------------------------------


class TestMultipleDomains:
    """Policy file with multiple domain entries."""

    POLICY = {
        "friendly.com": {"preferred_mode": "http_simple"},
        "tricky.com": {"preferred_mode": "http_hardened", "rate_limit_ms": 1000},
        "hostile.com": {"deny": True},
        "stealthy.com": {
            "preferred_mode": "http_stealth",
            "forbidden_modes": ["http_simple", "http_hardened"],
            "rate_limit_ms": 5000,
        },
    }

    def test_friendly(self):
        result = interpret_domain_policy("https://friendly.com", domain_policy=self.POLICY)
        assert result.allow is True
        assert result.preferred_mode == "http_simple"

    def test_tricky(self):
        result = interpret_domain_policy("https://tricky.com", domain_policy=self.POLICY)
        assert result.allow is True
        assert result.preferred_mode == "http_hardened"
        assert result.rate_limit_ms == 1000

    def test_hostile(self):
        result = interpret_domain_policy("https://hostile.com", domain_policy=self.POLICY)
        assert result.is_denied is True

    def test_stealthy(self):
        result = interpret_domain_policy("https://stealthy.com", domain_policy=self.POLICY)
        assert result.preferred_mode == "http_stealth"
        assert result.forbidden_modes == ("http_simple", "http_hardened")
        assert result.rate_limit_ms == 5000

    def test_unknown(self):
        result = interpret_domain_policy("https://unknown.com", domain_policy=self.POLICY)
        assert result.allow is True
        assert result.preferred_mode is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Miscellaneous edge cases."""

    def test_empty_policy_entry(self):
        policy = {"example.com": {}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.allow is True

    def test_allow_true_explicit(self):
        policy = {"example.com": {"allow": True}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        assert result.allow is True

    def test_notes_field_ignored(self):
        """notes in the policy entry should not appear in output fields."""
        policy = {"example.com": {"notes": "this is test data"}}
        result = interpret_domain_policy("https://example.com", domain_policy=policy)
        # notes is not on DomainPolicy, so it won't be there
        assert result.allow is True

    def test_url_with_fragment(self):
        result = interpret_domain_policy("https://example.com/page#section")
        assert result.domain == "example.com"

    def test_url_with_auth(self):
        result = interpret_domain_policy("https://user:pass@example.com/path")
        assert result.domain == "example.com"

    def test_non_http_scheme(self):
        result = interpret_domain_policy("ftp://files.example.com/data")
        assert result.domain == "files.example.com"