"""
Tests for the PHASE 3.12.7 sanitisation layer.

Verifies that ``sanitise_response`` strips ALL internal fields
and rewrites error types/messages into public-safe categories.
"""

from __future__ import annotations

import pytest

from src.core.types.fetch.sanitisation import sanitise_response


# ============================================================================
# Helpers
# ============================================================================


def _raw_success(**overrides) -> dict:
    """Build a raw internal success response."""
    base = {
        "ok": True,
        "status_code": 200,
        "final_url": "https://example.com/page",
        "headers": {"content-type": "text/html"},
        "cookies": {"session": "abc123"},
        "body": "<html><body>Hello</body></html>",
        "elapsed_ms": 150,
        "internal": {
            "mode": "http_simple",
            "signals": {"js_required": False, "blank_html": False},
            "fallback_history": [],
            "policy": {"preferred_mode": None, "forbidden_modes": []},
            "hydration": {"headers_added": 2},
            "search_provider": None,
            "error_type": None,
            "error_message": None,
            "stack": None,
        },
    }
    base.update(overrides)
    return base


def _raw_failure(**overrides) -> dict:
    """Build a raw internal failure response."""
    base = {
        "ok": False,
        "status_code": None,
        "final_url": None,
        "headers": None,
        "cookies": {},
        "body": None,
        "elapsed_ms": 3000,
        "internal": {
            "mode": "http_simple",
            "signals": {"connection_reset": True},
            "fallback_history": ["http_simple→http_hardened"],
            "policy": {"preferred_mode": None, "forbidden_modes": []},
            "hydration": {},
            "search_provider": None,
            "error_type": "NetworkError",
            "error_message": "connection reset by peer",
            "stack": "Traceback (most recent call last):\n  File ...",
        },
    }
    base.update(overrides)
    return base


# ============================================================================
# Success path
# ============================================================================


class TestSuccessSanitisation:
    """Success responses preserve public fields, strip internal."""

    def test_public_fields_preserved(self):
        raw = _raw_success()
        result = sanitise_response(raw)

        assert result["ok"] is True
        assert result["status_code"] == 200
        assert result["final_url"] == "https://example.com/page"
        assert result["headers"] == {"content-type": "text/html"}
        assert result["cookies"] == {"session": "abc123"}
        assert result["body"] == "<html><body>Hello</body></html>"
        assert result["elapsed_ms"] == 150

    def test_no_internal_field(self):
        raw = _raw_success()
        result = sanitise_response(raw)

        assert "internal" not in result
        assert "mode" not in result
        assert "signals" not in result
        assert "fallback_history" not in result
        assert "policy" not in result
        assert "hydration" not in result
        assert "search_provider" not in result
        assert "stack" not in result

    def test_no_error_fields_on_success(self):
        raw = _raw_success()
        result = sanitise_response(raw)

        assert "error_type" not in result
        assert "error_message" not in result

    def test_none_body(self):
        raw = _raw_success(body=None)
        result = sanitise_response(raw)
        assert result["body"] == ""

    def test_null_headers_and_cookies(self):
        raw = _raw_success(headers=None, cookies=None)
        result = sanitise_response(raw)
        assert result["headers"] == {}
        assert result["cookies"] == {}


# ============================================================================
# Failure path — error type mapping
# ============================================================================


