"""TUI Channel — pure-logic TUI transport adapter for Stratum-4.

Converts TUI app events (keyboard shortcuts, panel interactions) into
:class:`InboundChannelMessage` objects and converts outbound S4 messages
into structured screen-rendering data models.

This slice is pure logic only: no curses, no textual, no terminal IO.
The runnable textual app lives in ``tools/channels/tui_app.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from src.platform.runtime.channels.base import Channel, InboundChannelMessage
from src.platform.runtime.channels.registry import ChannelRegistry


# ---------------------------------------------------------------------------
# Data models — structured TUI screen layout (pure logic)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TUIPanel:
    """A single panel in the TUI layout.

    Attributes:
        panel_id:   Unique identifier (e.g. ``"workers"``, ``"jobs"``).
        title:      Panel header text.
        lines:      List of ``(content, style_hint)`` tuples forming rows.
        style_hint: Overall panel decoration hint (``"default"``,
                    ``"highlight"``, ``"alert"``).
    """

    panel_id: str
    title: str
    lines: tuple[tuple[str, str], ...]  # (content, style_hint)
    style_hint: str = "default"


@dataclass(frozen=True)
class TUIStatusBar:
    """Single-line status bar data.

    Attributes:
        segments:  Ordered list of ``(text, style_hint)`` segments.
    """

    segments: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class TUIScreen:
    """Complete TUI screen layout — pure data.

    Attributes:
        panels:     The panels to render, in display order.
        status_bar: Optional footer status bar.
        title:      Optional window title override.
    """

    panels: tuple[TUIPanel, ...]
    status_bar: TUIStatusBar | None = None
    title: str = "VAI — Stratum-4 Operator Console"

    def with_updated_panel(self, panel_id: str, **overrides: Any) -> TUIScreen:
        """Return a new :class:`TUIScreen` with one panel replaced.

        Pure functional update — the original is not mutated.

        Args:
            panel_id: The panel to update.
            **overrides: Fields to pass to :func:`dataclasses.replace`.

        Returns:
            A new :class:`TUIScreen` with the updated panel.
        """
        new_panels: list[TUIPanel] = []
        for p in self.panels:
            if p.panel_id == panel_id:
                new_panels.append(
                    TUIPanel(
                        panel_id=p.panel_id,
                        title=overrides.get("title", p.title),
                        lines=overrides.get("lines", p.lines),
                        style_hint=overrides.get("style_hint", p.style_hint),
                    )
                )
            else:
                new_panels.append(p)
        return TUIScreen(
            panels=tuple(new_panels),
            status_bar=self.status_bar,
            title=self.title,
        )


# ---------------------------------------------------------------------------
# TUI Channel adapter
# ---------------------------------------------------------------------------


class TUIChannel(Channel):
    """TUI transport adapter.

    Converts TUI app events (dicts with ``action`` and optional ``data``
    fields) into canonical :class:`InboundChannelMessage` instances,
    normalises them into S4 job payloads, and converts outbound payloads
    into structured :class:`TUIScreen` rendering data.

    Pure logic — no curses, no textual, no terminal IO.

    Args:
        clock: A no-arg callable returning the current Unix timestamp
            (defaults to :func:`time.time`).  Inject a deterministic
            clock in tests.
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        from time import time

        self._clock = clock if clock is not None else time

    # ------------------------------------------------------------------
    # Channel protocol
    # ------------------------------------------------------------------

    def receive(self, raw_input: Any) -> InboundChannelMessage:
        """Convert a TUI app event into an :class:`InboundChannelMessage`.

        Args:
            raw_input: A ``dict`` with fields:

                - ``action`` (``str``): The event identifier (e.g.
                  ``"submit"``, ``"select_job"``, ``"quit"``).
                - ``data`` (``dict | None``, optional): Event payload.
                - ``sender`` (``str | None``, optional): The user identity.

        Returns:
            A canonical :class:`InboundChannelMessage` with
            ``channel="tui"``.

        Raises:
            TypeError: If *raw_input* is not a ``dict``.
            ValueError: If the ``action`` field is missing or not a string.
        """
        if not isinstance(raw_input, dict):
            raise TypeError(
                f"TUIChannel.receive requires a dict, got {type(raw_input).__name__}"
            )

        action = raw_input.get("action")
        if not isinstance(action, str) or not action.strip():
            raise ValueError(
                "TUIChannel.receive requires an 'action' field with a non-empty string"
            )

        sender: str | None = raw_input.get("sender", None)
        if sender is not None and not isinstance(sender, str):
            raise TypeError(
                f"TUIChannel.receive 'sender' must be a string or None, "
                f"got {type(sender).__name__}"
            )

        return InboundChannelMessage(
            channel="tui",
            sender=sender,
            payload={
                "action": action,
                "data": raw_input.get("data", {}),
            },
            timestamp=self._clock(),
        )

    def normalize(self, message: InboundChannelMessage) -> dict[str, Any]:
        """Normalise an :class:`InboundChannelMessage` into a canonical S4 job payload.

        Returns:
            A dict::

                {
                    "input": ...,        # the action text
                    "metadata": {...},   # channel metadata
                }
        """
        payload = message.payload
        return {
            "input": payload.get("action", ""),
            "metadata": {
                "channel": message.channel,
                "sender": message.sender,
                "event_data": payload.get("data", {}),
                "received_at": message.timestamp,
            },
        }

    def send(self, message: dict[str, Any]) -> dict[str, Any]:
        """Convert an outbound S4 payload into a TUI screen model.

        Returns:
            A dict representing a :class:`TUIScreen`::

                {
                    "screen": {
                        "panels": [...],
                        "status_bar": {...} | None,
                        "title": "...",
                    }
                }
        """
        return {
            "screen": message.get("screen", self._default_screen()),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _default_screen() -> dict[str, Any]:
        """Return an empty/default screen model."""
        return {
            "panels": [
                {
                    "panel_id": "workers",
                    "title": "WORKERS",
                    "lines": [("[dim](no workers)[/dim]", "dim")],
                    "style_hint": "default",
                },
                {
                    "panel_id": "jobs",
                    "title": "JOBS",
                    "lines": [("[dim](no jobs)[/dim]", "dim")],
                    "style_hint": "default",
                },
                {
                    "panel_id": "scheduling",
                    "title": "SCHEDULING",
                    "lines": [("[dim](idle)[/dim]", "dim")],
                    "style_hint": "default",
                },
            ],
            "status_bar": {
                "segments": [
                    ("Status", "dim"),
                    (" | ", "dim"),
                    ("Online", "green"),
                ]
            },
            "title": "VAI — Stratum-4 Operator Console",
        }

    def build_screen(
        self,
        workers: list[dict[str, Any]],
        jobs: list[dict[str, Any]],
        scheduling: dict[str, Any] | None = None,
        heartbeats: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a full :class:`TUIScreen` dict from runtime state.

        This is a convenience for the composition root — it translates
        worker/job/scheduling state into a structured screen layout.

        Args:
            workers:     List of worker state dicts.
            jobs:        List of job metadata dicts.
            scheduling:  Optional scheduling decision dict.
            heartbeats:  Optional heartbeat status dict.

        Returns:
            A screen dict suitable for ``TUIChannel.send()``.
        """
        panels: list[dict[str, Any]] = []

        # ── Workers panel ──────────────────────────────────────────────
        worker_lines: list[tuple[str, str]] = []
        for w in workers:
            wid = w.get("worker_id", "?")
            status = w.get("status", "unknown")
            active = w.get("active_job_id")
            icon = {"alive": "●", "busy": "▶", "idle": "○", "dead": "✖"}.get(
                status, "?"
            )
            colour = {"alive": "green", "busy": "cyan", "idle": "dim", "dead": "red"}.get(
                status, "white"
            )
            suffix = f"  job={active}" if active else ""
            worker_lines.append((f"[{colour}]{icon}[/{colour}]  {wid}{suffix}", status))
        if not worker_lines:
            worker_lines.append(("[dim](no workers)[/dim]", "dim"))

        panels.append({
            "panel_id": "workers",
            "title": f"WORKERS  ({len(workers)})",
            "lines": worker_lines,
            "style_hint": "default",
        })

        # ── Jobs panel ─────────────────────────────────────────────────
        job_lines: list[tuple[str, str]] = []
        for j in jobs:
            jid = j.get("job_id", "?")
            pri = j.get("priority", "-")
            status = j.get("status", "pending")
            style = {"running": "cyan", "pending": "dim", "completed": "green"}.get(
                status, "dim"
            )
            job_lines.append((f"  {jid}  pri={pri}  [{style}]{status}[/{style}]", status))
        if not job_lines:
            job_lines.append(("[dim](no jobs)[/dim]", "dim"))

        panels.append({
            "panel_id": "jobs",
            "title": f"JOBS  ({len(jobs)})",
            "lines": job_lines,
            "style_hint": "default",
        })

        # ── Scheduling panel ───────────────────────────────────────────
        sched_lines: list[tuple[str, str]] = []
        if scheduling:
            mode = scheduling.get("mode", "?")
            decision = scheduling.get("decision", {})
            sched_lines.append((f"Mode: [bold]{mode}[/bold]", "info"))
            if decision.get("job_id"):
                sched_lines.append((f"Next:  {decision['job_id']}", "highlight"))
                sched_lines.append((f"Reason: {decision.get('reason', '-')}", "dim"))
            else:
                sched_lines.append(("[dim]No job selected[/dim]", "dim"))
        else:
            sched_lines.append(("[dim](idle)[/dim]", "dim"))

        panels.append({
            "panel_id": "scheduling",
            "title": "SCHEDULING",
            "lines": sched_lines,
            "style_hint": "default",
        })

        # ── Heartbeats panel (optional) ────────────────────────────────
        hb_lines: list[tuple[str, str]] = []
        if heartbeats:
            hb = heartbeats
            hb_lines.append((
                f"Interval: {hb.get('interval_seconds', '?')}s  "
                f"Last: {hb.get('last_seen_ago', '?')}s",
                "dim",
            ))
            colour = "green" if heartbeats.get("healthy", True) else "red"
            hb_lines.append((
                f"Health: [{colour}]{'Healthy' if heartbeats.get('healthy', True) else 'Unhealthy'}[/{colour}]",
                "dim",
            ))
        else:
            hb_lines.append(("[dim](no heartbeats)[/dim]", "dim"))

        panels.append({
            "panel_id": "heartbeats",
            "title": "HEARTBEATS",
            "lines": hb_lines,
            "style_hint": "default",
        })

        return {
            "screen": {
                "panels": panels,
                "status_bar": {
                    "segments": [
                        (f"Workers: {len(workers)}", "dim"),
                        (" | ", "dim"),
                        (f"Jobs: {len(jobs)}", "dim"),
                        (" | ", "dim"),
                        ("q: Quit  r: Refresh", "dim"),
                    ],
                },
                "title": "VAI — Stratum-4 Operator Console",
            },
        }


# ---------------------------------------------------------------------------
# Convenience — register the default TUI channel
# ---------------------------------------------------------------------------


def register_tui_channel(
    registry: ChannelRegistry,
    clock: Callable[[], float] | None = None,
) -> None:
    """Register a :class:`TUIChannel` in *registry* under the name ``"tui"``.

    Args:
        registry: The :class:`ChannelRegistry` to register into.
        clock:    Optional deterministic clock (see :class:`TUIChannel`).
    """
    registry.register("tui", TUIChannel(clock=clock))
