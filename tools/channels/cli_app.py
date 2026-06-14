"""
CLI Channel Application -- runnable entry point for the Stratum-4 CLI channel.

Demonstrates end-to-end job processing through the CLI channel::

    raw_input -> receive() -> InboundChannelMessage -> normalize() -> ChannelMessage
    -> create_job() -> queue.push() -> worker.process_next() -> result

Usage:
    # Single command
    python -m tools.channels.cli_app "deploy the app" --sender alice

    # Interactive mode (type commands line by line)
    python -m tools.channels.cli_app

    # Pipe mode
    echo "list jobs" | python -m tools.channels.cli_app

When a job is submitted, the app runs a single worker cycle to process it
and displays the result.
"""

from __future__ import annotations

import argparse
import sys
import time
import threading

from src.platform.queue.queue import InMemoryQueue
from src.platform.runtime.channels.cli import register_cli_channel
from src.platform.runtime.channels.registry import ChannelRegistry
from src.platform.runtime.control_plane import ControlPlane
from src.platform.runtime.gateway_entrypoint import submit_channel_input
from src.platform.runtime.worker import Worker

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HEADER = r"""
+--------------------------------------------------------------------+
|  VAI -- CLI Channel  (Stratum-4)                                    |
|  Type a command or Ctrl+C to exit                                   |
|  Job: submit -> worker -> result                                    |
+--------------------------------------------------------------------+
"""

PROMPT = "vai> "

# ---------------------------------------------------------------------------
# Shared runtime — one queue, one control plane, shared worker
# ---------------------------------------------------------------------------

_queue: InMemoryQueue = InMemoryQueue()
_cp: ControlPlane = ControlPlane()


def _process_one(registry: ChannelRegistry | None = None) -> None:
    """Run one worker cycle if there is a pending job."""
    worker = Worker(
        queue=_queue,
        control_plane=_cp,
        channel_registry=registry,
    )
    job = worker.process_next()
    if job is not None:
        print(f"\n  [worker] {job.job_id:<8} -> {job.state.value}")
        if job.result:
            print(f"  [result] {job.result}")


# ---------------------------------------------------------------------------
# Core loop
# ---------------------------------------------------------------------------


def run_single(text: str, sender: str | None, registry: ChannelRegistry) -> None:
    """Submit a command as a Job and process it with one worker cycle."""
    result = submit_channel_input(
        registry, "cli", {"text": text, "sender": sender},
        queue=_queue, control_plane=_cp,
    )

    if "error" in result:
        print(f"[!] {result['error']}")
        return

    print(f"\n-- Job submitted -----------------------------------------")
    print(f"  job_id:   {result['job_id']}")
    print(f"  state:    {result['state']}")
    print(f"  channel:  {result['channel']}")

    # Run one worker cycle to process the new job
    _process_one(registry)

    # Re-fetch the completed job for the result
    from src.platform.runtime.job_store import job_store

    stored = job_store.get(result["job_id"])
    if stored and stored.result:
        print(f"\n-- Result -------------------------------------------------")
        print(f"  output:   {stored.result}")

    # Show the send() output
    from src.platform.runtime.channels.cli import CLIChannel

    channel = CLIChannel()
    outbound = channel.send({
        "output": stored.result if stored and stored.result else f"Processed: {text}",
        "metadata": {"job_id": result["job_id"], "status": stored.state.value if stored else "unknown"},
    })
    print(f"\n-- Egress (send() result) -------------------------------")
    print(f"  text:     {outbound['text']}")
    print(f"  metadata: {outbound['metadata']}")
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
        help="Single command text (omit for interactive/pipe mode)",
    )
    parser.add_argument(
        "--sender",
        default=None,
        help="Optional sender identity",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

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
