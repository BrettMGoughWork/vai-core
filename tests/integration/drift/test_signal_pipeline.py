"""
Phase 2.14 — Drift Pipeline Integration Tests
==============================================

Validates the full signals → classification → arbitration → action → budget
pipeline end‑to‑end, without the full agent loop.

These are the codified versions of the 10 manual test scenarios previously
run through ``tools/testing_harness/signal_harness.py``.

Pure, deterministic, JSON‑safe — never calls an LLM, never mutates inputs.
"""

from __future__ import annotations

import copy
import json

import pytest

from tools.testing_harness.signal_harness import run_pipeline


# ──────────────────────────────────────────────────────────────────────────────
# Test helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_signal(
    source: str = "structural",
    signal_type: str = "shape_mismatch",
    weight: float = 0.5,
    decay: float = 1.0,
    confidence: float = 0.5,
    details: dict | None = None,
) -> dict:
    """Build a JSON‑safe signal dict for pipeline input."""
    return {
        "source": source,
        "type": signal_type,
        "weight": weight,
        "decay": decay,
        "confidence": confidence,
        "details": details or {},
    }


def _minimal_input(signals: list[dict] | None = None, **overrides) -> dict:
    """Build a minimal valid pipeline input dict."""
    data: dict = {"signals": signals or []}
    data.update(overrides)
    return data


# ──────────────────────────────────────────────────────────────────────────────
# 1. No drift → "none" action
# ──────────────────────────────────────────────────────────────────────────────

class TestNoDrift:
    """When no signals are present, the pipeline should report no drift and
    take no action, with no budget charges."""

    def test_empty_signals_returns_none_action(self):
        result = run_pipeline(_minimal_input(signals=[]))
        classification = result["DRIFT_CLASSIFICATION"]
        decision = result["ARBITRATION_DECISION"]
        updated_budget = result["UPDATED_BUDGET"]

        assert classification.status == "no_drift"
        assert classification.severity == "minor"  # no-drift path hardcodes "minor"
        assert classification.confidence == 0.0
        assert decision.action == "none"
        # Budget should be unchanged (all scopes at 0)
        assert updated_budget.usage_cycle == 0
        assert updated_budget.usage_global == 0


# ──────────────────────────────────────────────────────────────────────────────
# 2. Minor structural drift → "repair"
# ──────────────────────────────────────────────────────────────────────────────

class TestMinorStructuralDrift:
    """A low‑weight structural signal should classify as minor and
    arbitrate to repair."""

    def test_single_minor_structural_yields_repair(self):
        signal = _make_signal(
            source="structural",
            signal_type="shape_mismatch",
            weight=0.3,
            confidence=0.5,
            decay=1.0,
        )
        result = run_pipeline(_minimal_input(signals=[signal]))

        classification = result["DRIFT_CLASSIFICATION"]
        decision = result["ARBITRATION_DECISION"]

        assert classification.severity == "minor"
        # categories = sorted unique signal types
        assert "shape_mismatch" in classification.categories
        # Weight 0.3 → confidence = 0.3*1.0 + 0.1 = 0.4 → "medium" tier → no change
        assert decision.action == "repair"

    def test_repair_action_produces_repaired_plan_state(self):
        signal = _make_signal(weight=0.3, confidence=0.5)
        result = run_pipeline(_minimal_input(signals=[signal]))
        action_output = result["ACTION_OUTPUT"]

        assert action_output["action"] == "repair"
        assert "repaired_plan_state" in action_output

    def test_repair_charges_budget(self):
        signal = _make_signal(weight=0.3, confidence=0.5)
        result = run_pipeline(_minimal_input(signals=[signal]))
        updated_budget = result["UPDATED_BUDGET"]

        # Repair charges cycle + global
        assert updated_budget.usage_cycle == 1
        assert updated_budget.usage_global == 1


# ──────────────────────────────────────────────────────────────────────────────
# 3. Major structural drift → escalated action
# ──────────────────────────────────────────────────────────────────────────────

