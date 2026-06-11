"""stdlib.net.post — HTTP POST primitive (Phase 3.18.5)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class NetHttpPostPrimitive(PrimitiveBase):
    """Perform an HTTP POST request with a JSON or form body and return status, body, and headers."""

    name = "stdlib.net.post"
    description = "HTTP POST request returning status code, body, and headers"
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
                raise ValueError(f"'timeout' must be a number, got {type(timeout).__name__}")
            if timeout <= 0:
                raise ValueError(f"'timeout' must be positive, got {timeout}")
        if "headers" in args:
            headers = args["headers"]
            if not isinstance(headers, dict):
                raise ValueError(f"'headers' must be a dict, got {type(headers).__name__}")
        if "json" in args and "data" in args:
            raise ValueError("cannot specify both 'json' and 'data' keys")
        if "json" in args and not isinstance(args["json"], dict):
            raise ValueError(f"'json' must be a dict, got {type(args['json']).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        url: str = args["url"]
        timeout: float = args.get("timeout", 10.0)
        headers: dict[str, str] | None = args.get("headers")
        json_body: dict | None = args.get("json")
        data: str | None = args.get("data")

        start = time.perf_counter()
        try:
            with httpx.Client() as client:
                response = client.post(
                    url,
                    timeout=timeout,
                    headers=headers,
                    json=json_body,
                    data=data,
                )
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                return PrimitiveResult(
                    status="success",
                    data={
                        "status_code": response.status_code,
                        "body": response.text,
                        "headers": dict(response.headers),
                        "elapsed_ms": elapsed_ms,
                    },
                )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return PrimitiveResult(
                status="error",
                data={"elapsed_ms": elapsed_ms},
                error=f"{type(exc).__name__}: {exc}",
            )
