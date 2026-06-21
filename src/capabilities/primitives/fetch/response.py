"""
FetchResponse — Immutable HTTP response descriptor for chainable fetch operations.

Captures everything returned by an HTTP fetch (success or error) plus parsed
cookies for subsequent request hydration.  Pure data — no network logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .request import FetchRequest


def _parse_set_cookie(value: str) -> dict[str, str]:
    """Parse a ``Set-Cookie`` header value into a ``{name: value}`` map.

    Only the first ``key=value`` pair (the actual cookie) is extracted;
    attributes such as ``Path``, ``Domain``, ``Max-Age``, ``Secure``,
    ``HttpOnly`` and ``SameSite`` are discarded.  Multiple ``Set-Cookie``
    headers from the same origin are handled by the caller (see
    :meth:`FetchResponse.from_primitive_result`).
    """
    pairs: dict[str, str] = {}
    for part in value.split(";"):
        part = part.strip()
        if "=" in part and not _is_cookie_attribute(part):
            name, _, val = part.partition("=")
            pairs[name.strip()] = val.strip()
        elif not _is_cookie_attribute(part) and part:
            # Valueless cookie flag (rare but valid: e.g. "debug")
            pairs[part] = ""
    # Crumb-like cookies may still need dedup — take the last value per name.
    return pairs


# Lower-cased set of known cookie attributes so we can skip them.
_COOKIE_ATTRS = frozenset(
    {
        "path",
        "domain",
        "expires",
        "max-age",
        "secure",
        "httponly",
        "samesite",
        "priority",
    }
)


def _is_cookie_attribute(part: str) -> bool:
    """Return ``True`` if *part* looks like a cookie attribute rather than a name=value pair."""
    name = part.split("=", 1)[0].strip().lower()
    return name in _COOKIE_ATTRS


def _extract_cookies(headers: dict[str, str]) -> dict[str, str]:
    """Collect all cookies from response headers.

    Handles single ``Set-Cookie`` entries as well as the (non‑standard but
    common) practice of folding multiple cookies into one header.
    """
    cookies: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() == "set-cookie":
            cookies.update(_parse_set_cookie(value))
    return cookies


@dataclass(frozen=True)
class FetchResponse:
    """An immutable HTTP response descriptor.

    Attributes:
        ok:            Whether the request completed at the transport level.
        status_code:   HTTP status code (``None`` on transport failures).
        body:          Response body as a UTF‑8 string (``None`` on transport failures).
        headers:       Response headers (string-to-string map).
        cookies:       Parsed ``Set-Cookie`` key-value pairs.
        elapsed_ms:    Wall-clock time in milliseconds.
        url:           The request URL that produced this response.
        error_type:    Machine-readable error class (e.g. ``"TimeoutError"``).
        error_message: Human-readable error description.
    """

    ok: bool
    status_code: int | None = None
    body: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    elapsed_ms: int = 0
    url: str = ""
    error_type: str | None = None
    error_message: str | None = None

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def from_primitive_result(cls, data: dict, url: str = "") -> FetchResponse:
        """Construct a ``FetchResponse`` from an HTTP fetch primitive return value.

        *data* is the raw dictionary returned by the primitive (either the
        success or error form).  *url* is the original request URL (used for
        traceability; it is also present inside the data dict on error).
        """
        ok = bool(data.get("ok", False))
        elapsed_ms = int(data.get("elapsed_ms", 0))
        headers = dict(data.get("headers", {}))
        # Merge cookies extracted from Set-Cookie headers with cookies the
        # primitive returned directly (e.g. browser or hardened primitives
        # that already provide a parsed cookies map).  Direct cookies win.
        cookies = _extract_cookies(headers)
        extra_cookies = dict(data.get("cookies", {}))
        cookies.update(extra_cookies)
        return cls(
            ok=ok,
            status_code=data.get("status_code"),
            body=data.get("body"),
            headers=headers,
            cookies=cookies,
            elapsed_ms=elapsed_ms,
            url=url or str(data.get("url", "")),
            error_type=str(data["error_type"]) if "error_type" in data else None,
            error_message=str(data["error_message"]) if "error_message" in data else None,
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary suitable for LLM inspection.

        Omits ``None`` values so that success responses are not cluttered with
        error fields and vice‑versa.
        """
        from dataclasses import asdict

        raw = asdict(self)
        return {k: v for k, v in raw.items() if v is not None}

    # ------------------------------------------------------------------
    # Chaining
    # ------------------------------------------------------------------

    def hydrate_next_request(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> FetchRequest:
        """Create a new :class:`FetchRequest` pre‑filled with this response's cookies.

        Typical usage::

            resp = fetch_url("https://example.com/login")
            req2 = resp.hydrate_next_request("https://example.com/dashboard")
            resp2 = fetch_url(req2.to_args())

        The returned request's ``Cookie`` header is set from the parsed cookies
        of this response.  Explicit *headers* are merged on top (caller wins),
        and *timeout* falls back to the primitive default when ``None``.
        """
        cookies = dict(self.cookies)
        merged_headers = dict(headers or {})

        # Serialise cookies as a Cookie header if not already provided.
        if cookies and "Cookie" not in merged_headers:
            merged_headers["Cookie"] = "; ".join(
                f"{k}={v}" for k, v in cookies.items()
            )

        return FetchRequest(
            url=url,
            headers=merged_headers,
            timeout=timeout,
            cookies=cookies,
        )
