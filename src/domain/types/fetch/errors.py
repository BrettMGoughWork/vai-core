"""
FetchError Taxonomy — Canonical error types for the fetch subsystem.

All errors emitted by fetch primitives and consumed across strata. This module
is fully isolated: no fetch logic, no network calls, no logging. Pure dataclasses
only — classify_exception lives in the infrastructure layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.domain._markers import deadcode_ignore


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

    ``body`` and ``headers`` are captured so consumers can inspect error pages
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
