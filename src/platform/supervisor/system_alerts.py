"""
S4.7.4 System-Level Alerts
===========================

Accepts alert events from S4 supervisors, validates payloads, formats for
Slack/email, and delivers via configured transports — all without blocking
supervisor loops.

Usage
-----
    from src.platform.supervisor.system_alerts import AlertManager, SlackTransport, EmailTransport, alert

    mgr = AlertManager(transports=[SlackTransport("#ops"), EmailTransport()])
    mgr.alert("error", "supervisor_loop", "Worker-7 unresponsive",
              "Worker-7 missed 3 consecutive heartbeats")

    # Non-blocking variant (safe from supervisor loops):
    mgr.alert_async("critical", "control_plane", "Job poisoned",
                    "Job abc-123 exceeded max failure threshold")

    # Module-level convenience (uses global singleton):
    configure_alert_manager(mgr)
    alert("error", "worker", "Pipeline crash", "Exception in stage 4")
"""

from __future__ import annotations

import enum
import sys
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Alert severity levels
# ---------------------------------------------------------------------------


class AlertSeverity(enum.Enum):
    """Allowed alert severity levels, ordered from least to most severe."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    @classmethod
    def valid_values(cls) -> list[str]:
        return [m.value for m in cls]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SystemAlert:
    """A validated system-level alert event.

    Attributes:
        id: Unique alert identifier (UUID4 string).
        severity: One of info/warning/error/critical.
        source: Component that generated the alert (e.g. "supervisor_loop").
        summary: Single-sentence summary.
        details: Long-form detail text.
        timestamp: ISO-8601 timestamp string.
        metadata: Machine-readable key/value map.
    """

    id: str
    severity: str
    source: str
    summary: str
    details: str
    timestamp: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeliveryResult:
    """Result of delivering an alert to one transport.

    Attributes:
        event: Always ``"alert_delivery_result"``.
        alert_id: The alert that was delivered.
        transport: Transport name (e.g. ``"slack"``, ``"email"``).
        status: ``"success"`` or ``"failure"``.
        timestamp: ISO-8601 timestamp string.
    """

    event: str = "alert_delivery_result"
    alert_id: str = ""
    transport: str = ""
    status: str = ""
    timestamp: str = ""


# ---------------------------------------------------------------------------
# Transport interface
# ---------------------------------------------------------------------------


class AlertTransport(ABC):
    """Abstract base for alert transports."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable transport name (e.g. ``"slack"``, ``"email"``)."""
        ...

    @abstractmethod
    def deliver(self, alert: SystemAlert) -> dict[str, Any]:
        """Deliver *alert* and return a result dict with at least ``success``.

        Must not raise exceptions — callers wrap in try/except.
        """
        ...


# ---------------------------------------------------------------------------
# Slack transport
# ---------------------------------------------------------------------------


class SlackTransport(AlertTransport):
    """Formats and "delivers" a Slack Block Kit message.

    In this dev-tier implementation, the formatted payload is written to
    stdout as NDJSON.  A production integration would POST to the Slack API.
    """

    def __init__(self, channel: str = "#alerts") -> None:
        self._channel = channel

    @property
    def name(self) -> str:
        return "slack"

    def deliver(self, alert: SystemAlert) -> dict[str, Any]:
        payload = self._format_payload(alert)
        # In development: write to stdout (non-blocking, no network I/O).
        # In production: replace with `requests.post(url, json=payload)`.
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()
        return {"success": True, "transport": "slack", "channel": self._channel}

    def _format_payload(self, alert: SystemAlert) -> dict[str, Any]:
        return {
            "type": "slack",
            "channel": self._channel,
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"[{alert.severity.upper()}] {alert.summary}",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": alert.details,
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"Source: {alert.source}"},
                        {"type": "mrkdwn", "text": f"Timestamp: {alert.timestamp}"},
                    ],
                },
            ],
        }


# ---------------------------------------------------------------------------
# Email transport
# ---------------------------------------------------------------------------


