"""
Agentic Step Executor — tool-calling loop for DevSquad engineer steps.

Drives an LLM with tool definitions (read_file, write_file, list_directory,
execute_command, run_tests) in a loop until the model produces a text-only
response, signalling completion.

The engineer agent's tools (declared in config/agents/agent-engineer.yaml)
only exist as labels — they are NOT registered as primitives in the S1
runtime.  This module bridges the gap by supplying inline OpenAI-format
tool definitions and executing them locally.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from src.runtime.llm.types import CoreLLMResponse

logger = logging.getLogger(__name__)

_MAX_TOOL_ITERATIONS = 50

# ── Tool definitions (OpenAI function-calling format) ────────────────
# These match the tools declared in config/agents/agent-engineer.yaml.
# They are NOT runtime primitives — they exist only as labels in the
# agent config.  We define them here as proper OpenAI-compatible
# function definitions so the LLM can call them via native function
# calling.

ENGINEER_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the contents of a file at the given path.  "
                "Path may be absolute or relative to the project directory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative path to the file to read.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write content to a file at the given path.  Creates parent "
                "directories if they don't exist.  Path may be absolute or "
                "relative to the project directory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative path where the file should be written.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The full content to write to the file.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": (
                "List the files and directories at the given path.  "
                "Returns a formatted string with names, types, and sizes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative path to the directory to list.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_command",
            "description": (
                "Execute a shell command and return its stdout and stderr.  "
                "Use for running builds, linters, or any command-line tool "
                "(but NOT tests — use run_tests for those)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute.",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": (
                "Run the project's test suite and return the test output "
                "with pass/fail summary.  Defaults to 'pytest' if no "
                "command is specified."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": (
                            "The test command to run (default: 'pytest')."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
]


# ── Path resolution ─────────────────────────────────────────────────


def _resolve_path(raw_path: str, project_dir: str | Path) -> Path:
    """Resolve *raw_path* — absolute stays absolute, relative is joined to *project_dir*.

    Guards against root-relative paths on Windows (e.g. ``\\projects\\...``
    which would otherwise resolve to the drive root instead of *project_dir*).
    """
    p = Path(raw_path)
    if p.is_absolute():
        return p
    # Strip leading path separators so root-relative paths don't override
    # the drive root on Windows (Path('C:\\a') / Path('\\projects\\x')
    # yields C:\\projects\\x instead of C:\\a\\projects\\x).
    cleaned = raw_path.lstrip("/\\")
    return Path(project_dir) / cleaned


# ── Inline tool implementations ─────────────────────────────────────


def _tool_read_file(path: str, project_dir: str | Path) -> str:
    """Read *path* and return its content (or an error message)."""
    resolved = _resolve_path(path, project_dir)
    if not resolved.exists():
        return f"ERROR: file not found: {resolved}"
    if not resolved.is_file():
        return f"ERROR: not a file: {resolved}"
    try:
        return resolved.read_text(encoding="utf-8")
    except Exception as exc:
        return f"ERROR reading file {resolved}: {exc}"


def _tool_write_file(path: str, content: str, project_dir: str | Path) -> str:
    """Write *content* to *path*, creating parent directories as needed."""
    resolved = _resolve_path(path, project_dir)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    try:
        resolved.write_text(content, encoding="utf-8")
        return f"OK: wrote {len(content)} bytes to {resolved}"
    except Exception as exc:
        return f"ERROR writing file {resolved}: {exc}"


def _tool_list_directory(path: str, project_dir: str | Path) -> str:
    """Return a formatted directory listing for *path*."""
    resolved = _resolve_path(path, project_dir)
    if not resolved.exists():
        return f"ERROR: path not found: {resolved}"
    if not resolved.is_dir():
        return f"ERROR: not a directory: {resolved}"
    try:
        lines: list[str] = []
        entries = sorted(resolved.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        for entry in entries:
            if entry.is_dir():
                lines.append(f"  [DIR ]  {entry.name}/")
            elif entry.is_file():
                size = entry.stat().st_size
                lines.append(f"  [FILE]  {entry.name}  ({size} bytes)")
            else:
                lines.append(f"  [OTH ]  {entry.name}")
        return "\n".join(lines) if lines else "(empty directory)"
    except Exception as exc:
        return f"ERROR listing directory {resolved}: {exc}"


def _tool_execute_command(command: str) -> str:
    """Execute *command* in a shell and return its output."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        parts: list[str] = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(f"[STDERR]\n{result.stderr}")
        parts.append(f"\n[EXIT CODE: {result.returncode}]")
        return "\n".join(parts)
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out after 120 seconds"
    except Exception as exc:
        return f"ERROR executing command: {exc}"


