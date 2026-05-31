"""
Stratum-2 Agent Inspection Dashboard.

A read-only, developer-facing TUI that visualises agent cycle traces
and memory substrate state in real time.

Usage:
    python -m tools.inspector.dashboard
    python -m tools.inspector.dashboard --trace-dir /path/to/agent_traces
    python -m tools.inspector.dashboard --trace-dir /path/to/agent_traces --watch

No runtime modification. No LLM calls. No side effects.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static

from tools.inspector.file_watcher import TraceDirectoryWatcher
from tools.inspector.panels.cycle_list import CycleListPanel
from tools.inspector.panels.cycle_details import CycleDetailsPanel
from tools.inspector.panels.memory_inspector import MemoryInspectorPanel
from tools.inspector.panels.health_summary import HealthSummaryPanel


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class InspectorApp(App):
    """
    Stratum-2 Inspection Dashboard.

    Layout:
        ┌─────────────────────────────────────────┐
        │  Header (title + trace dir)             │
        ├──────────────┬──────────────────────────┤
        │  Cycle List  │  Cycle Details           │
        │  (left)      │  (right)                 │
        ├──────────────┴──────────────────────────┤
        │  Memory Inspector (tabbed)              │
        ├─────────────────────────────────────────┤
        │  Health Summary (footer bar)            │
        └─────────────────────────────────────────┘
    """

    TITLE = "VAI — Stratum-2 Inspection Dashboard"
    SUB_TITLE = "read-only · no runtime modification"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]

    CSS = """
    Screen {
        background: $background;
        layout: vertical;
    }

    #top-pane {
        height: 60%;
        layout: horizontal;
    }

    #bottom-pane {
        height: 40%;
        layout: vertical;
    }

    #no-dir-warning {
        color: $warning;
        text-align: center;
        padding: 1;
    }
    """

    def __init__(self, trace_dir: Path) -> None:
        super().__init__()
        self._trace_dir = trace_dir
        self._watcher: Optional[TraceDirectoryWatcher] = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top-pane"):
            yield CycleListPanel()
            yield CycleDetailsPanel()
        with Vertical(id="bottom-pane"):
            yield MemoryInspectorPanel()
        yield HealthSummaryPanel()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"trace dir: {self._trace_dir}"
        self._watcher = TraceDirectoryWatcher(
            path=self._trace_dir,
            callback=self._on_new_cycle,
        )
        # Initial scan
        self._watcher.poll()
        # Subsequent polls every 500 ms
        self.set_interval(0.5, self._watcher.poll)

    # ── Watcher callback ──────────────────────────────────────────────────

    def _on_new_cycle(self, filename: str, data: dict) -> None:
        """Called by TraceDirectoryWatcher when a new/modified file is found."""
        cycle_list = self.query_one(CycleListPanel)
        cycle_list.add_cycle(filename, data)
        health = self.query_one(HealthSummaryPanel)
        health.update_stats(cycle_list.aggregate_stats())

    # ── Cycle selection ───────────────────────────────────────────────────

    def on_cycle_list_panel_cycle_selected(
        self, event: CycleListPanel.CycleSelected
    ) -> None:
        cycle_list = self.query_one(CycleListPanel)
        prev_data = cycle_list.get_previous_data(event.filename)

        self.query_one(CycleDetailsPanel).show_cycle(event.cycle_data)
        self.query_one(MemoryInspectorPanel).show_cycle(event.cycle_data, prev_data)

    # ── Key actions ───────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        """Force an immediate poll of the trace directory."""
        if self._watcher:
            self._watcher.poll()

    def action_quit(self) -> None:
        self.exit()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tools.inspector.dashboard",
        description="Stratum-2 Agent Inspection Dashboard — read-only TUI",
    )
    parser.add_argument(
        "--trace-dir",
        default="agent_traces",
        metavar="DIR",
        help="Directory containing cycle_*.json trace files (default: agent_traces/)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    trace_dir = Path(args.trace_dir)

    if not trace_dir.exists():
        print(f"[warn] Trace directory '{trace_dir}' does not exist — watching anyway.")

    app = InspectorApp(trace_dir=trace_dir)
    app.run()
