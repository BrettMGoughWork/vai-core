"""stdlib.fetch — Unified fetch primitive with multi-mode fallback.

This is the ONLY fetch tool exposed to the LLM.  Individual strategies
(http_simple, http_hardened, http_headless_browser, http_stealth) are
internal implementation detail — the orchestrator selects and escalates
between them transparently.

Usage::

    from src.capabilities.primitives.fetch.fetch_primitive import FetchPrimitive

    primitive = FetchPrimitive()
    result = primitive.execute({"url": "https://example.com"}, {})
"""

from __future__ import annotations

from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType

from .fetch_url import FetchResult, fetch_url
from .request import FetchRequest
from .response import FetchResponse


class FetchPrimitive(PrimitiveBase):
    """Unified fetch primitive with transparent multi-mode fallback.

    Accepts a URL and optional parameters.  Internally runs the full
    orchestrator pipeline: domain policy → mode selection → execution
    → signal extraction → fallback → sanitisation.  The LLM sees only
    a single ``stdlib.fetch`` tool.
    """

    name = "stdlib.fetch"
    description = (
        "Fetch a URL with automatic fallback through multiple strategies "
        "(simple HTTP, hardened, headless browser, stealth). "
        "Use this for ALL web fetching — it will pick the best approach."
    )
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to fetch."},
            "timeout": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "Request timeout in seconds.",
            },
            "headers": {
                "type": "object",
                "description": "Optional HTTP headers as key-value pairs.",
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
    # Internal executor factory
    # ------------------------------------------------------------------

    @staticmethod
    def _build_executor() -> Any:
        """Build the executor that dispatches mode strings to fetch strategies.

        The individual strategies are imported lazily so optional
        dependencies (curl_cffi, playwright) don't block registration.
        """
        from src.capabilities.primitives.stdlib._http_simple import (
            HttpSimpleFetchPrimitive,
        )

        primitives: dict[str, Any] = {
            "http_simple": HttpSimpleFetchPrimitive(),
        }

        # Optional: hardened (needs curl_cffi)
        try:
            from src.capabilities.primitives.stdlib._http_hardened import (
                HttpHardenedFetchPrimitive,
            )
            primitives["http_hardened"] = HttpHardenedFetchPrimitive()
        except ImportError:
            pass

        # Optional: headless browser (needs playwright)
        try:
            from src.capabilities.primitives.stdlib._http_headless_browser import (
                HttpHeadlessBrowserPrimitive,
            )
            primitives["http_headless_browser"] = HttpHeadlessBrowserPrimitive()
        except ImportError:
            pass

        # Optional: stealth (needs playwright + playwright_stealth)
        try:
            from src.capabilities.primitives.stdlib._http_stealth import (
                HttpStealthPrimitive,
            )
            primitives["http_stealth"] = HttpStealthPrimitive()
        except ImportError:
            pass

        def _exec(mode: str, request: FetchRequest) -> FetchResponse:
            primitive = primitives.get(mode)
            if primitive is None:
                return FetchResponse(
                    ok=False,
                    url=request.url,
                    elapsed_ms=0,
                    error_type="UnsupportedModeError",
                    error_message=f"no primitive for mode '{mode}'",
                )
            result = primitive.execute(request.to_args(), {})
            if result.status == "success":
                return FetchResponse.from_primitive_result(
                    result.data, url=request.url
                )
            return FetchResponse(
                ok=False,
                url=request.url,
                elapsed_ms=int(result.data.get("elapsed_ms", 0)),
                error_type=result.data.get("error_type", "UnknownError"),
                error_message=result.data.get(
                    "error_message", str(result.error or "")
                ),
            )

        return _exec

    # ------------------------------------------------------------------
    # Public API
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

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)

        url: str = args["url"]
        timeout: float | None = args.get("timeout")
        headers: dict[str, str] | None = args.get("headers")

        executor = self._build_executor()

        result: FetchResult = fetch_url(
            url,
            timeout=timeout,
            headers=headers,
            executor=executor,
        )

        if result.ok:
            return PrimitiveResult(
                status="success",
                data={
                    "ok": True,
                    "status_code": result.status_code,
                    "final_url": result.final_url,
                    "headers": result.headers,
                    "cookies": result.cookies,
                    "body": result.body,
                    "elapsed_ms": result.elapsed_ms,
                },
            )
        else:
            return PrimitiveResult(
                status="error",
                data={
                    "ok": False,
                    "error_type": result.error_type,
                    "error_message": result.error_message,
                    "elapsed_ms": result.elapsed_ms,
                },
                error=result.error_message or result.error_type or "Fetch failed",
            )
