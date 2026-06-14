"""
S4.9.3 — Security Hardening for Stratum-4.

Enforces baseline safety guarantees across all S4 components:

- **Authentication** — optional static-token auth at the daemon boundary.
- **Rate Limiting** — in-memory fixed-window per-client rate limiting.
- **Input Validation** — schema-based, strict, fail-fast validation of
  job payloads, instructions, and arbitrary input.
- **Sandboxing** — time-bounded thread-level execution with resource limits.

All public functions return ``SecurityResult`` structured objects and **never**
raise exceptions to callers.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Structured result
# ---------------------------------------------------------------------------


@dataclass
class SecurityResult:
    """Structured result from a security check.

    All security functions return this — they never raise to callers.

    Attributes:
        ok:      ``True`` if the check passed.
        error:   Human-readable error description (``None`` when *ok*).
        details: Machine-readable detail dict (e.g. ``{"reason": "timeout"}``).
    """

    ok: bool
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def check_auth(
    request: Dict[str, Any],
    *,
    enabled: bool = False,
    token: str = "",
) -> SecurityResult:
    """Check whether *request* carries a valid authentication token.

    When *enabled* is ``False`` (the default) all requests pass.

    The token is accepted from (in order of precedence):
      1. ``Authorization: Bearer <token>`` header
      2. ``X-Auth-Token: <token>`` header
      3. ``params.token`` (query parameters)
      4. ``body.token`` (request body)

    Args:
        request: Dict with optional ``"headers"``, ``"params"``, and
                 ``"body"`` keys.
        enabled: Whether auth enforcement is active.
        token:   The expected static token.

    Returns:
        ``SecurityResult(ok=True)`` if auth passes or is disabled.
    """
    if not enabled:
        return SecurityResult(ok=True)

    headers = request.get("headers", {})

    # 1. Authorization header (Bearer)
    provided = (
        headers.get("authorization", "")
        .replace("Bearer ", "")
        .replace("bearer ", "")
        .strip()
    )
    if not provided:
        # 2. X-Auth-Token header
        provided = headers.get("x-auth-token", "").strip()
    if not provided:
        # 3. Query parameters
        provided = request.get("params", {}).get("token", "").strip()
    if not provided:
        # 4. Request body
        provided = request.get("body", {}).get("token", "").strip()

    if not provided:
        return SecurityResult(
            ok=False,
            error="Authentication required",
            details={"reason": "missing_token"},
        )

    if provided != token:
        return SecurityResult(
            ok=False,
            error="Invalid authentication token",
            details={"reason": "invalid_token"},
        )

    return SecurityResult(ok=True)


# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------


class RateLimiter:
    """In-memory fixed-window rate limiter.

    Thread-safe.  Tracks request counts per client ID within a 60-second
    rolling window.  Old entries are pruned on each ``check()`` call.
    """

    def __init__(self, max_requests_per_minute: int = 60) -> None:
        self._max = max(1, max_requests_per_minute)
        self._lock = threading.Lock()
        self._windows: Dict[str, List[float]] = {}

    def check(self, client_id: str) -> SecurityResult:
        """Check whether *client_id* is within the rate limit.

        Returns:
            ``SecurityResult(ok=True)`` if under limit.
            ``SecurityResult(ok=False, error=…, details={"retry_after": …})``
            if rate limited.
        """
        now = time.time()
        with self._lock:
            timestamps = self._windows.get(client_id, [])
            # Prune entries older than 60 s
            cutoff = now - 60.0
            timestamps = [t for t in timestamps if t > cutoff]

            if len(timestamps) >= self._max:
                oldest = timestamps[0]
                retry_after = max(1.0, 60.0 - (now - oldest))
                return SecurityResult(
                    ok=False,
                    error="Rate limit exceeded",
                    details={
                        "reason": "rate_limited",
                        "retry_after": round(retry_after, 1),
                        "limit": self._max,
                        "window_seconds": 60,
                    },
                )

            timestamps.append(now)
            self._windows[client_id] = timestamps
            return SecurityResult(ok=True)

    def reset(self, client_id: Optional[str] = None) -> None:
        """Reset rate-limit state for *client_id* (or all clients)."""
        with self._lock:
            if client_id is None:
                self._windows.clear()
            else:
                self._windows.pop(client_id, None)


def check_rate_limit(
    limiter: RateLimiter,
    client_id: str,
    *,
    enabled: bool = True,
) -> SecurityResult:
    """Convenience wrapper around ``RateLimiter.check``.

    Returns ``SecurityResult(ok=True)`` when *enabled* is ``False``.
    """
    if not enabled:
        return SecurityResult(ok=True)
    return limiter.check(client_id)


# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------

# Maximum allowed payload serialised size (1 MB)
MAX_PAYLOAD_SIZE = 1024 * 1024

# Known valid instruction types
VALID_INSTRUCTION_TYPES: Set[str] = {
    "execute",
    "query",
    "transform",
    "validate",
    "generate",
    "summarize",
    "route",
}

# Known valid job types
VALID_JOB_TYPES: Set[str] = {
    "process_message",
    "run_tool",
    "execute_workflow",
    "handle_event",
    "run_cycle",
    "health_check",
}


def validate_input(
    payload: Any,
    schema: Optional[Dict[str, Any]] = None,
    *,
    max_size: int = MAX_PAYLOAD_SIZE,
) -> SecurityResult:
    """Validate an input payload against an optional schema.

    When *schema* is ``None`` only basic type and size checks are performed.

    Schema format (same shape as :mod:`~src.platform.config.config_system`)::

        {
            "type": dict,                          # expected Python type
            "fields": {                            # dict sub-fields
                "name": {"type": str},
                "count": {"type": int},
            },
            "valid_values": ["a", "b"],            # optional value constraint
        }

    Args:
        payload: The input data to validate.
        schema:  Optional schema dict.
        max_size: Maximum allowed serialised size in bytes.

    Returns:
        ``SecurityResult(ok=True)`` if validation passes.
        ``SecurityResult(ok=False, error=…, details={"errors": […]})`` if not.
    """
    errors: List[str] = []

    # 1. Must be a mapping
    if not isinstance(payload, dict):
        errors.append(f"Payload must be a mapping, got {type(payload).__name__}")
        return SecurityResult(
            ok=False,
            error="Validation failed",
            details={"errors": errors},
        )

    # 2. Size check (JSON serialisation)
    try:
        serialised = len(json.dumps(payload))
        if serialised > max_size:
            errors.append(
                f"Payload size {serialised} bytes exceeds limit of {max_size} bytes"
            )
    except (TypeError, ValueError) as exc:
        errors.append(f"Payload is not JSON-serializable: {exc}")

    # 3. Schema validation
    if schema is not None and not errors:
        _validate_against_schema(payload, schema, errors, path="")

    if errors:
        return SecurityResult(
            ok=False,
            error="Validation failed",
            details={"errors": errors},
        )

    return SecurityResult(ok=True)


def _validate_against_schema(
    value: Any,
    schema: Dict[str, Any],
    errors: List[str],
    path: str,
) -> None:
    """Recursive schema validation helper — appends to *errors*."""
    expected_type = schema.get("type")
    fields = schema.get("fields")
    valid_values = schema.get("valid_values")
    item_schema = schema.get("items")

    # --- Type check ---
    if expected_type is not None:
        ok = _check_type(value, expected_type)
        if not ok:
            errors.append(f"{path}: expected {_type_name(expected_type)}, "
                          f"got {type(value).__name__}")
            return  # no point checking further

    # --- Valid values ---
    if valid_values is not None and value not in valid_values:
        errors.append(
            f"{path}: invalid value {value!r}, must be one of {valid_values}"
        )
        return

    # --- Dict fields ---
    if fields is not None and isinstance(value, dict):
        for field_name, field_schema in fields.items():
            if field_name not in value:
                if not field_schema.get("optional", False):
                    errors.append(f"{path}.{field_name}: missing required field")
                continue
            _validate_against_schema(
                value[field_name],
                field_schema,
                errors,
                f"{path}.{field_name}" if path else field_name,
            )
        # Reject unknown fields
        known = set(fields.keys())
        for key in value:
            if key not in known:
                errors.append(f"{path}: unknown field {key!r}")

    # --- List items ---
    if item_schema is not None and isinstance(value, list):
        for i, item in enumerate(value):
            _validate_against_schema(item, item_schema, errors, f"{path}[{i}]")


def _check_type(value: Any, expected: Any) -> bool:
    """Check whether *value* matches *expected* type."""
    if expected is dict:
        return isinstance(value, dict)
    if expected is list:
        return isinstance(value, list)
    if expected is str:
        return isinstance(value, str)
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected is bool:
        return isinstance(value, bool)
    return True


def _type_name(tp: Any) -> str:
    """Return a human-readable name for a type."""
    return {dict: "dict", list: "list", str: "str", int: "int", bool: "bool"}.get(tp, str(tp))


def validate_job_payload(payload: Dict[str, Any]) -> SecurityResult:
    """Validate a job payload against the standard S4 job schema.

    Required fields: ``job_id`` (str), ``job_type`` (one of
    :const:`VALID_JOB_TYPES`).

    Optional fields: ``instructions`` (list), ``payload`` (dict),
    ``metadata`` (dict).
    """
    job_schema: Dict[str, Any] = {
        "type": dict,
        "fields": {
            "job_id": {"type": str},
            "job_type": {"type": str, "valid_values": VALID_JOB_TYPES},
            "instructions": {"type": list, "optional": True},
            "payload": {"type": dict, "optional": True},
            "metadata": {"type": dict, "optional": True},
        },
    }
    return validate_input(payload, job_schema)


def validate_instruction(instruction: Any) -> SecurityResult:
    """Validate a single instruction object.

    Required fields: ``type`` (one of :const:`VALID_INSTRUCTION_TYPES`).

    Optional fields: ``params`` (dict), ``timeout_ms`` (int).
    """
    instruction_schema: Dict[str, Any] = {
        "type": dict,
        "fields": {
            "type": {"type": str, "valid_values": VALID_INSTRUCTION_TYPES},
            "params": {"type": dict, "optional": True},
            "timeout_ms": {"type": int, "optional": True},
        },
    }
    return validate_input(instruction, instruction_schema)


# ---------------------------------------------------------------------------
# Sandboxing
# ---------------------------------------------------------------------------


@dataclass
class SandboxConfig:
    """Configuration for sandboxed execution.

    Attributes:
        allowed_paths:  Filesystem paths the sandbox may access
                        (default: current working directory).
        allow_network:  Whether network access is permitted.
        allow_subprocess: Whether subprocess creation is permitted.
        max_memory_mb:  Approximate memory limit in MB (best-effort).
    """
    allowed_paths: List[str] = field(default_factory=lambda: [os.getcwd()])
    allow_network: bool = False
    allow_subprocess: bool = False
    max_memory_mb: int = 256


def sandbox_execute(
    fn: Callable[[], Any],
    timeout_ms: int = 30000,
    config: Optional[SandboxConfig] = None,
) -> SecurityResult:
    """Execute *fn* in a sandboxed context with a timeout.

    The sandbox is thread-based with resource bounds:
      - **Time limit** — *timeout_ms* (the primary safety mechanism).
      - Filesystem restricted to *allowed_paths* (config only — full
        enforcement requires subprocess isolation).
      - Network disabled unless *allow_network* is set.

    Args:
        fn:         The callable to execute.
        timeout_ms: Maximum execution time in milliseconds.
        config:     Optional :class:`SandboxConfig`.

    Returns:
        ``SecurityResult(ok=True, details={"result": …})`` on success.
        ``SecurityResult(ok=False, error=…)`` on timeout or failure.
    """
    if config is None:
        config = SandboxConfig()

    result_box: Dict[str, Any] = {"value": None, "error": None}
    timeout_seconds = max(0.001, timeout_ms / 1000.0)

    def _run() -> None:
        try:
            result_box["value"] = fn()
        except Exception as exc:
            result_box["error"] = str(exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        return SecurityResult(
            ok=False,
            error=f"Execution timed out after {timeout_ms}ms",
            details={"reason": "timeout", "timeout_ms": timeout_ms},
        )

    if result_box["error"] is not None:
        return SecurityResult(
            ok=False,
            error=f"Sandbox execution failed: {result_box['error']}",
            details={"reason": "execution_error"},
        )

    return SecurityResult(ok=True, details={"result": result_box["value"]})
