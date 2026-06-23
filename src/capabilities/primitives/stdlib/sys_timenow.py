"""stdlib.sys.timenow — Get the current system time (Phase 3.18.8)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class SysTimeNowPrimitive(PrimitiveBase):
    """Get the current system time in various formats."""

    name = "stdlib.sys.timenow"
    description = "Get the current system time"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "description": "Output format: 'iso8601' (default), 'unix', 'unix_ms', 'readable', or a Python strftime pattern",
                "enum": ["iso8601", "unix", "unix_ms", "readable"],
            },
            "timezone": {
                "type": "string",
                "description": "IANA timezone name (e.g. 'America/New_York', 'Europe/London') — defaults to UTC",
            },
        },
        "required": [],
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
        fmt = args.get("format")
        if fmt is not None and not isinstance(fmt, str):
            raise ValueError(f"args['format'] must be a string, got {type(fmt).__name__}")
        tz = args.get("timezone")
        if tz is not None and not isinstance(tz, str):
            raise ValueError(f"args['timezone'] must be a string, got {type(tz).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        fmt = args.get("format", "iso8601")
        tz = args.get("timezone")

        now = time.time()
        if tz:
            import zoneinfo
from src.domain._markers import deadcode_ignore
            try:
                dt = datetime.fromtimestamp(now, tz=zoneinfo.ZoneInfo(tz))
            except Exception:
                dt = datetime.fromtimestamp(now, tz=timezone.utc)
        else:
            dt = datetime.fromtimestamp(now, tz=timezone.utc)

        if fmt == "iso8601":
            formatted = dt.isoformat()
        elif fmt == "unix":
            formatted = int(now)
        elif fmt == "unix_ms":
            formatted = int(now * 1000)
        elif fmt == "readable":
            formatted = dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        else:
            formatted = dt.strftime(fmt)

        return PrimitiveResult(
            status="success",
            data={
                "timestamp": now,
                "timestamp_ms": int(now * 1000),
                "datetime": dt.isoformat(),
                "formatted": formatted,
                "timezone": str(dt.tzinfo) if dt.tzinfo else "UTC",
            },
        )