class TestErrorTypeMapping:
    """Internal error types → public categories."""

    @pytest.mark.parametrize(
        "raw_type,expected",
        [
            ("NetworkError", "NetworkError"),
            ("SSLError", "NetworkError"),
            ("ConnectionResetError", "NetworkError"),
            ("ConnectionError", "NetworkError"),
            ("DNSFailure", "NetworkError"),
            ("TransportError", "NetworkError"),
            ("ProtocolError", "NetworkError"),
            ("HTTPError", "NetworkError"),
            ("TimeoutError", "Timeout"),
            ("ScriptTimeoutError", "Timeout"),
            ("ConnectTimeout", "Timeout"),
            ("ReadTimeout", "Timeout"),
            ("ParseError", "InvalidResponse"),
            ("InvalidResponse", "InvalidResponse"),
            ("MalformedHtmlError", "InvalidResponse"),
            ("EmptyBodyError", "InvalidResponse"),
            ("CloudflareBlockError", "Blocked"),
            ("DataDomeBlockError", "Blocked"),
            ("PerimeterXBlockError", "Blocked"),
            ("AkamaiBlockError", "Blocked"),
            ("CaptchaError", "Blocked"),
            ("BlockedError", "Blocked"),
            ("HTTP403", "Blocked"),
            ("DomainDeniedError", "Blocked"),
            ("FetchFailedError", "UnknownError"),
            ("FetchExhaustedError", "UnknownError"),
        ],
    )
    def test_error_type_mapped(self, raw_type, expected):
        raw = _raw_failure(ok=False)
        raw["internal"]["error_type"] = raw_type
        result = sanitise_response(raw)

        assert result["ok"] is False
        assert result["error_type"] == expected

    def test_unrecognised_type_becomes_unknown(self):
        raw = _raw_failure(ok=False)
        raw["internal"]["error_type"] = "WeirdCustomThing"
        result = sanitise_response(raw)

        assert result["error_type"] == "UnknownError"

    def test_missing_error_type_becomes_unknown(self):
        raw = _raw_failure(ok=False)
        raw["internal"]["error_type"] = ""
        result = sanitise_response(raw)

        assert result["error_type"] == "UnknownError"


# ============================================================================
# Failure path — error message sanitisation
# ============================================================================


class TestErrorMessageSanitisation:
    """Internal error messages are rewritten to generic descriptions."""

    def test_internal_mode_names_scrubbed(self):
        raw = _raw_failure()
        raw["internal"]["error_type"] = "NetworkError"
        raw["internal"][
            "error_message"
        ] = "http_simple failed: connection reset; fell back to http_hardened"

        result = sanitise_response(raw)

        assert "http_simple" not in result["error_message"]
        assert "http_hardened" not in result["error_message"]
        assert "internal fetch strategy" in result["error_message"]

    def test_signal_names_removed(self):
        raw = _raw_failure()
        raw["internal"]["error_type"] = "NetworkError"
        raw["internal"][
            "error_message"
        ] = "cloudflare_challenge detected, signal extraction failed"

        result = sanitise_response(raw)

        assert "cloudflare_challenge" not in result["error_message"].lower()

    def test_heavily_internal_message_replaced(self):
        """Message with many internal markers gets replaced with generic."""
        raw = _raw_failure()
        raw["internal"]["error_type"] = "NetworkError"
        raw["internal"]["error_message"] = (
            "http_simple→http_hardened escalation: js_required=True, "
            "blank_html=True, hydration_error=True, script_timeout=False"
        )

        result = sanitise_response(raw)

        # Should have been replaced with generic (contains too many internal markers)
        assert result["error_message"] == "A network error occurred while fetching the URL."

    def test_empty_message_gets_generic(self):
        raw = _raw_failure()
        raw["internal"]["error_type"] = "TimeoutError"
        raw["internal"]["error_message"] = ""

        result = sanitise_response(raw)

        assert result["error_message"] == (
            "The request timed out before a response was received."
        )

    def test_stack_trace_removed(self):
        raw = _raw_failure()
        raw["internal"]["error_type"] = "NetworkError"
        raw["internal"]["error_message"] = (
            "something broke\n"
            "File \"C:\\code\\http_fetch.py\", line 42, in fetch\n"
            "    raise ConnectionError(msg)\n"
            "__traceback__: ..."
        )

        result = sanitise_response(raw)

        # Stack trace markers should trigger full replacement
        assert "File \"" not in result["error_message"]
        assert "__traceback__" not in result["error_message"]

    def test_long_message_truncated(self):
        raw = _raw_failure()
        raw["internal"]["error_type"] = "NetworkError"
        raw["internal"]["error_message"] = "An error with a very long description. " * 30

        result = sanitise_response(raw)

        assert len(result["error_message"]) <= 500


