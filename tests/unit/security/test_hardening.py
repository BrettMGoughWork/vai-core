"""Unit tests for S4.9.3 Security Hardening.

Covers:
- Authentication (disabled, missing token, invalid token, valid token via
  every supported transport)
- Rate Limiting (within limit, over limit, window expiry, reset, disabled)
- Input Validation (valid, invalid type, oversized, unknown fields, missing
  required fields, invalid values)
- Job payload validation (valid, invalid job_type)
- Instruction validation (valid, invalid type)
- Sandboxing (success, timeout, execution error)
"""

from __future__ import annotations

import time
from typing import Any, Dict

import pytest

from src.platform.security.hardening import (
    SecurityResult,
    check_auth,
    RateLimiter,
    check_rate_limit,
    validate_input,
    validate_job_payload,
    validate_instruction,
    SandboxConfig,
    sandbox_execute,
)

# ===================================================================
# Authentication
# ===================================================================


class TestAuth:
    def test_disabled_passes(self):
        """When auth is disabled, all requests pass."""
        result = check_auth({}, enabled=False, token="secret")
        assert result.ok is True

    def test_disabled_passes_even_without_token(self):
        """Disabled auth does not check for a token at all."""
        result = check_auth({"headers": {}}, enabled=False, token="")
        assert result.ok is True

    def test_enabled_missing_token(self):
        """Enabled auth without any token should fail."""
        result = check_auth({"headers": {}}, enabled=True, token="secret")
        assert result.ok is False
        assert "Authentication required" in (result.error or "")

    def test_enabled_wrong_token(self):
        """Enabled auth with wrong token should fail."""
        result = check_auth(
            {"headers": {"authorization": "Bearer wrong"}},
            enabled=True,
            token="secret",
        )
        assert result.ok is False
        assert "Invalid authentication token" in (result.error or "")

    def test_authorization_header(self):
        """Bearer token in Authorization header should pass."""
        result = check_auth(
            {"headers": {"authorization": "Bearer secret"}},
            enabled=True,
            token="secret",
        )
        assert result.ok is True

    def test_authorization_header_lowercase_bearer(self):
        """Lowercase 'bearer' prefix should also work."""
        result = check_auth(
            {"headers": {"authorization": "bearer secret"}},
            enabled=True,
            token="secret",
        )
        assert result.ok is True

    def test_x_auth_token_header(self):
        """Token in X-Auth-Token header should pass."""
        result = check_auth(
            {"headers": {"x-auth-token": "secret"}},
            enabled=True,
            token="secret",
        )
        assert result.ok is True

    def test_query_param(self):
        """Token in query params should pass."""
        result = check_auth(
            {"params": {"token": "secret"}},
            enabled=True,
            token="secret",
        )
        assert result.ok is True

    def test_body_token(self):
        """Token in request body should pass."""
        result = check_auth(
            {"body": {"token": "secret"}},
            enabled=True,
            token="secret",
        )
        assert result.ok is True

    def test_empty_token_when_enabled(self):
        """Enabled auth with empty expected token requires a token."""
        result = check_auth({"headers": {}}, enabled=True, token="")
        assert result.ok is False


# ===================================================================
# Rate Limiting
# ===================================================================


