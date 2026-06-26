"""
CLI Channel Application — runnable entry point demonstrating Gateway → S5.

Demonstrates the correct architectural flow::

    raw_input -> Channel.normalize() -> submit_channel_input() -> S5 Supervisor

Usage:
    # Single command
    python -m tools.channels.cli_app "deploy the app" --sender alice

    # Interactive mode (type commands line by line)
    python -m tools.channels.cli_app

    # Pipe mode
    echo "list jobs" | python -m tools.channels.cli_app

    # Print usage
    python -m tools.channels.cli_app --help
"""

from __future__ import annotations

import argparse
import json
import sys

from src.agent.composition_root import (
    agent_registry,
    s5_adapter,
    workflow_registry,
)
from src.gateway.channels.cli import register_cli_channel
from src.gateway.channels.registry import ChannelRegistry
from src.gateway.entrypoint import submit_channel_input
from src.platform.observability import logging as _obs_logging
from src.platform.observability import metrics as _obs_metrics
from src.platform.observability import tracing as _obs_tracing

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HEADER = r"""
+--------------------------------------------------------------------+
|  VAI -- CLI Channel  (Stratum-5)                                    |
|  Type a command or Ctrl+C to exit                                   |
|  Gateway -> S5 Supervisor -> response                               |
+--------------------------------------------------------------------+
"""

PROMPT = "vai> "


# ---------------------------------------------------------------------------
# Module-level state for HITL resume tracking
# ---------------------------------------------------------------------------

_waiting_agent_id: str | None = None
"""Set when the last ``ingest()`` returned a WAITING state with HITL
interaction metadata.  When set, the next user input is sent via
``resume()`` instead of ``ingest()``."""

_current_agent_id: str = "default-agent"
"""The agent selected via ``/agent <agent_id>``.  Defaults to the
system default; changed at runtime via the ``/agent`` command."""


def _handle_result(result: dict, registry: ChannelRegistry) -> None:
    """Print a response result and update HITL resume tracking."""
    global _waiting_agent_id

    if "error" in result:
        print(f"[!] {result['error']}")
        _waiting_agent_id = None
        return

    # HITL pending state: show reply (LLM analysis) AND HITL prompt
    if "reply" in result and "state" in result:
        _waiting_agent_id = result.get("agent_id")
        print(f"\n-- S5 Pending --------------------------------------------")
        print(f"  state:    {result.get('state', 'unknown')}")
        print(f"  agent_id: {_waiting_agent_id}")
        reply_text = result['reply']
        if isinstance(reply_text, str):
            try:
                reply_text.encode(sys.stdout.encoding or 'utf-8')
            except UnicodeEncodeError:
                reply_text = reply_text.encode('utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8', errors='replace')
        print(f"  reply:    {reply_text}")
        # Show confirmation prompt separately
        prompt_text = result.get("prompt")
        if prompt_text:
            print(f"\n  +- HITL Request ----")
            for line in prompt_text.split("\n"):
                print(f"  | {line}")
            print(f"  +--------------------")
        print()
        return

    if "reply" in result:
        print(f"\n-- S5 Response -------------------------------------------")
        reply_text = result['reply']
        # Handle Unicode characters that may not be encodable in cp1252
        if isinstance(reply_text, str):
            try:
                reply_text.encode(sys.stdout.encoding or 'utf-8')
            except UnicodeEncodeError:
                reply_text = reply_text.encode('utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8', errors='replace')
        print(f"  reply:    {reply_text}")
        if result.get("metadata"):
            print(f"  metadata: {result['metadata']}")
        _waiting_agent_id = None
        return

    # Pending / waiting state
    _waiting_agent_id = result.get("agent_id")
    print(f"\n-- S5 Pending --------------------------------------------")
    print(f"  state:    {result.get('state', 'unknown')}")
    print(f"  agent_id: {_waiting_agent_id}")

    # Show HITL interaction prompt if the workflow is asking for user input
    prompt_text = result.get("prompt")
    if prompt_text:
        print(f"\n  +- HITL Request ----")
        for line in prompt_text.split("\n"):
            print(f"  | {line}")
        schema = result.get("input_schema")
        if schema:
            print(f"  |")
            print(f"  | Schema: {json.dumps(schema)}")
        print(f"  +--------------------")
    print()


def _show_agent() -> None:
    """Display the current agent."""
    print(f"\n  Current agent: {_current_agent_id}")
    if agent_registry.has_agent(_current_agent_id):
        meta = agent_registry.get_agent(_current_agent_id)
        act = meta.identity
        print(f"    name:        {act.name}")
        print(f"    description: {act.description}")
        if meta.persona:
            print(f"    persona:     {meta.persona}")
    print()


