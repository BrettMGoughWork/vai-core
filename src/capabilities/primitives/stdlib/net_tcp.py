"""stdlib.net.tcp — TCP port check primitive (Phase 3.18.5)."""

from __future__ import annotations

import socket
import time

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class NetTcpCheckPrimitive(PrimitiveBase):
    """Check if a TCP port on a host is open or closed."""

    name = "stdlib.net.tcp"
    description = "Check whether a TCP port on a host is open"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "host": {
                "type": "string",
                "description": "Hostname or IP address to connect to",
            },
            "port": {
                "type": "integer",
                "minimum": 1,
                "maximum": 65535,
                "description": "TCP port number to check",
            },
            "timeout": {
                "type": "number",
                "description": "Connection timeout in seconds (default: 5)",
            },
        },
        "required": ["host", "port"],
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
        if "host" not in args:
            raise ValueError("args must contain 'host' key")
        host = args["host"]
        if not isinstance(host, str):
            raise ValueError(f"'host' must be a string, got {type(host).__name__}")
        if not host:
            raise ValueError("'host' must not be empty")
        if "port" not in args:
            raise ValueError("args must contain 'port' key")
        port = args["port"]
        if not isinstance(port, int):
            raise ValueError(f"'port' must be an integer, got {type(port).__name__}")
        if not 1 <= port <= 65535:
            raise ValueError(f"'port' must be between 1 and 65535, got {port}")
        if "timeout" in args:
            timeout = args["timeout"]
            if not isinstance(timeout, (int, float)):
                raise ValueError(f"'timeout' must be a number, got {type(timeout).__name__}")
            if timeout <= 0:
                raise ValueError(f"'timeout' must be positive, got {timeout}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        host: str = args["host"]
        port: int = args["port"]
        timeout: float = args.get("timeout", 5.0)

        start = time.perf_counter()
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return PrimitiveResult(
                status="success",
                data={
                    "host": host,
                    "port": port,
                    "open": True,
                    "elapsed_ms": elapsed_ms,
                },
            )
        except (socket.timeout, ConnectionRefusedError, OSError) as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return PrimitiveResult(
                status="success",
                data={
                    "host": host,
                    "port": port,
                    "open": False,
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
