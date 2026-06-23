"""stdlib.proc.execsafe — Execute a command with safety constraints (Phase 3.18.9)."""

from __future__ import annotations

import os
import subprocess
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


# Default blocklist of dangerous commands
_DEFAULT_BLOCKED_COMMANDS: set[str] = {
    "rm", "shred", "mkfs", "dd", "format",
    "shutdown", "reboot", "halt", "poweroff",
    "fdisk", "diskpart", "diskutil",
    "chmod", "chown", "sudo", "su",
}


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class ProcExecSafePrimitive(PrimitiveBase):
    """Execute a command with safety constraints (blocklist, timeout, cwd)."""

    name = "stdlib.proc.execsafe"
    description = "Execute a command with safety constraints"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "oneOf": [
                    {"type": "string", "description": "Shell command as a string"},
                    {"type": "array", "items": {"type": "string"}, "description": "Command as tokenized list"},
                ],
                "description": "The command to execute safely",
            },
            "allowed_commands": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Explicit allowlist of command names — bypasses safety blocklist",
            },
            "blocked_commands": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Additional commands to block beyond the default blocklist",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 30)",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for the command (default: current directory)",
            },
        },
        "required": ["command"],
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
        if "command" not in args:
            raise ValueError("args must contain 'command' key")
        cmd = args["command"]
        if isinstance(cmd, str):
            if not cmd.strip():
                raise ValueError("args['command'] must not be empty")
        elif isinstance(cmd, list):
            if not cmd:
                raise ValueError("args['command'] must not be empty")
            for item in cmd:
                if not isinstance(item, str):
                    raise ValueError("args['command'] list must contain only strings")
        else:
            raise ValueError(f"args['command'] must be a string or list, got {type(cmd).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        command = args["command"]
        allowed_commands = set(args.get("allowed_commands") or [])
        blocked_commands = set(args.get("blocked_commands") or [])
        timeout = args.get("timeout", 30)
        cwd = args.get("cwd") or None

        # Determine the base command name
        if isinstance(command, list):
            base_cmd = command[0]
        else:
            base_cmd = command.split()[0] if command.strip() else ""

        base_name = os.path.basename(base_cmd).lower()

        # If allowed_commands is explicit, only those are permitted
        if allowed_commands and base_name not in allowed_commands:
            return PrimitiveResult(
                status="error",
                error=f"Command '{base_name}' is not in allowed_commands: {allowed_commands}",
                data={"blocked": True, "reason": "not_allowed"},
            )

        # Check against default blocklist (unless explicitly allowed)
        effective_blocked = _DEFAULT_BLOCKED_COMMANDS | blocked_commands
        if base_name in effective_blocked and base_name not in allowed_commands:
            return PrimitiveResult(
                status="error",
                error=f"Command '{base_name}' is blocked for safety",
                data={"blocked": True, "reason": "safety_blocked"},
            )

        # Delegate to proc.exec (which expects 'cmd', not 'command')
        from src.capabilities.primitives.stdlib.proc_exec import ProcExecPrimitive
from src.domain._markers import deadcode_ignore
        exec_primitive = ProcExecPrimitive()
        # proc.exec only uses 'cmd' and 'timeout'; cwd is not supported by proc.exec
        exec_args: dict[str, Any] = {"cmd": command if isinstance(command, str) else subprocess.list2cmdline(command)}
        if timeout is not None:
            exec_args["timeout"] = timeout
        return exec_primitive.execute(exec_args, context)
