"""
Agent CLI Application — runnable entry point for the S5 Agent Runtime.

Wires the S5 supervisor into an interactive CLI so users can send messages
to an agent and get conversational responses back::

    user message → AgentMessage → Supervisor.activate_agent()
        → Supervisor.run_agent_step() → AgentResponse → display

This is deliberately separate from ``tools/channels/cli_app.py`` (the pure S4
channel CLI) so each layer can be tested and debugged independently.

Usage::

    # Interactive mode
    python -m tools.agent.cli_app

    # Single command
    python -m tools.agent.cli_app "write me a haiku about programming"

    # Pipe mode
    echo "list available agents" | python -m tools.agent.cli_app

    # Pick a different agent
    python -m tools.agent.cli_app --agent help "what can you do?"
"""

from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.agent import (
    AgentMessage,
    AgentRegistry,
    AgentState,
    MemoryAgentStateStore,
    Supervisor,
    load_agent_manifest,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HEADER = r"""
+--------------------------------------------------------------------+
|  VAI -- Agent Runtime  (Stratum-5)                                  |
|  Type a message or Ctrl+C to exit                                   |
|  agent → activate → think → respond                                 |
+--------------------------------------------------------------------+
"""

PROMPT = "vai> "

DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "config" / "agents.yaml"
"""Path to the agent manifest YAML file."""

DEFAULT_AGENT_ID = "assistant"

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Dry-run submit-job callback
# ---------------------------------------------------------------------------


def _dry_run_submit_job(payload: dict) -> str:
    """Print what would be dispatched to S4B and return a fake job ID."""
    print(f"  [s4b] would dispatch job to: {payload.get('destination', '?')}")
    print(f"  [s4b] payload: {payload}")
    return "dry-run-job-00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def _bootstrap(
    manifest_path: str | Path | None = None,
    *,
    submit_job_callable: Callable[[Any], str] | None = None,
) -> tuple[Supervisor, AgentRegistry]:
    """Load the agent manifest, build the registry, and create a Supervisor.

    Returns:
        A (supervisor, registry) tuple ready for interactive use.
    """
    registry = AgentRegistry()
    manifest = Path(manifest_path) if manifest_path else DEFAULT_MANIFEST

    if manifest.exists():
        try:
            count = load_agent_manifest(registry, str(manifest))
            print(f"  [init] loaded {count} agent(s) from {manifest.name}", file=sys.stderr)
        except Exception as exc:
            print(
                f"  [init] failed to load {manifest}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        print(
            f"  [init] no manifest found at {manifest} — agent registry is empty",
            file=sys.stderr,
        )

    # Ephemeral in-memory store — clean slate on every launch.
    store = MemoryAgentStateStore()
    supervisor = Supervisor(
        registry=registry,
        store=store,
        submit_job_callable=submit_job_callable,
        auto_persist=True,
    )

    return supervisor, registry


# ---------------------------------------------------------------------------
# Agent interaction helpers
# ---------------------------------------------------------------------------


def _handle_message(
    supervisor: Supervisor,
    text: str,
    agent_id: str,
) -> None:
    """Route a user message through the S5 supervisor and print the response.

    Creates an agent, activates it with the user message, runs one
    cognitive step, and displays the ``AgentResponse``.
    """
    try:
        # 1. Create runtime state
        state: AgentState = supervisor.create_agent(agent_id)

        # 2. Activate with the user's message
        message = AgentMessage(
            message=text,
            context={"channel": "cli", "sender": None},
        )
        state = supervisor.activate_agent(state, message, channel="cli")

        # 3. Run one routing step (route -> dispatch)
        state = supervisor.run_agent_step(state, message=text)

        # 4. Retrieve the final response
        response = Supervisor.get_response(state)
        if response is not None:
            if response.reply:
                print(response.reply)
            if response.metadata:
                print(f"  [meta] agent={response.metadata.get('agent_id', '?')} "
                      f"confidence={response.metadata.get('confidence', '?')}")
        else:
            # Agent may be WAITING (jobs dispatched) or FAILED
            if state.lifecycle_state.value == "waiting":
                print("  [agent] waiting for job results — not yet complete")
            elif state.lifecycle_state.value == "failed":
                print("  [agent] failed with errors:")
                for err in state.errors:
                    print(f"    - {err.get('type')}: {err.get('message')}")
            else:
                print(f"  [agent] state={state.lifecycle_state.value} — no response")

    except Exception:
        print(f"  [error] unhandled exception:")
        traceback.print_exc()


