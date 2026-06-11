"""
Tests for the fallback router (PHASE 3.12.2).

Covers:
- Strict linear fallback chain
- Mode-specific timeouts
- Reasoning messages
- Error-type awareness (for reasoning only — chain does NOT branch)
- Nil error handling
- Invalid mode rejection
- should_give_up / should_retry flags
"""

from __future__ import annotations

import pytest

from src.strategy.types.fetch.errors import (
    ConnectionError,
    FetchError,
    HTTPError,
    ParseError,
    TimeoutError,
)
from src.strategy.types.fetch.fallback_router import (
    FallbackSelection,
    _FALLBACK_CHAIN,
    _MODE_TIMEOUTS,
    select_fallback,
)


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------

class TestFallbackRouterSmoke:
    """Basic sanity checks — the router exists and returns the expected shape."""

    def test_returns_fallback_selection(self):
        result = select_fallback("http_simple")
        assert isinstance(result, FallbackSelection)

    def test_has_required_fields(self):
        result = select_fallback("http_simple")
        assert hasattr(result, "next_mode")
        assert hasattr(result, "timeout_seconds")
        assert hasattr(result, "reasoning")

    def test_is_frozen(self):
        result = select_fallback("http_simple")
        with pytest.raises(Exception):
            result.next_mode = "give_up"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Strict linear fallback chain
# ---------------------------------------------------------------------------

class TestStrictChain:
    """The chain MUST be simple → hardened → browser → stealth → search → give_up."""

    @pytest.mark.parametrize(
        "current, expected_next",
        [
            ("http_simple", "http_hardened"),
            ("http_hardened", "http_headless_browser"),
            ("http_headless_browser", "http_stealth"),
            ("http_stealth", "search"),
            ("search", "give_up"),
        ],
    )
    def test_chain_step(self, current, expected_next):
        result = select_fallback(current)
        assert result.next_mode == expected_next

    def test_chain_never_skips(self):
        """No step should skip ahead in the chain."""
        # simple → headless would be a skip
        result = select_fallback("http_simple")
        assert result.next_mode != "http_headless_browser"
        # hardened → search would be a skip
        result = select_fallback("http_hardened")
        assert result.next_mode != "search"

    def test_chain_is_exhaustive(self):
        """All recognised modes must have a defined next step."""
        expected_keys = {
            "http_simple",
            "http_hardened",
            "http_headless_browser",
            "http_stealth",
            "search",
        }
        assert set(_FALLBACK_CHAIN.keys()) == expected_keys

    def test_give_up_is_terminal(self):
        assert "give_up" not in _FALLBACK_CHAIN


# ---------------------------------------------------------------------------
# Mode-specific timeouts
# ---------------------------------------------------------------------------

class TestTimeouts:
    """Every next_mode must carry the correct timeout."""

    @pytest.mark.parametrize(
        "current, expected_timeout",
        [
            ("http_simple", 15),            # → hardened
            ("http_hardened", 30),          # → headless
            ("http_headless_browser", 45),  # → stealth
            ("http_stealth", 10),           # → search
            ("search", 0),                  # → give_up
        ],
    )
    def test_timeout_per_step(self, current, expected_timeout):
        result = select_fallback(current)
        assert result.timeout_seconds == expected_timeout

    def test_all_timeout_keys_present(self):
        """Ensure all destinations have timeout entries."""
        for dest in set(_FALLBACK_CHAIN.values()):
            assert dest in _MODE_TIMEOUTS, f"Missing timeout for {dest}"

    def test_timeouts_are_positive_int_except_give_up(self):
        for mode, timeout in _MODE_TIMEOUTS.items():
            if mode == "give_up":
                assert timeout == 0
            else:
                assert timeout > 0
                assert isinstance(timeout, int)


# ---------------------------------------------------------------------------
# Error-type awareness (reasoning only)
# ---------------------------------------------------------------------------

class TestErrorAwareness:
    """The chain does NOT branch on error type, but reasoning includes it."""

    def test_timeout_reasoning_includes_error(self):
        err = TimeoutError(url="https://example.com", timeout=10.0, elapsed=5.0)
        result = select_fallback("http_simple", error=err)
        assert "TimeoutError" in result.reasoning

    def test_http_error_reasoning_includes_status(self):
        err = HTTPError(url="https://example.com", status_code=429)
        result = select_fallback("http_simple", error=err)
        assert "HTTPError" in result.reasoning

    def test_connection_error_reasoning(self):
        err = ConnectionError(url="https://example.com", message="refused")
        result = select_fallback("http_simple", error=err)
        assert "ConnectionError" in result.reasoning

    def test_parse_error_reasoning(self):
        err = ParseError(url="https://example.com", message="invalid JSON")
        result = select_fallback("http_simple", error=err)
        assert "ParseError" in result.reasoning

    def test_error_kind_in_reasoning(self):
        err = TimeoutError(url="https://example.com", timeout=10.0, elapsed=5.0)
        result = select_fallback("http_simple", error=err)
        assert "timeout" in result.reasoning.lower()

    def test_error_type_does_not_alter_chain(self):
        """Regardless of error type, the chain is identical."""
        timeout_err = TimeoutError(url="https://example.com", timeout=10.0, elapsed=5.0)
        conn_err = ConnectionError(url="https://example.com", message="oops")

        result_timeout = select_fallback("http_simple", error=timeout_err)
        result_conn = select_fallback("http_simple", error=conn_err)

        assert result_timeout.next_mode == result_conn.next_mode
        assert result_timeout.timeout_seconds == result_conn.timeout_seconds

    def test_nil_error_noop(self):
        """None error should not crash."""
        result = select_fallback("http_simple", error=None)
        assert result.next_mode == "http_hardened"

    def test_nil_error_reasoning_still_usable(self):
        result = select_fallback("http_simple", error=None)
        assert result.reasoning  # not empty