# ============================================================================
# Failure path — output shape
# ============================================================================


class TestFailureShape:
    """Failure responses have correct shape with no internal leaks."""

    def test_public_fields_only(self):
        raw = _raw_failure()
        result = sanitise_response(raw)

        assert set(result.keys()) == {"ok", "error_type", "error_message", "elapsed_ms"}

    def test_no_internal_leakage(self):
        raw = _raw_failure()
        result = sanitise_response(raw)

        assert "internal" not in result
        assert "mode" not in result
        assert "signals" not in result
        assert "fallback_history" not in result
        assert "policy" not in result
        assert "hydration" not in result
        assert "search_provider" not in result
        assert "stack" not in result
        assert "status_code" not in result  # failure omits this
        assert "body" not in result  # failure omits this
        assert "final_url" not in result  # failure omits this

    def test_elapsed_ms_preserved(self):
        raw = _raw_failure()
        raw["elapsed_ms"] = 4242
        result = sanitise_response(raw)

        assert result["elapsed_ms"] == 4242


# ============================================================================
# Edge cases
# ============================================================================


class TestEdgeCases:
    """Corner cases for defensive sanitisation."""

    def test_missing_internal_key(self):
        """Response with no 'internal' key at all."""
        raw = {
            "ok": True,
            "status_code": 200,
            "final_url": "https://example.com",
            "headers": {},
            "cookies": {},
            "body": "ok",
            "elapsed_ms": 50,
        }
        result = sanitise_response(raw)

        assert result["ok"] is True
        assert result["status_code"] == 200
        assert result["body"] == "ok"

    def test_empty_internal_dict(self):
        raw = _raw_failure()
        raw["internal"] = {}
        result = sanitise_response(raw)

        assert result["ok"] is False
        assert result["error_type"] == "UnknownError"

    def test_none_values_everywhere(self):
        raw = {
            "ok": False,
            "status_code": None,
            "final_url": None,
            "headers": None,
            "cookies": None,
            "body": None,
            "elapsed_ms": None,
            "internal": {
                "mode": None,
                "signals": None,
                "fallback_history": None,
                "policy": None,
                "hydration": None,
                "search_provider": None,
                "error_type": None,
                "error_message": None,
                "stack": None,
            },
        }
        result = sanitise_response(raw)

        assert result["ok"] is False
        assert result["elapsed_ms"] == 0
        assert result["error_type"] == "UnknownError"
        assert "internal" not in result

    def test_error_type_from_top_level_fallback(self):
        """If internal.error_type is missing, top-level error_type is used."""
        raw = {
            "ok": False,
            "status_code": None,
            "final_url": None,
            "headers": None,
            "cookies": {},
            "body": None,
            "elapsed_ms": 100,
            "error_type": "TimeoutError",
            "error_message": "top-level timeout",
            "internal": {},
        }
        result = sanitise_response(raw)

        assert result["ok"] is False
        assert result["error_type"] == "Timeout"
        assert result["error_message"] == "top-level timeout"

    def test_every_error_type_mapped(self):
        """All entries in _ERROR_TYPE_MAP produce valid output."""
        from src.core.types.fetch.sanitisation import _ERROR_TYPE_MAP

        for raw_type in _ERROR_TYPE_MAP:
            raw = _raw_failure()
            raw["internal"]["error_type"] = raw_type
            result = sanitise_response(raw)

            assert result["error_type"] in (
                "NetworkError",
                "Timeout",
                "InvalidResponse",
                "Blocked",
                "UnknownError",
            ), f"{raw_type!r} mapped to unexpected {result['error_type']!r}"