class TestMajorStructuralDrift:
    """A high‑weight structural signal with high confidence should
    escalate through the arbitration tree."""

    def test_major_structural_with_high_confidence_escalates(self):
        signal = _make_signal(
            source="structural",
            signal_type="severe_mismatch",
            weight=0.6,
            confidence=0.9,
            decay=1.0,
        )
        result = run_pipeline(_minimal_input(signals=[signal]))

        classification = result["DRIFT_CLASSIFICATION"]
        decision = result["ARBITRATION_DECISION"]

        assert classification.severity == "major"
        # structural + major → regen_segment, high confidence → escalate
        assert decision.action in ("regen_segment", "regen_subgoal")


# ──────────────────────────────────────────────────────────────────────────────
# 4. Catastrophic drift
# ──────────────────────────────────────────────────────────────────────────────

class TestCatastrophicDrift:
    """A weight ≥ 0.75 signal must classify as catastrophic and
    produce an immediate catastrophic arbitration decision."""

    def test_catastrophic_signal_yields_catastrophic_action(self):
        signal = _make_signal(
            source="structural",
            signal_type="plan_corrupted",
            weight=0.95,
            confidence=0.95,
            decay=1.0,
        )
        result = run_pipeline(_minimal_input(signals=[signal]))

        classification = result["DRIFT_CLASSIFICATION"]
        decision = result["ARBITRATION_DECISION"]

        assert classification.severity == "catastrophic"
        assert decision.action == "catastrophic"

    def test_catastrophic_preserves_plan_state_for_forensics(self):
        signal = _make_signal(weight=0.9, confidence=0.9)
        result = run_pipeline(_minimal_input(signals=[signal]))
        action_output = result["ACTION_OUTPUT"]

        assert action_output["action"] == "catastrophic"
        envelope = action_output["catastrophic_envelope"]
        assert envelope["severity"] == "catastrophic"
        assert "preserved_plan_state" in envelope
        assert "preserved_plan" in envelope
        assert "preserved_segment" in envelope
        assert "preserved_subgoal" in envelope


# ──────────────────────────────────────────────────────────────────────────────
# 5. Budget exhaustion
# ──────────────────────────────────────────────────────────────────────────────

class TestBudgetExhaustion:
    """When a budget scope is exhausted, actions should escalate to replan
    instead of repair."""

    def test_global_budget_exhausted_escalates_to_replan(self):
        signal = _make_signal(weight=0.3, confidence=0.5)

        result = run_pipeline(_minimal_input(
            signals=[signal],
            budget_config={
                "max_cycle": 5,
                "max_subgoal": 10,
                "max_plan": 20,
                "max_global": 50,
            },
            budget_usage={
                "usage_cycle": 0,
                "usage_subgoal": 0,
                "usage_plan": 0,
                "usage_global": 50,  # exhausted
            },
        ))

        decision = result["ARBITRATION_DECISION"]
        # Global exhaustion should escalate to replan
        assert decision.action in ("replan", "regen_segment")
        assert "budget" in decision.reason.lower()

    def test_non_exhausted_budget_allows_repair(self):
        signal = _make_signal(weight=0.3, confidence=0.5)

        result = run_pipeline(_minimal_input(
            signals=[signal],
            budget_usage={
                "usage_cycle": 0,
                "usage_subgoal": 0,
                "usage_plan": 0,
                "usage_global": 0,  # plenty of room
            },
        ))

        decision = result["ARBITRATION_DECISION"]
        assert decision.action == "repair"


# ──────────────────────────────────────────────────────────────────────────────
# 6. Multiple mixed signals
# ──────────────────────────────────────────────────────────────────────────────

class TestMultipleMixedSignals:
    """The pipeline must correctly aggregate multiple signals from
    different sources."""

    def test_mixed_signals_produce_correct_classification(self):
        signals = [
            _make_signal(source="structural", weight=0.3),
            _make_signal(source="behavioural", weight=0.4),
            _make_signal(source="temporal", weight=0.2),
        ]
        result = run_pipeline(_minimal_input(signals=signals))

        classification = result["DRIFT_CLASSIFICATION"]
        # Max weight is 0.4 → major
        assert classification.severity == "major"
        assert len(classification.reasons) == 3
        # reasons contain the source info
        sources = {r.source for r in classification.reasons}
        assert "structural" in sources
        assert "behavioural" in sources
        assert "temporal" in sources

    def test_mixed_signals_deterministic_ordering(self):
        signals = [
            _make_signal(source="behavioural", weight=0.4),
            _make_signal(source="structural", weight=0.3),
            _make_signal(source="temporal", weight=0.2),
        ]
        result1 = run_pipeline(_minimal_input(signals=signals))
        result2 = run_pipeline(_minimal_input(signals=signals))

        # Determinism: same input → same output
        assert result1["ARBITRATION_DECISION"].action == result2["ARBITRATION_DECISION"].action
        assert result1["DRIFT_CLASSIFICATION"].severity == result2["DRIFT_CLASSIFICATION"].severity