class TestRateLimiter:
    def test_within_limit(self):
        """Requests under the limit should pass."""
        limiter = RateLimiter(max_requests_per_minute=5)
        for _ in range(5):
            result = limiter.check("client-1")
            assert result.ok is True

    def test_exceeds_limit(self):
        """Requests over the limit should be rejected."""
        limiter = RateLimiter(max_requests_per_minute=3)
        for _ in range(3):
            limiter.check("client-1")  # should pass
        result = limiter.check("client-1")  # should fail
        assert result.ok is False
        assert "Rate limit exceeded" in (result.error or "")
        assert "retry_after" in result.details

    def test_different_clients_independent(self):
        """Different clients have independent counters."""
        limiter = RateLimiter(max_requests_per_minute=2)
        assert limiter.check("client-a").ok is True
        assert limiter.check("client-a").ok is True
        assert limiter.check("client-a").ok is False  # client-a limited
        assert limiter.check("client-b").ok is True   # client-b still okay

    def test_reset_client(self):
        """Resetting a specific client clears its counter."""
        limiter = RateLimiter(max_requests_per_minute=1)
        assert limiter.check("client-1").ok is True
        assert limiter.check("client-1").ok is False  # limited
        limiter.reset("client-1")
        assert limiter.check("client-1").ok is True   # reset

    def test_reset_all(self):
        """Resetting all clients clears all counters."""
        limiter = RateLimiter(max_requests_per_minute=1)
        assert limiter.check("a").ok is True
        assert limiter.check("b").ok is True
        assert limiter.check("a").ok is False
        limiter.reset()
        assert limiter.check("a").ok is True
        assert limiter.check("b").ok is True

    def test_disabled_check_passes(self):
        """check_rate_limit with enabled=False always passes."""
        limiter = RateLimiter(max_requests_per_minute=1)
        # Saturate the limiter
        limiter.check("client-1")
        limiter.check("client-1")  # would be limited
        # But with enabled=False, it should pass
        result = check_rate_limit(limiter, "client-1", enabled=False)
        assert result.ok is True

    def test_min_max_one(self):
        """max_requests_per_minute should floor at 1."""
        limiter = RateLimiter(max_requests_per_minute=0)
        assert limiter._max == 1


# ===================================================================
# Input Validation
# ===================================================================


