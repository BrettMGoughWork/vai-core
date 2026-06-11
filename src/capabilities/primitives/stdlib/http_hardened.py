"""stdlib.http.hardened — Hardened HTTP GET primitive (Phase 3.11.1).

Uses curl_cffi with anti-bot headers, retry envelope, and persistent
cookie jar.  ISOLATED from the fallback router — no signal classification,
no mode escalation, no multi-step fallback.
"""

from __future__ import annotations

import random
import time
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType

_curl_cffi_available: bool
try:
    from curl_cffi.requests import Session
    from curl_cffi.requests.exceptions import (
from src.strategy.types.validation import deadcode_ignore
        ConnectTimeout,
        ConnectionError as CurlConnectionError,
        DNSError,
        HTTPError as CurlHTTPError,
        InvalidURL,
        MissingSchema,
        ProxyError,
        ReadTimeout,
        RequestException,
        SSLError,
        Timeout,
    )

    _curl_cffi_available = True
except ImportError:  # pragma: no cover
    _curl_cffi_available = False
    # Allow module to be importable even if curl_cffi is not installed —
    # the execute() method will raise at call time.
    Session = None  # type: ignore[assignment,misc]
    RequestException = Exception

# ---------------------------------------------------------------------------
# Rotating user agents
# ---------------------------------------------------------------------------

_USER_AGENTS: list[str] = [
    # Chrome 120 on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Chrome 119 on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    # Firefox 121 on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    # Edge 120 on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    # Chrome 120 on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# ---------------------------------------------------------------------------
# Default anti-bot headers (User-Agent is set per-request via rotation)
# ---------------------------------------------------------------------------

_DEFAULT_HEADERS: dict[str, str] = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "*/*",
}


def _build_headers(user_headers: dict[str, str] | None) -> dict[str, str]:
    """Build the final headers dict.

    1. Start with anti-bot defaults.
    2. Apply a random User-Agent.
    3. Merge user-provided headers last (user overrides defaults).
    """
    headers = dict(_DEFAULT_HEADERS)
    headers["User-Agent"] = random.choice(_USER_AGENTS)
    if user_headers:
        headers.update(user_headers)
    return headers


def _classify_curl_exception(
    exc: RequestException,
) -> tuple[str, str]:
    """Map a curl_cffi exception to (error_type, error_message).

    This is the hardened primitive's own classification — it does NOT
    reuse the httpx-based ``classify_exception`` from ``errors.py`` so
    that the two primitives remain fully decoupled.
    """
    if isinstance(exc, (Timeout, ConnectTimeout, ReadTimeout)):
        return "TimeoutError", str(exc)
    if isinstance(exc, SSLError):
        return "ConnectionError", f"SSL/TLS error: {exc}"
    if isinstance(exc, (CurlConnectionError, DNSError, ProxyError)):
        return "ConnectionError", str(exc)
    if isinstance(exc, (InvalidURL, MissingSchema)):
        return "ParseError", str(exc)
    if isinstance(exc, CurlHTTPError):
        return "HTTPError", str(exc)
    return "ConnectionError", str(exc)