def _list_agents(registry: AgentRegistry) -> None:
    """Print all registered agents."""
    print("  Registered agents:")
    for meta in sorted(
        registry.list_agents(),
        key=lambda m: m.identity.agent_id,
    ):
        print(f"    {meta.identity.agent_id:<20} {meta.identity.name}")
        if meta.identity.description:
            print(f"    {'':20} {meta.identity.description}")


# ---------------------------------------------------------------------------
# Core loop
# ---------------------------------------------------------------------------


def run_single(
    text: str,
    agent_id: str,
    supervisor: Supervisor,
    registry: AgentRegistry,
) -> None:
    """Process one command and exit."""
    lower = text.lower()
    if lower in (":help", "help"):
        _list_agents(registry)
        print()
        print("  Built-in commands:  :help  :list  :exit  :quit")
        return
    if lower in (":list",):
        _list_agents(registry)
        return
    if lower in (":exit", ":quit", "exit", "quit"):
        print("Goodbye.")
        return

    _handle_message(supervisor, text, agent_id)


def run_interactive(
    supervisor: Supervisor,
    registry: AgentRegistry,
    agent_id: str,
) -> None:
    """Read commands from stdin in a continuous interactive loop."""
    is_piped = not sys.stdout.isatty()

    if not is_piped:
        print(HEADER)
        print(f"  Agent: {agent_id}  |  :help for available commands")
        print()
        print(PROMPT, end="", flush=True)

    try:
        for line in sys.stdin:
            text = line.strip()
            if not text:
                if not is_piped:
                    print(PROMPT, end="", flush=True)
                continue

            # Handle meta-commands
            lower = text.lower()
            if lower in (":help",):
                _list_agents(registry)
                print()
                print("  Built-in commands:  :help  :list  :exit  :quit")
                if not is_piped:
                    print(PROMPT, end="", flush=True)
                continue
            if lower in (":list",):
                _list_agents(registry)
                if not is_piped:
                    print(PROMPT, end="", flush=True)
                continue
            if lower in (":exit", ":quit", "exit", "quit"):
                if not is_piped:
                    print("Goodbye.")
                break

            _handle_message(supervisor, text, agent_id)

            if not is_piped:
                print()
                print(PROMPT, end="", flush=True)

    except (KeyboardInterrupt, EOFError):
        if not is_piped:
            print("\nGoodbye.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tools.agent.cli_app",
        description="Stratum-5 Agent Runtime CLI — conversational agent interface",
    )
    parser.add_argument(
        "text",
        nargs="?",
        default=None,
        help="Single message (omit for interactive/pipe mode)",
    )
    parser.add_argument(
        "--agent",
        default=DEFAULT_AGENT_ID,
        help=f"Agent to use (default: {DEFAULT_AGENT_ID})",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="Path to agent manifest YAML (default: config/agents.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print S4B dispatch info instead of submitting real jobs",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    submit_job_callable = _dry_run_submit_job if args.dry_run else None
    supervisor, registry = _bootstrap(args.manifest, submit_job_callable=submit_job_callable)

    if not registry.has_agent(args.agent):
        available = ", ".join(
            sorted(m.identity.agent_id for m in registry.list_agents())
        ) or "(none)"
        print(f"Unknown agent {args.agent!r}. Available: {available}")
        sys.exit(1)

    if args.dry_run:
        print("  [init] dry-run mode — S4B jobs will be printed, not submitted")

    if args.text:
        run_single(args.text, args.agent, supervisor, registry)
    else:
        run_interactive(supervisor, registry, args.agent)


if __name__ == "__main__":
    main()
