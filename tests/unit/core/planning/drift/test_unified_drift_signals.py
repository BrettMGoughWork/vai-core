"""
Tests for Phase 2.9.1 — Unified Drift Signal Builder
====================================================

Covers ``unify_drift_signals()`` with the following test cases:

- Merging correctness across all four signal families
- Weighting correctness (source‑specific multipliers)
- Decay correctness (decrement and floor behaviour)
- Deterministic ordering (source, then type alphabetically)
- JSON‑safe output
- No mutation of inputs
"""
from __future__ import annotations

import json

import pytest

from src.core.planning.drift.behavioural_signal_types import BehaviouralSignal, BehaviouralSignalType
from src.core.planning.drift.drift_types import DriftSignal
from src.core.planning.drift.semantic_signal_types import SemanticDriftSignal
from src.core.planning.drift.temporal_signal_types import TemporalDriftSignal
from src.core.planning.drift.unified_drift_signals import unify_drift_signals
from src.core.planning.drift.unified_drift_types import UnifiedDriftSignal


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_structural(type_: str = "shape_mismatch", confidence: float = 0.9) -> DriftSignal:
    return DriftSignal(
        type=type_,
        severity="high",
        timestamp="2025-01-01T00:00:00",
        signal_class="structural",
        metadata={"confidence": confidence, "field": "output"},
    )


def _make_behavioural(type_: BehaviouralSignalType = BehaviouralSignalType.WRONG_CAPABILITY) -> BehaviouralSignal:
    return BehaviouralSignal(
        signal_type=type_,
        segment_id="seg-1",
        subgoal_id="sg-1",
        details={"declared": "read", "executed": "write"},
        timestamp="2025-01-01T00:00:00",
    )


def _make_temporal(type_: str = "oscillation", confidence: float = 0.8) -> TemporalDriftSignal:
    return TemporalDriftSignal(
        type=type_,
        confidence=confidence,
        details={"cycles": 3},
    )


def _make_semantic(type_: str = "contradictplan", confidence: float = 0.7) -> SemanticDriftSignal:
    return SemanticDriftSignal(
        type=type_,
        confidence=confidence,
        details={"reason": "output contradicts plan intent"},
    )


# ── Merging ───────────────────────────────────────────────────────────────────


class TestMergeAllFamilies:
    """Signals from all four families should be merged into one unified list."""

    def test_empty_all(self) -> None:
        result = unify_drift_signals([], [], [], [])
        assert result == []

    def test_one_per_family(self) -> None:
        structural = [_make_structural("shape_mismatch", 0.9)]
        behavioural = [_make_behavioural(BehaviouralSignalType.WRONG_OUTPUT_SHAPE)]
        temporal = [_make_temporal("oscillation", 0.8)]
        semantic = [_make_semantic("contradictplan", 0.7)]
        result = unify_drift_signals(structural, behavioural, temporal, semantic)
        assert len(result) == 4

    def test_multiple_same_source(self) -> None:
        temporal = [
            _make_temporal("oscillation", 0.8),
            _make_temporal("no_progress", 0.6),
        ]
        result = unify_drift_signals([], [], temporal, [])
        assert len(result) == 2
        types = {s.type for s in result}
        assert types == {"oscillation", "no_progress"}


# ── Weighting ─────────────────────────────────────────────────────────────────


class TestWeighting:
    """Source‑specific multipliers must be applied correctly."""

    def test_structural_weight(self) -> None:
        structural = [_make_structural("shape_mismatch", 0.9)]
        result = unify_drift_signals(structural, [], [], [])
        assert result[0].weight == pytest.approx(0.9 * 1.0)  # structural × 1.0

    def test_behavioural_weight(self) -> None:
        behavioural = [_make_behavioural()]
        result = unify_drift_signals([], behavioural, [], [])
        # Behavioural has no native confidence → defaults to 1.0 × 0.9
        assert result[0].weight == pytest.approx(0.9)

    def test_temporal_weight(self) -> None:
        temporal = [_make_temporal("oscillation", 0.8)]
        result = unify_drift_signals([], [], temporal, [])
        assert result[0].weight == pytest.approx(0.8 * 0.8)  # 0.8 × 0.8

    def test_semantic_weight(self) -> None:
        semantic = [_make_semantic("contradictplan", 0.7)]
        result = unify_drift_signals([], [], [], semantic)
        assert result[0].weight == pytest.approx(0.7 * 0.7)  # 0.7 × 0.7

    def test_weight_clamped_to_1(self) -> None:
        structural = [_make_structural("shape_mismatch", 1.0)]
        result = unify_drift_signals(structural, [], [], [])
        assert result[0].weight <= 1.0


# ── Decay ─────────────────────────────────────────────────────────────────────


