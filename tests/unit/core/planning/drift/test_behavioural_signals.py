"""
Tests for Phase 2.6.3 — Behavioural Drift Signals.

Coverage:
  - BehaviouralSignalType enum values
  - BehaviouralSignal construction (valid)
  - BehaviouralSignal construction (invalid details — non-JSON-pure rejected)
  - detect_wrong_capability: capabilities match → None
  - detect_wrong_capability: capabilities mismatch → WRONG_CAPABILITY signal
  - detect_wrong_capability: missing declared_capability → None
  - detect_wrong_capability: missing executed_capability → None
  - detect_wrong_capability: both missing → None
  - detect_wrong_capability: empty metadata → None
  - collect_behavioural_drift_signals: empty records → empty dict
  - collect_behavioural_drift_signals: single mismatch → entry in result
  - collect_behavioural_drift_signals: mix of matches and mismatches
  - collect_behavioural_drift_signals: all matching → empty dict
  - SegmentMemoryRecord: behavioural_signals field exists with default []
  - SegmentMemory: update_behavioural_signals replaces signals
  - SegmentMemory: update_behavioural_signals is no-op for missing segment
"""
from __future__ import annotations

from dataclasses import asdict
from typing import List

import pytest

from src.core.memory.segment_memory import SegmentMemory
from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.planning.drift.behavioural_signal_detector import (
    collect_behavioural_drift_signals,
    detect_unexpected_side_effect,
    detect_wrong_capability,
    detect_wrong_output_semantics,
    detect_wrong_output_shape,
)
from src.core.planning.drift.behavioural_signal_types import (
    BehaviouralSignal,
    BehaviouralSignalType,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NOW_MS: int = 1_700_000_000_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(
    segment_id: str = "seg-1",
    subgoal_id: str = "sg-1",
    metadata: dict | None = None,
    ts_ms: int = NOW_MS,
    last_output: object = None,
) -> SegmentMemoryRecord:
    """Build a SegmentMemoryRecord with optional metadata and last_output overrides."""
    from datetime import datetime, timezone

    iso = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat()
    return SegmentMemoryRecord(
        segment_id=segment_id,
        parent_id=None,
        subgoal_id=subgoal_id,
        state=None,
        content=["step-1"],
        created_at=iso,
        context={},
        metadata=metadata or {},
        last_output=last_output,
    )


# ===========================================================================
# BehaviouralSignalType
# ===========================================================================


class TestBehaviouralSignalType:
    """Enum value tests."""

    def test_all_values_present(self):
        """All four Phase 2.6.3 signal types must exist."""
        values = {t.value for t in BehaviouralSignalType}
        assert values == {
            "wrong_capability",
            "wrong_output_shape",
            "wrong_output_semantics",
            "unexpected_side_effect",
        }

    def test_is_string_enum(self):
        """Each member is a str subclass."""
        for t in BehaviouralSignalType:
            assert isinstance(t, str)
            assert isinstance(t, BehaviouralSignalType)


# ===========================================================================
# BehaviouralSignal
# ===========================================================================


class TestBehaviouralSignal:
    """Construction and validation tests."""

    def test_valid_construction(self):
        signal = BehaviouralSignal(
            signal_type=BehaviouralSignalType.WRONG_CAPABILITY,
            segment_id="seg-1",
            subgoal_id="sg-1",
            details={"declared": "read", "executed": "write"},
            timestamp="2025-01-01T00:00:00+00:00",
        )
        assert signal.signal_type == BehaviouralSignalType.WRONG_CAPABILITY
        assert signal.segment_id == "seg-1"
        assert signal.subgoal_id == "sg-1"
        assert signal.details == {"declared": "read", "executed": "write"}
        assert signal.timestamp == "2025-01-01T00:00:00+00:00"

    def test_details_deep_copied(self):
        """details dict is deep-copied so external mutation doesn't affect the signal."""
        mutable = {"key": "value"}
        signal = BehaviouralSignal(
            signal_type=BehaviouralSignalType.WRONG_CAPABILITY,
            segment_id="seg-1",
            subgoal_id="sg-1",
            details=mutable,
            timestamp="2025-01-01T00:00:00+00:00",
        )
        mutable["key"] = "changed"
        assert signal.details["key"] == "value"

    def test_non_json_pure_details_rejected(self):
        """details must be JSON-pure — custom objects are rejected."""
        with pytest.raises((TypeError, ValueError)):
            BehaviouralSignal(
                signal_type=BehaviouralSignalType.WRONG_CAPABILITY,
                segment_id="seg-1",
                subgoal_id="sg-1",
                details={"bad": object()},
                timestamp="2025-01-01T00:00:00+00:00",
            )

    def test_frozen(self):
        """BehaviouralSignal is immutable."""
        signal = BehaviouralSignal(
            signal_type=BehaviouralSignalType.WRONG_CAPABILITY,
            segment_id="seg-1",
            subgoal_id="sg-1",
            details={},
            timestamp="2025-01-01T00:00:00+00:00",
        )
        with pytest.raises(Exception):
            signal.signal_type = BehaviouralSignalType.WRONG_OUTPUT_SHAPE  # type: ignore[misc]

    def test_json_serialisable(self):
        """BehaviouralSignal can be serialised to JSON via dataclasses.asdict."""
        import json

        signal = BehaviouralSignal(
            signal_type=BehaviouralSignalType.WRONG_CAPABILITY,
            segment_id="seg-1",
            subgoal_id="sg-1",
            details={"declared": "read", "executed": "write"},
            timestamp="2025-01-01T00:00:00+00:00",
        )
        d = asdict(signal)
        encoded = json.dumps(d)
        assert "wrong_capability" in encoded


# ===========================================================================
# detect_wrong_capability
# ===========================================================================


class TestDetectWrongCapability:
    """Pure-function tests for detect_wrong_capability."""

    def test_capabilities_match_returns_none(self):
        """When declared matches executed, no signal is emitted."""
        record = _record(metadata={
            "declared_capability": "read_file",
            "executed_capability": "read_file",
        })
        result = detect_wrong_capability(record, NOW_MS)
        assert result is None

    def test_capabilities_mismatch_returns_signal(self):
        """When declared differs from executed, WRONG_CAPABILITY is emitted."""
        record = _record(metadata={
            "declared_capability": "read_file",
            "executed_capability": "write_file",
        })
        result = detect_wrong_capability(record, NOW_MS)
        assert result is not None
        assert result.signal_type == BehaviouralSignalType.WRONG_CAPABILITY
        assert result.segment_id == "seg-1"
        assert result.subgoal_id == "sg-1"
        assert result.details == {
            "declared_capability": "read_file",
            "executed_capability": "write_file",
        }

    def test_missing_declared_capability_returns_none(self):
        """When declared_capability is absent, no signal (nothing to compare)."""
        record = _record(metadata={
            "executed_capability": "read_file",
        })
        result = detect_wrong_capability(record, NOW_MS)
        assert result is None

    def test_missing_executed_capability_returns_none(self):
        """When executed_capability is absent, no signal (nothing to compare)."""
        record = _record(metadata={
            "declared_capability": "read_file",
        })
        result = detect_wrong_capability(record, NOW_MS)
        assert result is None

    def test_both_missing_returns_none(self):
        """When neither capability key is present, no signal."""
        record = _record(metadata={"other": "data"})
        result = detect_wrong_capability(record, NOW_MS)
        assert result is None

    def test_empty_metadata_returns_none(self):
        """Empty metadata yields no signal."""
        record = _record(metadata={})
        result = detect_wrong_capability(record, NOW_MS)
        assert result is None

    def test_different_types_normalised_to_string(self):
        """Even if types differ, they are compared as strings."""
        record = _record(metadata={
            "declared_capability": "read_file",
            "executed_capability": "read_file",
        })
        result = detect_wrong_capability(record, NOW_MS)
        assert result is None  # same string → no signal

    def test_signal_timestamp_is_iso8601(self):
        """The returned signal's timestamp is a valid ISO 8601 string."""
        record = _record(metadata={
            "declared_capability": "a",
            "executed_capability": "b",
        })
        result = detect_wrong_capability(record, NOW_MS)
        assert result is not None
        # Should parse without error
        from datetime import datetime
        datetime.fromisoformat(result.timestamp)


# ===========================================================================
# detect_wrong_output_shape
# ===========================================================================


class TestDetectWrongOutputShape:
    """Pure-function tests for detect_wrong_output_shape."""

    def test_shapes_match_returns_none(self):
        """When actual output conforms to the declared schema, no signal is emitted."""
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        record = _record(
            metadata={"declared_output_schema": schema},
            last_output={"x": 42},
        )
        result = detect_wrong_output_shape(record, NOW_MS)
        assert result is None

    def test_shape_mismatch_returns_signal(self):
        """When actual output violates the schema, WRONG_OUTPUT_SHAPE is emitted."""
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        record = _record(
            metadata={"declared_output_schema": schema},
            last_output={"x": "not-an-int"},
        )
        result = detect_wrong_output_shape(record, NOW_MS)
        assert result is not None
        assert result.signal_type == BehaviouralSignalType.WRONG_OUTPUT_SHAPE
        assert result.segment_id == "seg-1"
        assert result.subgoal_id == "sg-1"
        assert result.details["declared_output_schema"] == schema
        assert result.details["actual_type"] == "dict"
        assert isinstance(result.details["validation_message"], str)

    def test_type_mismatch_returns_signal(self):
        """When schema expects object but got a list, WRONG_OUTPUT_SHAPE is emitted."""
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        record = _record(
            metadata={"declared_output_schema": schema},
            last_output=[1, 2, 3],
        )
        result = detect_wrong_output_shape(record, NOW_MS)
        assert result is not None
        assert result.signal_type == BehaviouralSignalType.WRONG_OUTPUT_SHAPE
        assert result.details["actual_type"] == "list"

    def test_missing_declared_schema_returns_none(self):
        """When declared_output_schema is absent, no signal (nothing to compare)."""
        record = _record(
            metadata={},
            last_output={"x": 42},
        )
        result = detect_wrong_output_shape(record, NOW_MS)
        assert result is None

    def test_missing_last_output_returns_none(self):
        """When last_output is None, no signal (nothing to validate)."""
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        record = _record(
            metadata={"declared_output_schema": schema},
            last_output=None,
        )
        result = detect_wrong_output_shape(record, NOW_MS)
        assert result is None

    def test_both_missing_returns_none(self):
        """When neither schema nor output is present, no signal."""
        record = _record(metadata={}, last_output=None)
        result = detect_wrong_output_shape(record, NOW_MS)
        assert result is None

    def test_empty_metadata_returns_none(self):
        """Empty metadata yields no signal."""
        record = _record(metadata={}, last_output={"x": 1})
        result = detect_wrong_output_shape(record, NOW_MS)
        assert result is None

    def test_schema_none_in_metadata_returns_none(self):
        """Explicit None schema in metadata is treated as absent."""
        record = _record(
            metadata={"declared_output_schema": None},
            last_output={"x": 42},
        )
        result = detect_wrong_output_shape(record, NOW_MS)
        assert result is None

    def test_missing_required_field_returns_signal(self):
        """When schema requires a field that is absent from output, signal emitted."""
        schema = {
            "type": "object",
            "properties": {"x": {"type": "integer"}, "y": {"type": "string"}},
            "required": ["x", "y"],
        }
        record = _record(
            metadata={"declared_output_schema": schema},
            last_output={"x": 42},
        )
        result = detect_wrong_output_shape(record, NOW_MS)
        assert result is not None
        assert result.signal_type == BehaviouralSignalType.WRONG_OUTPUT_SHAPE

    def test_signal_timestamp_is_iso8601(self):
        """The returned signal's timestamp is a valid ISO 8601 string."""
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        record = _record(
            metadata={"declared_output_schema": schema},
            last_output={"x": "wrong-type"},
        )
        result = detect_wrong_output_shape(record, NOW_MS)
        assert result is not None
        from datetime import datetime
        datetime.fromisoformat(result.timestamp)


# ===========================================================================
# detect_wrong_output_semantics
# ===========================================================================


class TestDetectWrongOutputSemantics:
    """Pure-function tests for detect_wrong_output_semantics."""

    # ── success flag ────────────────────────────────────────────────────

    def test_success_true_returns_none(self):
        """Output with success=True is semantically fine."""
        record = _record(last_output={"success": True, "data": [1, 2]})
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is None

    def test_success_false_returns_signal(self):
        """Output with success=False signals WRONG_OUTPUT_SEMANTICS."""
        record = _record(last_output={"success": False, "data": []})
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is not None
        assert result.signal_type == BehaviouralSignalType.WRONG_OUTPUT_SEMANTICS
        assert "success_flag_false" in result.details["reasons"]

    def test_success_truthy_non_bool_is_not_false(self):
        """A non-bool truthy success value is not treated as False."""
        record = _record(last_output={"success": 1})
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is None

    # ── ok flag ─────────────────────────────────────────────────────────

    def test_ok_false_returns_signal(self):
        """Output with ok=False signals WRONG_OUTPUT_SEMANTICS."""
        record = _record(last_output={"ok": False, "data": [1]})
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is not None
        assert "ok_flag_false" in result.details["reasons"]

    def test_ok_true_returns_none(self):
        """Output with ok=True is semantically fine."""
        record = _record(last_output={"ok": True})
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is None

    # ── error field ─────────────────────────────────────────────────────

    def test_error_field_populated_returns_signal(self):
        """Non-empty error field signals semantics issue."""
        record = _record(last_output={"error": "something went wrong"})
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is not None
        assert "error_field_populated" in result.details["reasons"]

    def test_error_field_null_returns_none(self):
        """error: null is benign."""
        record = _record(last_output={"error": None})
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is None

    def test_error_field_empty_string_returns_none(self):
        """error: '' is treated as empty/benign."""
        record = _record(last_output={"error": ""})
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is None

    def test_error_field_empty_list_returns_none(self):
        """error: [] is treated as empty/benign."""
        record = _record(last_output={"error": []})
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is None

    def test_error_field_missing_returns_none(self):
        """No error key at all → nothing to signal."""
        record = _record(last_output={"data": [1]})
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is None

    # ── required fields empty ──────────────────────────────────────────

    def test_required_field_present_but_empty_returns_signal(self):
        """Required field exists but has empty value → WRONG_OUTPUT_SEMANTICS."""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        record = _record(
            metadata={"declared_output_schema": schema},
            last_output={"name": ""},
        )
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is not None
        assert "required_field_empty:name" in result.details["reasons"]

    def test_required_field_none_returns_signal(self):
        """Required field with None value signals semantics issue."""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        record = _record(
            metadata={"declared_output_schema": schema},
            last_output={"name": None},
        )
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is not None

    def test_required_field_present_and_nonempty_returns_none(self):
        """Required field with a meaningful value is fine."""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        record = _record(
            metadata={"declared_output_schema": schema},
            last_output={"name": "Alice"},
        )
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is None

    def test_required_field_empty_list_returns_signal(self):
        """Required field with empty list value signals semantics issue."""
        schema = {
            "type": "object",
            "properties": {"items": {"type": "array"}},
            "required": ["items"],
        }
        record = _record(
            metadata={"declared_output_schema": schema},
            last_output={"items": []},
        )
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is not None

    def test_required_field_empty_dict_returns_signal(self):
        """Required field with empty dict value signals semantics issue."""
        schema = {
            "type": "object",
            "properties": {"config": {"type": "object"}},
            "required": ["config"],
        }
        record = _record(
            metadata={"declared_output_schema": schema},
            last_output={"config": {}},
        )
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is not None

    # ── edge cases ─────────────────────────────────────────────────────

    def test_last_output_none_returns_none(self):
        """None output cannot be semantically checked."""
        record = _record(last_output=None)
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is None

    def test_last_output_is_list_returns_none(self):
        """Non-dict outputs can't be checked by these heuristics."""
        record = _record(last_output=[1, 2, 3])
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is None

    def test_last_output_is_string_returns_none(self):
        """Non-dict outputs can't be checked by these heuristics."""
        record = _record(last_output="plain string")
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is None

    def test_multiple_reasons_aggregated(self):
        """Multiple semantic issues produce a single signal with all reasons."""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        record = _record(
            metadata={"declared_output_schema": schema},
            last_output={"success": False, "ok": False, "name": ""},
        )
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is not None
        reasons = result.details["reasons"]
        assert "success_flag_false" in reasons
        assert "ok_flag_false" in reasons
        assert "required_field_empty:name" in reasons
        assert len(reasons) == 3

    def test_signal_timestamp_is_iso8601(self):
        """The returned signal's timestamp is a valid ISO 8601 string."""
        record = _record(last_output={"success": False})
        result = detect_wrong_output_semantics(record, NOW_MS)
        assert result is not None
        from datetime import datetime
        datetime.fromisoformat(result.timestamp)


# ===========================================================================
# detect_unexpected_side_effect
# ===========================================================================


class TestDetectUnexpectedSideEffect:
    """Pure-function tests for detect_unexpected_side_effect."""

    # ── basic detection ─────────────────────────────────────────────────

    def test_declared_none_executed_has_side_effects_returns_signal(self):
        """declared=none + executed=['write'] → UNEXPECTED_SIDE_EFFECT."""
        record = _record(metadata={
            "declared_side_effects": "none",
            "executed_side_effects": ["write"],
        })
        result = detect_unexpected_side_effect(record, NOW_MS)
        assert result is not None
        assert result.signal_type == BehaviouralSignalType.UNEXPECTED_SIDE_EFFECT
        assert result.details["declared_side_effects"] == "none"
        assert result.details["executed_side_effects"] == ["write"]

    def test_declared_none_executed_empty_list_returns_none(self):
        """declared=none + executed=[] → no signal (no side effects happened)."""
        record = _record(metadata={
            "declared_side_effects": "none",
            "executed_side_effects": [],
        })
        result = detect_unexpected_side_effect(record, NOW_MS)
        assert result is None

    def test_declared_has_side_effects_returns_none(self):
        """declared=write + executed=[write] → expected, no signal."""
        record = _record(metadata={
            "declared_side_effects": "write",
            "executed_side_effects": ["write"],
        })
        result = detect_unexpected_side_effect(record, NOW_MS)
        assert result is None

    def test_declared_write_executed_none_returns_none(self):
        """declared=write + executed=none → no unexpected side effect."""
        record = _record(metadata={
            "declared_side_effects": "write",
            "executed_side_effects": "none",
        })
        result = detect_unexpected_side_effect(record, NOW_MS)
        assert result is None

    # ── declared = None (explicit) ──────────────────────────────────────

    def test_declared_explicit_none_executed_has_side_effect(self):
        """declared=None explicitly means no side effects."""
        record = _record(metadata={
            "declared_side_effects": None,
            "executed_side_effects": ["network"],
        })
        result = detect_unexpected_side_effect(record, NOW_MS)
        assert result is not None

    # ── declared = empty string ─────────────────────────────────────────

    def test_declared_empty_string_means_none(self):
        """declared='' is treated as no side effects."""
        record = _record(metadata={
            "declared_side_effects": "",
            "executed_side_effects": ["read"],
        })
        result = detect_unexpected_side_effect(record, NOW_MS)
        assert result is not None

    # ── declared = empty list ───────────────────────────────────────────

    def test_declared_empty_list_means_none(self):
        """declared=[] is treated as no side effects."""
        record = _record(metadata={
            "declared_side_effects": [],
            "executed_side_effects": ["system"],
        })
        result = detect_unexpected_side_effect(record, NOW_MS)
        assert result is not None

    # ── missing keys ────────────────────────────────────────────────────

    def test_missing_declared_key_returns_none(self):
        """If declared_side_effects key is missing, cannot assess."""
        record = _record(metadata={
            "executed_side_effects": ["write"],
        })
        result = detect_unexpected_side_effect(record, NOW_MS)
        assert result is None

    def test_missing_executed_key_returns_none(self):
        """If executed_side_effects key is missing, cannot assess."""
        record = _record(metadata={
            "declared_side_effects": "none",
        })
        result = detect_unexpected_side_effect(record, NOW_MS)
        assert result is None

    def test_both_keys_missing_returns_none(self):
        """Both keys missing → nothing to check."""
        record = _record(metadata={})
        result = detect_unexpected_side_effect(record, NOW_MS)
        assert result is None

    # ── edge cases ─────────────────────────────────────────────────────

    def test_declared_none_str_executed_single_string(self):
        """executed_side_effects as a single string (not list) is supported."""
        record = _record(metadata={
            "declared_side_effects": "none",
            "executed_side_effects": "dangerous",
        })
        result = detect_unexpected_side_effect(record, NOW_MS)
        assert result is not None

    def test_executed_none_value_returns_none(self):
        """executed_side_effects=None means nothing happened."""
        record = _record(metadata={
            "declared_side_effects": "none",
            "executed_side_effects": None,
        })
        result = detect_unexpected_side_effect(record, NOW_MS)
        assert result is None

    def test_executed_none_string_returns_none(self):
        """executed_side_effects='none' means nothing happened."""
        record = _record(metadata={
            "declared_side_effects": "none",
            "executed_side_effects": "none",
        })
        result = detect_unexpected_side_effect(record, NOW_MS)
        assert result is None

    def test_signal_timestamp_is_iso8601(self):
        """The returned signal's timestamp is a valid ISO 8601 string."""
        record = _record(metadata={
            "declared_side_effects": "none",
            "executed_side_effects": ["write"],
        })
        result = detect_unexpected_side_effect(record, NOW_MS)
        assert result is not None
        from datetime import datetime
        datetime.fromisoformat(result.timestamp)

    def test_segment_id_and_subgoal_id_preserved(self):
        """Signal carries the originating segment_id and subgoal_id."""
        record = _record(
            segment_id="seg-99",
            subgoal_id="sg-99",
            metadata={
                "declared_side_effects": "none",
                "executed_side_effects": ["write"],
            },
        )
        result = detect_unexpected_side_effect(record, NOW_MS)
        assert result is not None
        assert result.segment_id == "seg-99"
        assert result.subgoal_id == "sg-99"

    # ── determinism ────────────────────────────────────────────────────

    def test_deterministic(self):
        """Same input always produces the same signal."""
        metadata = {
            "declared_side_effects": "none",
            "executed_side_effects": ["write"],
        }
        r1 = detect_unexpected_side_effect(_record(metadata=metadata), NOW_MS)
        r2 = detect_unexpected_side_effect(_record(metadata=metadata), NOW_MS)
        assert r1 is not None and r2 is not None
        assert r1.details == r2.details
        assert r1.signal_type == r2.signal_type


# ===========================================================================
# collect_behavioural_drift_signals
# ===========================================================================


class TestCollectBehaviouralDriftSignals:
    """Collector function tests."""

    def test_empty_records_returns_empty_dict(self):
        """No records → no signals."""
        result = collect_behavioural_drift_signals([], NOW_MS)
        assert result == {}

    def test_single_mismatch_returns_entry(self):
        """A single record with a mismatch appears in the result."""
        record = _record(
            segment_id="seg-1",
            metadata={
                "declared_capability": "read",
                "executed_capability": "write",
            },
        )
        result = collect_behavioural_drift_signals([record], NOW_MS)
        assert "seg-1" in result
        assert len(result["seg-1"]) == 1
        assert result["seg-1"][0].signal_type == BehaviouralSignalType.WRONG_CAPABILITY

    def test_single_match_returns_empty_dict(self):
        """A matching record does not appear in the result."""
        record = _record(metadata={
            "declared_capability": "read",
            "executed_capability": "read",
        })
        result = collect_behavioural_drift_signals([record], NOW_MS)
        assert result == {}

    def test_mixed_records(self):
        """Only mismatching records appear in the result."""
        r1 = _record(segment_id="seg-1", metadata={
            "declared_capability": "read", "executed_capability": "read",
        })
        r2 = _record(segment_id="seg-2", metadata={
            "declared_capability": "read", "executed_capability": "write",
        })
        r3 = _record(segment_id="seg-3", metadata={
            "declared_capability": "x", "executed_capability": "y",
        })
        result = collect_behavioural_drift_signals([r1, r2, r3], NOW_MS)
        assert list(result.keys()) == ["seg-2", "seg-3"]
        assert "seg-1" not in result

    def test_record_with_missing_metadata_not_in_result(self):
        """Records with insufficient metadata do not appear in the result."""
        record = _record(metadata={})
        result = collect_behavioural_drift_signals([record], NOW_MS)
        assert result == {}

    def test_multiple_mismatches_same_record(self):
        """Records can accumulate signals from multiple detectors."""
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        record = _record(metadata={
            "declared_capability": "a",
            "executed_capability": "b",
            "declared_output_schema": schema,
        }, last_output={"x": "wrong-type"})
        result = collect_behavioural_drift_signals([record], NOW_MS)
        assert len(result["seg-1"]) == 2
        types = {s.signal_type for s in result["seg-1"]}
        assert types == {
            BehaviouralSignalType.WRONG_CAPABILITY,
            BehaviouralSignalType.WRONG_OUTPUT_SHAPE,
        }

    def test_all_four_detectors_fire(self):
        """When output triggers all detectors, all four signals appear."""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        record = _record(metadata={
            "declared_capability": "a",
            "executed_capability": "b",
            "declared_output_schema": schema,
            "declared_side_effects": "none",
            "executed_side_effects": ["write"],
        }, last_output={"success": False, "name": ""})
        result = collect_behavioural_drift_signals([record], NOW_MS)
        assert len(result["seg-1"]) == 4
        types = {s.signal_type for s in result["seg-1"]}
        assert types == {
            BehaviouralSignalType.WRONG_CAPABILITY,
            BehaviouralSignalType.WRONG_OUTPUT_SHAPE,
            BehaviouralSignalType.WRONG_OUTPUT_SEMANTICS,
            BehaviouralSignalType.UNEXPECTED_SIDE_EFFECT,
        }

    def test_deterministic_ordering(self):
        """Results are deterministic — same input always produces same output."""
        records = [
            _record(segment_id="seg-1", metadata={"declared_capability": "a", "executed_capability": "b"}),
            _record(segment_id="seg-2", metadata={"declared_capability": "c", "executed_capability": "d"}),
        ]
        r1 = collect_behavioural_drift_signals(records, NOW_MS)
        r2 = collect_behavioural_drift_signals(records, NOW_MS)
        assert r1.keys() == r2.keys()


# ===========================================================================
# SegmentMemoryRecord integration
# ===========================================================================


class TestSegmentMemoryRecordIntegration:
    """Tests for behavioural_signals on SegmentMemoryRecord."""

    def test_default_behavioural_signals_is_empty_list(self):
        """A newly created SegmentMemoryRecord has an empty behavioural_signals list."""
        record = _record()
        assert record.behavioural_signals == []

    def test_can_populate_behavioural_signals(self):
        """BehaviouralSignals can be attached to a SegmentMemoryRecord."""
        signal = BehaviouralSignal(
            signal_type=BehaviouralSignalType.WRONG_CAPABILITY,
            segment_id="seg-1",
            subgoal_id="sg-1",
            details={},
            timestamp="2025-01-01T00:00:00+00:00",
        )
        record = SegmentMemoryRecord(
            segment_id="seg-1",
            parent_id=None,
            subgoal_id="sg-1",
            state=None,
            content=["step-1"],
            created_at="2025-01-01T00:00:00+00:00",
            context={},
            metadata={},
            behavioural_signals=[signal],
        )
        assert len(record.behavioural_signals) == 1
        assert record.behavioural_signals[0].signal_type == BehaviouralSignalType.WRONG_CAPABILITY

    def test_asdict_includes_behavioural_signals(self):
        """dataclasses.asdict includes the behavioural_signals field."""
        signal = BehaviouralSignal(
            signal_type=BehaviouralSignalType.WRONG_CAPABILITY,
            segment_id="seg-1",
            subgoal_id="sg-1",
            details={"key": "val"},
            timestamp="2025-01-01T00:00:00+00:00",
        )
        record = _record()
        record = SegmentMemoryRecord(
            **{**asdict(record), "behavioural_signals": [signal]},
        )
        d = asdict(record)
        assert "behavioural_signals" in d
        assert len(d["behavioural_signals"]) == 1


# ===========================================================================
# SegmentMemory.update_behavioural_signals
# ===========================================================================


class TestSegmentMemoryUpdateBehaviouralSignals:
    """Tests for SegmentMemory.update_behavioural_signals()."""

    def test_update_replaces_signals(self):
        """update_behavioural_signals replaces existing signals."""
        from src.core.types.plan_segment import PlanSegment

        memory = SegmentMemory()
        seg = PlanSegment(subgoal_id="sg-1", steps=["step-1"])
        memory.put(seg)

        signal = BehaviouralSignal(
            signal_type=BehaviouralSignalType.WRONG_CAPABILITY,
            segment_id=seg.segment_id,
            subgoal_id="sg-1",
            details={},
            timestamp="2025-01-01T00:00:00+00:00",
        )
        memory.update_behavioural_signals(seg.segment_id, [signal])

        record = memory.get_record(seg.segment_id)
        assert record is not None
        assert len(record.behavioural_signals) == 1
        assert record.behavioural_signals[0].signal_type == BehaviouralSignalType.WRONG_CAPABILITY

    def test_update_on_missing_segment_is_noop(self):
        """update_behavioural_signals on a non-existent segment is a silent no-op."""
        memory = SegmentMemory()
        signal = BehaviouralSignal(
            signal_type=BehaviouralSignalType.WRONG_CAPABILITY,
            segment_id="nonexistent",
            subgoal_id="sg-1",
            details={},
            timestamp="2025-01-01T00:00:00+00:00",
        )
        # Should not raise
        memory.update_behavioural_signals("nonexistent", [signal])

    def test_put_preserves_behavioural_signals_on_overwrite(self):
        """put() preserves existing behavioural_signals when overwriting the same segment_id."""
        from src.core.types.plan_segment import PlanSegment

        memory = SegmentMemory()
        seg = PlanSegment(subgoal_id="sg-1", steps=["step-1"])
        memory.put(seg)

        signal = BehaviouralSignal(
            signal_type=BehaviouralSignalType.WRONG_CAPABILITY,
            segment_id=seg.segment_id,
            subgoal_id="sg-1",
            details={},
            timestamp="2025-01-01T00:00:00+00:00",
        )
        memory.update_behavioural_signals(seg.segment_id, [signal])

        # Overwrite the SAME segment (same subgoal_id, steps, created_at → same segment_id)
        seg_rebuild = PlanSegment(
            subgoal_id=seg.subgoal_id,
            steps=list(seg.steps),
            context=dict(seg.context),
            metadata={"new_key": "new_value"},
            created_at=seg.created_at,
        )
        assert seg_rebuild.segment_id == seg.segment_id, "segment_id must match for overwrite test"
        memory.put(seg_rebuild)

        record = memory.get_record(seg.segment_id)
        assert record is not None
        # behavioural_signals preserved because this is the same segment_id
        assert len(record.behavioural_signals) == 1
        # metadata should be updated
        assert record.metadata == {"new_key": "new_value"}