class EmailTransport(AlertTransport):
    """Formats and delivers alerts via DevSMTPTransport (plain text email).

    Uses the existing :class:`DevSMTPTransport` under the hood.  Falls back
    to a no-op if DevSMTPTransport is unavailable.
    """

    def __init__(
        self,
        recipient: str = "admin@vai-core.local",
        sender: str | None = None,
    ) -> None:
        self._recipient = recipient
        self._sender = sender
        self._smtp = self._build_transport()

    @property
    def name(self) -> str:
        return "email"

    def deliver(self, alert: SystemAlert) -> dict[str, Any]:
        subject = f"[{alert.severity.upper()}] {alert.summary}"
        body = (
            f"{alert.details}\n\n"
            f"Source: {alert.source}\n"
            f"Timestamp: {alert.timestamp}"
        )
        try:
            result = self._smtp.send(
                to=self._recipient,
                subject=subject,
                body=body,
                sender=self._sender,
            )
            return {"success": result.get("success", True), "transport": "email", "error": result.get("error")}
        except Exception as exc:
            return {"success": False, "transport": "email", "error": str(exc)}

    @staticmethod
    def _build_transport() -> Any:
        try:
            from src.platform.transport.dev_smtp import DevSMTPConfig, DevSMTPTransport
            return DevSMTPTransport(DevSMTPConfig())
        except ImportError:
            # Fallback to a minimal no-op transport when DevSMTP is not available
            return _NoOpSMTP()


class _NoOpSMTP:
    """Minimal SMTP stub used when DevSMTPTransport is unavailable."""

    def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        sender: str | None = None,
    ) -> dict[str, Any]:
        return {"success": True, "recipient": to, "subject": subject, "body_len": len(body)}


# ---------------------------------------------------------------------------
# Collecting transport (for testing)
# ---------------------------------------------------------------------------


class CollectingAlertTransport(AlertTransport):
    """Buffers alerts in-memory for test assertions.

    Attributes:
        alerts: List of ``(SystemAlert, delivery_result_dict)`` tuples.
    """

    def __init__(self) -> None:
        self.alerts: list[tuple[SystemAlert, dict[str, Any]]] = []

    @property
    def name(self) -> str:
        return "collecting"

    def deliver(self, alert: SystemAlert) -> dict[str, Any]:
        result = {"success": True, "transport": "collecting"}
        self.alerts.append((alert, result))
        return result

    def delivered(self) -> list[SystemAlert]:
        """Return a snapshot of all collected alerts."""
        return [a for a, _ in self.alerts]

    def reset(self) -> None:
        """Clear all collected alerts."""
        self.alerts.clear()


# ---------------------------------------------------------------------------
# AlertManager
# ---------------------------------------------------------------------------


