"""
Stratum-4 Operator Console — TUI Channel Application.

A live, operator-facing dashboard for the S4 runtime.
Connects to the shared ControlPlane, InMemoryQueue, and JobStore
to display real-time worker status, job queue depth, and job details.

Usage::

    python -m tools.channels.tui_app

Keybindings:
    q / Ctrl+C — Quit
    r          — Refresh (manual)

The dashboard auto-refreshes every 2 seconds.
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static

from src.platform.queue.queue import InMemoryQueue
from src.platform.runtime.channels.tui import TUIChannel
from src.platform.runtime.control_plane import ControlPlane

# Shared runtime — same queue + CP that the CLI / web apps use
_live_queue: InMemoryQueue = InMemoryQueue()
_live_cp: ControlPlane = ControlPlane()

# ---------------------------------------------------------------------------
# Widget helpers
# ---------------------------------------------------------------------------

_WIDGET_CSS = """
PanelWidget {
    width: 1fr;
    height: 1fr;
    border: solid $primary-darken-2;
    background: $surface;
    padding: 0 1;
    margin: 0 1 0 0;
}
PanelWidget .panel-title {
    background: $primary-darken-3;
    color: $text;
    text-style: bold;
    padding: 0 1;
    height: 1;
}
PanelWidget .panel-body {
    padding: 0 1;
}
"""


class PanelWidget(Static):
    """A bordered panel with a title bar and body content."""

    DEFAULT_CSS = _WIDGET_CSS

    def __init__(self, panel_id: str, title: str, content: str = "") -> None:
        super().__init__(id=panel_id)
        self._panel_title = title
        self._panel_content = content

    def render(self) -> str:
        title = f"[bold white]{self._panel_title}[/bold white]"
        return f"{title}\n\n{self._panel_content}"

    def update_content(self, content: str, title: str | None = None) -> None:
        if title is not None:
            self._panel_title = title
        self._panel_content = content
        self.refresh()


class StatusBarWidget(Static):
    """Single-row metrics bar at the bottom of the dashboard."""

    DEFAULT_CSS = """
    StatusBarWidget {
        height: 1;
        background: $primary-darken-3;
        padding: 0 1;
        content-align: left middle;
    }
    """

    def __init__(self, text: str = "") -> None:
        super().__init__(text)

    def update_text(self, text: str) -> None:
        self.update(text)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


class OperatorConsoleApp(App):
    """
    Stratum-4 Operator Console.

    Layout:
        ┌──────────────────────────────────────────────────┐
        │  Header (title + channel mode)                   │
        ├────────────────┬────────────────┬────────────────┤
        │  WORKERS       │  JOBS          │  SCHEDULING    │
        │  (alive/busy) │  (pending/job) │  (mode/next)   │
        ├────────────────┴────────────────┴────────────────┤
        │  HEARTBEATS                                       │
        ├──────────────────────────────────────────────────┤
        │  Status Bar                                       │
        └──────────────────────────────────────────────────┘
    """

    TITLE = "VAI — Stratum-4 Operator Console"
    SUB_TITLE = "live runtime (pass --demo for demo data)"

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

    #top-grid {
        height: 60%;
        layout: horizontal;
    }

    #bottom-panel {
        height: 40%;
        layout: vertical;
    }
    """

    def __init__(
        self,
        channel: TUIChannel | None = None,
        queue: InMemoryQueue | None = None,
        control_plane: ControlPlane | None = None,
        demo: bool = False,
    ) -> None:
        super().__init__()
        self._channel = channel or TUIChannel()
        self._queue = queue or _live_queue
        self._cp = control_plane or _live_cp
        self._demo = demo

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="top-grid"):
            yield PanelWidget(panel_id="workers", title="WORKERS")
            yield PanelWidget(panel_id="jobs", title="JOBS")
            yield PanelWidget(panel_id="scheduling", title="SCHEDULING")

        with Vertical(id="bottom-panel"):
            yield PanelWidget(panel_id="heartbeats", title="HEARTBEATS")

        yield StatusBarWidget()
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(2.0, self._render_all)  # auto-refresh every 2s
        self._render_all()

    # ── Rendering ──────────────────────────────────────────────────────

    def _gather_data(self) -> dict:
        """Pull live data from the runtime, or fall back to demo data."""
        if self._demo:
            return _demo_state()

        now = time.time()

        # Workers via heartbeat monitor
        hm = self._cp.heartbeat_monitor
        workers = []
        if hm is not None:
            for status in hm.evaluate(now):
                # Map is_healthy → TUI icon/colour vocabulary
                colour_status = "alive" if status.is_healthy else "dead"
                workers.append({
                    "worker_id": status.worker_id,
                    "status": colour_status,
                    "is_healthy": status.is_healthy,
                    "reason": status.reason or "no recent heartbeat",
                })
        if not workers:
            workers.append({"worker_id": "(none)", "status": "idle", "active_job_id": None})

        # Jobs from job_store
        job_store = self._cp.job_store
        jobs = []
        for meta in job_store.list():
            job = job_store.get(meta["job_id"])
            if job is not None:
                jobs.append({
                    "job_id": job.job_id,
                    "status": job.state.value,
                    "created_at": job.created_at.isoformat() if job.created_at else "",
                })
        jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)

        # Queue depth
        queue_depth = len(self._queue)

        return {
            "workers": workers,
            "jobs": jobs[:20],  # cap display
            "scheduling": {
                "mode": "FIFO",
                "decision": {
                    "queue_depth": queue_depth,
                    "reason": f"{queue_depth} job(s) pending",
                },
            },
            "heartbeats": {
                "interval_seconds": 2.0,
                "last_seen_ago": 0.0,
                "healthy": hm is not None,
                "worker_count": len(workers),
                "total_jobs": len(jobs),
                "uptime": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
            },
        }

    def _render_all(self) -> None:
        """Build screen data from channel and update all widgets."""
        data = self._gather_data()

        screen = self._channel.build_screen(
            workers=data.get("workers", []),
            jobs=data.get("jobs", []),
            scheduling=data.get("scheduling"),
            heartbeats=data.get("heartbeats"),
        )

        panels = screen.get("screen", {}).get("panels", [])
        for p in panels:
            widget = self.query_one(f"#{p['panel_id']}", PanelWidget)
            lines = self._format_lines(p.get("lines", []))
            widget.update_content(lines, title=p.get("title", p["panel_id"]))

        status_bar = screen.get("screen", {}).get("status_bar", {})
        segments = status_bar.get("segments", [])
        bar_text = "  ".join(f"[{s}]{t}[/{s}]" for t, s in segments)
        self.query_one(StatusBarWidget).update_text(bar_text)

    @staticmethod
    def _format_lines(lines: list[tuple[str, str]]) -> str:
        return "\n".join(content for content, _ in lines)

    # ── Actions ────────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        """Re-render all panels."""
        self._render_all()

    def action_quit(self) -> None:
        self.exit()


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------


