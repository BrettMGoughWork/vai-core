"""Alert notification system — routes system events to configured transports.

Provides :class:`AlertNotifier` for sending severity-gated alerts and a
:func:`notify_on_dispatch` helper that composes the instruction dispatcher
with the notifier so daemon actions (panic, fail, degrade, etc.) trigger
email (or other) notifications automatically.

Usage
-----
    config = AlertNotifierConfig(recipient="ops@example.com")
    transport = DevSMTPTransport(DevSMTPConfig())
    notifier = AlertNotifier(config, transport)

    # Send an alert (filtered by min_level)
    result = notifier.alert(
        subject="Disk 90% full",
        body="/dev/sda1 at 90% capacity",
        level="error",
    )

    # Compose with the instruction dispatcher
    action, event, alert = notify_on_dispatch(
        {"type": "PanicInstruction", "reason": "OOM"},
        dispatcher,
        notifier,
    )
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Alert severity levels (ordered — comparisons work via IntEnum)
# ---------------------------------------------------------------------------


class AlertLevel(enum.IntEnum):
    """Alert severity levels in ascending order."""

    INFO = 0
    WARNING = 1
    ERROR = 2
    CRITICAL = 3

    @classmethod
    def from_string(cls, s: str) -> AlertLevel:
        """Parse a case-insensitive string to an :class:`AlertLevel`.

        Raises:
            ValueError: If *s* is not a recognised level name.
        """
        try:
            return cls[s.upper()]
        except KeyError:
            valid = ", ".join(m.name.lower() for m in cls)
            raise ValueError(
                f"Unknown alert level {s!r}. Valid: {valid}"
            ) from None


# Maps daemon actions produced by the instruction dispatcher to alert levels.
DISPATCH_ACTION_ALERT_MAP: dict[str, AlertLevel] = {
    "panic": AlertLevel.CRITICAL,
    "fail": AlertLevel.ERROR,
    "recover": AlertLevel.INFO,
    "degrade": AlertLevel.WARNING,
    "retry": AlertLevel.WARNING,
    "noop": AlertLevel.INFO,
}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class AlertNotifierConfig:
    """Configuration for the alert notification system.

    Attributes:
        recipient: Email address where alerts are delivered.
        min_level: Minimum severity that triggers delivery.  One of
            ``"info"``, ``"warning"``, ``"error"``, ``"critical"``.
        sender: Override the ``From`` address (``None`` = use transport
            default, e.g. ``alerts@vai-core.local`` from
            :class:`DevSMTPConfig`).
    """

    recipient: str = "admin@vai-core.local"
    min_level: str = "warning"
    sender: str | None = None


# ---------------------------------------------------------------------------
# AlertNotifier
# ---------------------------------------------------------------------------


class AlertNotifier:
    """Sends severity-gated alerts through a configured transport.

    The notifier checks the requested alert level against
    :attr:`AlertNotifierConfig.min_level` and only delivers when the
    threshold is met or exceeded.

    Args:
        config: Notification routing configuration.
        transport: An object with a ``send(*, to, subject, body, sender)``
            method that returns a result dict (e.g. :class:`DevSMTPTransport`).
        clock: A no-arg callable returning the current Unix timestamp
            (defaults to :func:`time.time`).  Inject a deterministic clock
            in tests.
    """

    def __init__(
        self,
        config: AlertNotifierConfig,
        transport: Any,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._clock = clock or time.time

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def config(self) -> AlertNotifierConfig:
        """Expose the underlying config for introspection."""
        return self._config

    def alert(
        self,
        subject: str,
        body: str,
        *,
        level: str | AlertLevel = AlertLevel.WARNING,
    ) -> dict[str, Any]:
        """Send an alert if *level* meets or exceeds the configured minimum.

        Args:
            subject: Alert subject line.
            body: Alert body text.
            level: Severity level (string like ``"warning"`` or an
                :class:`AlertLevel`).  Defaults to ``WARNING``.

        Returns:
            A result dict.  If the alert was skipped due to level filtering
            the dict contains ``{"skipped": True, "reason": ...}``.
            Otherwise returns the transport's send result.

        Raises:
            ValueError: If *level* is an unrecognised string.
        """
        level_enum = (
            level if isinstance(level, AlertLevel) else AlertLevel.from_string(level)
        )
        min_enum = AlertLevel.from_string(self._config.min_level)

        if level_enum < min_enum:
            return {
                "skipped": True,
                "reason": (
                    f"level {level_enum.name.lower()} below "
                    f"min_level {self._config.min_level}"
                ),
            }

        return self._transport.send(
            to=self._config.recipient,
            subject=subject,
            body=body,
            sender=self._config.sender,
        )


# ---------------------------------------------------------------------------
# Convenience factories
# ---------------------------------------------------------------------------


def default_alert_notifier(
    *,
    clock: Callable[[], float] | None = None,
) -> AlertNotifier:
    """Return an ``AlertNotifier`` with sensible defaults.

    Creates a mail-based notifier using :class:`DevSMTPTransport` pointed
    at the default MailHog endpoint.
    """
    from src.platform.transport.dev_smtp import DevSMTPConfig, DevSMTPTransport

    config = AlertNotifierConfig()
    transport = DevSMTPTransport(DevSMTPConfig(), clock=clock)
    return AlertNotifier(config, transport, clock=clock)


# ---------------------------------------------------------------------------
# Instruction dispatch integration
# ---------------------------------------------------------------------------

# Type alias for a dispatch callable — anything with ``.dispatch(instruction)``
# that returns ``(action: str, event: dict)``.
DispatchFn = Callable[[dict[str, Any]], tuple[str, dict[str, Any]]]


def notify_on_dispatch(
    instruction: dict[str, Any],
    dispatcher: DispatchFn,
    notifier: AlertNotifier,
    *,
    subject_prefix: str = "[S4]",
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    """Dispatch an instruction and send an alert if the action warrants it.

    Composes the :class:`UnifiedInstructionDispatcher` (or any dispatch
    callable) with the :class:`AlertNotifier`.  High-severity actions
    (panic → critical, fail → error) always produce alerts.  Low-severity
    actions (recover, noop) are filtered by the notifier's ``min_level``.

    Args:
        instruction: An instruction dict with at least a ``"type"`` key.
        dispatcher: A callable that accepts *instruction* and returns
            ``(action, dispatch_event)``.
        notifier: The :class:`AlertNotifier` to use for alert delivery.
        subject_prefix: Prefix for the alert subject line.

    Returns:
        A 3-tuple ``(action, dispatch_event, alert_result)``.
        *alert_result* is ``None`` when the action's severity is below the
        notifier's configured threshold.
    """
    action, event = dispatcher(instruction)

    alert_level = DISPATCH_ACTION_ALERT_MAP.get(action, AlertLevel.INFO)
    alert_result = notifier.alert(
        subject=f"{subject_prefix} {action.upper()}: {instruction.get('type', 'Unknown')}",
        body=instruction.get("reason", ""),
        level=alert_level,
    )

    if alert_result.get("skipped"):
        return action, event, None

    return action, event, alert_result
