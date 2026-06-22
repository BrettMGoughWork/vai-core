"""
CLIPrimitive — a primitive backed by a CLI command (Phase 3.1.4).

CLI primitives execute external commands in a subprocess with
deterministic semantics and runaway-process protection.
"""

from __future__ import annotations

import subprocess
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class CLIPrimitive(PrimitiveBase):
    """A primitive backed by an external CLI command."""

    __match_args__ = ("name",)
    input_schema = {
        "type": "object",
        "properties": {},
        "description": "Accepts arbitrary key-value pairs that are passed as CLI arguments.",
    }

    def __init__(self, *, name: str, description: str, command: str) -> None:
        super().__init__(
            name=name,
            description=description,
            primitive_type=PrimitiveType.CLI,
        )
        self.command = command
        """The base CLI command as a single string (e.g. ``'echo'``, ``'git'``)."""

    # ------------------------------------------------------------------
    # PrimitiveBase interface
    # ------------------------------------------------------------------

    def validate_args(self, args: dict) -> None:
        """
        Validate that ``args`` is a dict suitable for CLI execution.

        Values are coerced to strings when building the command line,
        so the only hard requirement is that ``args`` is a ``dict``.
        """
        if not isinstance(args, dict):
            raise ValueError("args must be a dict")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        """Execute the CLI command in a subprocess with a 5-second hard cap."""
        self.validate_args(args)

        full_cmd = [self.command]
        for k, v in args.items():
            full_cmd.append(str(k))
            full_cmd.append(str(v))

        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return PrimitiveResult(
                status="error",
                error="timeout",
            )

        if result.returncode == 0:
            return PrimitiveResult(
                status="success",
                data={
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                },
            )

        return PrimitiveResult(
            status="error",
            error=result.stderr or f"Exit code {result.returncode}",
        )
