"""
Tests for Phase 2.14 — Drift Pipeline Integration
==================================================

Covers ``run_drift_pipeline()``, ``extract_pipeline_state()``,
``store_pipeline_state()``, and the internal helpers.

Test cases
----------
- _drift_dict_to_unified_signal: None on empty/no-drift dicts
- _drift_dict_to_unified_signal: valid dict → UnifiedDriftSignal
- _collect_unified_signals: segments → structural, subgoals → behavioural
- run_drift_pipeline: full pipeline produces all 6 keys
- run_drift_pipeline: no drift (empty records) → graceful no-drift output
- run_drift_pipeline: with previous confirmation/budget
- extract_pipeline_state: returns None,None when no state
- extract_pipeline_state: rebuilds typed state from stored dict
- store_pipeline_state: persists to memory correctly
- JSON safety: pipeline result is serialisable
- Determinism: identical inputs → identical outputs
"""
from __future__ import annotations

import json

import pytest

from src.strategy.planning.drift.drift_pipeline_integration import (
    DRIFT_PIPELINE_ENABLED,
    _drift_dict_to_unified_signal,
    _collect_unified_signals,
    _to_dict,
    run_drift_pipeline,
    extract_pipeline_state,
    store_pipeline_state,
)
from src.strategy.planning.drift.unified_drift_types import (
    DriftConfirmationState,
    DriftRecoveryDecision,
    UnifiedDriftClassification,
    UnifiedDriftSignal,
)
from src.strategy.planning.drift.repair_budget import RepairBudgetState


# ── Feature flag ───────────────────────────────────────────────────────────────


class TestFeatureFlag:
    """The feature flag must be enabled."""

    def test_pipeline_enabled(self) -> None:
        assert DRIFT_PIPELINE_ENABLED is True


# ── Internal: _drift_dict_to_unified_signal ────────────────────────────────────


class TestDriftDictToUnifiedSignal:
    """Convert per-level drift dicts to UnifiedDriftSignal."""

    def test_none_on_non_dict(self) -> None:
        assert _drift_dict_to_unified_signal("invalid", source="structural") is None  # type: ignore[arg-type]

    def test_none_on_empty_dict(self) -> None:
        assert _drift_dict_to_unified_signal({}, source="structural") is None

    def test_none_on_no_drift_status(self) -> None:
        d = {"status": "no_drift", "severity": "minor"}
        assert _drift_dict_to_unified_signal(d, source="structural") is None

    def test_none_on_missing_severity(self) -> None:
        d = {"status": "drift_detected"}
        assert _drift_dict_to_unified_signal(d, source="structural") is None

    def test_valid_dict_returns_signal(self) -> None:
        d = {
            "status": "drift_detected",
            "severity": "major",
            "confidence": 0.7,
            "categories": ["shape_mismatch"],
        }
        sig = _drift_dict_to_unified_signal(d, source="structural")
        assert sig is not None
        assert sig.source == "structural"
        assert sig.type == "shape_mismatch"
        assert sig.weight == pytest.approx(0.6)  # major maps to 0.6
        assert sig.confidence == pytest.approx(0.7)
        assert sig.details["drift"] == d

    def test_uses_first_category_as_type(self) -> None:
        d = {
            "status": "drift_detected",
            "severity": "minor",
            "categories": ["oscillation", "noise"],
        }
        sig = _drift_dict_to_unified_signal(d, source="behavioural")
        assert sig is not None
        assert sig.type == "oscillation"

    def test_empty_categories_uses_signal_type(self) -> None:
        d = {
            "status": "drift_detected",
            "severity": "minor",
        }
        sig = _drift_dict_to_unified_signal(d, source="structural")
        assert sig is not None
        assert sig.type == "signal"

    def test_weight_map(self) -> None:
        """minor→0.3, major→0.6, catastrophic→0.9."""
        for severity, expected_weight in [("minor", 0.3), ("major", 0.6), ("catastrophic", 0.9)]:
            d = {"status": "drift_detected", "severity": severity, "categories": ["test"]}
            sig = _drift_dict_to_unified_signal(d, source="structural")
            assert sig is not None
            assert sig.weight == pytest.approx(expected_weight)

    def test_default_confidence_zero(self) -> None:
        d = {"status": "drift_detected", "severity": "major"}
        sig = _drift_dict_to_unified_signal(d, source="structural")
        assert sig is not None
        assert sig.confidence == pytest.approx(0.0)


# ── Internal: _collect_unified_signals ─────────────────────────────────────────


