"""Unit tests for the alert notification system (:mod:`src.platform.runtime.alerting`)."""

from __future__ import annotations

import re
import time

import pytest

from src.platform.runtime.alerting import (
    AlertLevel,
    AlertNotifier,
    AlertNotifierConfig,
    DISPATCH_ACTION_ALERT_MAP,
    default_alert_notifier,
    notify_on_dispatch,
)


# ===================================================================
# Helpers
# ===================================================================


class FakeTransport:
    """A transport stub that records sends and returns fixed results."""

    def __init__(self) -> None:
        self.sends: list[dict] = []

    def send(self, *, to, subject, body, sender=None) -> dict:
        result = {
            "success": True,
            "status_code": 200,
            "recipient": to,
            "subject": subject,
            "body_len": len(body),
            "error": None,
            "sent_at": 1234567890.0,
        }
        self.sends.append({"to": to, "subject": subject, "body": body, "sender": sender})
        return result


FakeDispatcher = dict


def fake_dispatch(instruction: dict) -> tuple[str, dict]:
    action = instruction.get("action", "noop")  # allow explicit action override
    return action, {
        "event": "instruction_dispatched",
        "instruction_type": instruction.get("type", "Unknown"),
        "action": action,
        "timestamp": "2025-01-01T00:00:00Z",
    }


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def config() -> AlertNotifierConfig:
    return AlertNotifierConfig(
        recipient="ops@example.com",
        min_level="warning",
        sender="alerts@vai-core.local",
    )


@pytest.fixture
def notifier(config, transport) -> AlertNotifier:
    return AlertNotifier(config, transport)


# ===================================================================
# AlertLevel
# ===================================================================


class TestAlertLevel:
    def test_level_ordering(self) -> None:
        assert AlertLevel.INFO < AlertLevel.WARNING
        assert AlertLevel.WARNING < AlertLevel.ERROR
        assert AlertLevel.ERROR < AlertLevel.CRITICAL

    def test_from_string_valid(self) -> None:
        assert AlertLevel.from_string("info") is AlertLevel.INFO
        assert AlertLevel.from_string("WARNING") is AlertLevel.WARNING
        assert AlertLevel.from_string("Error") is AlertLevel.ERROR  # mixed case
        assert AlertLevel.from_string("CRITICAL") is AlertLevel.CRITICAL

    def test_from_string_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown alert level"):
            AlertLevel.from_string("unknown")

    def test_from_string_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            AlertLevel.from_string("")


# ===================================================================
# DISPATCH_ACTION_ALERT_MAP guarantees
# ===================================================================


class TestDispatchActionAlertMap:
    def test_covers_all_canonical_actions(self) -> None:
        expected = {"panic", "fail", "recover", "degrade", "retry", "noop"}
        assert set(DISPATCH_ACTION_ALERT_MAP) == expected

    def test_panic_is_critical(self) -> None:
        assert DISPATCH_ACTION_ALERT_MAP["panic"] is AlertLevel.CRITICAL

    def test_fail_is_error(self) -> None:
        assert DISPATCH_ACTION_ALERT_MAP["fail"] is AlertLevel.ERROR

    def test_degrade_and_retry_are_warning(self) -> None:
        assert DISPATCH_ACTION_ALERT_MAP["degrade"] is AlertLevel.WARNING
        assert DISPATCH_ACTION_ALERT_MAP["retry"] is AlertLevel.WARNING

    def test_recover_and_noop_are_info(self) -> None:
        assert DISPATCH_ACTION_ALERT_MAP["recover"] is AlertLevel.INFO
        assert DISPATCH_ACTION_ALERT_MAP["noop"] is AlertLevel.INFO


# ===================================================================
# AlertNotifierConfig
# ===================================================================


class TestAlertNotifierConfig:
    def test_default_recipient(self) -> None:
        c = AlertNotifierConfig()
        assert c.recipient == "admin@vai-core.local"

    def test_default_min_level(self) -> None:
        c = AlertNotifierConfig()
        assert c.min_level == "warning"

    def test_default_sender_is_none(self) -> None:
        c = AlertNotifierConfig()
        assert c.sender is None

    def test_custom_values(self) -> None:
        c = AlertNotifierConfig(
            recipient="ops@example.com",
            min_level="critical",
            sender="noreply@example.com",
        )
        assert c.recipient == "ops@example.com"
        assert c.min_level == "critical"
        assert c.sender == "noreply@example.com"


