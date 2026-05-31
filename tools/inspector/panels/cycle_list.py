"""
CycleListPanel — scrollable list of agent cycle traces with colour-coded status badges.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------

STATUS_STYLES: Dict[str, str] = {
    "OK":       "bold green",
    "DRIFT":    "bold yellow",
    "REPAIRS":  "bold cyan",
    "ERROR":    "bold red",
    "TERMINAL": "bold magenta",
}

STATUS_ICONS: Dict[str, str] = {
    "OK":       "●",
    "DRIFT":    "◆",
    "REPAIRS":  "▲",
    "ERROR":    "✖",
    "TERMINAL": "■",
}


def classify_status(cycle_data: dict) -> str:
    """Derive a display status from a raw cycle outcome dict."""
    if cycle_data.get("terminal"):
        reason = cycle_data.get("termination_reason") or ""
        if reason == "terminal":
            return "TERMINAL"
        # error, safety, budget all map to ERROR
        return "ERROR"

    if cycle_data.get("errors"):
        return "ERROR"

    for sg in cycle_data.get("subgoal_results", []):
        outcome = sg.get("reflection_outcome") or {}
        drift = outcome.get("drift_report") or {}
        confirmed = (drift.get("confirmation") or {}).get("confirmed", False)
        has_trigger = drift.get("trigger") is not None
        if confirmed or has_trigger:
            return "DRIFT"

    for sg in cycle_data.get("subgoal_results", []):
        outcome = sg.get("reflection_outcome") or {}
        adj = outcome.get("plan_adjustment") or {}
        if adj.get("repair_succeeded"):
            return "REPAIRS"

    return "OK"


# ---------------------------------------------------------------------------
# Panel widget
# ---------------------------------------------------------------------------

class CycleListPanel(Widget):
    """Left panel: scrollable, selectable list of cycle traces."""

    DEFAULT_CSS = """
    CycleListPanel {
        width: 30;
        border-right: solid $primary-darken-2;
        background: $surface;
        padding: 0;
    }
    CycleListPanel #list-header {
        background: $primary-darken-3;
        color: $text;
        padding: 0 1;
        text-style: bold;
        height: 1;
    }
    CycleListPanel ListView {
        height: 1fr;
        background: $surface;
    }
    CycleListPanel ListItem {
        padding: 0 1;
    }
    CycleListPanel ListItem:hover {
        background: $primary-darken-2;
    }
    CycleListPanel ListItem.--highlight {
        background: $primary-darken-1;
    }
    """

    @dataclass
    class CycleSelected(Message):
        filename: str
        cycle_data: dict

    def __init__(self) -> None:
        super().__init__()
        self._data: Dict[str, dict] = {}      # item_id → cycle_data
        self._files: Dict[str, str] = {}      # item_id → filename
        self._order: list[str] = []           # ordered list of item_ids

    def compose(self) -> ComposeResult:
        yield Static(" ◆ CYCLES", id="list-header")
        yield ListView(id="cycle-lv")

    def add_cycle(self, filename: str, cycle_data: dict) -> None:
        """Add or refresh a cycle entry."""
        item_id = _filename_to_id(filename)
        cycle_num = cycle_data.get("cycle", "?")
        status = classify_status(cycle_data)
        ts = _short_ts(cycle_data.get("timestamp") or "")
        icon = STATUS_ICONS.get(status, "?")
        style = STATUS_STYLES.get(status, "bold white")

        label = (
            f"[{style}]{icon} {status:<8}[/{style}]\n"
            f"[bold white]  [{cycle_num:>04}][/bold white] [dim]{ts}[/dim]"
        )

        lv = self.query_one("#cycle-lv", ListView)

        if item_id in self._data:
            # update existing item label
            try:
                existing = lv.query_one(f"#{item_id}", ListItem)
                existing.query_one(Label).update(label)
            except Exception:
                pass
        else:
            item = ListItem(Label(label), id=item_id)
            lv.append(item)
            self._order.append(item_id)

        self._data[item_id] = cycle_data
        self._files[item_id] = filename

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id
        data = self._data.get(item_id)
        filename = self._files.get(item_id)
        if data is not None and filename:
            self.post_message(self.CycleSelected(filename=filename, cycle_data=data))

    def get_previous_data(self, filename: str) -> Optional[dict]:
        """Return the cycle data for the cycle immediately before *filename*."""
        item_id = _filename_to_id(filename)
        try:
            idx = self._order.index(item_id)
        except ValueError:
            return None
        if idx == 0:
            return None
        return self._data.get(self._order[idx - 1])

    @property
    def cycle_count(self) -> int:
        return len(self._data)

    def aggregate_stats(self) -> dict:
        """Aggregate health stats across all loaded cycles."""
        drift = repairs = errors = safety = 0
        for d in self._data.values():
            status = classify_status(d)
            if status == "DRIFT":
                drift += 1
            elif status == "REPAIRS":
                repairs += 1
            elif status == "ERROR":
                errors += 1
            for sg in d.get("subgoal_results", []):
                if sg.get("safety_blocked"):
                    safety += 1
        return {
            "total": len(self._data),
            "drift": drift,
            "repairs": repairs,
            "errors": errors,
            "safety_violations": safety,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _filename_to_id(filename: str) -> str:
    return "cl-" + filename.replace(".", "-").replace("_", "-")


def _short_ts(ts: str) -> str:
    # "2026-05-31T03:00:00+00:00" → "05-31 03:00"
    try:
        date_part = ts[5:10]   # MM-DD
        time_part = ts[11:16]  # HH:MM
        return f"{date_part} {time_part}"
    except (IndexError, TypeError):
        return ts[:16] if ts else "—"