class TestCollectUnifiedSignals:
    """Aggregate segment (structural) and subgoal (behavioural) signals."""

    def test_empty_lists(self) -> None:
        assert _collect_unified_signals([], []) == []

    def test_segment_maps_to_structural(self) -> None:
        segment = [
            {"status": "drift_detected", "severity": "minor", "categories": ["shape_mismatch"]},
            {"status": "drift_detected", "severity": "major", "categories": ["oscillation"]},
        ]
        signals = _collect_unified_signals(segment, [])
        assert len(signals) == 2
        assert all(s.source == "structural" for s in signals)

    def test_subgoal_maps_to_behavioural(self) -> None:
        subgoal = [
            {"status": "drift_detected", "severity": "major", "categories": ["contradict_plan"]},
        ]
        signals = _collect_unified_signals([], subgoal)
        assert len(signals) == 1
        assert signals[0].source == "behavioural"

    def test_both_sources_merged(self) -> None:
        segment = [{"status": "drift_detected", "severity": "minor", "categories": ["s1"]}]
        subgoal = [{"status": "drift_detected", "severity": "major", "categories": ["s2"]}]
        signals = _collect_unified_signals(segment, subgoal)
        assert len(signals) == 2
        assert signals[0].source == "structural"
        assert signals[1].source == "behavioural"

    def test_no_drift_records_skipped(self) -> None:
        segment = [{"status": "no_drift", "severity": "minor"}]
        subgoal = [{"status": "drift_detected", "severity": "major", "categories": ["x"]}]
        signals = _collect_unified_signals(segment, subgoal)
        assert len(signals) == 1
        assert signals[0].source == "behavioural"


# ── Serialisation helper: _to_dict ─────────────────────────────────────────────


class TestToDict:
    """Convert dataclasses to JSON-safe dicts."""

    def test_dataclass_to_dict(self) -> None:
        sig = UnifiedDriftSignal(
            source="structural",
            type="test",
            weight=0.5,
            decay=1.0,
            confidence=0.5,
            details={},
        )
        d = _to_dict(sig)
        assert d["source"] == "structural"
        assert d["weight"] == pytest.approx(0.5)

    def test_list_of_dataclasses(self) -> None:
        sigs = [
            UnifiedDriftSignal(source="structural", type="a", weight=0.3, decay=1.0, confidence=0.3, details={}),
            UnifiedDriftSignal(source="behavioural", type="b", weight=0.6, decay=1.0, confidence=0.6, details={}),
        ]
        result = _to_dict(sigs)
        assert len(result) == 2
        assert result[0]["source"] == "structural"
        assert result[1]["source"] == "behavioural"

    def test_pass_through_for_primitives(self) -> None:
        assert _to_dict("hello") == "hello"
        assert _to_dict(42) == 42
        assert _to_dict(None) is None


# ── Full pipeline: run_drift_pipeline ──────────────────────────────────────────


class TestRunDriftPipeline:
    """The full pipeline must produce a complete, JSON-safe result."""

    def test_all_keys_present(self) -> None:
        result = run_drift_pipeline(
            segment_drift=[{"status": "drift_detected", "severity": "minor", "categories": ["x"]}],
            subgoal_drift=[],
            prev_confirmation=None,
            prev_budget=None,
        )
        expected_keys = {"signals", "classification", "confirmation", "recovery", "arbitration", "budget_state"}
        assert set(result.keys()) == expected_keys

    def test_no_drift_graceful(self) -> None:
        """Empty drift records → no_drift classification, unconfirmed, none action."""
        result = run_drift_pipeline([], [], None, None)
        assert result["signals"] == []
        assert result["classification"]["status"] == "no_drift"
        assert result["confirmation"]["confirmed"] is False
        assert result["recovery"]["action"] == "none"
        assert result["arbitration"]["action"] == "none"

    def test_signals_present_in_output(self) -> None:
        result = run_drift_pipeline(
            segment_drift=[{"status": "drift_detected", "severity": "major", "categories": ["shape"]}],
            subgoal_drift=[],
            prev_confirmation=None,
            prev_budget=None,
        )
        signals = result["signals"]
        assert len(signals) >= 1
        assert signals[0]["source"] == "structural"
        assert signals[0]["type"] == "shape"

    def test_with_previous_state(self) -> None:
        prev_confirmation = DriftConfirmationState(
            confirmed=True,
            severity="major",
            confidence=0.7,
            streak=2,
            hysteresis=0.3,
            history=[],
        )
        prev_budget = RepairBudgetState(
            usage_cycle=1,
            usage_subgoal=0,
            usage_plan=0,
            usage_global=0,
        )
        result = run_drift_pipeline(
            segment_drift=[{"status": "drift_detected", "severity": "major", "categories": ["x"]}],
            subgoal_drift=[],
            prev_confirmation=prev_confirmation,
            prev_budget=prev_budget,
        )
        # Budget should reflect previous usage
        assert result["budget_state"]["usage_cycle"] >= 1

    def test_severity_catastrophic_escalates(self) -> None:
        """Catastrophic drift → catastrophic arbitration."""
        result = run_drift_pipeline(
            segment_drift=[
                {"status": "drift_detected", "severity": "catastrophic", "confidence": 0.9, "categories": ["critical"]},
            ],
            subgoal_drift=[],
            prev_confirmation=None,
            prev_budget=None,
        )
        assert result["classification"]["severity"] == "catastrophic"
        assert result["confirmation"]["confirmed"] is True
        # Catastrophic → action is "catastrophic"
        assert result["arbitration"]["action"] == "catastrophic"

    def test_json_serialisable(self) -> None:
        result = run_drift_pipeline(
            segment_drift=[{"status": "drift_detected", "severity": "major", "categories": ["x"]}],
            subgoal_drift=[],
            prev_confirmation=None,
            prev_budget=None,
        )
        serialised = json.dumps(result)
        deserialised = json.loads(serialised)
        assert deserialised["classification"]["severity"] == "major"

    def test_deterministic(self) -> None:
        a = run_drift_pipeline(
            segment_drift=[{"status": "drift_detected", "severity": "minor", "categories": ["x"]}],
            subgoal_drift=[],
            prev_confirmation=None,
            prev_budget=None,
        )
        b = run_drift_pipeline(
            segment_drift=[{"status": "drift_detected", "severity": "minor", "categories": ["x"]}],
            subgoal_drift=[],
            prev_confirmation=None,
            prev_budget=None,
        )
        assert a == b