# ===================================================================
# AlertNotifier.alert()
# ===================================================================


class TestAlertNotifierAlert:
    def test_sends_when_level_meets_min_level(self, notifier, transport) -> None:
        result = notifier.alert("disk full", "no space", level="warning")
        assert result["success"] is True
        assert transport.sends == [
            {
                "to": "ops@example.com",
                "subject": "disk full",
                "body": "no space",
                "sender": "alerts@vai-core.local",
            }
        ]

    def test_sends_when_level_exceeds_min_level(self, notifier, transport) -> None:
        result = notifier.alert("critical!", "OOM", level="critical")
        assert result["success"] is True
        assert len(transport.sends) == 1

    def test_skips_when_level_below_min_level(self, notifier, transport) -> None:
        result = notifier.alert("info only", "just letting you know", level="info")
        assert result == {
            "skipped": True,
            "reason": "level info below min_level warning",
        }
        assert transport.sends == []  # no transport call

    def test_skips_non_default_level_info(self, notifier, transport) -> None:
        """Default alert level is WARNING, but we also verify default level works."""
        # default level is WARNING — should send
        result = notifier.alert("default level", "body")
        assert result["success"] is True
        assert len(transport.sends) == 1

    def test_critical_always_sends_with_warning_min(self, notifier, transport) -> None:
        result = notifier.alert("critical!", "OOM", level="critical")
        assert result["success"] is True

    def test_sender_none_falls_through_to_transport(self, transport) -> None:
        cfg = AlertNotifierConfig(
            recipient="admin@example.com", min_level="info", sender=None
        )
        n = AlertNotifier(cfg, transport)
        n.alert("test", "body", level="info")
        assert transport.sends[0]["sender"] is None

    def test_accepts_alert_level_enum_directly(self, notifier, transport) -> None:
        result = notifier.alert("enum test", "body", level=AlertLevel.ERROR)
        assert result["success"] is True
        assert len(transport.sends) == 1

    def test_invalid_level_raises(self, notifier) -> None:
        with pytest.raises(ValueError, match="Unknown alert level"):
            notifier.alert("bad", "body", level="unknown")


# ===================================================================
# AlertNotifier.config property
# ===================================================================


class TestAlertNotifierConfigProperty:
    def test_exposes_underlying_config(self, config, notifier) -> None:
        assert notifier.config is config

    def test_config_mutation_reflected(self, config, notifier) -> None:
        assert notifier.config.recipient == "ops@example.com"
        config.recipient = "changed@example.com"
        # In-memory mutation — the notifier holds the same object ref
        assert notifier.config.recipient == "changed@example.com"


# ===================================================================
# default_alert_notifier()
# ===================================================================


class TestDefaultAlertNotifier:
    def test_returns_alert_notifier_instance(self) -> None:
        n = default_alert_notifier()
        assert isinstance(n, AlertNotifier)

    def test_config_has_default_recipient(self) -> None:
        n = default_alert_notifier()
        assert n.config.recipient == "admin@vai-core.local"

    def test_config_min_level_is_warning(self) -> None:
        n = default_alert_notifier()
        assert n.config.min_level == "warning"

    def test_config_sender_is_none(self) -> None:
        n = default_alert_notifier()
        assert n.config.sender is None

    def test_default_notifier_sends_via_dev_smtp(self) -> None:
        """Smoke — the factory wires DevSMTPTransport internally."""
        # We can't easily assert the transport type without exposing it,
        # but we can verify the notifier is fully initialised.
        n = default_alert_notifier()
        assert hasattr(n, "_transport")


# ===================================================================
# notify_on_dispatch()
# ===================================================================