def _list_agents() -> None:
    """Display all registered agents."""
    print(f"\n  Registered agents ({agent_registry.agent_count}):")
    for meta in agent_registry.list_agents():
        act = meta.identity
        print(f"    {act.agent_id:20s}  {act.name}")
        if meta.persona:
            print(f"    {'':20s}  persona: {meta.persona}")
    print()


def _list_workflows() -> None:
    """Display all registered workflows."""
    defs = workflow_registry.list()
    print(f"\n  Registered workflows ({len(defs)}):")
    for wf in defs:
        print(f"    {wf.workflow_id:20s}  {wf.description or ''}")
    print()


def run_single(text: str, sender: str | None, registry: ChannelRegistry) -> None:
    """Submit a command through the Gateway → S5 pipeline.

    Handles meta-commands:
      ``/agent``          — show current agent
      ``/agent <id>``     — switch to a different agent
      ``/agents``         — list all registered agents
      ``/workflows``      — list all registered workflows

    If the previous call left the agent ``WAITING`` for HITL input, this
    calls ``resume()`` instead of ``ingest()`` so the paused workflow
    receives the user's response.
    """
    global _waiting_agent_id, _current_agent_id

    # ── Meta-commands ──────────────────────────────────────────────────
    if text.startswith("/agent "):
        agent_id = text[7:].strip()
        if not agent_registry.has_agent(agent_id):
            print(f"  Unknown agent: {agent_id!r}")
            print(f"  Use /agents to see available agents.")
            return
        _current_agent_id = agent_id
        _show_agent()
        return

    if text == "/agent":
        _show_agent()
        return

    if text == "/agents":
        _list_agents()
        return

    if text == "/workflows":
        _list_workflows()
        return

    # ── Regular input ──────────────────────────────────────────────────
    if _waiting_agent_id:
        result = s5_adapter.resume(_waiting_agent_id, text)
    else:
        result = submit_channel_input(
            registry, "cli", {"text": text, "sender": sender},
            adapter=s5_adapter,
            agent_id=_current_agent_id,
        )

    _handle_result(result, registry)


def run_interactive(registry: ChannelRegistry) -> None:
    """Read commands from stdin in a continuous interactive loop.

    When stdout is a TTY (interactive mode) the header and prompt are shown.
    When stdout is piped (``| python -m dashboard``), header and prompt are
    suppressed so only structured JSON lines reach the downstream consumer.

    Supports Human-In-The-Loop (HITL) workflows: when the agent pauses at a
    ``user_input`` step, the prompt is displayed and the user's next line
    is submitted as the interaction response.
    """
    is_piped = not sys.stdout.isatty()

    if not is_piped:
        print(HEADER)
        print(PROMPT, end="", flush=True)

    try:
        for line in sys.stdin:
            text = line.strip()
            if not text:
                if not is_piped:
                    print(PROMPT, end="", flush=True)
                continue
            if text.lower() in (":quit", ":exit", "quit", "exit"):
                if not is_piped:
                    print("Goodbye.")
                break
            run_single(text, None, registry)
            if not is_piped:
                print(PROMPT, end="", flush=True)
    except (KeyboardInterrupt, EOFError):
        if not is_piped:
            print("\nGoodbye.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tools.channels.cli_app",
        description="Stratum-4 CLI Channel — demonstrate the CLI channel pipeline",
    )
    parser.add_argument(
        "text",
        nargs="?",
        default=None,
        help="Single command text. Required unless --interactive is used.",
    )
    parser.add_argument(
        "--sender",
        default=None,
        help="Optional sender identity",
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Start interactive REPL mode (reads commands from stdin)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose observability output (traces, metrics, logs)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.verbose:
        _obs_metrics.set_verbose(True)
        _obs_logging.set_verbose(True)
        _obs_tracing.set_verbose(True)
    else:
        _obs_metrics.set_verbose(False)
        _obs_logging.set_verbose(False)
        _obs_tracing.set_verbose(False)

    # Param guard: require text arg, --interactive flag, or pipe input
    if not args.text and not args.interactive:
        if sys.stdin.isatty():
            # Interactive terminal with no args — show usage
            print("Usage: python -m tools.channels.cli_app [--interactive] <text>")
            print("       python -m tools.channels.cli_app --interactive")
            print("       echo 'hello' | python -m tools.channels.cli_app")
            sys.exit(1)
        # stdin is a pipe — let run_interactive read from it

    # Wire up the CLI channel
    registry = ChannelRegistry()
    register_cli_channel(registry)

    if args.text:
        run_single(args.text, args.sender, registry)
    else:
        # Interactive or pipe mode
        run_interactive(registry)


if __name__ == "__main__":
    main()
