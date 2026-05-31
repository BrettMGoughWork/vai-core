"""
HealthSummaryPanel — compact footer bar with aggregate run metrics.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


class HealthSummaryPanel(Widget):
    """
    Single-row metrics bar shown at the bottom of the dashboard.

    Displays aggregated counts across all loaded cycles:
    total cycles, drift events, repairs, errors, safety violations.
    """

    DEFAULT_CSS = """
    HealthSummaryPanel {
        height: 1;
        background: $primary-darken-3;
        padding: 0 1;
    }
    HealthSummaryPanel Static {
        height: 1;
        content-align: left middle;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(self._format_bar({}), id="health-bar")

    def update_stats(self, stats: dict) -> None:
        """Re-render the bar with fresh *stats* from CycleListPanel.aggregate_stats()."""
        self.query_one("#health-bar", Static).update(self._format_bar(stats))

    @staticmethod
    def _format_bar(stats: dict) -> str:
        total   = stats.get("total", 0)
        drift   = stats.get("drift", 0)
        repairs = stats.get("repairs", 0)
        errors  = stats.get("errors", 0)
        safety  = stats.get("safety_violations", 0)

        drift_c  = "yellow" if drift   else "dim"
        repair_c = "cyan"   if repairs else "dim"
        error_c  = "red"    if errors  else "dim"
        safety_c = "red"    if safety  else "dim"

        return (
            f"[dim]Cycles:[/dim] [bold]{total}[/bold]  "
            f"[dim]Drift:[/dim] [{drift_c}]{drift}[/{drift_c}]  "
            f"[dim]Repairs:[/dim] [{repair_c}]{repairs}[/{repair_c}]  "
            f"[dim]Errors:[/dim] [{error_c}]{errors}[/{error_c}]  "
            f"[dim]Safety violations:[/dim] [{safety_c}]{safety}[/{safety_c}]"
        )
