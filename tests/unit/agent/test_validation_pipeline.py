"""Tests for R.11.7 — S5 ValidationPipeline."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from src.agent.validation.pipeline import ValidationPipeline
from src.strategy.memory.drift_memory import DriftMemory
from src.strategy.memory.drift_memory_types import DriftEvent
from src.strategy.signals.model import (
    GovernedSignal,
    SignalType,
    SignalSeverity,
    SignalSource,
)


# ---------------------------------------------------------------------------
# apply — no-op when expected_schema is None
# ---------------------------------------------------------------------------


def test_apply_noop_when_schema_is_none():
    """Pipeline skips drift evaluation when expected_schema is None
    (shape validation trivially passes, anomaly fires as info-only)."""
    pipeline = ValidationPipeline()
    diagnostics = pipeline.apply(
        skill_name="test_skill",
        actual_output={"result": 42},
        expected_schema=None,
        subgoal_id="sg1",
        segment_id="seg1",
        step_id="step1",
    )
    assert diagnostics.shape_ok is True
    assert diagnostics.shape_message == ""
    # detect_behavioural_anomaly flags output-without-schema
    assert diagnostics.anomaly == "Output produced with no declared schema"
    # drift evaluation requires expected_schema to detect a mismatch
    assert diagnostics.drift_signal is None


# ---------------------------------------------------------------------------
# apply — shape validation passes
# ---------------------------------------------------------------------------


def test_apply_shape_validation_passes():
    """Pipeline reports shape_ok when output matches schema."""
    pipeline = ValidationPipeline()
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": {"result": {"type": "integer"}},
    }
    diagnostics = pipeline.apply(
        skill_name="calc",
        actual_output={"result": 42},
        expected_schema=schema,
    )
    assert diagnostics.shape_ok is True
    assert diagnostics.shape_message == ""
    assert not diagnostics.anomaly


# ---------------------------------------------------------------------------
# apply — shape validation fails
# ---------------------------------------------------------------------------


def test_apply_shape_validation_fails():
    """Pipeline reports shape failure when output mismatches schema."""
    pipeline = ValidationPipeline()
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": {"result": {"type": "integer"}},
        "required": ["result"],
    }
    diagnostics = pipeline.apply(
        skill_name="calc",
        actual_output={"result": "not_an_int"},
        expected_schema=schema,
        subgoal_id="sg1",
        segment_id="seg1",
        step_id="step1",
    )
    assert diagnostics.shape_ok is False
    assert "expected integer" in diagnostics.shape_message.lower() or "expected int" in diagnostics.shape_message.lower()
    assert diagnostics.drift_signal is not None


# ---------------------------------------------------------------------------
# apply — anomaly detection fires
# ---------------------------------------------------------------------------


def test_apply_anomaly_output_without_schema():
    """Pipeline detects anomaly when output produced with no declared schema."""
    pipeline = ValidationPipeline()
    diagnostics = pipeline.apply(
        skill_name="mystery",
        actual_output={"something": 1},
        expected_schema=None,
    )
    # No schema + output -> anomaly, but shape is trivially ok
    assert diagnostics.shape_ok is True
    assert diagnostics.anomaly == "Output produced with no declared schema"


# ---------------------------------------------------------------------------
# apply — DriftMemory records drift events
# ---------------------------------------------------------------------------


def test_apply_records_drift_in_memory():
    """Pipeline records drift events into DriftMemory on shape mismatch."""
    memory = DriftMemory(capacity=5)
    pipeline = ValidationPipeline(drift_memory=memory)
    schema: Dict[str, Any] = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}

    diagnostics = pipeline.apply(
        skill_name="calc",
        actual_output={"x": "bad"},
        expected_schema=schema,
        subgoal_id="sg1",
        segment_id="seg1",
        step_id="step1",
    )

    assert diagnostics.drift_signal is not None
    assert len(memory) == 1
    event = memory.last()
    assert event is not None
    assert event.subgoal_id == "sg1"
    assert event.segment_id == "seg1"
    assert event.step_id == "step1"
    assert "expected integer" in event.details.get("validation_message", "").lower() or "expected int" in event.details.get("validation_message", "").lower()


# ---------------------------------------------------------------------------
# apply — multiple pipeline runs accumulate drift events
# ---------------------------------------------------------------------------


def test_apply_accumulates_drift_events():
    """Multiple shape mismatches accumulate drift events in memory."""
    memory = DriftMemory(capacity=20)
    pipeline = ValidationPipeline(drift_memory=memory)
    schema: Dict[str, Any] = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}

    for i in range(3):
        pipeline.apply(
            skill_name="calc",
            actual_output={"x": "bad"},
            expected_schema=schema,
            subgoal_id="sg1",
            segment_id="seg1",
            step_id=f"step{i}",
        )

    assert len(memory) == 3


# ---------------------------------------------------------------------------
# apply — valid output does not produce drift signal
# ---------------------------------------------------------------------------


def test_apply_valid_output_no_drift():
    """Valid output matching schema produces no drift signal."""
    pipeline = ValidationPipeline()
    schema: Dict[str, Any] = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}

    diagnostics = pipeline.apply(
        skill_name="calc",
        actual_output={"x": 42},
        expected_schema=schema,
        subgoal_id="sg1",
        segment_id="seg1",
        step_id="step1",
    )

    assert diagnostics.shape_ok is True
    assert diagnostics.drift_signal is None
    assert diagnostics.anomaly is None


# ---------------------------------------------------------------------------
# default DriftMemory created when none provided
# ---------------------------------------------------------------------------


def test_default_drift_memory():
    """Pipeline creates a default DriftMemory when none is provided."""
    pipeline = ValidationPipeline()
    assert pipeline.drift_memory is not None
    assert pipeline.drift_memory.capacity == 20
