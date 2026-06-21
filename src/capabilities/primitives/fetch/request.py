"""
FetchRequest — Immutable HTTP request descriptor for chainable fetch operations.

Represents every parameter needed to call an HTTP fetch (and, by extension,
any transport primitive) while remaining pure data — no network logic, no
side-effects.  Designed to be round-tripped through LLM JSON boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FetchRequest:
    """An immutable HTTP request descriptor.

    Attributes:
        url:     The target URL.
        method:  HTTP method (default ``"GET"``; reserved for future use).
        headers: Explicit request headers (string-to-string map).
        cookies: Key-value cookie map (serialised as ``Cookie`` header at call
                 time so the call site remains the single source of truth for
                 the wire format).
        timeout: Connection / read timeout in seconds (``None`` = no limit).
        body:    Request body (reserved for POST/PUT in later phases).
    """

    url: str
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    timeout: float | None = None
    body: str | None = None

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, d: dict) -> FetchRequest:
        """Construct a ``FetchRequest`` from an arbitrary dict (JSON round-trip).

        Unknown keys are silently ignored; missing optional keys fall back to
        their defaults.
        """
        return cls(
            url=str(d["url"]),
            method=str(d.get("method", "GET")),
            headers=dict(d.get("headers", {})),
            cookies=dict(d.get("cookies", {})),
            timeout=d.get("timeout"),
            body=d.get("body"),
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary suitable for LLM inspection."""
        from dataclasses import asdict

        return asdict(self)

    # ------------------------------------------------------------------
    # Primitive integration
    # ------------------------------------------------------------------

    def to_args(self) -> dict[str, Any]:
        """Return the argument dict expected by the HTTP fetch primitive.

        Cookies embedded in the request are rendered as a ``Cookie`` header so
        that the primitive (which is request/response‑unaware) sends them on the
        wire without any cooperation from its side.
        """
        args: dict[str, Any] = {"url": self.url}
        if self.timeout is not None:
            args["timeout"] = self.timeout

        headers = dict(self.headers)
        if self.cookies:
            cookie_str = "; ".join(
                f"{k}={v}" for k, v in self.cookies.items()
            )
            # Don't clobber an explicit Cookie header.
            headers.setdefault("Cookie", cookie_str)

        if headers:
            args["headers"] = headers

        return args