# ---------------------------------------------------------------------------
# should_give_up / should_retry
# ---------------------------------------------------------------------------

class TestTerminalFlags:
    """The FallbackSelection exposes convenience flags for terminal states."""

    def test_should_retry_true_for_intermediate_steps(self):
        for mode in ["http_simple", "http_hardened", "http_headless_browser", "http_stealth"]:
            result = select_fallback(mode)
            assert result.should_retry is True
            assert result.should_give_up is False

    def test_should_retry_false_at_end(self):
        # search → give_up means should_retry is False
        result = select_fallback("search")
        assert result.next_mode == "give_up"
        assert result.should_retry is False
        assert result.should_give_up is True

    def test_cannot_fallback_past_give_up(self):
        with pytest.raises(ValueError):
            select_fallback("give_up")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Invalid mode rejection
# ---------------------------------------------------------------------------

class TestInvalidMode:
    """select_fallback must reject unknown modes cleanly."""

    @pytest.mark.parametrize(
        "bad_mode",
        [
            "http_best_effort",
            "curl",
            "",
            "SIMPLE",
            "HTTP_SIMPLE",
            "http_simple_with_extra",
        ],
    )
    def test_raises_value_error_on_unknown_mode(self, bad_mode):
        with pytest.raises(ValueError, match="Unknown current_mode"):
            select_fallback(bad_mode)  # type: ignore[arg-type]

    def test_error_message_lists_valid_modes(self):
        with pytest.raises(ValueError) as exc_info:
            select_fallback("bogus_mode")  # type: ignore[arg-type]
        msg = str(exc_info.value)
        assert "http_simple" in msg
        assert "http_stealth" in msg


# ---------------------------------------------------------------------------
# Reasoning message quality
# ---------------------------------------------------------------------------

class TestReasoningMessages:
    """Reasoning must mention the current mode, next mode, and timeout."""

    def test_reasoning_mentions_current_mode(self):
        result = select_fallback("http_simple")
        assert "http_simple" in result.reasoning

    def test_reasoning_mentions_next_mode(self):
        result = select_fallback("http_simple")
        assert "http_hardened" in result.reasoning

    def test_reasoning_mentions_timeout(self):
        result = select_fallback("http_simple")
        assert "15" in result.reasoning or "timeout=15s" in result.reasoning

    def test_reasoning_is_human_readable(self):
        """Reasoning should be a single sentence, not a raw struct."""
        result = select_fallback("http_simple")
        assert len(result.reasoning) > 0
        assert not result.reasoning.startswith("{")
        assert not result.reasoning.startswith("[")


# ---------------------------------------------------------------------------
# Full chain walk
# ---------------------------------------------------------------------------

class TestFullChainWalk:
    """Walk the entire chain from start to give_up."""

    def test_full_walk(self):
        steps = []
        mode = "http_simple"
        while True:
            obj = select_fallback(mode)  # type: ignore[arg-type]
            steps.append((obj.next_mode, obj.timeout_seconds))
            if obj.should_give_up:
                break
            mode = obj.next_mode  # type: ignore[assignment]

        expected = [
            ("http_hardened", 15),
            ("http_headless_browser", 30),
            ("http_stealth", 45),
            ("search", 10),
            ("give_up", 0),
        ]
        assert steps == expected

    def test_full_walk_reasoning_does_not_repeat(self):
        """Each step's reasoning should be appropriate for its transition."""
        seen = set()
        mode = "http_simple"
        while True:
            obj = select_fallback(mode)  # type: ignore[arg-type]
            # Reasoning should include the current mode
            assert obj.next_mode not in seen  # shouldn't loop
            seen.add(obj.next_mode)
            if obj.should_give_up:
                break
            mode = obj.next_mode  # type: ignore[assignment]
        assert "give_up" in seen


# ---------------------------------------------------------------------------
# Immutability & data class properties
# ---------------------------------------------------------------------------

class TestDataClass:
    """Verify the FallbackSelection is well-formed."""

    def test_repr_contains_mode(self):
        result = select_fallback("http_simple")
        r = repr(result)
        assert "http_hardened" in r

    def test_eq_comparison(self):
        a = select_fallback("http_simple")
        b = select_fallback("http_simple")
        assert a == b

    def test_hashable(self):
        result = select_fallback("http_simple")
        assert hash(result) is not None
        # can be in a set
        s = {result}
        assert len(s) == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Miscellaneous edge-case behaviour."""

    def test_empty_error_message_in_reasoning(self):
        err = ConnectionError(url="https://example.com", message="")
        result = select_fallback("http_simple", error=err)
        assert result.next_mode == "http_hardened"

    def test_very_long_error_message(self):
        err = ConnectionError(url="https://example.com", message="x" * 10000)
        result = select_fallback("http_simple", error=err)
        assert result.next_mode == "http_hardened"

    def test_unicode_in_error_message(self):
        err = ConnectionError(url="https://example.com", message="🚫💥🔥")
        result = select_fallback("http_simple", error=err)
        assert result.next_mode == "http_hardened"

    def test_timeout_values_are_correct_for_all_chain_entries(self):
        """Spot-check the timeout dict itself."""
        assert _MODE_TIMEOUTS["http_simple"] == 10
        assert _MODE_TIMEOUTS["http_hardened"] == 15
        assert _MODE_TIMEOUTS["http_headless_browser"] == 30
        assert _MODE_TIMEOUTS["http_stealth"] == 45
        assert _MODE_TIMEOUTS["search"] == 10
        assert _MODE_TIMEOUTS["give_up"] == 0