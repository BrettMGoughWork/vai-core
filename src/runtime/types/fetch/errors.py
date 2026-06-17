"""
FetchError Taxonomy — Runtime exception classification.

Error types are re-exported from the domain stratum (canonical home).
The classify_exception function lives here because it depends on httpx.
"""

from __future__ import annotations

import json

import httpx

from src.domain.types.fetch.errors import ConnectionError as ConnectionError
from src.domain.types.fetch.errors import FetchError as FetchError
from src.domain.types.fetch.errors import HTTPError as HTTPError
from src.domain.types.fetch.errors import ParseError as ParseError
from src.domain.types.fetch.errors import TimeoutError as TimeoutError


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
