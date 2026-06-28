"""
CLIPrimitive — a primitive backed by a CLI command (Phase 3.1.4).

CLI primitives execute external commands in a subprocess with
deterministic semantics and runaway-process protection.

Timeouts use a **sliding-wall** approach: the process must be
continuously producing output (stdout or stderr).  As long as data
is emitted within each *timeout_ms* window, the process keeps
running.  If it goes silent longer than *timeout_ms*, it is killed.
"""

from __future__ import annotations

import shlex
import subprocess
import threading
import time
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class CLIPrimitive(PrimitiveBase):
    """A primitive backed by an external CLI command."""

    __match_args__ = ("name",)

    def __init__(
        self,
        *,
        name: str,
        description: str,
        command: str,
        input_schema: dict | None = None,
        side_effects: list[str] | None = None,
        timeout_ms: int | None = None,
    ) -> None:
        super().__init__(
            name=name,
            description=description,
            primitive_type=PrimitiveType.CLI,
        )
        self.command = command
        """The base CLI command as a single string (e.g. ``'echo'``, ``'git'``)."""

        self._input_schema = input_schema or {
            "type": "object",
            "properties": {},
            "description": "Accepts arbitrary key-value pairs that are passed as CLI arguments.",
        }
        self._side_effects: list[str] = side_effects or []

        # Sliding-wall timeout: the subprocess must produce output within
        # this window.  Default 30 s, None = no timeout.
        self._timeout_s: float | None = (
            (timeout_ms / 1000) if timeout_ms else 30.0
        )

    # ------------------------------------------------------------------
    # PrimitiveBase interface
    # ------------------------------------------------------------------

    @property
    def input_schema(self) -> dict:
        return self._input_schema

    def validate_args(self, args: dict) -> None:
        """
        Validate that ``args`` is a dict suitable for CLI execution.

        Values are coerced to strings when building the command line,
        so the only hard requirement is that ``args`` is a ``dict``.
        """
        if not isinstance(args, dict):
            raise ValueError("args must be a dict")

    # ------------------------------------------------------------------
    # Execution with sliding-wall timeout
    # ------------------------------------------------------------------

    @staticmethod
    def _read_stream(
        stream: Any,
        collected: list[str],
        last_activity: list[float],
        stop_event: threading.Event,
    ) -> None:
        """Read *stream* line by line into *collected*.

        Updates ``last_activity[0] = time.monotonic()`` on each line.
        Exits when *stream* is exhausted or *stop_event* is set.
        """
        for line in iter(stream.readline, ""):
            if stop_event.is_set():
                break
            collected.append(line)
            last_activity[0] = time.monotonic()
        stream.close()

    def _run_subprocess(
        self,
        cmd: list[str],
        stdin_data: str | None,
    ) -> PrimitiveResult:
        """Run *cmd* in a subprocess with a sliding-wall timeout.

        The subprocess must produce new output (stdout or stderr) within
        ``self._timeout_s`` seconds, otherwise it is killed.
        """
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Pass stdin, then close the pipe so the subprocess can proceed
        if stdin_data is not None:
            process.stdin.write(stdin_data)
            process.stdin.close()

        last_activity: list[float] = [time.monotonic()]
        stop_event = threading.Event()
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        stdout_thread = threading.Thread(
            target=self._read_stream,
            args=(process.stdout, stdout_lines, last_activity, stop_event),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._read_stream,
            args=(process.stderr, stderr_lines, last_activity, stop_event),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        killed = False
        window = self._timeout_s

        # ── Watchdog loop ──────────────────────────────────────────
        while process.poll() is None:
            elapsed = time.monotonic() - last_activity[0]
            if window is not None and elapsed > window:
                process.kill()
                killed = True
                break
            time.sleep(0.5)

        # ── Cleanup ────────────────────────────────────────────────
        stop_event.set()
        stdout_thread.join(timeout=3)
        stderr_thread.join(timeout=3)
        process.wait(timeout=5)

        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)
        rc = process.returncode

        if killed:
            return PrimitiveResult(status="error", error="timeout")

        if rc == 0:
            return PrimitiveResult(
                status="success",
                data={
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": rc,
                },
            )

        return PrimitiveResult(
            status="error",
            error=stderr or f"Exit code {rc}",
        )

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        """Execute the CLI command in a subprocess with sliding-wall timeout."""
        self.validate_args(args)

        # Extract stdin_data if provided; don't pass it as CLI args
        stdin_data = args.pop("stdin_data", None)

        # Support multi-word commands (e.g. "python -m ...")
        full_cmd = shlex.split(self.command)
        for k, v in args.items():
            full_cmd.append(str(k))
            full_cmd.append(str(v))

        try:
            return self._run_subprocess(full_cmd, stdin_data)
        except Exception as exc:
            return PrimitiveResult(status="error", error=str(exc))