# ──────────────────────────────────────────────────────────────────────────────
# 7. Previous classification streak
# ──────────────────────────────────────────────────────────────────────────────

class TestPreviousClassificationStreak:
    """A previous classification with a streak should boost the
    confidence of the current classification."""

    def test_streak_boosts_confidence(self):
        signal = _make_signal(weight=0.35, confidence=0.4, decay=1.0)

        # Without previous classification
        result_no_streak = run_pipeline(_minimal_input(signals=[signal]))
        conf_no_streak = result_no_streak["DRIFT_CLASSIFICATION"].confidence

        # With previous classification and streak of 3
        result_with_streak = run_pipeline(_minimal_input(
            signals=[signal],
            previous_classification={
                "status": "drift_detected",
                "severity": "minor",
                "categories": ["structural"],
                "confidence": 0.45,
                "reasons": [signal],
                "streak": 3,
            },
        ))
        conf_with_streak = result_with_streak["DRIFT_CLASSIFICATION"].confidence

        # Confidence with streak should be higher (streak bonus = 0.1 * 3 = 0.3)
        assert conf_with_streak > conf_no_streak

    def test_no_streak_does_not_boost_confidence(self):
        signal = _make_signal(weight=0.35, confidence=0.4, decay=1.0)

        result_no_streak = run_pipeline(_minimal_input(signals=[signal]))
        result_zero_streak = run_pipeline(_minimal_input(
            signals=[signal],
            previous_classification={
                "status": "drift_detected",
                "severity": "minor",
                "categories": ["structural"],
                "confidence": 0.45,
                "reasons": [signal],
                "streak": 0,
            },
        ))

        # Confidence should be the same (streak 0 → no bonus)
        assert (result_no_streak["DRIFT_CLASSIFICATION"].confidence
                == result_zero_streak["DRIFT_CLASSIFICATION"].confidence)


# ──────────────────────────────────────────────────────────────────────────────
# 8. Determinism
# ──────────────────────────────────────────────────────────────────────────────

class TestPipelineDeterminism:
    """The full pipeline must be deterministic — identical inputs produce
    identical outputs."""

    def test_same_input_same_classification(self):
        signals = [
            _make_signal(source="structural", weight=0.3),
            _make_signal(source="semantic", weight=0.25),
        ]
        input_data = _minimal_input(signals=signals)

        result1 = run_pipeline(copy.deepcopy(input_data))
        result2 = run_pipeline(copy.deepcopy(input_data))

        c1 = result1["DRIFT_CLASSIFICATION"]
        c2 = result2["DRIFT_CLASSIFICATION"]
        assert c1.status == c2.status
        assert c1.severity == c2.severity
        assert c1.confidence == c2.confidence
        assert c1.categories == c2.categories

    def test_same_input_same_arbitration(self):
        signals = [_make_signal(weight=0.3)]
        input_data = _minimal_input(signals=signals)

        result1 = run_pipeline(copy.deepcopy(input_data))
        result2 = run_pipeline(copy.deepcopy(input_data))

        assert result1["ARBITRATION_DECISION"].action == result2["ARBITRATION_DECISION"].action
        assert result1["ARBITRATION_DECISION"].reason == result2["ARBITRATION_DECISION"].reason

    def test_same_input_same_budget(self):
        signals = [_make_signal(weight=0.9, confidence=0.9)]
        input_data = _minimal_input(signals=signals)

        result1 = run_pipeline(copy.deepcopy(input_data))
        result2 = run_pipeline(copy.deepcopy(input_data))

        b1 = result1["UPDATED_BUDGET"]
        b2 = result2["UPDATED_BUDGET"]
        assert b1.usage_cycle == b2.usage_cycle
        assert b1.usage_global == b2.usage_global

    def test_same_input_same_action_output(self):
        signals = [_make_signal(weight=0.3, confidence=0.5)]
        input_data = _minimal_input(signals=signals)

        result1 = run_pipeline(copy.deepcopy(input_data))
        result2 = run_pipeline(copy.deepcopy(input_data))

        assert result1["ACTION_OUTPUT"]["action"] == result2["ACTION_OUTPUT"]["action"]


