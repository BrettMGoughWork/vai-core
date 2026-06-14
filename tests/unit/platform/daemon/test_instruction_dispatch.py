"""Unit tests for UnifiedInstructionDispatcher.

Tests are grouped by contract area:
- Schema validation (validate, reject bad inputs)
- Dispatch (known types, unknown types, action_map override)
- Behavioural contract (determinism, no mutation, side-effect-free)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.platform.daemon.instruction_dispatch import (
    DEFAULT_ACTION_MAP,
    VALID_ACTIONS,
    InstructionDispatchConfig,
    UnifiedInstructionDispatcher,
    default_dispatcher,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fixed_clock() -> list[datetime]:
    """Deterministic clock that always returns the same timestamp."""
    dt = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)
    return [dt]


@pytest.fixture
def dispatcher(fixed_clock: list[datetime]) -> UnifiedInstructionDispatcher:
    return default_dispatcher(clock=lambda: fixed_clock[0])


# ---------------------------------------------------------------------------
# UnifiedInstructionDispatcher.validate
# ---------------------------------------------------------------------------


class TestValidate:
    """Schema validation — all inputs are dicts with at least a ``type`` key."""

    def test_valid_minimal(self, dispatcher: UnifiedInstructionDispatcher) -> None:
        """Minimal valid instruction: only type."""
        result = dispatcher.validate({"type": "PanicInstruction"})
        assert result == {"type": "PanicInstruction"}

    def test_valid_full(self, dispatcher: UnifiedInstructionDispatcher) -> None:
        """Valid instruction with all fields."""
        instruction = {
            "type": "RetryInstruction",
            "reason": "Transient timeout",
            "metadata": {"attempt": 3, "delay": 5.0},
        }
        result = dispatcher.validate(instruction)
        assert result is instruction  # no mutation

    def test_rejects_non_dict(self, dispatcher: UnifiedInstructionDispatcher) -> None:
        """Non-dict input raises TypeError."""
        with pytest.raises(TypeError, match="must be a dict"):
            dispatcher.validate("PanicInstruction")  # type: ignore[arg-type]

    def test_rejects_missing_type(self, dispatcher: UnifiedInstructionDispatcher) -> None:
        """Missing 'type' key raises ValueError."""
        with pytest.raises(ValueError, match="missing required key 'type'"):
            dispatcher.validate({"reason": "nope"})

    def test_rejects_non_string_type(self, dispatcher: UnifiedInstructionDispatcher) -> None:
        """Non-string type raises TypeError."""
        with pytest.raises(TypeError, match="type' must be a string"):
            dispatcher.validate({"type": 42})

    def test_rejects_empty_type(self, dispatcher: UnifiedInstructionDispatcher) -> None:
        """Empty string type raises ValueError."""
        with pytest.raises(ValueError, match="type' must not be empty"):
            dispatcher.validate({"type": ""})

    def test_rejects_non_string_reason(self, dispatcher: UnifiedInstructionDispatcher) -> None:
        """Non-string reason raises TypeError."""
        with pytest.raises(TypeError, match="reason' must be a string"):
            dispatcher.validate({"type": "Foo", "reason": 99})

    def test_rejects_non_dict_metadata(self, dispatcher: UnifiedInstructionDispatcher) -> None:
        """Non-dict metadata raises TypeError."""
        with pytest.raises(TypeError, match="metadata' must be a dict"):
            dispatcher.validate({"type": "Foo", "metadata": "bar"})


# ---------------------------------------------------------------------------
# UnifiedInstructionDispatcher.dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    """Core dispatch routing — instruction type → canonical action."""

    def test_panic_maps_to_panic(self, dispatcher: UnifiedInstructionDispatcher) -> None:
        action, event = dispatcher.dispatch({"type": "PanicInstruction"})
        assert action == "panic"
        assert event["event"] == "instruction_dispatched"
        assert event["instruction_type"] == "PanicInstruction"
        assert event["action"] == "panic"

    def test_poison_maps_to_fail(self, dispatcher: UnifiedInstructionDispatcher) -> None:
        action, event = dispatcher.dispatch({"type": "PoisonInstruction"})
        assert action == "fail"
        assert event["action"] == "fail"

    def test_recovery_maps_to_recover(self, dispatcher: UnifiedInstructionDispatcher) -> None:
        action, event = dispatcher.dispatch({"type": "RecoveryInstruction"})
        assert action == "recover"
        assert event["action"] == "recover"

    def test_degraded_maps_to_degrade(self, dispatcher: UnifiedInstructionDispatcher) -> None:
        action, event = dispatcher.dispatch({"type": "DegradedInstruction"})
        assert action == "degrade"
        assert event["action"] == "degrade"

    def test_retry_maps_to_retry(self, dispatcher: UnifiedInstructionDispatcher) -> None:
        action, event = dispatcher.dispatch({"type": "RetryInstruction"})
        assert action == "retry"
        assert event["action"] == "retry"

    def test_unknown_type_defaults_to_noop(
        self, dispatcher: UnifiedInstructionDispatcher
    ) -> None:
        """Unknown instruction types resolve to 'noop'."""
        action, event = dispatcher.dispatch({"type": "QuantumInstruction"})
        assert action == "noop"
        assert event["action"] == "noop"

    def test_reason_and_metadata_are_ignored(
        self, dispatcher: UnifiedInstructionDispatcher
    ) -> None:
        """Full instruction payload still routes correctly."""
        action, event = dispatcher.dispatch({
            "type": "PoisonInstruction",
            "reason": "Job exceeded max retries",
            "metadata": {"job_id": "j-7", "attempts": 5},
        })
        assert action == "fail"
        assert event["instruction_type"] == "PoisonInstruction"

    def test_action_map_override(
        self, dispatcher: UnifiedInstructionDispatcher
    ) -> None:
        """Temporary override of the registry."""
        action, event = dispatcher.dispatch(
            {"type": "CustomOp"},
            action_map_override={"CustomOp": "retry"},
        )
        assert action == "retry"

    def test_invalid_action_in_map_defaults_to_noop(
        self, dispatcher: UnifiedInstructionDispatcher
    ) -> None:
        """If the action_map value is not a valid action, default to 'noop'."""
        override = {"SomeType": "fly_to_the_moon"}
        action, event = dispatcher.dispatch(
            {"type": "SomeType"},
            action_map_override=override,
        )
        assert action == "noop"


# ---------------------------------------------------------------------------
# InstructionDispatchConfig
# ---------------------------------------------------------------------------


class TestConfig:
    """Config dataclass construction and defaults."""

    def test_default_action_map(self) -> None:
        cfg = InstructionDispatchConfig()
        assert cfg.action_map == DEFAULT_ACTION_MAP

    def test_custom_action_map(self) -> None:
        custom = {"Foobar": "degrade"}
        cfg = InstructionDispatchConfig(action_map=custom)
        assert cfg.action_map == custom

    def test_isolation(self) -> None:
        """Modifying one config doesn't affect another or the default."""
        cfg1 = InstructionDispatchConfig()
        cfg2 = InstructionDispatchConfig()
        cfg2.action_map["MyInstruction"] = "panic"
        assert "MyInstruction" not in cfg1.action_map


