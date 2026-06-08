"""
sanitisation — Public-safe response filter (PHASE 3.12.7).

Transforms an internal ``raw_response`` (which may contain internal mode
identifiers, signal data, fallback history, domain policy fields, and
other non-public metadata) into a clean, public-facing response that
exposes ONLY the fields allowed by the ``fetch_url`` interface.

Usage::

    from src.core.types.fetch.sanitisation import sanitise_response

    clean = sanitise_response(raw_response)
    # clean contains only: ok, status_code, final_url, headers, cookies,
    #                       body, elapsed_ms, error_type, error_message
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Public error categories (the ONLY error types the LLM may see)
# ---------------------------------------------------------------------------

_PUBLIC_ERROR_NETWORK = "NetworkError"
_PUBLIC_ERROR_TIMEOUT = "Timeout"
_PUBLIC_ERROR_INVALID = "InvalidResponse"
_PUBLIC_ERROR_BLOCKED = "Blocked"
_PUBLIC_ERROR_UNKNOWN = "UnknownError"

# ---------------------------------------------------------------------------
# Internal → public error type mapping
# ---------------------------------------------------------------------------

# Internal error types map to generic public categories.
# Any internal type NOT listed here falls through to "UnknownError".
_ERROR_TYPE_MAP: dict[str, str] = {
    # Network / transport layer
    "NetworkError": _PUBLIC_ERROR_NETWORK,
    "SSLError": _PUBLIC_ERROR_NETWORK,
    "ConnectionResetError": _PUBLIC_ERROR_NETWORK,
    "ConnectionError": _PUBLIC_ERROR_NETWORK,
    "DNSFailure": _PUBLIC_ERROR_NETWORK,
    "TransportError": _PUBLIC_ERROR_NETWORK,
    "ProtocolError": _PUBLIC_ERROR_NETWORK,
    # Timeouts
    "TimeoutError": _PUBLIC_ERROR_TIMEOUT,
    "ScriptTimeoutError": _PUBLIC_ERROR_TIMEOUT,
    "ConnectTimeout": _PUBLIC_ERROR_TIMEOUT,
    "ReadTimeout": _PUBLIC_ERROR_TIMEOUT,
    # Malformed / unparseable responses
    "ParseError": _PUBLIC_ERROR_INVALID,
    "InvalidResponse": _PUBLIC_ERROR_INVALID,
    "MalformedHtmlError": _PUBLIC_ERROR_INVALID,
    "EmptyBodyError": _PUBLIC_ERROR_INVALID,
    # Anti-bot / blocking
    "CloudflareBlockError": _PUBLIC_ERROR_BLOCKED,
    "DataDomeBlockError": _PUBLIC_ERROR_BLOCKED,
    "PerimeterXBlockError": _PUBLIC_ERROR_BLOCKED,
    "AkamaiBlockError": _PUBLIC_ERROR_BLOCKED,
    "CaptchaError": _PUBLIC_ERROR_BLOCKED,
    "BlockedError": _PUBLIC_ERROR_BLOCKED,
    "HTTP403": _PUBLIC_ERROR_BLOCKED,
    # Domain policy
    "DomainDeniedError": _PUBLIC_ERROR_BLOCKED,
    # Orchestrator-level
    "FetchFailedError": _PUBLIC_ERROR_UNKNOWN,
    "FetchExhaustedError": _PUBLIC_ERROR_UNKNOWN,
    # Generic HTTP errors
    "HTTPError": _PUBLIC_ERROR_NETWORK,
}

# ---------------------------------------------------------------------------
# Patterns to scrub from error messages
# ---------------------------------------------------------------------------

# Internal mode names — replace with generic phrase
_INTERNAL_MODE_NAMES = (
    "http_simple",
    "http_hardened",
    "http_headless_browser",
    "http_stealth",
)

# Phrases that leak internals — replaced with safe alternatives
_INTERNAL_PHRASES: list[tuple[str, str]] = [
    ("http_simple", "internal fetch strategy"),
    ("http_hardened", "internal fetch strategy"),
    ("http_headless_browser", "internal fetch strategy"),
    ("http_stealth", "internal fetch strategy"),
    ("fallback chain", "fetch pipeline"),
    ("signal", "analysis"),
    ("escalation", "retry"),
    ("domain policy", "site configuration"),
    ("rate_limit_ms", "timing"),
    ("redirect_count", "redirect"),
    ("browser-mode", "fetch"),
    ("headless", "fetch"),
    ("stealth", "fetch"),
    ("hydration", "request preparation"),
]

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sanitise_response(raw_response: dict[str, Any]) -> dict[str, Any]:
    """Return a public-safe response dict from *raw_response*.

    All internal metadata (mode, signals, fallback history, domain policy,
    hydration details, search provider, stack traces) is stripped.
    Error types and messages are rewritten into generic public categories.

    Parameters
    ----------
    raw_response:
        The raw internal response dict as described by the PHASE 3.12.7
        input schema.  Must contain ``ok``, ``status_code``, ``final_url``,
        ``headers``, ``cookies``, ``body``, ``elapsed_ms``, and an
        ``internal`` sub-dict.

    Returns
    -------
    dict
        A clean public response with ONLY the fields permitted by the
        ``fetch_url`` output schema.
    """
    # Extract internal blob (strip it immediately)
    internal = raw_response.get("internal", {})

    ok = bool(raw_response.get("ok", False))

    if ok:
        return _build_success(raw_response)
    else:
        return _build_failure(raw_response, internal)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_success(raw: dict[str, Any]) -> dict[str, Any]:
    """Build a success response with only public fields."""
    return {
        "ok": True,
        "status_code": _safe_int(raw.get("status_code"), 200),
        "final_url": _safe_str(raw.get("final_url")),
        "headers": _safe_dict(raw.get("headers")),
        "cookies": _safe_dict(raw.get("cookies")),
        "body": _safe_str(raw.get("body")),
        "elapsed_ms": _safe_int(raw.get("elapsed_ms"), 0),
    }


def _build_failure(raw: dict[str, Any], internal: dict[str, Any]) -> dict[str, Any]:
    """Build a failure response with sanitised error fields."""
    raw_error_type = internal.get("error_type") or raw.get("error_type") or ""
    raw_error_message = internal.get("error_message") or raw.get("error_message") or ""

    public_error_type = _map_error_type(raw_error_type)
    public_error_message = _sanitise_error_message(raw_error_message, public_error_type)

    return {
        "ok": False,
        "error_type": public_error_type,
        "error_message": public_error_message,
        "elapsed_ms": _safe_int(raw.get("elapsed_ms"), 0),
    }


def _map_error_type(raw_type: str) -> str:
    """Map an internal error type string to a public category."""
    if not raw_type:
        return _PUBLIC_ERROR_UNKNOWN
    return _ERROR_TYPE_MAP.get(raw_type, _PUBLIC_ERROR_UNKNOWN)


def _sanitise_error_message(raw_message: str, public_type: str) -> str:
    """Rewrite an internal error message into a generic public description.

    Scans for internal mode names, signal references, fallback terminology,
    and domain policy details, replacing them with generic phrases.
    """
    if not raw_message:
        return _generic_message_for(public_type)

    cleaned = raw_message

    # Replace internal phrases with generic alternatives
    for pattern, replacement in _INTERNAL_PHRASES:
        cleaned = cleaned.replace(pattern, replacement)

    # If the message is still suspiciously internal-looking, replace entirely
    if _contains_internal_markers(cleaned):
        return _generic_message_for(public_type)

    # Cap length to prevent verbose internal messages from leaking
    if len(cleaned) > 500:
        cleaned = cleaned[:497] + "..."

    return cleaned


def _generic_message_for(public_type: str) -> str:
    """Return a safe default message for a public error category."""
    defaults: dict[str, str] = {
        _PUBLIC_ERROR_NETWORK: "A network error occurred while fetching the URL.",
        _PUBLIC_ERROR_TIMEOUT: "The request timed out before a response was received.",
        _PUBLIC_ERROR_INVALID: "The response could not be processed.",
        _PUBLIC_ERROR_BLOCKED: "The request was blocked by the target site.",
        _PUBLIC_ERROR_UNKNOWN: "An unexpected error occurred while fetching the URL.",
    }
    return defaults.get(public_type, defaults[_PUBLIC_ERROR_UNKNOWN])


def _contains_internal_markers(message: str) -> bool:
    """Return True if *message* contains internal implementation details."""
    lower = message.lower()
    internal_keywords = (
        "http_simple",
        "http_hardened",
        "http_headless",
        "http_stealth",
        "signal:",
        "signals:",
        "cloudflare_challenge",
        "datadome_block",
        "perimeterx_block",
        "akamai_bot",
        "captcha_present",
        "js_required",
        "blank_html",
        "hydration_error",
        "script_timeout",
        "json_endpoint_detected",
        "redirect_loop",
        "ssl_error",
        "connection_reset",
        "malformed_html",
        "empty_body",
        "suspicious_meta_refresh",
        "fallback_history",
        "escalation_chain",
        "forbidden_mode",
        "preferred_mode",
        "search_provider",
        "browser_metadata",
        "__traceback__",
        "File \"",
        "line ",
    )
    for keyword in internal_keywords:
        if keyword in lower:
            return True
    return False


# ---------------------------------------------------------------------------
# Type coercers (defensive against malformed input)
# ---------------------------------------------------------------------------


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce *value* to int, returning *default* on failure."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _safe_str(value: Any) -> str:
    """Coerce *value* to str, returning "" on failure."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        return ""


def _safe_dict(value: Any) -> dict[str, str]:
    """Coerce *value* to a ``dict[str, str]``, returning ``{}`` on failure."""
    if value is None:
        return {}
    if isinstance(value, dict):
        result: dict[str, str] = {}
        for k, v in value.items():
            result[str(k)] = str(v) if v is not None else ""
        return result
    return {}