class TestValidateInput:
    def test_valid_payload(self):
        """Valid payload against a simple schema should pass."""
        schema = {
            "type": dict,
            "fields": {
                "name": {"type": str},
            },
        }
        result = validate_input({"name": "test"}, schema)
        assert result.ok is True

    def test_invalid_type(self):
        """Non-dict payload should fail."""
        result = validate_input("not_a_dict")
        assert result.ok is False
        assert "must be a mapping" in (result.details.get("errors", [None])[0] or "")

    def test_oversized_payload(self, monkeypatch):
        """Payload exceeding max_size should fail."""
        big = {"data": "x" * 2_000_000}
        with monkeypatch.context() as m:
            m.setattr("src.platform.security.hardening.MAX_PAYLOAD_SIZE", 100)
            result = validate_input(big)
        assert result.ok is False
        assert "exceeds limit" in (result.details.get("errors", [None])[0] or "")

    def test_unknown_fields_rejected(self):
        """Payload with fields not in schema should fail."""
        schema = {
            "type": dict,
            "fields": {
                "known": {"type": str},
            },
        }
        result = validate_input({"known": "ok", "unknown": "bad"}, schema)
        assert result.ok is False
        assert "unknown field" in (result.details.get("errors", [None])[0] or "")

    def test_missing_required_field(self):
        """Payload missing a required field should fail."""
        schema = {
            "type": dict,
            "fields": {
                "required_field": {"type": str},
            },
        }
        result = validate_input({}, schema)
        assert result.ok is False
        assert "missing required field" in (result.details.get("errors", [None])[0] or "")

    def test_optional_field_allowed_missing(self):
        """Optional field that is missing should not fail."""
        schema = {
            "type": dict,
            "fields": {
                "name": {"type": str, "optional": True},
            },
        }
        result = validate_input({}, schema)
        assert result.ok is True

    def test_invalid_field_type(self):
        """Field with wrong type should fail."""
        schema = {
            "type": dict,
            "fields": {
                "count": {"type": int},
            },
        }
        result = validate_input({"count": "not_an_int"}, schema)
        assert result.ok is False
        assert "expected int" in (result.details.get("errors", [None])[0] or "")

    def test_invalid_valid_value(self):
        """Field value outside valid_values should fail."""
        schema = {
            "type": dict,
            "fields": {
                "level": {"type": str, "valid_values": ["a", "b"]},
            },
        }
        result = validate_input({"level": "c"}, schema)
        assert result.ok is False
        assert "invalid value" in (result.details.get("errors", [None])[0] or "")

    def test_nested_schema_validation(self):
        """Nested dict fields should be validated recursively."""
        schema: Dict[str, Any] = {
            "type": dict,
            "fields": {
                "inner": {
                    "type": dict,
                    "fields": {
                        "value": {"type": int},
                    },
                },
            },
        }
        result = validate_input({"inner": {"value": 42}}, schema)
        assert result.ok is True

        result = validate_input({"inner": {"value": "wrong"}}, schema)
        assert result.ok is False

    def test_list_of_items_schema(self):
        """List with item schema should validate each element."""
        schema: Dict[str, Any] = {
            "type": dict,
            "fields": {
                "items": {
                    "type": list,
                    "items": {"type": str},
                },
            },
        }
        result = validate_input({"items": ["a", "b"]}, schema)
        assert result.ok is True

        result = validate_input({"items": ["a", 42]}, schema)
        assert result.ok is False

    def test_no_schema_type_check_only(self):
        """Without a schema, only basic type and size checks run."""
        # List payloads are rejected (must be dict)
        result = validate_input([1, 2, 3])
        assert result.ok is False

    def test_validates_job_payload(self):
        """Standard job payload validation — valid case."""
        result = validate_job_payload({
            "job_id": "test-1",
            "job_type": "run_tool",
        })
        assert result.ok is True

    def test_validates_job_payload_invalid_type(self):
        """Job payload with invalid job_type should fail."""
        result = validate_job_payload({
            "job_id": "test-1",
            "job_type": "nonexistent_job",
        })
        assert result.ok is False

    def test_validates_job_payload_missing_job_id(self):
        """Job payload missing job_id should fail."""
        result = validate_job_payload({
            "job_type": "run_tool",
        })
        assert result.ok is False

    def test_validates_instruction(self):
        """Instruction validation — valid case."""
        result = validate_instruction({
            "type": "execute",
            "params": {"cmd": "echo hello"},
        })
        assert result.ok is True

    def test_validates_instruction_invalid_type(self):
        """Instruction with invalid type should fail."""
        result = validate_instruction({
            "type": "invalid_type",
        })
        assert result.ok is False


# ===================================================================
# Sandboxing
# ===================================================================


class TestSandbox:
    def test_successful_execution(self):
        """Function that completes within timeout should return result."""
        result = sandbox_execute(lambda: 42, timeout_ms=5000)
        assert result.ok is True
        assert result.details.get("result") == 42

    def test_timeout(self):
        """Function that exceeds timeout should fail."""
        result = sandbox_execute(lambda: time.sleep(10), timeout_ms=50)
        assert result.ok is False
        assert "timed out" in (result.error or "")
        assert result.details.get("reason") == "timeout"

    def test_execution_error(self):
        """Function that raises should return error."""
        def _crash() -> None:
            raise ValueError("something broke")

        result = sandbox_execute(_crash, timeout_ms=5000)
        assert result.ok is False
        assert result.details.get("reason") == "execution_error"

    def test_custom_sandbox_config(self):
        """SandboxConfig should be accepted and propagated."""
        cfg = SandboxConfig(
            allowed_paths=["/tmp"],
            allow_network=False,
            allow_subprocess=False,
            max_memory_mb=128,
        )
        result = sandbox_execute(lambda: "ok", timeout_ms=5000, config=cfg)
        assert result.ok is True
        assert result.details.get("result") == "ok"

    def test_return_value_types(self):
        """Sandbox should handle various return value types."""
        for val in [None, True, "hello", [1, 2, 3], {"key": 42}]:
            result = sandbox_execute(lambda v=val: v, timeout_ms=5000)
            assert result.ok is True
            assert result.details.get("result") == val