def _demo_state() -> dict:
    """Return a demo state snapshot for the TUI display."""
    return {
        "workers": [
            {"worker_id": "worker-001", "status": "busy", "active_job_id": "job-004"},
            {"worker_id": "worker-002", "status": "alive", "active_job_id": None},
            {"worker_id": "worker-003", "status": "idle", "active_job_id": None},
            {"worker_id": "worker-004", "status": "alive", "active_job_id": "job-005"},
        ],
        "jobs": [
            {"job_id": "job-001", "priority": 1, "status": "pending"},
            {"job_id": "job-002", "priority": 2, "status": "pending"},
            {"job_id": "job-003", "priority": 3, "status": "completed"},
            {"job_id": "job-004", "priority": 5, "status": "running"},
            {"job_id": "job-005", "priority": 4, "status": "running"},
        ],
        "scheduling": {
            "mode": "PRIORITY",
            "decision": {"job_id": "job-004", "reason": "highest priority"},
        },
        "heartbeats": {
            "interval_seconds": 1.0,
            "last_seen_ago": 0.3,
            "healthy": True,
            "worker_count": 4,
            "total_jobs": 5,
            "uptime": "demo",
        },
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tools.channels.tui_app",
        description="Stratum-4 Operator Console — read-only TUI dashboard",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Show demo data instead of connecting to live runtime",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    app = OperatorConsoleApp(demo=args.demo)
    app.run()
