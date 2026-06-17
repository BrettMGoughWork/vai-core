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
import sys

from src.agent.composition_root import s5_adapter
from src.gateway.channels.cli import register_cli_channel
from src.gateway.channels.registry import ChannelRegistry
from src.gateway.entrypoint import submit_channel_input

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
# Core loop
# ---------------------------------------------------------------------------


def run_single(text: str, sender: str | None, registry: ChannelRegistry) -> None:
    """Submit a command through the Gateway → S5 pipeline."""
    result = submit_channel_input(
        registry, "cli", {"text": text, "sender": sender},
        adapter=s5_adapter,
    )

    if "error" in result:
        print(f"[!] {result['error']}")
        return

    if "reply" in result:
        print(f"\n-- S5 Response -------------------------------------------")
        print(f"  reply:    {result['reply']}")
        if result.get("metadata"):
            print(f"  metadata: {result['metadata']}")
    else:
        print(f"\n-- S5 Pending --------------------------------------------")
        print(f"  state:    {result.get('state', 'unknown')}")
        print(f"  agent_id: {result.get('agent_id', 'unknown')}")
    print()


def run_interactive(registry: ChannelRegistry) -> None:
    """Read commands from stdin in a continuous interactive loop.

    When stdout is a TTY (interactive mode) the header and prompt are shown.
    When stdout is piped (``| python -m dashboard``), header and prompt are
    suppressed so only structured JSON lines reach the downstream consumer.
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
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

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
