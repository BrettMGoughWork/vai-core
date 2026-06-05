"""
Tests for Phase 2.8.2 — Semantic Drift Signals.

Covers:
  - SemanticDriftSignal frozen dataclass validation
  - emit_semantic_drift_signals() pure function
  - plan contradiction → correct signal
  - subgoal contradiction → correct signal
  - memory contradiction → correct signal
  - prior behaviour contradiction → correct signal
  - Multiple mismatches → sorted signals
  - Confidence copied correctly
  - Details copied correctly
  - Deterministic output
  - JSON‑safe
  - Empty input → empty list
  - No mutation of inputs
"""
from __future__ import annotations

import copy
import json
from typing import Any, Dict, List

import pytest

from src.core.planning.drift.semantic_signal_types import (
    SemanticDriftSignal,
    SemanticMismatch,
)
from src.core.planning.drift.semantic_drift_signals import (
    emit_semantic_drift_signals,
)


# ── helpers ─────────────────────────────────────────────────────────────────


def _mismatch(
    type: str = "plan_mismatch",
    confidence: float = 0.8,
    details: Dict[str, Any] | None = None,
) -> SemanticMismatch:
    return SemanticMismatch(
        type=type,  # type: ignore[arg-type]
        confidence=confidence,
        details=details or {"reason": f"test {type}"},
    )


def _assert_json_safe(signal: SemanticDriftSignal) -> None:
    """Verify a signal can round-trip through JSON."""
    # dataclasses.asdict isn’t available here, so use the __dict__ pattern
    raw = {
        "type": signal.type,
        "confidence": signal.confidence,
        "details": signal.details,
    }
    encoded = json.dumps(raw)
    decoded = json.loads(encoded)
    assert decoded["type"] == signal.type
    assert decoded["confidence"] == signal.confidence
    assert decoded["details"] == signal.details


# ── dataclass validation ───────────────────────────────────────────────────


class TestSemanticDriftSignalValidation:
    """SemanticDriftSignal frozen dataclass validation."""

    def test_confidence_too_low_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            SemanticDriftSignal(
                type="contradictplan",
                confidence=-0.1,
                details={},
            )

    def test_confidence_too_high_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            SemanticDriftSignal(
                type="contradictplan",
                confidence=1.1,
                details={},
            )

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="type"):
            SemanticDriftSignal(
                type="invalid_type",  # type: ignore[arg-type]
                confidence=0.5,
                details={},
            )

    def test_frozen(self) -> None:
        signal = SemanticDriftSignal(
            type="contradictplan",
            confidence=0.8,
            details={"a": 1},
        )
        with pytest.raises(Exception):
            signal.confidence = 0.9  # type: ignore[misc]

    def test_details_deep_copied(self) -> None:
        d = {"key": ["mutable"]}
        signal = SemanticDriftSignal(
            type="contradictplan",
            confidence=0.8,
            details=d,
        )
        d["key"].append("extra")
        assert signal.details["key"] == ["mutable"]


# ── signal emission ────────────────────────────────────────────────────────


class TestEmitSemanticDriftSignals:
    """emit_semantic_drift_signals() pure function."""

    def test_empty_mismatches_returns_empty(self) -> None:
        assert emit_semantic_drift_signals([]) == []

    def test_plan_mismatch_emits_contradictplan(self) -> None:
        mismatch = _mismatch(type="plan_mismatch", confidence=0.8)
        signals = emit_semantic_drift_signals([mismatch])
        assert len(signals) == 1
        assert signals[0].type == "contradictplan"
        assert signals[0].confidence == 0.8
        assert signals[0].details == mismatch.details

    def test_subgoal_mismatch_emits_contradictsubgoal(self) -> None:
        mismatch = _mismatch(type="subgoal_mismatch", confidence=0.9)
        signals = emit_semantic_drift_signals([mismatch])
        assert len(signals) == 1
        assert signals[0].type == "contradictsubgoal"
        assert signals[0].confidence == 0.9

    def test_memory_mismatch_emits_contradictmemory(self) -> None:
        mismatch = _mismatch(type="memory_mismatch", confidence=0.6)
        signals = emit_semantic_drift_signals([mismatch])
        assert len(signals) == 1
        assert signals[0].type == "contradictmemory"
        assert signals[0].confidence == 0.6

    def test_step_mismatch_emits_contradictprior_behaviour(self) -> None:
        mismatch = _mismatch(type="step_mismatch", confidence=0.7)
        signals = emit_semantic_drift_signals([mismatch])
        assert len(signals) == 1
        assert signals[0].type == "contradictprior_behaviour"
        assert signals[0].confidence == 0.7


# ── multiple mismatches ────────────────────────────────────────────────────


