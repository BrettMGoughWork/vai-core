"""
CycleDetailsPanel — expanded view of a selected cycle's transitions, drift,
repairs, memory writes, safety checks, and errors.
"""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static


class CycleDetailsPanel(Widget):
    """Right panel: structured detail view of one selected cycle."""

    DEFAULT_CSS = """
    CycleDetailsPanel {
        width: 1fr;
        background: $background;
        padding: 0;
    }
    CycleDetailsPanel #details-header {
        background: $primary-darken-3;
        color: $text;
        padding: 0 1;
        text-style: bold;
        height: 1;
    }
    CycleDetailsPanel VerticalScroll {
        height: 1fr;
        padding: 0 1;
    }
    CycleDetailsPanel #details-body {
        padding: 1 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(" ◇ CYCLE DETAILS", id="details-header")
        with VerticalScroll():
            yield Static(
                "[dim]Select a cycle from the list to view details.[/dim]",
                id="details-body",
            )

    def show_cycle(self, cycle_data: dict) -> None:
        """Render *cycle_data* into the details panel."""
        body = self.query_one("#details-body", Static)
        body.update(_render_cycle(cycle_data))

    def clear(self) -> None:
        body = self.query_one("#details-body", Static)
        body.update("[dim]Select a cycle from the list to view details.[/dim]")


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _render_cycle(d: dict) -> str:
    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────────────────
    cycle_num = d.get("cycle", "?")
    ts = d.get("timestamp", "")
    terminal = d.get("terminal", False)
    reason = d.get("termination_reason") or ""

    lines.append(f"[bold white]Cycle {cycle_num:>04}[/bold white]  [dim]{ts}[/dim]")
    if terminal:
        colour = "magenta" if reason == "terminal" else "red"
        lines.append(f"[bold {colour}]  ■ TERMINAL — {reason.upper()}[/bold {colour}]")
    lines.append("")

    # ── Transitions ───────────────────────────────────────────────────────
    lines.append(_section_header("Transitions"))
    transitions = _collect_transitions(d)
    if transitions:
        for sg_id, t in transitions:
            ok = t.get("success", False)
            mark = "[green]✓[/green]" if ok else "[red]✗[/red]"
            frm = t.get("from_state", "?")
            evt = t.get("event", "?")
            to = t.get("to_state") or "—"
            sg_short = _short_id(sg_id)
            lines.append(f"  {mark} [dim]{sg_short}[/dim]  {frm} [cyan]─[{evt}]→[/cyan] {to}")
    else:
        lines.append("  [dim](none)[/dim]")
    lines.append("")

    # ── Drift Signals ─────────────────────────────────────────────────────
    lines.append(_section_header("Drift Signals"))
    drifts = _collect_drift(d)
    if drifts:
        for sg_id, drift in drifts:
            cls = drift.get("classification", "unknown")
            conf = drift.get("confidence", 0.0)
            confirmed = (drift.get("confirmation") or {}).get("confirmed", False)
            badge = "[yellow]CONFIRMED[/yellow]" if confirmed else "[dim]pending[/dim]"
            lines.append(
                f"  {badge} [yellow]{cls}[/yellow] "
                f"(conf={conf:.2f}) [dim]{_short_id(sg_id)}[/dim]"
            )
            for sig in (drift.get("confirmation") or {}).get("signals", []):
                stype = sig.get("type", "?")
                sev = sig.get("severity", "?")
                sev_colour = {"low": "dim", "medium": "yellow", "high": "red"}.get(sev, "white")
                lines.append(f"    [dim]·[/dim] [{sev_colour}]{stype} [{sev}][/{sev_colour}]")
    else:
        lines.append("  [dim](none)[/dim]")
    lines.append("")

    # ── Repairs ───────────────────────────────────────────────────────────
    lines.append(_section_header("Repairs"))
    repairs = _collect_repairs(d)
    if repairs:
        for sg_id, adj in repairs:
            ok = adj.get("repair_succeeded", False)
            colour = "green" if ok else "red"
            plan_id = _short_id(adj.get("plan_id") or "")
            actions = ", ".join(adj.get("actions_applied") or []) or "—"
            lines.append(
                f"  [{colour}]{'OK' if ok else 'FAIL'}[/{colour}] "
                f"plan={plan_id}  actions=[dim]{actions}[/dim]  "
                f"[dim]{_short_id(sg_id)}[/dim]"
            )
            if adj.get("error"):
                lines.append(f"    [red]error: {adj['error']}[/red]")
    else:
        lines.append("  [dim](none)[/dim]")
    lines.append("")

    # ── Memory Writes ─────────────────────────────────────────────────────
    lines.append(_section_header("Memory Writes"))
    writes = _collect_writes(d)
    if writes:
        for mu in writes:
            op = mu.get("operation", "?")
            store = mu.get("store", "?")
            rid = mu.get("record_id", "?")
            colour = "green" if op == "write" else "red"
            lines.append(
                f"  [{colour}]{op:<6}[/{colour}] "
                f"[cyan]{store:<8}[/cyan] [dim]{rid[:40]}[/dim]"
            )
    else:
        lines.append("  [dim](none)[/dim]")
    lines.append("")

    # ── Safety Checks ─────────────────────────────────────────────────────
    lines.append(_section_header("Safety Checks"))
    blocked = [
        (sg.get("subgoal_id", "?"), sg.get("safety_errors", []))
        for sg in d.get("subgoal_results", [])
        if sg.get("safety_blocked")
    ]
    if blocked:
        for sg_id, errs in blocked:
            lines.append(f"  [bold red]BLOCKED[/bold red] [dim]{_short_id(sg_id)}[/dim]")
            for err in errs:
                lines.append(f"    [red]· {err}[/red]")
    else:
        lines.append("  [dim green]✓ All clear[/dim green]")
    lines.append("")

    # ── Errors ────────────────────────────────────────────────────────────
    lines.append(_section_header("Errors"))
    errors = d.get("errors") or []
    if errors:
        for e in errors:
            etype = e.get("error_type", "?")
            msg = e.get("message", "")
            sg_id = e.get("subgoal_id") or ""
            lines.append(
                f"  [bold red]{etype}[/bold red] {msg}"
                + (f"  [dim]{_short_id(sg_id)}[/dim]" if sg_id else "")
            )
    else:
        lines.append("  [dim](none)[/dim]")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Data extraction helpers
# ---------------------------------------------------------------------------

def _collect_transitions(d: dict) -> list[tuple[str, dict]]:
    out = []
    for sg in d.get("subgoal_results", []):
        sg_id = sg.get("subgoal_id", "?")
        outcome = sg.get("reflection_outcome") or {}
        for t in outcome.get("transitions_applied", []):
            out.append((sg_id, t))
    return out


def _collect_drift(d: dict) -> list[tuple[str, dict]]:
    out = []
    for sg in d.get("subgoal_results", []):
        outcome = sg.get("reflection_outcome") or {}
        drift = outcome.get("drift_report") or {}
        cls = drift.get("classification", "no_drift")
        confirmed = (drift.get("confirmation") or {}).get("confirmed", False)
        if cls != "no_drift" or confirmed or drift.get("trigger"):
            out.append((sg.get("subgoal_id", "?"), drift))
    return out


def _collect_repairs(d: dict) -> list[tuple[str, dict]]:
    out = []
    for sg in d.get("subgoal_results", []):
        outcome = sg.get("reflection_outcome") or {}
        adj = outcome.get("plan_adjustment")
        if adj:
            out.append((sg.get("subgoal_id", "?"), adj))
    return out


def _collect_writes(d: dict) -> list[dict]:
    out = []
    for sg in d.get("subgoal_results", []):
        outcome = sg.get("reflection_outcome") or {}
        out.extend(outcome.get("memory_updates", []))
    return out


def _section_header(title: str) -> str:
    return f"[bold white underline]{title}[/bold white underline]"


def _short_id(id_str: str) -> str:
    if not id_str:
        return "—"
    return id_str[:24] + "…" if len(id_str) > 24 else id_str