def _tool_run_tests(command: str | None, project_dir: str | Path) -> str:
    """Run tests (default ``pytest``) inside *project_dir*."""
    cmd = command or "pytest"
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(project_dir),
        )
        parts: list[str] = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(f"[STDERR]\n{result.stderr}")
        parts.append(f"\n[EXIT CODE: {result.returncode}]")
        return "\n".join(parts)
    except subprocess.TimeoutExpired:
        return "ERROR: tests timed out after 300 seconds"
    except Exception as exc:
        return f"ERROR running tests: {exc}"


# ── Tool dispatcher ─────────────────────────────────────────────────

_TOOL_HANDLERS: dict[str, Any] = {
    "read_file": _tool_read_file,
    "write_file": _tool_write_file,
    "list_directory": _tool_list_directory,
    "execute_command": _tool_execute_command,
    "run_tests": _tool_run_tests,
}


def _execute_tool(tool_name: str, tool_args: dict[str, Any], project_dir: str | Path) -> str:
    """Dispatch a single tool call to its inline implementation."""
    handler = _TOOL_HANDLERS.get(tool_name)
    if handler is None:
        available = ", ".join(sorted(_TOOL_HANDLERS))
        return f"ERROR: unknown tool '{tool_name}'. Available: {available}"

    try:
        # Each handler has a different signature, so dispatch explicitly.
        if tool_name == "execute_command":
            return handler(tool_args.get("command", ""))
        if tool_name == "run_tests":
            return handler(tool_args.get("command"), project_dir)
        if tool_name in ("read_file", "list_directory"):
            return handler(tool_args.get("path", ""), project_dir)
        if tool_name == "write_file":
            return handler(tool_args.get("path", ""), tool_args.get("content", ""), project_dir)
        # Fallback for any future tools that match the (args..., project_dir) pattern
        return handler(**tool_args, project_dir=project_dir)
    except Exception as exc:
        return f"ERROR in tool '{tool_name}': {exc}"


# ── Main entry point ────────────────────────────────────────────────