class TestDecay:
    """Decay must decrement by 0.1 per cycle and floor at 0.0."""

    def test_first_cycle_decay_is_one(self) -> None:
        temporal = [_make_temporal("oscillation", 0.8)]
        result = unify_drift_signals([], [], temporal, [])
        assert result[0].decay == 1.0

    def test_decay_decrements_on_match(self) -> None:
        temporal = [_make_temporal("oscillation", 0.8)]
        previous = [
            UnifiedDriftSignal(
                source="temporal",
                type="oscillation",
                weight=0.64,
                decay=0.9,
                confidence=0.8,
                details={"cycles": 3},
            )
        ]
        result = unify_drift_signals([], [], temporal, [], previous)
        assert result[0].decay == pytest.approx(0.8)

    def test_decay_floors_at_zero(self) -> None:
        temporal = [_make_temporal("oscillation", 0.8)]
        # Decay already at 0.0
        previous = [
            UnifiedDriftSignal(
                source="temporal",
                type="oscillation",
                weight=0.64,
                decay=0.0,
                confidence=0.8,
                details={"cycles": 3},
            )
        ]
        result = unify_drift_signals([], [], temporal, [], previous)
        assert result[0].decay == 0.0

    def test_no_decay_on_mismatch(self) -> None:
        temporal = [_make_temporal("oscillation", 0.8)]
        # Previous has different type — no match
        previous = [
            UnifiedDriftSignal(
                source="temporal",
                type="stall",
                weight=0.48,
                decay=0.7,
                confidence=0.6,
                details={"cycles": 2},
            )
        ]
        result = unify_drift_signals([], [], temporal, [], previous)
        assert result[0].decay == 1.0

    def test_decay_only_matches_same_source_and_type(self) -> None:
        """Decay should only apply when both source AND type match."""
        temporal = [_make_temporal("oscillation", 0.8)]
        # Same type, different source → no match
        previous = [
            UnifiedDriftSignal(
                source="semantic",
                type="oscillation",
                weight=0.5,
                decay=0.5,
                confidence=0.7,
                details={},
            )
        ]
        result = unify_drift_signals([], [], temporal, [], previous)
        assert result[0].decay == 1.0


# ── Ordering ──────────────────────────────────────────────────────────────────


class TestOrdering:
    """Unified signals must be sorted deterministically by source, then type."""

    def test_sorted_by_source_then_type(self) -> None:
        behavioural = [_make_behavioural(BehaviouralSignalType.WRONG_CAPABILITY)]
        temporal = [_make_temporal("oscillation", 0.8)]
        semantic = [_make_semantic("contradictplan", 0.7)]
        structural = [_make_structural("shape_mismatch", 0.9)]
        result = unify_drift_signals(structural, behavioural, temporal, semantic)
        order = [(s.source, s.type) for s in result]
        # Alphabetical by source: behavioural, semantic, structural, temporal
        expected = [
            ("behavioural", "wrong_capability"),
            ("semantic", "contradictplan"),
            ("structural", "shape_mismatch"),
            ("temporal", "oscillation"),
        ]
        assert order == expected

    def test_deterministic_output(self) -> None:
        """Identical inputs must produce identical outputs."""
        structural = [_make_structural(), _make_structural("type_mismatch")]
        a = unify_drift_signals(structural, [], [], [])
        b = unify_drift_signals(structural, [], [], [])
        assert a == b


# ── JSON safety ───────────────────────────────────────────────────────────────


class TestJSONSafety:
    """UnifiedDriftSignal must be JSON‑serialisable."""

    def test_serialisable(self) -> None:
        temporal = [_make_temporal("oscillation", 0.8)]
        result = unify_drift_signals([], [], temporal, [])
        as_dict = {
            "source": result[0].source,
            "type": result[0].type,
            "weight": result[0].weight,
            "decay": result[0].decay,
            "confidence": result[0].confidence,
            "details": result[0].details,
        }
        serialised = json.dumps(as_dict)
        deserialised = json.loads(serialised)
        assert deserialised["source"] == "temporal"
        assert deserialised["type"] == "oscillation"


# ── No mutation ───────────────────────────────────────────────────────────────


class TestNoMutation:
    """unify_drift_signals must not mutate its inputs."""

    def test_structural_not_mutated(self) -> None:
        structural = [_make_structural()]
        original_type = structural[0].type
        original_metadata = dict(structural[0].metadata)
        unify_drift_signals(structural, [], [], [])
        assert structural[0].type == original_type
        assert structural[0].metadata == original_metadata

    def test_behavioural_not_mutated(self) -> None:
        behavioural = [_make_behavioural()]
        original_details = dict(behavioural[0].details)
        unify_drift_signals([], behavioural, [], [])
        assert behavioural[0].details == original_details

    def test_temporal_not_mutated(self) -> None:
        temporal = [_make_temporal()]
        original_details = dict(temporal[0].details)
        unify_drift_signals([], [], temporal, [])
        assert temporal[0].details == original_details

    def test_semantic_not_mutated(self) -> None:
        semantic = [_make_semantic()]
        original_details = dict(semantic[0].details)
        unify_drift_signals([], [], [], semantic)
        assert semantic[0].details == original_details

    def test_previous_not_mutated(self) -> None:
        previous = [
            UnifiedDriftSignal(
                source="temporal",
                type="oscillation",
                weight=0.64,
                decay=0.5,
                confidence=0.8,
                details={"cycles": 3},
            )
        ]
        original_decay = previous[0].decay
        temporal = [_make_temporal("oscillation", 0.8)]
        unify_drift_signals([], [], temporal, [], previous)
        assert previous[0].decay == original_decay


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Boundary and edge case behaviour."""

    def test_previous_is_none(self) -> None:
        """None previous_unified should behave like empty list."""
        temporal = [_make_temporal()]
        result = unify_drift_signals([], [], temporal, [], None)
        assert result[0].decay == 1.0

    def test_confidence_copied_correctly(self) -> None:
        temporal = [_make_temporal("regression", 0.75)]
        result = unify_drift_signals([], [], temporal, [])
        assert result[0].confidence == 0.75
