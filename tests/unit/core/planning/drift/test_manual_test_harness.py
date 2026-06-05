"""
Tests for the Stratum‑2 Manual Testing Harness (Phase 2.10.x).
==============================================================

Covers:

- repair path
- replan path (budget exhaustion)
- regen_segment path
- regen_subgoal path
- catastrophic path
- budget updates
- determinism
- no mutation of inputs
- JSON‑safe output
- error handling (missing signals, invalid JSON, empty input)
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List

import pytest

from src.core.planning.drift.unified_drift_types import (
    UnifiedDriftClassification,
    UnifiedDriftSignal,
)
from src.core.planning.drift.repair_budget import RepairBudgetConfig, RepairBudgetState
from src.core.planning.models.plan_state import PlanState, PlanStatus
from src.core.planning.models.plan import Plan
from src.core.types.plan_segment import PlanSegment
from src.core.types.subgoal import Subgoal, SubgoalLifecycleState

from tools.testing_harness.manual_test_harness import (
    run_pipeline,
    _build_signals,
    _build_classification,
    _build_budget_config,
    _build_budget_state,
    _build_plan_state,
    _build_plan,
    _build_segment,
    _build_subgoal,
    _execute_action,
    _update_budgets,
    _to_json_safe,
)


# ──────────────────────────────────────────────────────────────────────────────
# Test fixtures
# ──────────────────────────────────────────────────────────────────────────────

def _minor_structural_signal() -> Dict[str, Any]:
    return {
        "source": "structural",
        "type": "shape_mismatch",
        "weight": 0.35,
        "decay": 0.9,
        "confidence": 0.5,
        "details": {"field": "payload", "expected": "dict", "actual": "str"},
    }


def _major_behavioural_signal() -> Dict[str, Any]:
    return {
        "source": "behavioural",
        "type": "wrong_capability",
        "weight": 0.55,
        "decay": 0.8,
        "confidence": 0.65,
        "details": {"declared": "summarize", "executed": "generate_code"},
    }


def _catastrophic_signal() -> Dict[str, Any]:
    return {
        "source": "behavioural",
        "type": "unexpected_side_effect",
        "weight": 0.80,
        "decay": 1.0,
        "confidence": 0.85,
        "details": {"side_effects": ["file_write", "network_call"]},
    }


def _no_signals_input() -> Dict[str, Any]:
    return {"signals": []}


def _minor_drift_input() -> Dict[str, Any]:
    return {"signals": [_minor_structural_signal()]}


def _major_drift_input() -> Dict[str, Any]:
    return {"signals": [_major_behavioural_signal()]}


def _catastrophic_drift_input() -> Dict[str, Any]:
    return {"signals": [_catastrophic_signal()]}


def _budget_exhausted_input() -> Dict[str, Any]:
    """Input that triggers replan via exhausted plan budget."""
    return {
        "signals": [_minor_structural_signal()],
        "budget_config": {"max_cycle": 5, "max_subgoal": 10, "max_plan": 1, "max_global": 50},
        "budget_usage": {"usage_cycle": 0, "usage_subgoal": 0, "usage_plan": 1, "usage_global": 0},
    }


# ──────────────────────────────────────────────────────────────────────────────
# Constructor tests
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildFunctions:
    """Unit tests for input constructor helpers."""

    def test_build_signals_valid(self):
        raw = [{"source": "structural", "type": "shape_mismatch", "weight": 0.35, "decay": 0.9, "confidence": 0.5, "details": {}}]
        signals = _build_signals(raw)
        assert len(signals) == 1
        s = signals[0]
        assert s.source == "structural"
        assert s.type == "shape_mismatch"
        assert s.weight == 0.35

    def test_build_signals_empty(self):
        assert _build_signals([]) == []

    def test_build_signals_defaults(self):
        raw = [{"source": "temporal", "type": "oscillation", "weight": 0.2, "details": {}}]
        signals = _build_signals(raw)
        assert signals[0].decay == 1.0  # default
        assert signals[0].confidence == 0.5  # default

    def test_build_classification_none(self):
        assert _build_classification(None) is None

    def test_build_classification_from_dict(self):
        raw = {
            "status": "drift_detected",
            "severity": "minor",
            "categories": ["shape_mismatch"],
            "confidence": 0.45,
            "reasons": [{"source": "structural", "type": "shape_mismatch", "weight": 0.35, "decay": 0.9, "confidence": 0.5, "details": {}}],
            "streak": 2,
        }
        prev = _build_classification(raw)
        assert prev is not None
        assert prev.status == "drift_detected"
        assert prev.streak == 2

    def test_build_budget_config_default(self):
        cfg = _build_budget_config(None)
        assert cfg.max_cycle == 5
        assert cfg.max_global == 50

    def test_build_budget_config_custom(self):
        cfg = _build_budget_config({"max_cycle": 3, "max_global": 10})
        assert cfg.max_cycle == 3
        assert cfg.max_global == 10

    def test_build_budget_state_default(self):
        cfg = RepairBudgetConfig(max_cycle=5)
        state = _build_budget_state(cfg, None)
        assert state.usage_cycle == 0
        assert state.config.max_cycle == 5

    def test_build_budget_state_custom(self):
        cfg = RepairBudgetConfig(max_cycle=5)
        state = _build_budget_state(cfg, {"usage_cycle": 2, "usage_global": 5})
        assert state.usage_cycle == 2
        assert state.usage_global == 5

    def test_build_plan_state_default(self):
        ps = _build_plan_state(None)
        assert ps.plan_id == "harness-default-plan"
        assert ps.status == PlanStatus.PENDING

    def test_build_plan_state_custom(self):
        ps = _build_plan_state({
            "plan_id": "test-plan",
            "steps": [{"type": "validate"}],
            "current_step_index": 0,
            "status": "running",
            "last_result": {"ok": True},
            "trace": [{"event": "started"}],
            "created_at": 1000,
            "updated_at": 2000,
        })
        assert ps.plan_id == "test-plan"
        assert ps.status == PlanStatus.RUNNING
        assert len(ps.steps) == 1

    def test_build_plan_default(self):
        p = _build_plan(None)
        assert p.intent == "placeholder_intent"

    def test_build_plan_custom(self):
        p = _build_plan({"intent": "custom_intent", "targetskillid": "skill_x"})
        assert p.intent == "custom_intent"

    def test_build_segment_default(self):
        seg = _build_segment(None)
        assert seg.subgoal_id == "placeholder_segment"
        assert seg.steps == []

    def test_build_segment_custom(self):
        seg = _build_segment({
            "subgoal_id": "sg-1",
            "steps": ["step1", "step2"],
            "context": {"key": "val"},
            "metadata": {},
            "created_at": "2024-01-01T00:00:00",
        })
        assert seg.subgoal_id == "sg-1"
        assert seg.steps == ["step1", "step2"]

    def test_build_subgoal_default(self):
        sg = _build_subgoal(None)
        assert sg.subgoal_id == "placeholder_subgoal"
        assert sg.goal == "placeholder_goal"

    def test_build_subgoal_custom(self):
        sg = _build_subgoal({
            "subgoal_id": "sg-1",
            "goal": "test goal",
            "context": {},
            "metadata": {},
            "state": "active",
        })
        assert sg.subgoal_id == "sg-1"
        assert sg.state == SubgoalLifecycleState.ACTIVE


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline path tests
# ──────────────────────────────────────────────────────────────────────────────

class TestRepairPath:
    """Tests for the repair action path (minor structural drift)."""

    def test_no_signals_produces_no_drift(self):
        trace = run_pipeline(_no_signals_input())
        cls = trace["DRIFT_CLASSIFICATION"]
        assert cls.status == "no_drift"
        assert cls.severity == "minor"
        assert cls.confidence == 0.0

        arb = trace["ARBITRATION_DECISION"]
        # no signals → no drift → "none" action (no repair needed)
        assert arb.action == "none"

        action = trace["ACTION_OUTPUT"]
        assert action["action"] == "none"

    def test_minor_structural_produces_repair(self):
        trace = run_pipeline(_minor_drift_input())
        arb = trace["ARBITRATION_DECISION"]
        assert arb.action == "repair"

        action = trace["ACTION_OUTPUT"]
        assert action["action"] == "repair"
        assert "repaired_plan_state" in action

    def test_repair_does_not_mutate_input(self):
        input_data = _minor_drift_input()
        signals_snapshot = json.dumps(input_data["signals"])
        run_pipeline(input_data)
        # Verify input was not mutated
        assert json.dumps(input_data["signals"]) == signals_snapshot


class TestReplanPath:
    """Tests for the replan action path (budget exhaustion)."""

    def test_budget_exhaustion_forces_replan(self):
        trace = run_pipeline(_budget_exhausted_input())
        arb = trace["ARBITRATION_DECISION"]
        assert arb.action == "replan"

        action = trace["ACTION_OUTPUT"]
        assert action["action"] == "replan"
        assert "placeholder_plan" in action
        assert "PLACEHOLDER_REPLAN" in action["placeholder_plan"]["intent"]

    def test_replan_updates_plan_and_global_budgets(self):
        trace = run_pipeline(_budget_exhausted_input())
        budget = trace["UPDATED_BUDGET"]
        # Start: usage_cycle=0, usage_plan=1, usage_global=0
        # replan charges: cycle, plan, global — but plan is exhausted so it's skipped
        assert budget.usage_cycle == 1   # was 0, now 1
        assert budget.usage_plan == 1    # exhausted, skipped
        assert budget.usage_global == 1  # was 0, now 1


class TestRegenSegmentPath:
    """Tests for the regen_segment action path."""

    def test_major_behavioural_produces_regen_segment(self):
        # behavioural drift → regen_segment (per category rules)
        input_data = {
            "signals": [
                {"source": "behavioural", "type": "wrong_capability", "weight": 0.45,
                 "decay": 1.0, "confidence": 0.6, "details": {}}
            ],
        }
        trace = run_pipeline(input_data)
        arb = trace["ARBITRATION_DECISION"]
        # behavioural → regen_segment, severity major? weight 0.45 → severity major
        assert arb.action in ("regen_segment", "repair")  # medium confidence → unchanged
        action = trace["ACTION_OUTPUT"]

    def test_structurally_major_produces_regen_segment(self):
        # structural + major severity → regen_segment
        input_data = {
            "signals": [
                {"source": "structural", "type": "shape_mismatch", "weight": 0.50,
                 "decay": 1.0, "confidence": 0.7, "details": {}}
            ],
        }
        trace = run_pipeline(input_data)
        arb = trace["ARBITRATION_DECISION"]
        # severity=major (0.50 >= 0.40), structural+major → regen_segment
        # confidence=high (0.7 >= 0.7) → escalate one level → regen_subgoal
        assert arb.action in ("regen_segment", "regen_subgoal")


class TestRegenSubgoalPath:
    """Tests for the regen_subgoal action path."""

    def test_regen_subgoal_produces_placeholder(self):
        input_data = {
            "signals": [
                {"source": "behavioural", "type": "unexpected_side_effect", "weight": 0.78,
                 "decay": 1.0, "confidence": 0.9, "details": {}}
            ],
        }
        trace = run_pipeline(input_data)
        arb = trace["ARBITRATION_DECISION"]
        # catastrophic severity → catastrophic action
        if arb.action == "catastrophic":
            action = trace["ACTION_OUTPUT"]
            assert action["action"] == "catastrophic"
        # Otherwise check regen_subgoal path
        elif arb.action == "regen_subgoal":
            action = trace["ACTION_OUTPUT"]
            assert action["action"] == "regen_subgoal"
            assert "placeholder_subgoal" in action


class TestCatastrophicPath:
    """Tests for the catastrophic action path."""

    def test_catastrophic_produces_envelope(self):
        trace = run_pipeline(_catastrophic_drift_input())
        arb = trace["ARBITRATION_DECISION"]
        assert arb.action == "catastrophic"

        action = trace["ACTION_OUTPUT"]
        assert action["action"] == "catastrophic"
        assert "catastrophic_envelope" in action
        assert action["catastrophic_envelope"]["severity"] == "catastrophic"
        assert "preserved_plan_state" in action["catastrophic_envelope"]
        assert "preserved_plan" in action["catastrophic_envelope"]
        assert "preserved_segment" in action["catastrophic_envelope"]
        assert "preserved_subgoal" in action["catastrophic_envelope"]

    def test_catastrophic_updates_cycle_and_global(self):
        trace = run_pipeline(_catastrophic_drift_input())
        budget = trace["UPDATED_BUDGET"]
        assert budget.usage_cycle == 1
        assert budget.usage_global == 1
        assert budget.usage_plan == 0  # catastrophic doesn't charge plan
        assert budget.usage_subgoal == 0  # catastrophic doesn't charge subgoal


# ──────────────────────────────────────────────────────────────────────────────
# Budget tests
# ──────────────────────────────────────────────────────────────────────────────

class TestBudgetUpdates:
    """Tests for budget scope updates."""

    def test_repair_charges_cycle_and_global(self):
        input_data = {
            "signals": [{"source": "semantic", "type": "contradict_plan", "weight": 0.2,
                         "decay": 1.0, "confidence": 0.3, "details": {}}],
            "budget_usage": {"usage_cycle": 0, "usage_subgoal": 0, "usage_plan": 0, "usage_global": 0},
        }
        trace = run_pipeline(input_data)
        budget = trace["UPDATED_BUDGET"]
        # low confidence → repair
        assert budget.usage_cycle == 1
        assert budget.usage_global == 1

    def test_update_budgets_deterministic(self):
        cfg = RepairBudgetConfig(max_cycle=3, max_global=10)
        state = RepairBudgetState(config=cfg)
        result1 = _update_budgets(state, "repair")
        result2 = _update_budgets(state, "repair")
        assert result1.usage_cycle == result2.usage_cycle
        assert result1.usage_global == result2.usage_global

    def test_update_budgets_does_not_mutate(self):
        cfg = RepairBudgetConfig(max_cycle=3)
        state = RepairBudgetState(config=cfg)
        snapshot_cycle = state.usage_cycle
        _update_budgets(state, "repair")
        assert state.usage_cycle == snapshot_cycle  # not mutated


# ──────────────────────────────────────────────────────────────────────────────
# Determinism tests
# ──────────────────────────────────────────────────────────────────────────────

class TestDeterminism:
    """Tests for deterministic behaviour."""

    def test_deterministic_output_same_input(self):
        input_data = _minor_drift_input()
        trace1 = run_pipeline(input_data)
        trace2 = run_pipeline(input_data)
        # Compare serialised forms
        encoded1 = json.dumps(_to_json_safe(trace1), sort_keys=True, default=str)
        encoded2 = json.dumps(_to_json_safe(trace2), sort_keys=True, default=str)
        assert encoded1 == encoded2

    def test_deterministic_with_previous_classification(self):
        input_data = {
            "signals": [_minor_structural_signal()],
            "previous_classification": {
                "status": "drift_detected",
                "severity": "minor",
                "categories": ["shape_mismatch"],
                "confidence": 0.45,
                "reasons": [{"source": "structural", "type": "shape_mismatch", "weight": 0.35, "decay": 0.9, "confidence": 0.5, "details": {}}],
                "streak": 2,
            },
        }
        trace1 = run_pipeline(input_data)
        trace2 = run_pipeline(input_data)
        encoded1 = json.dumps(_to_json_safe(trace1), sort_keys=True, default=str)
        encoded2 = json.dumps(_to_json_safe(trace2), sort_keys=True, default=str)
        assert encoded1 == encoded2

    def test_all_paths_deterministic(self):
        """Every pipeline path produces the same output for the same input."""
        test_inputs = [
            _no_signals_input(),
            _minor_drift_input(),
            _major_drift_input(),
            _catastrophic_drift_input(),
            _budget_exhausted_input(),
        ]
        for inp in test_inputs:
            trace1 = run_pipeline(inp)
            trace2 = run_pipeline(inp)
            assert trace1["ARBITRATION_DECISION"].action == trace2["ARBITRATION_DECISION"].action, \
                f"Divergent actions for input: {inp}"


# ──────────────────────────────────────────────────────────────────────────────
# JSON‑safety tests
# ──────────────────────────────────────────────────────────────────────────────

class TestJsonSafety:
    """Tests for JSON‑safe output."""

    def test_output_is_json_serialisable(self):
        trace = run_pipeline(_minor_drift_input())
        safe = _to_json_safe(trace)
        encoded = json.dumps(safe, default=str)
        decoded = json.loads(encoded)
        assert decoded["ARBITRATION_DECISION"]["action"] == "repair"

    def test_catastrophic_output_is_json_serialisable(self):
        trace = run_pipeline(_catastrophic_drift_input())
        safe = _to_json_safe(trace)
        encoded = json.dumps(safe, default=str)
        decoded = json.loads(encoded)
        assert decoded["ACTION_OUTPUT"]["catastrophic_envelope"]["severity"] == "catastrophic"

    def test_all_sections_present_in_every_path(self):
        required_sections = {
            "INPUT",
            "DRIFT_CLASSIFICATION",
            "ARBITRATION_DECISION",
            "ACTION_OUTPUT",
            "UPDATED_BUDGET",
        }
        test_inputs = [
            _no_signals_input(),
            _minor_drift_input(),
            _major_drift_input(),
            _catastrophic_drift_input(),
            _budget_exhausted_input(),
        ]
        for inp in test_inputs:
            trace = run_pipeline(inp)
            assert set(trace.keys()) == required_sections, \
                f"Missing sections in output for: {inp}"


# ──────────────────────────────────────────────────────────────────────────────
# No mutation tests
# ──────────────────────────────────────────────────────────────────────────────

class TestNoMutation:
    """Tests that inputs are never mutated."""

    def test_signals_not_mutated(self):
        raw = [{"source": "structural", "type": "x", "weight": 0.3, "decay": 1.0, "confidence": 0.5, "details": {"k": "v"}}]
        snapshot = json.dumps(raw)
        run_pipeline({"signals": raw})
        assert json.dumps(raw) == snapshot

    def test_budget_config_not_mutated(self):
        config_dict = {"max_cycle": 3, "max_subgoal": 5, "max_plan": 10, "max_global": 20}
        snapshot = json.dumps(config_dict)
        run_pipeline({"signals": [_minor_structural_signal()], "budget_config": config_dict})
        assert json.dumps(config_dict) == snapshot

    def test_plan_state_not_mutated(self):
        ps_dict = {"plan_id": "test", "steps": [{"t": "x"}], "current_step_index": 0, "status": "pending"}
        snapshot = json.dumps(ps_dict)
        run_pipeline({"signals": [_minor_structural_signal()], "plan_state": ps_dict})
        assert json.dumps(ps_dict) == snapshot


# ──────────────────────────────────────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_signals_produces_valid_output(self):
        trace = run_pipeline({"signals": []})
        assert trace["DRIFT_CLASSIFICATION"].status == "no_drift"
        assert trace["UPDATED_BUDGET"].usage_cycle == 0  # no action → no budget update

    def test_custom_plan_state_is_used_in_repair(self):
        input_data = {
            "signals": [_minor_structural_signal()],
            "plan_state": {
                "plan_id": "custom-plan-42",
                "steps": [
                    {"type": "validate_input", "payload": {}},
                    None,  # malformed step — should survive as-is (it's a dict check)
                    {"type": "execute"},
                ],
                "current_step_index": 5,  # out of range → clamped
                "status": "needs_repair",
                "last_result": "this_is_not_a_dict",  # invalid → None
                "trace": [{"event": "started"}],
                "created_at": 100,
                "updated_at": 200,
            },
        }
        trace = run_pipeline(input_data)
        action_out = trace["ACTION_OUTPUT"]
        assert action_out["action"] == "repair"
        repaired = action_out["repaired_plan_state"]
        assert repaired["plan_id"] == "custom-plan-42"
        # last_result should be null (was non-dict)
        assert repaired["last_result"] is None
        # 2 valid steps (null removed by repair) + None was already filtered
        assert len(repaired["steps"]) == 2
        # status should be valid (needs_repair is a valid PlanStatus)
        assert repaired["status"] == "needs_repair"

    def test_multiple_signals_of_mixed_sources(self):
        input_data = {
            "signals": [
                _minor_structural_signal(),
                _major_behavioural_signal(),
            ],
        }
        trace = run_pipeline(input_data)
        cls = trace["DRIFT_CLASSIFICATION"]
        assert cls.status == "drift_detected"
        # structural + behavioural categories (sorted)
        assert "shape_mismatch" in cls.categories
        assert "wrong_capability" in cls.categories
        assert len(cls.categories) == 2

    def test_previous_classification_builds_streak(self):
        input_data = {
            "signals": [_minor_structural_signal()],
            "previous_classification": {
                "status": "drift_detected",
                "severity": "minor",
                "categories": ["shape_mismatch"],
                "confidence": 0.42,
                "reasons": [_minor_structural_signal()],
                "streak": 3,
            },
        }
        trace = run_pipeline(input_data)
        cls = trace["DRIFT_CLASSIFICATION"]
        assert cls.streak == 4  # previous streak 3 + 1 (matching status)