def execute_agentic_step(
    config: dict[str, Any],
    project_dir: str | Path,
    llm_transport: Any,
) -> str:
    """Execute an agentic tool-calling step with the given *llm_transport*.

    Parameters
    ----------
    config:
        Step configuration dict.  Expected keys:
        - ``system_prompt``:  system-level instruction for the LLM
        - ``user_prompt``:    user message (the task description)
        - ``agent_id``:       agent identifier (e.g. ``"agent-engineer"``)
    project_dir:
        Base directory for resolving relative file paths.
    llm_transport:
        An ``LLMTransport`` instance with a ``complete_with_tools(messages, tools)``
        method that returns ``CoreLLMResponse``.

    Returns
    -------
    The final text output from the LLM after it stops issuing tool calls.
    """
    system_prompt = config.get("system_prompt", "") or ""
    user_prompt = config.get("user_prompt", config.get("message", "")) or ""

    if not system_prompt and not user_prompt:
        logger.warning(
            "execute_agentic_step: no prompts in config — returning empty"
        )
        return ""

    # Inject a context reminder into the system prompt
    context_suffix = (
        "\n\nIMPORTANT:\n"
        "You have tools available for creating files and running commands, but you "
        "MUST eventually stop calling tools and produce a final text response.  "
        "Once all task blocks are implemented and tests pass, call NO MORE tools "
        "and output your final summary as a markdown report.  "
        "Do not make tool calls beyond what is necessary — when the work is done, "
        "report the result in plain text."
    )
    system_prompt_with_context = system_prompt + context_suffix

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt_with_context},
        {"role": "user", "content": user_prompt},
    ]

    for iteration in range(_MAX_TOOL_ITERATIONS):
        response: CoreLLMResponse = llm_transport.complete_with_tools(
            messages, ENGINEER_TOOLS,
        )

        # ── Tool call path ─────────────────────────────────────────
        if response.tool_name and response.tool_calls:
            for raw_tc in response.tool_calls:
                func = raw_tc.get("function", {})
                t_name: str = func.get("name", "")
                raw_args = func.get("arguments", "{}")

                if isinstance(raw_args, str):
                    try:
                        parsed_args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        parsed_args = {}
                else:
                    parsed_args = raw_args

                t_id: str = raw_tc.get(
                    "id", f"call_{iteration}_{t_name}",
                )
                result_text = _execute_tool(t_name, parsed_args, project_dir)

                if os.environ.get("DEVSQUAD_DEBUG"):
                    logger.info(
                        "Agentic tool %s(%s) → %s",
                        t_name, parsed_args, result_text[:200],
                    )

                # Append the assistant's tool-call message, then the
                # tool result — this is the standard OpenAI multi-turn
                # tool-calling protocol.
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [raw_tc],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": t_id,
                    "content": result_text,
                })
            continue

        # ── Text-only response → the model considers the task done ─
        text = (response.text or "").strip()
        if text:
            logger.info(
                "Agent step completed after %d tool iteration(s).  "
                "Response: %d characters.",
                iteration + 1,
                len(text),
            )
        else:
            logger.warning(
                "Agent step returned empty text after %d iteration(s).",
                iteration + 1,
            )
        return text

    # ── Exceeded max iterations — build a summary ──────────────
    logger.warning(
        "Agent step exceeded %d iterations.  "
        "Building fallback summary of work done.",
        _MAX_TOOL_ITERATIONS,
    )

    # Collect tool calls that were actually made
    tool_counts: dict[str, int] = {}
    written_files: list[str] = []
    for msg in messages:
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {}).get("name", "?")
                tool_counts[fn] = tool_counts.get(fn, 0) + 1
        if msg["role"] == "tool":
            content = msg.get("content", "")
            if content.startswith("OK: wrote"):
                # Extract file path from "OK: wrote N bytes to /path/to/file"
                written_files.append(content)

    parts: list[str] = [
        "## Summary of Work Done",
        "",
        f"The engineer agent performed {sum(tool_counts.values())} tool calls "
        f"across {_MAX_TOOL_ITERATIONS} iterations before reaching the "
        f"iteration limit.",
        "",
        "### Tool Call Breakdown",
        "",
    ]
    for tool_name, count in sorted(tool_counts.items()):
        parts.append(f"- **{tool_name}**: {count} call(s)")
    parts.append("")

    if written_files:
        parts.append("### Files Written")
        parts.append("")
        for entry in written_files:
            parts.append(f"- {entry}")
        parts.append("")

    # Check what exists on disk
    if project_dir and Path(project_dir).exists():
        all_on_disk = sorted(Path(project_dir).rglob("*"))
        files_on_disk = [f for f in all_on_disk if f.is_file()]
        if files_on_disk:
            parts.append("### Files on Disk")
            parts.append("")
            for f in files_on_disk:
                try:
                    rel = f.relative_to(project_dir)
                    size = f.stat().st_size
                    parts.append(f"- `{rel}` ({size} bytes)")
                except (ValueError, OSError):
                    parts.append(f"- `{f.name}`")
            parts.append("")

    # Look for any assistant text content anywhere in the conversation
    for msg in reversed(messages):
        if msg["role"] == "assistant" and isinstance(msg.get("content"), str) and msg["content"].strip():
            parts.append("### Last Assistant Text Response")
            parts.append("")
            parts.append(msg["content"])
            break

    parts.append("")
    parts.append(
        "_The agent reached the iteration limit before producing a final "
        "response. The work above was completed before the limit was hit._"
    )

    return "\n".join(parts)