# ---------------------------------------------------------------------------
# Primitive
# ---------------------------------------------------------------------------


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class HttpHardenedFetchPrimitive(PrimitiveBase):
    """Hardened HTTP GET with anti-bot headers, retries, and cookie jar."""

    name = "stdlib.http.hardened"
    description = (
        "Hardened HTTP GET with anti-bot headers, retry envelope, "
        "persistent cookie jar"
    )
    primitive_type = PrimitiveType.PYTHON

    def __init__(self) -> None:
        super().__init__(
            name=self.name,
            description=self.description,
            primitive_type=self.primitive_type,
        )

    # ------------------------------------------------------------------
    # Argument validation
    # ------------------------------------------------------------------

    def validate_args(self, args: dict) -> None:
        if not isinstance(args, dict):
            raise ValueError(f"args must be a dict, got {type(args).__name__}")
        if "url" not in args:
            raise ValueError("args must contain 'url' key")
        url = args["url"]
        if not isinstance(url, str):
            raise ValueError(f"'url' must be a string, got {type(url).__name__}")
        if not url:
            raise ValueError("'url' must not be empty")

        if "timeout" in args:
            timeout = args["timeout"]
            if not isinstance(timeout, (int, float)):
                raise ValueError(
                    f"'timeout' must be a number, got {type(timeout).__name__}"
                )
            if timeout <= 0:
                raise ValueError(f"'timeout' must be positive, got {timeout}")

        if "headers" in args:
            headers = args["headers"]
            if not isinstance(headers, dict):
                raise ValueError(
                    f"'headers' must be a dict, got {type(headers).__name__}"
                )
            for k, v in headers.items():
                if not isinstance(k, str):
                    raise ValueError(
                        f"'headers' keys must be strings, got {type(k).__name__}"
                    )
                if not isinstance(v, str):
                    raise ValueError(
                        f"'headers' values must be strings, got {type(v).__name__}"
                    )

        if "max_retries" in args:
            mr = args["max_retries"]
            if not isinstance(mr, int):
                raise ValueError(
                    f"'max_retries' must be an integer, got {type(mr).__name__}"
                )
            if mr < 0:
                raise ValueError(f"'max_retries' must be >= 0, got {mr}")

        if "backoff_base_ms" in args:
            bb = args["backoff_base_ms"]
            if not isinstance(bb, (int, float)):
                raise ValueError(
                    f"'backoff_base_ms' must be a number, got {type(bb).__name__}"
                )
            if bb <= 0:
                raise ValueError(f"'backoff_base_ms' must be positive, got {bb}")

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)

        if not _curl_cffi_available:
            return PrimitiveResult(
                status="error",
                data={
                    "ok": False,
                    "error_type": "MissingDependencyError",
                    "error_message": (
                        "curl_cffi is not installed. "
                        "Install it with: pip install curl-cffi"
                    ),
                    "elapsed_ms": 0,
                },
                error="curl_cffi not installed",
            )

        url: str = args["url"]
        timeout: float | None = args.get("timeout")
        user_headers: dict[str, str] | None = args.get("headers")
        max_retries: int = args.get("max_retries", 3)
        backoff_base_ms: float = args.get("backoff_base_ms", 200)

        final_headers = _build_headers(user_headers)

        start = time.perf_counter()
        last_error: RequestException | None = None

        session: Session = Session()
        try:
            for attempt in range(max_retries + 1):
                try:
                    response = session.get(
                        url,
                        timeout=timeout,
                        headers=final_headers,
                        impersonate="chrome120",
                    )
                    elapsed_ms = int((time.perf_counter() - start) * 1000)

                    return PrimitiveResult(
                        status="success",
                        data={
                            "ok": True,
                            "status_code": response.status_code,
                            "body": response.text,
                            "headers": dict(response.headers),
                            "cookies": {
                                k: v for k, v in response.cookies.items()
                            },
                            "elapsed_ms": elapsed_ms,
                        },
                    )

                except RequestException as exc:
                    last_error = exc

                    # Don't sleep on the last attempt
                    if attempt < max_retries:
                        delay_ms = backoff_base_ms * (2**attempt)
                        # Add jitter: ±25% of delay
                        jitter = delay_ms * random.uniform(-0.25, 0.25)
                        time.sleep((delay_ms + jitter) / 1000)

            # All retries exhausted
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            error_type, error_message = _classify_curl_exception(
                last_error  # type: ignore[arg-type]
            )

            return PrimitiveResult(
                status="error",
                data={
                    "ok": False,
                    "error_type": error_type,
                    "error_message": error_message,
                    "elapsed_ms": elapsed_ms,
                },
                error=error_message,
            )

        finally:
            session.close()
