"""stdlib.proc.exec — Execute a shell command (Phase 3.7.4)."""

from __future__ import annotations

import json
import os
import subprocess

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


class ProcExecPrimitive(PrimitiveBase):
    """Execute a shell command and return stdout, stderr, and exit code."""

    name = "stdlib.proc.exec"
    description = (
        "Execute a shell command and return stdout, stderr, and exit code"
    )
    primitive_type = PrimitiveType.CLI

    def __init__(self) -> None:
        super().__init__(
            name=self.name,
            description=self.description,
            primitive_type=self.primitive_type,
        )

    def validate_args(self, args: dict) -> None:
        if not isinstance(args, dict):
            raise ValueError(f"args must be a dict, got {type(args).__name__}")
        if "cmd" not in args:
            raise ValueError("args must contain 'cmd' key")
        cmd = args["cmd"]
        if not isinstance(cmd, str):
            raise ValueError(f"'cmd' must be a string, got {type(cmd).__name__}")
        if "\x00" in cmd:
            raise ValueError("'cmd' must not contain null bytes")
        if not cmd:
            raise ValueError("'cmd' must not be empty")
        try:
            json.dumps(cmd)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"'cmd' must be JSON-serializable: {exc}") from exc
        if "timeout" in args:
            timeout = args["timeout"]
            if timeout is not None:
                if not isinstance(timeout, int):
                    raise ValueError(
                        f"'timeout' must be None or an int, got {type(timeout).__name__}"
                    )
                if timeout <= 0:
                    raise ValueError(
                        f"'timeout' must be a positive integer, got {timeout}"
                    )
                try:
                    json.dumps(timeout)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"'timeout' must be JSON-serializable: {exc}"
                    ) from exc

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        cmd = args["cmd"]
        timeout = args.get("timeout")
        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return PrimitiveResult(
                status="error",
                data=None,
                error="TimeoutError: command timed out",
            )
        except OSError as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"OSError: {exc}",
            )
        return PrimitiveResult(
            status="success",
            data={
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": proc.returncode,
            },
        )
