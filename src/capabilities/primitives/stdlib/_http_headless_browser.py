"""stdlib.http.headless_browser — Headless browser HTTP GET (Phase 3.11.2).

Uses Playwright to perform a JavaScript-capable HTTP GET with full DOM
rendering and dynamic content support.  ISOLATED from the fallback router
— no signal classification, no mode escalation, no multi-step fallback.
"""

from __future__ import annotations

import random
import time
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType

_playwright_available: bool
try:
    from playwright.sync_api import (
from src.strategy.types.validation import deadcode_ignore
        Error as PwError,
        TimeoutError as PwTimeoutError,
        sync_playwright,
    )

    _playwright_available = True
except ImportError:  # pragma: no cover
    _playwright_available = False
    sync_playwright = None  # type: ignore[assignment]
    PwTimeoutError = Exception
    PwError = Exception

# ---------------------------------------------------------------------------
# Browser-like default headers
# ---------------------------------------------------------------------------

_DEFAULT_HEADERS: dict[str, str] = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "*/*",
}

_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def _build_headers(user_headers: dict[str, str] | None) -> dict[str, str]:
    """Build the final headers dict.

    1. Start with browser-like defaults.
    2. Apply a random desktop User-Agent.
    3. Merge user-provided headers last (user overrides defaults).
    """
    headers = dict(_DEFAULT_HEADERS)
    headers["User-Agent"] = random.choice(_USER_AGENTS)
    if user_headers:
        headers.update(user_headers)
    return headers


def _classify_pw_exception(exc: Exception) -> tuple[str, str]:
    """Map a Playwright exception to (error_type, error_message)."""
    if isinstance(exc, PwTimeoutError):
        return "TimeoutError", str(exc)
    if isinstance(exc, PwError):
        msg = str(exc).lower()
        if "dns" in msg or "resolve" in msg or "dns" in type(exc).__name__.lower():
            return "ConnectionError", str(exc)
        if "refused" in msg or "connection" in msg:
            return "ConnectionError", str(exc)
        if "ssl" in msg or "certificate" in msg or "err_cert" in msg:
            return "ConnectionError", f"SSL/TLS error: {exc}"
        if "timeout" in msg or "timed out" in msg:
            return "TimeoutError", str(exc)
        return "ConnectionError", str(exc)
    return "ConnectionError", str(exc)


# ---------------------------------------------------------------------------
# Primitive
# ---------------------------------------------------------------------------


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class HttpHeadlessBrowserPrimitive(PrimitiveBase):
    """Headless browser HTTP GET with JS execution and DOM rendering."""

    name = "stdlib.http.headless_browser"
    description = (
        "Headless browser HTTP GET with JS execution, DOM rendering, "
        "and dynamic content support"
    )
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to load in the headless browser",
            },
            "timeout": {
                "type": "number",
                "description": "Timeout in seconds (must be positive)",
            },
            "headers": {
                "type": "object",
                "description": "Additional HTTP headers as key-value pairs",
            },
            "wait_until": {
                "type": "string",
                "enum": ["load", "domcontentloaded", "networkidle"],
                "description": "When to consider the page loaded",
            },
            "wait_ms": {
                "type": "number",
                "minimum": 0,
                "description": "Additional wait time in milliseconds after page load",
            },
        },
        "required": ["url"],
    }

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

        if "wait_until" in args:
            wu = args["wait_until"]
            if wu not in ("load", "domcontentloaded", "networkidle"):
                raise ValueError(
                    f"'wait_until' must be one of 'load', 'domcontentloaded', "
                    f"or 'networkidle', got {wu!r}"
                )

        if "wait_ms" in args:
            wm = args["wait_ms"]
            if not isinstance(wm, (int, float)):
                raise ValueError(
                    f"'wait_ms' must be a number, got {type(wm).__name__}"
                )
            if wm < 0:
                raise ValueError(f"'wait_ms' must be >= 0, got {wm}")

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)

        if not _playwright_available:
            return PrimitiveResult(
                status="error",
                data={
                    "ok": False,
                    "error_type": "MissingDependencyError",
                    "error_message": (
                        "Playwright is not installed. "
                        "Install it with: pip install playwright && "
                        "playwright install chromium"
                    ),
                    "elapsed_ms": 0,
                },
                error="Playwright not installed",
            )

        url: str = args["url"]
        timeout: float | None = args.get("timeout")
        user_headers: dict[str, str] | None = args.get("headers")
        wait_until: str = args.get("wait_until", "networkidle")
        wait_ms: int = args.get("wait_ms", 2000)

        final_headers = _build_headers(user_headers)

        start = time.perf_counter()

        try:
            with sync_playwright() as pw:  # type: ignore[arg-type]
                browser = pw.chromium.launch(headless=True)
                try:
                    page = browser.new_page()

                    # Capture the primary response for status code and headers
                    captured: dict[str, Any] = {"response": None}

                    def _on_response(resp: Any) -> None:
                        if captured["response"] is None:
                            captured["response"] = resp

                    page.on("response", _on_response)

                    timeout_ms = int((timeout or 30) * 1000)
                    page.goto(url, wait_until=wait_until, timeout=timeout_ms)

                    # Extra post-load wait for dynamic content
                    if wait_ms > 0:
                        time.sleep(wait_ms / 1000)

                    elapsed_ms = int((time.perf_counter() - start) * 1000)
                    body: str = page.content()
                    final_url: str = page.url

                    # Collect cookies from the browser context
                    cookies_raw = page.context.cookies()
                    cookies: dict[str, str] = {
                        c["name"]: c["value"] for c in cookies_raw
                    }

                    resp_obj = captured["response"]
                    status_code: int | None = resp_obj.status if resp_obj else None
                    headers: dict[str, str] | None = (
                        dict(resp_obj.headers) if resp_obj else None
                    )

                    return PrimitiveResult(
                        status="success",
                        data={
                            "ok": True,
                            "final_url": final_url,
                            "status_code": status_code,
                            "body": body,
                            "headers": headers,
                            "cookies": cookies,
                            "elapsed_ms": elapsed_ms,
                        },
                    )
                finally:
                    browser.close()
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            error_type, error_message = _classify_pw_exception(exc)
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
