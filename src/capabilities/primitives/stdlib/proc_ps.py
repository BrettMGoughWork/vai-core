"""stdlib.proc.ps — List running processes (Phase 3.18.9)."""

from __future__ import annotations

import sys
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


class ProcPsPrimitive(PrimitiveBase):
    """List running processes on the system."""

    name = "stdlib.proc.ps"
    description = "List running processes"
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
        if "name_filter" in args and not isinstance(args["name_filter"], str):
            raise ValueError(f"args['name_filter'] must be a string, got {type(args['name_filter']).__name__}")
        if "limit" in args and not isinstance(args["limit"], int):
            raise ValueError(f"args['limit'] must be an integer, got {type(args['limit']).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        name_filter: str | None = args.get("name_filter")
        limit: int = args.get("limit", 50)

        try:
            if sys.platform == "win32":
                # Use WMIC on Windows
                import subprocess
                result = subprocess.run(
                    ["wmic", "process", "get", "ProcessId,Name,CommandLine", "/format:csv"],
                    capture_output=True, text=True, timeout=15,
                )
                processes = []
                for line in result.stdout.strip().split("\n")[2:]:  # skip header
                    parts = [p.strip() for p in line.split(",") if p.strip()]
                    if len(parts) >= 2:
                        processes.append({"pid": parts[-1].strip(), "name": parts[-2].strip()})
            else:
                import subprocess
                result = subprocess.run(
                    ["ps", "-eo", "pid,comm,args", "--no-headers"],
                    capture_output=True, text=True, timeout=10,
                )
                processes = []
                for line in result.stdout.strip().split("\n"):
                    parts = line.split(None, 2)
                    if len(parts) >= 2:
                        processes.append({
                            "pid": parts[0].strip(),
                            "name": parts[1].strip(),
                            "command": parts[2].strip() if len(parts) > 2 else parts[1].strip(),
                        })

            if name_filter:
                processes = [p for p in processes if name_filter.lower() in p["name"].lower()]

            if limit > 0:
                processes = processes[:limit]

            return PrimitiveResult(
                status="success",
                data={
                    "processes": processes,
                    "count": len(processes),
                },
            )
        except FileNotFoundError:
            return PrimitiveResult(
                status="error",
                error="Unable to list processes: required system tools not available",
            )
        except Exception as e:
            return PrimitiveResult(
                status="error",
                error=str(e),
            )