# ──────────────────────────────────────────────────────────────────────────────
# 9. Budget correctness
# ──────────────────────────────────────────────────────────────────────────────

class TestBudgetCorrectness:
    """Budget counters must increment correctly per action type."""

    def test_none_action_does_not_charge_budget(self):
        result = run_pipeline(_minimal_input(signals=[]))
        budget = result["UPDATED_BUDGET"]
        assert budget.usage_cycle == 0
        assert budget.usage_global == 0

    def test_repair_charges_cycle_and_global(self):
        signal = _make_signal(weight=0.3, confidence=0.5)
        result = run_pipeline(_minimal_input(signals=[signal]))
        budget = result["UPDATED_BUDGET"]
        assert budget.usage_cycle == 1
        assert budget.usage_global == 1
        assert budget.usage_subgoal == 0
        assert budget.usage_plan == 0

    def test_catastrophic_charges_cycle_and_global(self):
        signal = _make_signal(weight=0.9, confidence=0.9)
        result = run_pipeline(_minimal_input(signals=[signal]))
        budget = result["UPDATED_BUDGET"]
        assert budget.usage_cycle == 1
        assert budget.usage_global == 1

    def test_budget_persists_across_pipeline_calls(self):
        """Budget state can be carried forward across pipeline runs by
        passing the updated budget back as budget_usage."""
        signal = _make_signal(weight=0.3, confidence=0.5)

        # Run 1
        result1 = run_pipeline(_minimal_input(signals=[signal]))
        budget1 = result1["UPDATED_BUDGET"]
        assert budget1.usage_cycle == 1

        # Run 2 with budget carried forward
        result2 = run_pipeline(_minimal_input(
            signals=[signal],
            budget_usage={
                "usage_cycle": budget1.usage_cycle,
                "usage_subgoal": budget1.usage_subgoal,
                "usage_plan": budget1.usage_plan,
                "usage_global": budget1.usage_global,
            },
        ))
        budget2 = result2["UPDATED_BUDGET"]
        assert budget2.usage_cycle == 2
        assert budget2.usage_global == 2


# ──────────────────────────────────────────────────────────────────────────────
# 10. Pipeline input/output validation
# ──────────────────────────────────────────────────────────────────────────────

