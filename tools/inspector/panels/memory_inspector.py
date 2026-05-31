"""
MemoryInspectorPanel — tabbed view of the memory snapshot from a selected cycle.

Tabs: Subgoals | Segments | Plans | Drift | Reflection
Each tab shows the current JSON snapshot + a diff from the previous cycle.
"""

from __future__ import annotations

import json
from typing import Optional

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static, TabbedContent, TabPane

from tools.inspector.diff_engine import diff_cycles, format_diff_rich, format_json_rich


_TABS = [
    ("subgoals",    "Subgoals",    "subgoals"),
    ("segments",    "Segments",    "segments"),
    ("plans",       "Plans",       "plans"),
    ("drift",       "Drift",       "drift_events"),
    ("reflection",  "Reflection",  None),   # derived from subgoal_results
]


class MemoryInspectorPanel(Widget):
    """Bottom panel: tabbed memory snapshot viewer with diff support."""

    DEFAULT_CSS = """
    MemoryInspectorPanel {
        height: 1fr;
        border-top: thick $primary-darken-2;
        background: $surface;
    }
    MemoryInspectorPanel #mem-header {
        background: $primary-darken-3;
        color: $text;
        padding: 0 1;
        text-style: bold;
        height: 1;
    }
    MemoryInspectorPanel TabbedContent {
        height: 1fr;
    }
    MemoryInspectorPanel TabPane {
        padding: 0 1;
    }
    MemoryInspectorPanel VerticalScroll {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(" ◈ MEMORY INSPECTOR", id="mem-header")
        with TabbedContent(id="mem-tabs"):
            with TabPane("Subgoals", id="tab-subgoals"):
                with VerticalScroll():
                    yield Static("", id="mem-subgoals", markup=True)
            with TabPane("Segments", id="tab-segments"):
                with VerticalScroll():
                    yield Static("", id="mem-segments", markup=True)
            with TabPane("Plans", id="tab-plans"):
                with VerticalScroll():
                    yield Static("", id="mem-plans", markup=True)
            with TabPane("Drift", id="tab-drift"):
                with VerticalScroll():
                    yield Static("", id="mem-drift", markup=True)
            with TabPane("Reflection", id="tab-reflection"):
                with VerticalScroll():
                    yield Static("", id="mem-reflection", markup=True)

    def show_cycle(self, cycle_data: dict, prev_data: Optional[dict] = None) -> None:
        """Populate all tabs from *cycle_data*, diffing against *prev_data*."""
        snapshot = cycle_data.get("memory_snapshot") or {}
        prev_snapshot = (prev_data or {}).get("memory_snapshot") or {}

        for tab_id, _label, snapshot_key in _TABS:
            static_id = f"mem-{tab_id}"
            static = self.query_one(f"#{static_id}", Static)

            if snapshot_key is not None:
                curr_val = snapshot.get(snapshot_key, [])
                prev_val = prev_snapshot.get(snapshot_key, [])
                static.update(_render_snapshot_tab(curr_val, prev_val))
            else:
                # Reflection tab: collect from subgoal_results
                static.update(_render_reflection_tab(cycle_data, prev_data))

    def clear(self) -> None:
        """Reset all tabs to empty state."""
        for _, _, _ in _TABS:
            pass  # handled below
        for tab_id, _, _ in _TABS:
            try:
                self.query_one(f"#mem-{tab_id}", Static).update(
                    "[dim]No cycle selected.[/dim]"
                )
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Tab renderers
# ---------------------------------------------------------------------------

def _render_snapshot_tab(curr_val: list, prev_val: list) -> str:
    lines: list[str] = []

    # Current snapshot
    lines.append("[bold white underline]Current Snapshot[/bold white underline]")
    if curr_val:
        lines.append(_pretty_list(curr_val))
    else:
        lines.append("[dim](empty)[/dim]")

    # Diff section
    lines.append("")
    lines.append("[bold white underline]Δ Changes from Previous Cycle[/bold white underline]")

    curr_dict = _list_to_indexed_dict(curr_val)
    prev_dict = _list_to_indexed_dict(prev_val)
    diff = diff_cycles(prev_dict, curr_dict)
    lines.append(format_diff_rich(diff))

    return "\n".join(lines)


def _render_reflection_tab(cycle_data: dict, prev_data: Optional[dict]) -> str:
    lines: list[str] = []
    lines.append("[bold white underline]Reflection Traces[/bold white underline]")

    results = cycle_data.get("subgoal_results") or []
    if not results:
        lines.append("[dim](no subgoal results)[/dim]")
        return "\n".join(lines)

    for sg in results:
        sg_id = sg.get("subgoal_id", "?")
        outcome = sg.get("reflection_outcome") or {}
        trace = outcome.get("trace") or {}

        lines.append(f"\n[bold cyan]{_short_id(sg_id)}[/bold cyan]")

        if sg.get("skipped"):
            lines.append(f"  [dim]skipped: {sg.get('skip_reason') or '—'}[/dim]")
            continue

        if trace:
            progress = trace.get("progress") or {}
            drift = trace.get("drift") or {}
            lines.append(
                f"  progress: [bold]{progress.get('progress_rate', '?')}[/bold]  "
                f"subgoals {progress.get('subgoals_complete', 0)}/{progress.get('subgoals_total', 0)}  "
                f"segments {progress.get('segments_complete', 0)}/{progress.get('segments_total', 0)}"
            )
            cls = drift.get("classification", "no_drift")
            conf = drift.get("confidence", 0.0)
            colour = _drift_colour(cls)
            lines.append(f"  drift: [{colour}]{cls}[/{colour}] conf={conf:.2f}")

            repairs = trace.get("repairs") or []
            if repairs:
                lines.append(f"  repairs: {len(repairs)} applied")

            mem_updates = trace.get("memory_updates") or []
            writes = sum(1 for m in mem_updates if m.get("operation") == "write")
            rejects = sum(1 for m in mem_updates if m.get("operation") == "reject")
            lines.append(f"  memory: {writes} writes, {rejects} rejected")
        else:
            lines.append("  [dim](no trace)[/dim]")

    # Diff of reflection traces vs prev
    if prev_data:
        lines.append("\n[bold white underline]Δ Changes from Previous Cycle[/bold white underline]")
        curr_traces = _extract_traces(cycle_data)
        prev_traces = _extract_traces(prev_data)
        diff = diff_cycles(prev_traces, curr_traces)
        lines.append(format_diff_rich(diff))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _pretty_list(items: list) -> str:
    if not items:
        return "[dim](empty)[/dim]"
    try:
        return json.dumps(items, indent=2, default=str)
    except Exception:
        return str(items)


def _list_to_indexed_dict(items: list) -> dict:
    """Convert a list to an index-keyed dict for diffing."""
    return {str(i): v for i, v in enumerate(items)}


def _extract_traces(cycle_data: dict) -> dict:
    """Extract reflection traces as a dict keyed by subgoal_id."""
    out = {}
    for sg in cycle_data.get("subgoal_results") or []:
        sg_id = sg.get("subgoal_id", "?")
        outcome = sg.get("reflection_outcome") or {}
        trace = outcome.get("trace") or {}
        out[sg_id] = trace
    return out


def _drift_colour(classification: str) -> str:
    return {
        "no_drift":       "dim green",
        "minor_drift":    "yellow",
        "moderate_drift": "dark_orange",
        "severe_drift":   "red",
        "critical_drift": "bold red",
    }.get(classification, "white")


def _short_id(id_str: str) -> str:
    if not id_str:
        return "—"
    return id_str[:32] + "…" if len(id_str) > 32 else id_str
