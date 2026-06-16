"""
FetchError Taxonomy — Complete error classification for the fetch subsystem.

All errors emitted by S0/S1 fetch primitives and consumed by S2/S3. This module
is fully isolated: no fetch logic, no network calls, no logging. Safe to extend
in 3.11 (hardened modes) and 3.12 (fallback chain).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

import httpx

from src.runtime._markers import deadcode_ignore


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FetchError(Exception):
    """Common base for all fetch-related errors.

    Subclasses must set ``kind`` to a fixed literal string identifying the
    error category (``"timeout"``, ``"http"``, ``"parse"``, ``"connection"``).

    Every subclass is a frozen dataclass, so instances are hashable, immutable,
    and trivially JSON-serializable via :func:`dataclasses.asdict`.
    """

    kind: str = field(default="fetch", init=False)

    def __str__(self) -> str:
        return f"[{self.kind}] fetch error"

    def to_dict(self) -> dict:
        """Return a JSON-safe dictionary representation."""
        from dataclasses import asdict

        return asdict(self)


# ---------------------------------------------------------------------------
# Concrete error types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TimeoutError(FetchError):
    """The request exceeded its allotted time budget.

    ``elapsed`` records how long the request actually ran before being
    cancelled, which lets callers distinguish between near-miss timeouts
    and severely under-provisioned budgets.
    """

    url: str
    timeout: float
    elapsed: float
    kind: str = field(default="timeout", init=False)

    def __str__(self) -> str:
        return (
            f"[timeout] {self.url} -- "
            f"timed out after {self.elapsed:.1f}s "
            f"(limit {self.timeout:.1f}s)"
        )


@dataclass(frozen=True)
class HTTPError(FetchError):
    """The server responded, but with a non-2xx status code.

    ``body`` and ``headers`` are captured so S2/S3 can inspect error pages
    (e.g. Cloudflare challenge pages, API error payloads) without re-fetching.
    """

    url: str
    status_code: int
    body: str | None = None
    headers: dict[str, str] | None = None
    kind: str = field(default="http", init=False)

    def __str__(self) -> str:
        body_preview = ""
        if self.body:
            snippet = self.body[:120].replace("\n", " ")
            body_preview = f" -- {snippet}"
        return f"[http {self.status_code}] {self.url}{body_preview}"


@deadcode_ignore(reason="Part of fetch error taxonomy, instantiated via classify_exception()")
@dataclass(frozen=True)
class ParseError(FetchError):
    """The response body could not be interpreted.

    Covers JSON decode failures, unexpected content types, and any other
    structural mismatch between the raw response and the expected schema.
    """

    url: str
    message: str
    body: str | None = None
    kind: str = field(default="parse", init=False)

    def __str__(self) -> str:
        return f"[parse] {self.url} -- {self.message}"


@deadcode_ignore(reason="Part of fetch error taxonomy, instantiated via classify_exception()")
@dataclass(frozen=True)
class ConnectionError(FetchError):
    """A transport-level failure prevented any response from being received.

    Covers DNS failures, refused connections, TLS errors, and read errors
    mid-stream.  The ``message`` field carries the underlying OS / library
    error string.
    """

    url: str
    message: str
    kind: str = field(default="connection", init=False)

    def __str__(self) -> str:
        return f"[connection] {self.url} -- {self.message}"


# ---------------------------------------------------------------------------
# Exception classification (pure -- no network calls, no logging)
# ---------------------------------------------------------------------------


def classify_exception(exc: Exception, url: str) -> FetchError:
    """Map a raw exception to the appropriate :class:`FetchError` subtype.

    This is the single entry-point for translating library-level exceptions
    (``httpx``, ``json``, etc.) into the deterministic taxonomy that S2/S3
    can reason about.

    Mapping rules
    -------------
    * ``httpx.TimeoutException`` -> :class:`TimeoutError`
    * ``httpx.ConnectError``     -> :class:`ConnectionError`
    * ``httpx.ReadError``        -> :class:`ConnectionError`
    * ``httpx.HTTPStatusError``  -> :class:`HTTPError`
    * ``ValueError``             -> :class:`ParseError`
    * ``json.JSONDecodeError``   -> :class:`ParseError`
    * everything else            -> :class:`ConnectionError` (safe default)
    """
    if isinstance(exc, httpx.TimeoutException):
        timeout_val: float = getattr(exc, "timeout", 0.0) or 0.0
        elapsed: float = 0.0
        try:
            req = exc.request  # property may raise RuntimeError if unset
            if req is not None:
                elapsed = getattr(req, "elapsed", 0.0) or 0.0
        except RuntimeError:
            pass
        return TimeoutError(
            url=url,
            timeout=float(timeout_val),
            elapsed=float(elapsed),
        )

    if isinstance(exc, httpx.ConnectError):
        return ConnectionError(url=url, message=_exc_message(exc))

    if isinstance(exc, httpx.ReadError):
        return ConnectionError(url=url, message=_exc_message(exc))

    if isinstance(exc, httpx.HTTPStatusError):
        body: str | None = None
        headers: dict[str, str] | None = None
        if exc.response is not None:
            try:
                body = exc.response.text
            except Exception:
                body = "<unreadable body>"
            headers = dict(exc.response.headers)
        return HTTPError(
            url=url,
            status_code=exc.response.status_code if exc.response is not None else 0,
            body=body,
            headers=headers,
        )

    if isinstance(exc, json.JSONDecodeError):
        return ParseError(url=url, message=_exc_message(exc), body=getattr(exc, "doc", None))

    if isinstance(exc, ValueError):
        return ParseError(url=url, message=_exc_message(exc))

    # Safe fallback: treat unknown exceptions as connection-level failures.
    return ConnectionError(url=url, message=_exc_message(exc))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _exc_message(exc: BaseException) -> str:
    """Extract a concise message from any exception, falling back to the type name."""
    msg = str(exc).strip()
    return msg if msg else type(exc).__name__