class TestMultipleMismatches:
    """Multiple mismatches → sorted deterministic signals."""

    def test_all_four_types_emitted(self) -> None:
        mismatches = [
            _mismatch(type="step_mismatch", confidence=0.7),
            _mismatch(type="plan_mismatch", confidence=0.8),
            _mismatch(type="subgoal_mismatch", confidence=0.9),
            _mismatch(type="memory_mismatch", confidence=0.6),
        ]
        signals = emit_semantic_drift_signals(mismatches)
        assert len(signals) == 4

        # Deterministic order: contradictplan, contradictsubgoal,
        #   contradictmemory, contradictprior_behaviour
        expected_order = [
            "contradictplan",
            "contradictsubgoal",
            "contradictmemory",
            "contradictprior_behaviour",
        ]
        assert [s.type for s in signals] == expected_order

    def test_order_always_deterministic(self) -> None:
        """Order depends only on signal type, not input order."""
        mismatches_reversed = [
            _mismatch(type="memory_mismatch", confidence=0.6),
            _mismatch(type="subgoal_mismatch", confidence=0.9),
            _mismatch(type="plan_mismatch", confidence=0.8),
            _mismatch(type="step_mismatch", confidence=0.7),
        ]
        signals = emit_semantic_drift_signals(mismatches_reversed)
        expected_order = [
            "contradictplan",
            "contradictsubgoal",
            "contradictmemory",
            "contradictprior_behaviour",
        ]
        assert [s.type for s in signals] == expected_order

    def test_duplicate_types_kept(self) -> None:
        """Duplicate mismatch types produce duplicate signals, sorted."""
        mismatches = [
            _mismatch(type="plan_mismatch", confidence=0.5),
            _mismatch(type="plan_mismatch", confidence=0.9),
        ]
        signals = emit_semantic_drift_signals(mismatches)
        assert len(signals) == 2
        assert all(s.type == "contradictplan" for s in signals)

    def test_partial_mismatches_ordered(self) -> None:
        """Only emitted types appear, still sorted."""
        mismatches = [
            _mismatch(type="memory_mismatch", confidence=0.6),
            _mismatch(type="subgoal_mismatch", confidence=0.9),
        ]
        signals = emit_semantic_drift_signals(mismatches)
        assert [s.type for s in signals] == [
            "contradictsubgoal",
            "contradictmemory",
        ]


# ── defensive copy ─────────────────────────────────────────────────────────


class TestDefensiveCopy:
    """Confidence and details are copied, not referenced."""

    def test_details_are_independent(self) -> None:
        details = {"reason": "original"}
        mismatch = SemanticMismatch(
            type="plan_mismatch",
            confidence=0.8,
            details=details,
        )
        signals = emit_semantic_drift_signals([mismatch])
        details["extra"] = "mutated"
        assert "extra" not in signals[0].details

    def test_mismatches_not_mutated(self) -> None:
        mismatch = _mismatch(type="plan_mismatch", confidence=0.8)
        original = copy.deepcopy(mismatch)
        emit_semantic_drift_signals([mismatch])
        # Mismatch should be unchanged
        assert mismatch.type == original.type
        assert mismatch.confidence == original.confidence
        assert mismatch.details == original.details


# ── JSON safety ────────────────────────────────────────────────────────────


class TestJsonSafe:
    """All signal outputs are JSON‑safe."""

    def test_contradictplan_json_safe(self) -> None:
        signals = emit_semantic_drift_signals(
            [_mismatch(type="plan_mismatch")]
        )
        _assert_json_safe(signals[0])

    def test_contradictsubgoal_json_safe(self) -> None:
        signals = emit_semantic_drift_signals(
            [_mismatch(type="subgoal_mismatch")]
        )
        _assert_json_safe(signals[0])

    def test_contradictmemory_json_safe(self) -> None:
        signals = emit_semantic_drift_signals(
            [_mismatch(type="memory_mismatch")]
        )
        _assert_json_safe(signals[0])

    def test_contradictprior_behaviour_json_safe(self) -> None:
        signals = emit_semantic_drift_signals(
            [_mismatch(type="step_mismatch")]
        )
        _assert_json_safe(signals[0])

    def test_complex_details_json_safe(self) -> None:
        mismatch = _mismatch(
            type="plan_mismatch",
            details={
                "nested": {"list": [1, "two", None, True]},
                "float": 3.14,
            },
        )
        signals = emit_semantic_drift_signals([mismatch])
        _assert_json_safe(signals[0])


# ── deterministic output ───────────────────────────────────────────────────


class TestDeterministicOutput:
    """Identical inputs produce identical outputs."""

    def test_same_input_same_output(self) -> None:
        mismatches = [
            _mismatch(type="plan_mismatch", confidence=0.8, details={"x": 1}),
            _mismatch(type="memory_mismatch", confidence=0.6, details={"y": 2}),
        ]
        result1 = emit_semantic_drift_signals(mismatches)
        result2 = emit_semantic_drift_signals(mismatches)
        # Same types
        assert [s.type for s in result1] == [s.type for s in result2]
        # Same confidences
        assert [s.confidence for s in result1] == [s.confidence for s in result2]
        # Same details
        assert [s.details for s in result1] == [s.details for s in result2]

    def test_pure_no_mutation(self) -> None:
        """Repeated calls produce identical results."""
        mismatches = [_mismatch(type="plan_mismatch")]
        r1 = emit_semantic_drift_signals(mismatches)
        r2 = emit_semantic_drift_signals(mismatches)
        assert r1[0].type == r2[0].type
        assert r1[0].confidence == r2[0].confidence
        assert r1[0].details == r2[0].details
