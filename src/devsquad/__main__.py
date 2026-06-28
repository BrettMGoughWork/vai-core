"""
DevSquad CLI -- multi-agent sprint factory

Usage::

    python -m src.devsquad interview [--json [path]] [--confirm]
                                       Run the sprint interview
    python -m src.devsquad status       Show pipeline status
    python -m src.devsquad list         List projects
    python -m src.devsquad help         Show this help

Flags for ``interview``:

    --json [path]    Read JSON input from a file (or stdin if no path).
                     Requires a ``north_star`` key in the JSON payload.
    --confirm        Skip the "Shall I start this sprint?" prompt.

When ``--json`` is provided the command is non-interactive and outputs
JSON results (suitable for CLI primitive integration).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .interview import run_interview


def _cmd_help() -> None:
    print(__doc__)


def _cmd_status() -> None:
    """Print a summary of running / completed sprints."""
    projects_root = Path(os.environ.get("DEVSQUAD_PROJECTS_ROOT", ".\\projects"))

    if not projects_root.is_dir():
        print(f"  Project root not found: {projects_root}")
        print("  (nothing has been kicked off yet)")
        return

    projects = sorted(
        [d for d in projects_root.iterdir() if d.is_dir() and d.name != "inbox"]
    )
    if not projects:
        print(f"  No sprint projects found in {projects_root}")
        print("  Run 'interview' to kick off your first sprint!")
        return

    print(f"  Sprint projects in {projects_root}:\n")
    for proj in projects:
        prd = proj / "prd.md"
        status = "[HAS PRD]" if prd.exists() else "[IN PROGRESS]"
        print(f"    {proj.name}  {status}")
    print()


def _cmd_list() -> None:
    """Alias for ``status``."""
    _cmd_status()


def _parse_interview_flags() -> tuple[bool, str | None, bool]:
    """Parse flags after ``interview`` subcommand.

    Returns (json_flag, json_arg, auto_confirm).
    """
    # Find where "interview" is in argv
    try:
        idx = [a.lower() for a in sys.argv].index("interview")
    except ValueError:
        return False, None, False

    raw = sys.argv[idx + 1:]
    json_flag = False
    json_arg: str | None = None
    auto_confirm = False

    for i, arg in enumerate(raw):
        if arg == "--json":
            json_flag = True
            # Next non-flag token is the file path (if it exists and doesn't start with --)
            if i + 1 < len(raw) and not raw[i + 1].startswith("--"):
                json_arg = raw[i + 1]
        elif arg == "--confirm":
            auto_confirm = True

    return json_flag, json_arg, auto_confirm


def main() -> None:
    """Dispatch CLI subcommands."""
    args = [a.lower() for a in sys.argv[1:]]

    if not args or args[0] in ("help", "--help", "-h"):
        _cmd_help()
        return

    cmd = args[0]

    if cmd == "interview":
        json_flag, json_arg, auto_confirm = _parse_interview_flags()

        if json_flag:
            import json
            if json_arg:
                json_payload = open(json_arg, encoding="utf-8").read()
            else:
                json_payload = sys.stdin.read()
            run_interview(json_input=json_payload)
        else:
            run_interview(auto_confirm=auto_confirm)
    elif cmd in ("status", "list"):
        _cmd_status()
    else:
        print(f"  Unknown command: {cmd!r}")
        print()
        _cmd_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
