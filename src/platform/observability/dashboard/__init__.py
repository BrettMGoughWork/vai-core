"""
Dashboard v1 — Stratum-4 Observability Dashboard.

A read-only, non-interactive web dashboard that visualises S4's internal
state by consuming observability events (metrics, traces, logs, health).

Usage:

    # Pipe S4 stdout into the dashboard:
    python -m tools.channels.cli_app | python -m src.platform.observability.dashboard

    # Or read from an event file:
    python -m src.platform.observability.dashboard --from-file s4_events.jsonl

    # Then open http://localhost:8765 in your browser.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NoReturn

from src.platform.observability.dashboard.event_model import DashboardEventStore
from src.platform.observability.dashboard.web_server import DashboardWebServer


def run_dashboard(
    mode: str = "web",
    *,
    event_file: str | None = None,
    host: str = "localhost",
    port: int = 8765,
    max_events: int = 5000,
) -> None:
    """Start the S4 Observability Dashboard.

    Args:
        mode:       ``"web"`` or ``"tui"`` (only ``"web"`` is implemented).
        event_file: Path to a JSON-lines event file to tail, or ``None`` for stdin.
        host:       Web server host.
        port:       Web server port.
        max_events: Rolling buffer size for events.

    Raises:
        ValueError: If ``mode`` is not ``"web"``.
    """
    if mode != "web":
        raise ValueError(f"Only mode='web' is implemented, got {mode!r}")

    store = DashboardEventStore(max_events=max_events)
    server = DashboardWebServer(store=store, host=host, port=port)

    # Determine event source
    if event_file:
        source_path = str(Path(event_file).resolve())

        def _ingest_events() -> None:
            import time

            try:
                with open(source_path) as f:
                    # Seek to end for tail mode
                    f.seek(0, 2)
                    while True:
                        line = f.readline()
                        if line:
                            line = line.strip()
                            if line:
                                store.ingest_json_line(line)
                        else:
                            time.sleep(0.05)
            except FileNotFoundError:
                print(f"[dashboard] WARN: event file not found: {source_path}", file=sys.stderr)
            except KeyboardInterrupt:
                pass

        source_label = event_file

    else:

        def _ingest_events() -> None:
            """Read JSON lines from stdin."""
            try:
                for line in sys.stdin:
                    line = line.strip()
                    if line:
                        store.ingest_json_line(line)
            except KeyboardInterrupt:
                pass

        source_label = "stdin"

    import threading

    ingest_thread = threading.Thread(target=_ingest_events, daemon=True)
    ingest_thread.start()

    print(
        f"[dashboard] S4 Observability Dashboard running at http://{host}:{port}",
        file=sys.stderr,
    )
    print(f"[dashboard] Events from: {source_label}", file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] Shutting down.", file=sys.stderr)


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="S4 Observability Dashboard — read-only web UI",
    )
    parser.add_argument(
        "--from-file",
        default=None,
        help="JSON-lines event file to tail (default: stdin)",
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Web server host (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Web server port (default: 8765)",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=5000,
        help="Rolling event buffer size (default: 5000)",
    )
    args = parser.parse_args()

    run_dashboard(
        mode="web",
        event_file=args.from_file,
        host=args.host,
        port=args.port,
        max_events=args.max_events,
    )


if __name__ == "__main__":
    main()