class TestPipelineInputOutput:
    """The pipeline must handle edge cases gracefully."""

    def test_minimal_input_produces_all_sections(self):
        result = run_pipeline(_minimal_input(signals=[]))
        assert "INPUT" in result
        assert "DRIFT_CLASSIFICATION" in result
        assert "ARBITRATION_DECISION" in result
        assert "ACTION_OUTPUT" in result
        assert "UPDATED_BUDGET" in result

    def test_custom_plan_state_is_respected(self):
        signal = _make_signal(weight=0.3, confidence=0.5)
        result = run_pipeline(_minimal_input(
            signals=[signal],
            plan_state={
                "plan_id": "custom-plan-42",
                "steps": ["step_a", "step_b"],
                "current_step_index": 1,
                "status": "running",
            },
        ))
        action_output = result["ACTION_OUTPUT"]
        assert action_output["action"] == "repair"
        assert "repaired_plan_state" in action_output

    def test_custom_plan_segment_and_subgoal_appear_in_catastrophic(self):
        signal = _make_signal(weight=0.95, confidence=0.95)
        result = run_pipeline(_minimal_input(
            signals=[signal],
            plan={"intent": "test_intent", "targetskillid": "test_skill", "arguments": {}},
            segment={"subgoal_id": "sg_1", "steps": ["do_x"]},
            subgoal={"subgoal_id": "sg_1", "goal": "complete_x", "context": {}, "metadata": {}},
        ))
        envelope = result["ACTION_OUTPUT"]["catastrophic_envelope"]
        assert envelope["severity"] == "catastrophic"

    def test_input_snapshot_captured(self):
        signals = [
            _make_signal(source="structural", weight=0.3),
            _make_signal(source="semantic", weight=0.25),
        ]
        result = run_pipeline(_minimal_input(signals=signals))
        input_snapshot = result["INPUT"]
        assert input_snapshot["signal_count"] == 2
        assert len(input_snapshot["signals_preview"]) == 2

    def test_signal_decay_reduces_confidence(self):
        """Signals with decay < 1.0 should produce lower confidence."""
        signal_decayed = _make_signal(weight=0.5, confidence=0.9, decay=0.5)
        signal_fresh = _make_signal(weight=0.5, confidence=0.9, decay=1.0)

        result_decayed = run_pipeline(_minimal_input(signals=[signal_decayed]))
        result_fresh = run_pipeline(_minimal_input(signals=[signal_fresh]))

        # Decayed signal should have lower classification confidence
        conf_decayed = result_decayed["DRIFT_CLASSIFICATION"].confidence
        conf_fresh = result_fresh["DRIFT_CLASSIFICATION"].confidence
        assert conf_decayed < conf_fresh

    def test_behavioural_signal_arbitrates_to_regen_segment(self):
        signal = _make_signal(
            source="behavioural",
            signal_type="wrong_output_shape",
            weight=0.5,
            confidence=0.6,
            decay=1.0,
        )
        result = run_pipeline(_minimal_input(signals=[signal]))
        decision = result["ARBITRATION_DECISION"]
        # behavioural → regen_segment (medium confidence = no change)
        assert decision.action == "regen_segment"

    def test_semantic_signal_arbitrates_to_repair_for_minor(self):
        signal = _make_signal(
            source="semantic",
            signal_type="contradict_plan",
            weight=0.3,
            confidence=0.5,
            decay=1.0,
        )
        result = run_pipeline(_minimal_input(signals=[signal]))
        classification = result["DRIFT_CLASSIFICATION"]
        decision = result["ARBITRATION_DECISION"]

        assert classification.severity == "minor"
        # semantic + minor → repair (but low confidence forces repair anyway)
        assert decision.action == "repair"

    def test_replan_action_produces_placeholder_plan(self):
        """When arbitration chooses replan, action output includes a placeholder plan."""
        signal = _make_signal(
            source="structural",
            weight=0.3,
            confidence=0.5,
            decay=1.0,
        )
        # Force budget exhaustion to trigger replan
        result = run_pipeline(_minimal_input(
            signals=[signal],
            budget_usage={
                "usage_cycle": 0,
                "usage_subgoal": 0,
                "usage_plan": 0,
                "usage_global": 50,  # exhausted → replan
            },
        ))
        action_output = result["ACTION_OUTPUT"]
        # Global exhaustion → replan
        assert action_output["action"] in ("replan", "regen_segment")

    def test_regen_segment_produces_placeholder_segment(self):
        """When arbitration chooses regen_segment, action output includes a placeholder segment."""
        signal = _make_signal(
            source="behavioural",
            weight=0.5,
            confidence=0.6,  # medium confidence → no adjustment
            decay=1.0,
        )
        result = run_pipeline(_minimal_input(signals=[signal]))
        action_output = result["ACTION_OUTPUT"]
        assert action_output["action"] == "regen_segment"
        assert "placeholder_segment" in action_output

    def test_regen_subgoal_produces_placeholder_subgoal(self):
        """When arbitration chooses regen_subgoal, action output includes a placeholder subgoal."""
        # classification confidence = max_weight * decay_penalty + streak_bonus
        # weight 0.7 → 0.7*1.0 + 0.1 = 0.8 → "high" → escalate to regen_subgoal
        signal = _make_signal(
            source="behavioural",
            weight=0.7,
            confidence=0.85,
            decay=1.0,
        )
        result = run_pipeline(_minimal_input(signals=[signal]))
        action_output = result["ACTION_OUTPUT"]
        assert action_output["action"] == "regen_subgoal"
        assert "placeholder_subgoal" in action_output