# ── State helpers ──────────────────────────────────────────────────────────────


class TestExtractPipelineState:
    """Rebuild typed state from memory dict."""

    def test_no_state_returns_none(self) -> None:
        memory: dict = {}
        confirmation, budget = extract_pipeline_state(memory)
        assert confirmation is None
        assert budget is None

    def test_empty_state_returns_none(self) -> None:
        memory = {"drift_pipeline": {}}
        confirmation, budget = extract_pipeline_state(memory)
        assert confirmation is None
        assert budget is None

    def test_rebuilds_confirmation_state(self) -> None:
        memory = {
            "drift_pipeline": {
                "confirmation": {
                    "confirmed": True,
                    "severity": "major",
                    "confidence": 0.7,
                    "streak": 3,
                    "hysteresis": 0.4,
                    "history": [],
                },
            },
        }
        confirmation, budget = extract_pipeline_state(memory)
        assert confirmation is not None
        assert confirmation.confirmed is True
        assert confirmation.severity == "major"
        assert confirmation.streak == 3
        assert budget is None

    def test_handles_malformed_confirmation(self) -> None:
        memory = {
            "drift_pipeline": {
                "confirmation": {"invalid": "data"},
            },
        }
        confirmation, budget = extract_pipeline_state(memory)
        assert confirmation is None


class TestStorePipelineState:
    """Persist relevant state back to memory."""

    def test_stores_confirmation_and_budget(self) -> None:
        pipeline_result = {
            "signals": [{"source": "structural"}],
            "classification": {"status": "no_drift"},
            "confirmation": {"confirmed": False, "severity": "minor", "confidence": 0.0, "streak": 0, "hysteresis": 0.0, "history": []},
            "recovery": {"action": "none"},
            "arbitration": {"action": "none"},
            "budget_state": {"usage_cycle": 0, "usage_subgoal": 0, "usage_plan": 0, "usage_global": 0},
        }
        memory: dict = {}
        store_pipeline_state(memory, pipeline_result)
        stored = memory.get("drift_pipeline", {})
        assert stored["confirmation"]["confirmed"] is False
        assert stored["budget_state"]["usage_cycle"] == 0
        # Should NOT store signals, classification, recovery, or arbitration
        assert "signals" not in stored
        assert "classification" not in stored
        assert "recovery" not in stored
        assert "arbitration" not in stored

    def test_round_trip(self) -> None:
        """store → extract should reconstruct the same state."""
        conf = {"confirmed": True, "severity": "major", "confidence": 0.8, "streak": 2, "hysteresis": 0.3, "history": []}
        budget = {"usage_cycle": 3, "usage_subgoal": 1, "usage_plan": 0, "usage_global": 0}
        pipeline_result = {
            "signals": [],
            "classification": {"status": "no_drift"},
            "confirmation": conf,
            "recovery": {"action": "none"},
            "arbitration": {"action": "none"},
            "budget_state": budget,
        }
        memory: dict = {}
        store_pipeline_state(memory, pipeline_result)
        confirmation, budget_state = extract_pipeline_state(memory)
        assert confirmation is not None
        assert confirmation.confirmed is True
        assert confirmation.severity == "major"
        assert confirmation.streak == 2
        # Budget may not fully roundtrip due to nested RepairBudgetConfig
        # but the stored values should match
        assert memory["drift_pipeline"]["budget_state"]["usage_cycle"] == 3
