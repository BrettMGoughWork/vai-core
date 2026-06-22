"""stdlib.proc.kill — Kill a process by PID (Phase 3.18.9)."""

from __future__ import annotations

import os
import signal
import sys
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class ProcKillPrimitive(PrimitiveBase):
    """Kill a running process by PID."""

    name = "stdlib.proc.kill"
    description = "Kill a process by PID"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "pid": {
                "type": "integer",
                "exclusiveMinimum": 0,
                "description": "Process ID to kill (must be positive)",
            },
            "signal": {
                "type": "integer",
                "description": "Signal number to send (e.g. 9 for SIGKILL, 15 for SIGTERM)",
            },
        },
        "required": ["pid"],
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
        if "pid" not in args:
            raise ValueError("args must contain 'pid' key")
        if not isinstance(args["pid"], int):
            raise ValueError(f"args['pid'] must be an integer, got {type(args['pid']).__name__}")
        if args["pid"] <= 0:
            raise ValueError("args['pid'] must be a positive integer")
        if "signal" in args and not isinstance(args["signal"], int):
            raise ValueError(f"args['signal'] must be an integer, got {type(args['signal']).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        pid = args["pid"]
        sig = args.get("signal", signal.SIGTERM)

        try:
            if sys.platform == "win32":
                # On Windows, use TerminateProcess via ctypes
                import ctypes
from src.strategy.types.validation import deadcode_ignore
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(1, False, pid)  # PROCESS_TERMINATE
                if not handle:
                    return PrimitiveResult(
                        status="error",
                        error=f"Unable to open process {pid}",
                    )
                success = kernel32.TerminateProcess(handle, 0)
                kernel32.CloseHandle(handle)
                if not success:
                    return PrimitiveResult(
                        status="error",
                        error=f"Failed to terminate process {pid}",
                    )
            else:
                os.kill(pid, sig)

            return PrimitiveResult(
                status="success",
                data={
                    "pid": pid,
                    "signal": sig,
                    "signal_name": signal.Signals(sig).name if hasattr(signal, "Signals") else str(sig),
                },
            )
        except ProcessLookupError:
            return PrimitiveResult(
                status="error",
                error=f"No process found with PID {pid}",
            )
        except PermissionError:
            return PrimitiveResult(
                status="error",
                error=f"Permission denied to kill process {pid}",
            )
        except Exception as e:
            return PrimitiveResult(
                status="error",
                error=str(e),
            )
