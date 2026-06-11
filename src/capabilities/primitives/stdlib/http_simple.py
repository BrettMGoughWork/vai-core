"""stdlib.http.simple — HTTP GET primitive (Phase 3.10.2).

Performs a real HTTP GET request using httpx and returns a structured
response matching the S0/S1 fetch schema.  Transport-level failures
(DNS, timeout, connection refused, SSL) are caught and returned as
structured errors; 4xx/5xx status codes are returned as successful
responses with the actual status_code included.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.strategy.types.fetch.errors import classify_exception
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class HttpSimpleFetchPrimitive(PrimitiveBase):
    """Perform an HTTP GET request returning status, body, headers, and elapsed time."""

    name = "stdlib.http.simple"
    description = "HTTP GET request returning status, body, headers, and elapsed time"
    primitive_type = PrimitiveType.PYTHON

    def __init__(self) -> None:
        super().__init__(
            name=self.name,
            description=self.description,
            primitive_type=self.primitive_type,
        )

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

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)

        url: str = args["url"]
        timeout: float | None = args.get("timeout")
        headers: dict[str, str] | None = args.get("headers")

        start = time.perf_counter()

        try:
            with httpx.Client() as client:
                response = client.get(
                    url,
                    timeout=timeout,
                    headers=headers,
                )
                elapsed_ms = int((time.perf_counter() - start) * 1000)

                return PrimitiveResult(
                    status="success",
                    data={
                        "ok": True,
                        "status_code": response.status_code,
                        "body": response.text,
                        "headers": dict(response.headers),
                        "elapsed_ms": elapsed_ms,
                    },
                )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            fetch_error = classify_exception(exc, url)

            return PrimitiveResult(
                status="error",
                data={
                    "ok": False,
                    "error_type": type(fetch_error).__name__,
                    "error_message": str(fetch_error),
                    "elapsed_ms": elapsed_ms,
                },
                error=str(fetch_error),
            )