class TestNotifyOnDispatch:
    def test_panic_instruction_sends_critical_alert(self, notifier, transport) -> None:
        instruction = {"type": "PanicInstruction", "reason": "OOM detected"}
        action, event, alert = notify_on_dispatch(
            instruction, fake_dispatch, notifier
        )
        assert action == "noop"  # default from fake_dispatch
        # We need to override the action for panic
        instruction_with_action = {
            "type": "PanicInstruction",
            "reason": "OOM detected",
            "action": "panic",
        }
        action, event, alert = notify_on_dispatch(
            instruction_with_action, fake_dispatch, notifier
        )
        assert action == "panic"
        assert event["instruction_type"] == "PanicInstruction"
        assert alert is not None
        assert alert["success"] is True
        assert transport.sends[0]["subject"] == "[S4] PANIC: PanicInstruction"

    def test_fail_instruction_sends_error_alert(self, notifier, transport) -> None:
        instruction = {"type": "PoisonInstruction", "reason": "corrupt state", "action": "fail"}
        action, event, alert = notify_on_dispatch(
            instruction, fake_dispatch, notifier
        )
        assert action == "fail"
        assert alert is not None
        assert alert["success"] is True
        assert transport.sends[0]["body"] == "corrupt state"

    def test_recover_instruction_skipped_at_warning_min(self, notifier, transport) -> None:
        """recover → INFO, which is below default min_level 'warning'."""
        instruction = {"type": "RecoveryInstruction", "reason": "all good", "action": "recover"}
        action, event, alert = notify_on_dispatch(
            instruction, fake_dispatch, notifier
        )
        assert action == "recover"
        assert alert is None  # filtered out
        assert transport.sends == []

    def test_recover_sends_when_min_level_is_info(self, transport) -> None:
        cfg = AlertNotifierConfig(recipient="ops@example.com", min_level="info")
        n = AlertNotifier(cfg, transport)
        instruction = {"type": "RecoveryInstruction", "reason": "recovered", "action": "recover"}
        action, event, alert = notify_on_dispatch(
            instruction, fake_dispatch, n
        )
        assert action == "recover"
        assert alert is not None
        assert alert["success"] is True
        assert len(transport.sends) == 1

    def test_degrade_sends_warning_alert(self, notifier, transport) -> None:
        instruction = {"type": "DegradedInstruction", "reason": "high load", "action": "degrade"}
        action, event, alert = notify_on_dispatch(
            instruction, fake_dispatch, notifier
        )
        assert action == "degrade"
        assert alert is not None
        assert alert["success"] is True

    def test_retry_sends_warning_alert(self, notifier, transport) -> None:
        instruction = {"type": "RetryInstruction", "reason": "timeout", "action": "retry"}
        action, event, alert = notify_on_dispatch(
            instruction, fake_dispatch, notifier
        )
        assert action == "retry"
        assert alert is not None
        assert alert["success"] is True

    def test_unknown_type_maps_to_noop_info_skipped(self, notifier, transport) -> None:
        """Unknown instruction → noop → INFO → skipped at warning min_level."""
        instruction = {"type": "UnknownInstruction", "reason": "something", "action": "noop"}
        action, event, alert = notify_on_dispatch(
            instruction, fake_dispatch, notifier
        )
        assert action == "noop"
        assert alert is None
        assert transport.sends == []

    def test_custom_subject_prefix(self, notifier, transport) -> None:
        instruction = {"type": "PanicInstruction", "reason": "OOM", "action": "panic"}
        action, event, alert = notify_on_dispatch(
            instruction, fake_dispatch, notifier, subject_prefix="[CUSTOM]"
        )
        assert alert is not None
        assert transport.sends[0]["subject"] == "[CUSTOM] PANIC: PanicInstruction"

    def test_returns_three_tuple(self, notifier) -> None:
        instruction = {"type": "PanicInstruction", "reason": "OOM", "action": "panic"}
        result = notify_on_dispatch(instruction, fake_dispatch, notifier)
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_dispatch_event_contains_expected_keys(self, notifier) -> None:
        instruction = {"type": "RetryInstruction", "reason": "timeout", "action": "retry"}
        action, event, alert = notify_on_dispatch(
            instruction, fake_dispatch, notifier
        )
        assert "event" in event
        assert "instruction_type" in event
        assert "action" in event
        assert "timestamp" in event
