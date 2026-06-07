"""
CLIPrimitive – a primitive backed by a CLI command.

CLI primitives execute external commands in a subprocess.
They provide sandboxing at the process level and are suitable
for tools that run outside the Python runtime.
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict, List, Optional

from src.capabilities.primitives.base import PrimitiveBase, PrimitiveResult, PrimitiveType


class CLIPrimitive(PrimitiveBase):
    """A primitive backed by an external CLI command."""

    def __init__(
        self,
        name: str,
        description: str,
        command: List[str],
        *,
        input_schema: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        side_effects: Optional[list[str]] = None,
        deterministic: bool = False,
        pure: bool = False,
        idempotent: bool = False,
        enabled: bool = True,
        timeout_ms: Optional[int] = None,
        working_dir: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ):
        super().__init__(
            name=name,
            primitive_type=PrimitiveType.CLI,
            description=description,
            handler=self._run_command,
            input_schema=input_schema or {},
            output_schema=output_schema,
            side_effects=side_effects or [],
            deterministic=deterministic,
            pure=pure,
            idempotent=idempotent,
            enabled=enabled,
        )
        self._command = command
        self._timeout_ms = timeout_ms
        self._working_dir = working_dir
        self._env = env

    def _run_command(self, **kwargs) -> PrimitiveResult:
        """Execute the CLI command in a subprocess."""
        import time
        start = time.perf_counter()
        try:
            timeout = (self._timeout_ms / 1000.0) if self._timeout_ms else None
            result = subprocess.run(
                self._command,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self._working_dir,
                env=self._env,
            )
            duration = (time.perf_counter() - start) * 1000
            if result.returncode == 0:
                return PrimitiveResult(
                    success=True,
                    value={
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "returncode": result.returncode,
                    },
                    duration_ms=duration,
                )
            else:
                return PrimitiveResult(
                    success=False,
                    error=result.stderr or f"Exit code {result.returncode}",
                    error_type="SubprocessError",
                    duration_ms=duration,
                )
        except Exception as exc:
            return PrimitiveResult(
                success=False,
                error=str(exc),
                error_type=type(exc).__name__,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