class AlertManager:
    """Central alert orchestrator.

    Validates alert payloads, formats for each configured transport, and
    delivers them.  The synchronous :meth:`alert` method is the testable core.
    Use :meth:`alert_async` from supervisor loops to avoid blocking.
    """

    def __init__(self, transports: list[AlertTransport] | None = None) -> None:
        self._transports: list[AlertTransport] = transports or []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Transport management
    # ------------------------------------------------------------------

    def add_transport(self, transport: AlertTransport) -> None:
        """Register an additional transport."""
        with self._lock:
            self._transports.append(transport)

    @property
    def transports(self) -> list[AlertTransport]:
        """Return a snapshot of configured transports."""
        with self._lock:
            return list(self._transports)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def alert(
        self,
        severity: str,
        source: str,
        summary: str,
        details: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[DeliveryResult]:
        """Validate and deliver an alert synchronously.

        Args:
            severity: One of ``"info"``, ``"warning"``, ``"error"``,
                ``"critical"``.
            source: Component generating the alert.
            summary: Single-sentence summary.
            details: Long-form description.
            metadata: Optional machine-readable key/value map.

        Returns:
            A list of :class:`DeliveryResult` — one per transport.

        Raises:
            ValueError: If *severity* is not recognised or *summary* is empty.
        """
        alert = self._build_alert(severity, source, summary, details, metadata)
        return self._deliver(alert)

    def alert_async(
        self,
        severity: str,
        source: str,
        summary: str,
        details: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Non-blocking alert delivery.  Safe from supervisor loops.

        Fires a daemon thread per-transport so the caller is never blocked.
        """
        transports = self.transports
        if not transports:
            return

        def _fire() -> None:
            try:
                alert = self._build_alert(severity, source, summary, details, metadata)
                self._deliver(alert)
            except Exception:
                pass  # never throw from background thread

        thread = threading.Thread(target=_fire, daemon=True)
        thread.start()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_alert(
        self,
        severity: str,
        source: str,
        summary: str,
        details: str,
        metadata: dict[str, Any] | None = None,
    ) -> SystemAlert:
        """Construct and validate a :class:`SystemAlert`.

        Raises:
            ValueError: On invalid severity or empty summary.
        """
        sev = severity.lower()
        if sev not in AlertSeverity.valid_values():
            raise ValueError(
                f"Unknown severity {severity!r}. Valid: {AlertSeverity.valid_values()}"
            )
        if not summary or not summary.strip():
            raise ValueError("summary must be a non-empty string")

        now = _iso_timestamp()
        return SystemAlert(
            id=str(uuid.uuid4()),
            severity=sev,
            source=source,
            summary=summary.strip(),
            details=details.strip() if details else "",
            timestamp=now,
            metadata=metadata or {},
        )

    def _deliver(self, alert: SystemAlert) -> list[DeliveryResult]:
        """Deliver *alert* to all configured transports."""
        results: list[DeliveryResult] = []
        transports = self.transports
        if not transports:
            return results

        for transport in transports:
            result = self._deliver_one(transport, alert)
            results.append(result)
        return results

    def _deliver_one(self, transport: AlertTransport, alert: SystemAlert) -> DeliveryResult:
        """Deliver *alert* to a single *transport* and return the result."""
        now = _iso_timestamp()
        try:
            delivery = transport.deliver(alert)
            status = "success" if delivery.get("success") else "failure"
        except Exception:
            status = "failure"

        dr = DeliveryResult(
            alert_id=alert.id,
            transport=transport.name,
            status=status,
            timestamp=now,
        )

        # Also emit via metrics substrate for observability
        _emit_delivery_metric(transport.name, status)

        return dr


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------

_default_manager: AlertManager | None = None
_default_lock: threading.Lock = threading.Lock()


def configure_alert_manager(manager: AlertManager) -> None:
    """Set the global alert manager singleton."""
    global _default_manager
    with _default_lock:
        _default_manager = manager


def get_alert_manager() -> AlertManager | None:
    """Return the configured global alert manager (or ``None``)."""
    with _default_lock:
        return _default_manager


def alert(
    severity: str,
    source: str,
    summary: str,
    details: str,
    metadata: dict[str, Any] | None = None,
) -> list[DeliveryResult] | None:
    """Convenience function — delegates to the global AlertManager.

    Returns ``None`` silently if no manager is configured (no-op).
    """
    mgr = get_alert_manager()
    if mgr is None:
        return None
    return mgr.alert(severity, source, summary, details, metadata)


def alert_async(
    severity: str,
    source: str,
    summary: str,
    details: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Non-blocking convenience function — delegates to the global AlertManager."""
    mgr = get_alert_manager()
    if mgr is None:
        return
    mgr.alert_async(severity, source, summary, details, metadata)


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------


def _iso_timestamp() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return time.strftime("%Y-%m-%dT%H:%M:%S.000000+00:00", time.gmtime())


def _emit_delivery_metric(transport: str, status: str) -> None:
    """Emit a metrics event for alert delivery outcome."""
    try:
        from src.platform.observability.metrics import emit_metric as _em
        _em("s4.alert.delivery", 1.0, {"transport": transport, "status": status})
    except Exception:
        pass


# Must be at end for circular-safe json import
import json  # noqa: E402