# ---------------------------------------------------------------------------
# Behavioural contract
# ---------------------------------------------------------------------------


class TestBehaviouralContract:
    """Verifies the dispatcher's behavioural guarantees."""

    def test_deterministic(self, dispatcher: UnifiedInstructionDispatcher) -> None:
        """Same input → same output every time."""
        instruction = {"type": "RetryInstruction", "reason": "timeout"}
        r1 = dispatcher.dispatch(instruction)
        r2 = dispatcher.dispatch(instruction)
        assert r1 == r2

    @pytest.mark.parametrize("known_type, expected_action", [
        ("PanicInstruction", "panic"),
        ("PoisonInstruction", "fail"),
        ("RecoveryInstruction", "recover"),
        ("DegradedInstruction", "degrade"),
        ("RetryInstruction", "retry"),
    ])
    def test_all_known_types(
        self,
        dispatcher: UnifiedInstructionDispatcher,
        known_type: str,
        expected_action: str,
    ) -> None:
        action, event = dispatcher.dispatch({"type": known_type})
        assert action == expected_action
        assert event["action"] == expected_action
        assert event["instruction_type"] == known_type

    @pytest.mark.parametrize("unknown_type", [
        "FutureInstruction",
        "Unknown",
        "",
        "CustomS9Instruction",
    ])
    def test_unknown_types_never_crash(
        self,
        dispatcher: UnifiedInstructionDispatcher,
        unknown_type: str,
    ) -> None:
        """Any unknown type must produce noop, not crash."""
        d = {"type": unknown_type} if unknown_type else {}
        try:
            action, event = dispatcher.dispatch(d)
            assert action == "noop"
            assert event["action"] == "noop"
        except (KeyError, TypeError, ValueError):
            if unknown_type == "":
                return  # empty type → validation error is expected
            raise

    def test_no_mutation(self, dispatcher: UnifiedInstructionDispatcher) -> None:
        """Dispatcher never mutates the input instruction."""
        original = {
            "type": "PanicInstruction",
            "reason": "test",
            "metadata": {"a": 1},
        }
        snapshot = dict(original)
        dispatcher.dispatch(original)
        assert original == snapshot

    def test_event_has_iso_timestamp(
        self, dispatcher: UnifiedInstructionDispatcher
    ) -> None:
        """Timestamp is ISO-8601 formatted."""
        _, event = dispatcher.dispatch({"type": "PanicInstruction"})
        ts = event["timestamp"]
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None

    def test_config_property(
        self, dispatcher: UnifiedInstructionDispatcher
    ) -> None:
        assert isinstance(dispatcher.config, InstructionDispatchConfig)


# ---------------------------------------------------------------------------
# default_dispatcher
# ---------------------------------------------------------------------------


class TestDefaultDispatcher:
    """Convenience factory."""

    def test_returns_configured_dispatcher(self) -> None:
        d = default_dispatcher()
        assert isinstance(d, UnifiedInstructionDispatcher)
        action, _ = d.dispatch({"type": "RetryInstruction"})
        assert action == "retry"

    def test_clock_injection(self, fixed_clock: list[datetime]) -> None:
        d = default_dispatcher(clock=lambda: fixed_clock[0])
        _, event = d.dispatch({"type": "PanicInstruction"})
        assert event["timestamp"] == fixed_clock[0].isoformat()
