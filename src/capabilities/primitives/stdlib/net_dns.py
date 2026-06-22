"""stdlib.net.dns — DNS lookup primitive (Phase 3.18.5)."""

from __future__ import annotations

import socket
import time

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class NetDnsLookupPrimitive(PrimitiveBase):
    """Resolve a hostname to IP addresses using getaddrinfo."""

    name = "stdlib.net.dns"
    description = "Resolve a hostname to IP addresses"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "hostname": {
                "type": "string",
                "description": "Hostname to resolve (e.g. 'github.com')",
            },
        },
        "required": ["hostname"],
    }

    def __init__(self) -> None:
        super().__init__(
            name=self.name,
            description=self.description,
            primitive_type=self.primitive_type,
        )

    def validate_args(self, args: dict) -> None:
        if not isinstance(args, dict):
            raise ValueError(f"args must be a dict, got {type(args).__name__}")
        if "hostname" not in args:
            raise ValueError("args must contain 'hostname' key")
        hostname = args["hostname"]
        if not isinstance(hostname, str):
            raise ValueError(f"'hostname' must be a string, got {type(hostname).__name__}")
        if not hostname:
            raise ValueError("'hostname' must not be empty")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        hostname: str = args["hostname"]

        start = time.perf_counter()
        try:
            info = socket.getaddrinfo(hostname, None)
            addresses: list[str] = []
            seen: set[str] = set()
            for family, _type, _proto, _canonname, sockaddr in info:
                ip = sockaddr[0]
                if ip not in seen:
                    seen.add(ip)
                    addresses.append(ip)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return PrimitiveResult(
                status="success",
                data={
                    "hostname": hostname,
                    "addresses": addresses,
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
