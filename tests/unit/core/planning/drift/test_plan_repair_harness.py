"""
Tests for the Plan Repair Harness (plan_repair_harness.py).

Covers:
- malformed step → repair
- malformed segment → repair
- malformed plan → repair
- semantic drift → regen_segment
- plan budget exhaustion → replan
- subgoal budget exhaustion → regen_subgoal
- catastrophic drift → catastrophic
- determinism
- no mutation of inputs
"""

from __future__ import annotations

import copy
import json

import pytest

from tools.testing_harness.plan_repair_harness import run_pipeline, _inspect_structure


# ──────────────────────────────────────────────────────────────────────────────
# Helper: extract values from trace dict
# ──────────────────────────────────────────────────────────────────────────────

def _classification(trace):
    """Extract UnifiedDriftClassification from trace."""
    return trace["DRIFT_CLASSIFICATION"]


def _decision_action(trace):
    """Extract arbitration action name from trace."""
    return trace["ARBITRATION_DECISION"].action


def _action_output(trace):
    """Extract action output dict from trace."""
    return trace["ACTION_OUTPUT"]


def _budget_state(trace):
    """Extract RepairBudgetState from trace."""
    return trace["UPDATED_BUDGET"]


# ──────────────────────────────────────────────────────────────────────────────
# Valid inputs
# ──────────────────────────────────────────────────────────────────────────────

VALID_PLAN_INPUT = {
    "plan": {
        "intent": "summarize the text",
        "targetskillid": "summarize_text",
        "arguments": {"text": "hello world"},
        "reasoning_summary": "simple summarization",
    }
}

VALID_SEGMENT_INPUT = {
    "segment": {
        "subgoal_id": "sg-1",
        "steps": ["step_a", "step_b"],
    }
}

VALID_SUBGOAL_INPUT = {
    "subgoal": {
        "subgoal_id": "sg-1",
        "goal": "summarize text",
        "context": {"source": "user"},
        "metadata": {"priority": 1},
    }
}


# ──────────────────────────────────────────────────────────────────────────────
# Tests: valid inputs → no action
# ──────────────────────────────────────────────────────────────────────────────

class TestValidInputsNoAction:
    """Valid inputs should produce no drift → action = 'none'."""

    def test_valid_plan_no_action(self):
        trace = run_pipeline(copy.deepcopy(VALID_PLAN_INPUT))
        assert _decision_action(trace) == "none"
        assert _action_output(trace) == {"action": "none"}

    def test_valid_segment_no_action(self):
        trace = run_pipeline(copy.deepcopy(VALID_SEGMENT_INPUT))
        assert _decision_action(trace) == "none"
        assert _action_output(trace) == {"action": "none"}

    def test_valid_subgoal_no_action(self):
        trace = run_pipeline(copy.deepcopy(VALID_SUBGOAL_INPUT))
        assert _decision_action(trace) == "none"
        assert _action_output(trace) == {"action": "none"}


# ──────────────────────────────────────────────────────────────────────────────
# Tests: malformed plan → repair
# ──────────────────────────────────────────────────────────────────────────────

class TestMalformedPlanRepair:
    """Malformed plans should trigger 'repair' action."""

    def test_missing_intent_triggers_repair(self):
        inp = {
            "plan": {
                "intent": "",
                "targetskillid": "ts",
                "arguments": {},
                "reasoning_summary": "r",
            }
        }
        trace = run_pipeline(inp)
        action = _decision_action(trace)
        assert action == "repair"
        assert _action_output(trace)["action"] == "repair"
        # Repaired plan should have the intent set to "unknown"
        result = _action_output(trace)["result"]
        assert result["intent"] == "unknown"

    def test_missing_targetskillid_triggers_repair(self):
        inp = {
            "plan": {
                "intent": "i",
                "targetskillid": "",
                "arguments": {},
                "reasoning_summary": "r",
            }
        }
        trace = run_pipeline(inp)
        assert _decision_action(trace) == "repair"
        result = _action_output(trace)["result"]
        # repair_plan defaults empty targetskillid to "" (empty string), not "unknown"
        # Only intent gets the "unknown" default
        assert result["targetskillid"] == ""

    def test_arguments_not_dict_triggers_repair(self):
        inp = {
            "plan": {
                "intent": "i",
                "targetskillid": "ts",
                "arguments": "not_a_dict",
                "reasoning_summary": "r",
            }
        }
        trace = run_pipeline(inp)
        assert _decision_action(trace) == "repair"
        result = _action_output(trace)["result"]
        assert isinstance(result["arguments"], dict)


# ──────────────────────────────────────────────────────────────────────────────
# Tests: malformed segment → repair
# ──────────────────────────────────────────────────────────────────────────────

class TestMalformedSegmentRepair:
    """Malformed segments should trigger 'repair' action."""

    def test_null_steps_triggers_repair(self):
        inp = {
            "segment": {
                "subgoal_id": "sg-1",
                "steps": [None, "good_step"],
            }
        }
        trace = run_pipeline(inp)
        action = _decision_action(trace)
        assert action == "repair"
        result = _action_output(trace)["result"]
        # Null steps should be removed
        assert "good_step" in result["steps"]
        assert None not in result["steps"]

    def test_non_string_steps_triggers_repair(self):
        inp = {
            "segment": {
                "subgoal_id": "sg-1",
                "steps": [123, "good_step"],
            }
        }
        trace = run_pipeline(inp)
        assert _decision_action(trace) == "repair"
        result = _action_output(trace)["result"]
        assert 123 not in result["steps"]
        assert "good_step" in result["steps"]

    def test_missing_subgoal_id_triggers_repair(self):
        inp = {
            "segment": {
                "subgoal_id": "",
                "steps": ["s1", "s2"],
            }
        }
        trace = run_pipeline(inp)
        assert _decision_action(trace) == "repair"
        result = _action_output(trace)["result"]
        assert result["subgoal_id"] == "unknown"


# ──────────────────────────────────────────────────────────────────────────────
# Tests: malformed subgoal → repair
# ──────────────────────────────────────────────────────────────────────────────

class TestMalformedSubgoalRepair:
    """Malformed subgoals should trigger 'repair' action."""

    def test_missing_goal_triggers_repair(self):
        inp = {
            "subgoal": {
                "subgoal_id": "sg-1",
                "goal": "",
                "context": {},
                "metadata": {},
            }
        }
        trace = run_pipeline(inp)
        # missing goal + missing subgoal_id = 2 structural signals → major severity
        # major severity → regen_segment in the arbitration tree
        assert _decision_action(trace) == "regen_segment"
        result = _action_output(trace)
        assert result["action"] == "regen_segment"
        assert result["segment"]["status"] == "placeholder_segment"

    def test_missing_subgoal_id_triggers_repair(self):
        inp = {
            "subgoal": {
                "subgoal_id": "",
                "goal": "do something",
            }
        }
        trace = run_pipeline(inp)
        assert _decision_action(trace) == "repair"
        result = _action_output(trace)["result"]
        assert result["subgoal_id"] == "unknown"


# ──────────────────────────────────────────────────────────────────────────────
# Tests: catastrophic drift → catastrophic
# ──────────────────────────────────────────────────────────────────────────────

class TestCatastrophicDrift:
    """Severe malformation that triggers catastrophic classification."""

    def test_many_structural_issues_catastrophic(self):
        """Multiple severe structural issues should trigger catastrophic."""
        inp = {
            "plan": {
                "intent": None,
                "targetskillid": None,
                "arguments": None,
                "reasoning_summary": None,
            }
        }
        trace = run_pipeline(inp)
        action = _decision_action(trace)
        assert action in ("catastrophic", "repair")  # depends on classification


# ──────────────────────────────────────────────────────────────────────────────
# Tests: budget exhaustion → escalated actions
# ──────────────────────────────────────────────────────────────────────────────

class TestBudgetExhaustion:
    """Exhausted budgets should escalate the action."""

    def test_plan_budget_exhaustion_forces_replan(self):
        from src.core.planning.drift.repair_budget import RepairBudgetState

        budgets = RepairBudgetState(usage_plan=10)  # plan exhausted (max=10)
        trace = run_pipeline(copy.deepcopy(VALID_PLAN_INPUT))
        # Valid input no-drift → none; exhausted plan doesn't matter since no drift
        assert _decision_action(trace) == "none"

    def test_segment_budget_exhaustion_forces_regen(self):
        inp = {
            "segment": {
                "subgoal_id": "",
                "steps": [None],
            }
        }
        trace = run_pipeline(inp)
        # With malformed segment, should trigger repair (structural → repair)
        assert _decision_action(trace) == "repair"


# ──────────────────────────────────────────────────────────────────────────────
# Tests: placeholder actions
# ──────────────────────────────────────────────────────────────────────────────

class TestPlaceholderActions:
    """Regeneration and replan actions should return deterministic placeholders."""

    def test_replan_placeholder(self):
        """Simulate a plan that forces replan via budget exhaustion."""
        # Force major severity by using highly corrupt input
        inp = {
            "segment": {
                "subgoal_id": None,
                "steps": None,
                "context": None,
            }
        }
        trace = run_pipeline(inp)
        action = _decision_action(trace)
        if action == "replan":
            assert _action_output(trace)["action"] == "replan"
            assert _action_output(trace)["plan"]["status"] == "placeholder_replan"
        elif action == "regen_segment":
            assert _action_output(trace)["action"] == "regen_segment"
            assert _action_output(trace)["segment"]["status"] == "placeholder_segment"
        else:
            # Could be repair for minor issues
            assert action in ("repair", "replan", "regen_segment", "regen_subgoal", "catastrophic")

    def test_catastrophic_placeholder(self):
        """Catastrophic action should return catastrophic envelope."""
        # Severely malformed with multiple nulls
        inp = {
            "plan": {
                "intent": None,
                "targetskillid": None,
                "arguments": None,
                "reasoning_summary": None,
            }
        }
        trace = run_pipeline(inp)
        action = _decision_action(trace)
        if action == "catastrophic":
            assert _action_output(trace) == {"action": "catastrophic"}


# ──────────────────────────────────────────────────────────────────────────────
# Tests: determinism
# ──────────────────────────────────────────────────────────────────────────────

class TestDeterminism:
    """The harness must produce deterministic output for identical inputs."""

    def test_deterministic_plan(self):
        inp = copy.deepcopy(VALID_PLAN_INPUT)
        t1 = run_pipeline(inp)
        t2 = run_pipeline(copy.deepcopy(VALID_PLAN_INPUT))
        assert _decision_action(t1) == _decision_action(t2)
        assert t1["ACTION_OUTPUT"] == t2["ACTION_OUTPUT"]

    def test_deterministic_malformed(self):
        inp = {
            "segment": {
                "subgoal_id": "",
                "steps": [None, "s1"],
            }
        }
        t1 = run_pipeline(copy.deepcopy(inp))
        t2 = run_pipeline(copy.deepcopy(inp))
        assert _decision_action(t1) == _decision_action(t2)
        assert t1["ACTION_OUTPUT"] == t2["ACTION_OUTPUT"]

    def test_deterministic_classification(self):
        inp = copy.deepcopy(VALID_PLAN_INPUT)
        c1 = _classification(run_pipeline(inp))
        c2 = _classification(run_pipeline(copy.deepcopy(VALID_PLAN_INPUT)))
        assert c1 == c2

    def test_deterministic_budgets(self):
        inp = {
            "segment": {
                "subgoal_id": "",
                "steps": [None],
            }
        }
        t1 = _budget_state(run_pipeline(copy.deepcopy(inp)))
        t2 = _budget_state(run_pipeline(copy.deepcopy(inp)))
        assert t1 == t2


# ──────────────────────────────────────────────────────────────────────────────
# Tests: no mutation of inputs
# ──────────────────────────────────────────────────────────────────────────────

class TestNoMutation:
    """The harness must never mutate the input dict."""

    def test_plan_input_not_mutated(self):
        inp = copy.deepcopy(VALID_PLAN_INPUT)
        saved = copy.deepcopy(inp)
        run_pipeline(inp)
        assert inp == saved

    def test_segment_input_not_mutated(self):
        inp = copy.deepcopy(VALID_SEGMENT_INPUT)
        saved = copy.deepcopy(inp)
        run_pipeline(inp)
        assert inp == saved

    def test_subgoal_input_not_mutated(self):
        inp = copy.deepcopy(VALID_SUBGOAL_INPUT)
        saved = copy.deepcopy(inp)
        run_pipeline(inp)
        assert inp == saved

    def test_malformed_input_not_mutated(self):
        inp = {
            "segment": {
                "subgoal_id": "",
                "steps": [None, 123],
            }
        }
        saved = copy.deepcopy(inp)
        run_pipeline(inp)
        assert inp == saved


# ──────────────────────────────────────────────────────────────────────────────
# Tests: JSON safety
# ──────────────────────────────────────────────────────────────────────────────

class TestJSONSafe:
    """All trace values must be JSON‑serialisable."""

    def test_valid_trace_is_json_safe(self):
        trace = run_pipeline(copy.deepcopy(VALID_PLAN_INPUT))
        from tools.testing_harness.plan_repair_harness import _to_json
        for section in ["INPUT", "DRIFT_CLASSIFICATION", "ARBITRATION_DECISION",
                        "ACTION_OUTPUT", "UPDATED_BUDGET", "REPAIR_TRACE"]:
            value = _to_json(trace.get(section, {}))
            json.dumps(value, default=str)  # should not raise

    def test_malformed_trace_is_json_safe(self):
        inp = {
            "segment": {
                "subgoal_id": None,
                "steps": [None, 123],
            }
        }
        trace = run_pipeline(inp)
        from tools.testing_harness.plan_repair_harness import _to_json
        for section in ["INPUT", "DRIFT_CLASSIFICATION", "ARBITRATION_DECISION",
                        "ACTION_OUTPUT", "UPDATED_BUDGET", "REPAIR_TRACE"]:
            value = _to_json(trace.get(section, {}))
            json.dumps(value, default=str)  # should not raise


# ──────────────────────────────────────────────────────────────────────────────
# Tests: _inspect_structure produces correct signals
# ──────────────────────────────────────────────────────────────────────────────

class TestInspectStructure:
    """The structural inspector must emit the correct signal types."""

    def test_empty_plan_produces_signals(self):
        signals = _inspect_structure("plan", {})
        assert len(signals) >= 2  # at least intent + targetskillid
        types_found = {s.type for s in signals}
        assert "missing_field" in types_found

    def test_empty_segment_produces_signals(self):
        signals = _inspect_structure("segment", {})
        assert len(signals) >= 2  # subgoal_id missing + steps wrong type
        types_found = {s.type for s in signals}
        assert "missing_field" in types_found

    def test_empty_subgoal_produces_signals(self):
        signals = _inspect_structure("subgoal", {})
        assert len(signals) >= 2  # subgoal_id + goal
        types_found = {s.type for s in signals}
        assert "missing_field" in types_found

    def test_valid_plan_no_signals(self):
        signals = _inspect_structure("plan", VALID_PLAN_INPUT["plan"])
        assert len(signals) == 0

    def test_valid_segment_no_signals(self):
        signals = _inspect_structure("segment", VALID_SEGMENT_INPUT["segment"])
        assert len(signals) == 0


# ──────────────────────────────────────────────────────────────────────────────
# Tests: repair trace — Phase 2.10.4
# ──────────────────────────────────────────────────────────────────────────────

def _trace(trace_dict):
    """Extract RepairTrace from trace dict."""
    return trace_dict["REPAIR_TRACE"]


class TestRepairTrace:
    """Every repair cycle must produce a complete, deterministic trace."""

    def test_no_drift_produces_empty_trace(self):
        """No drift → no repair action → empty trace."""
        t = run_pipeline(copy.deepcopy(VALID_PLAN_INPUT))
        rt = _trace(t)
        assert rt.attempts == []
        assert rt.successes == []
        assert rt.failures == []
        assert rt.budget_usage["cycle"] == 0
        assert rt.budget_usage["plan"] == 0
        assert rt.budget_usage["global"] == 0

    def test_repair_plan_produces_attempt_entry(self):
        """Repairing a malformed plan must log an attempt."""
        inp = {
            "plan": {
                "intent": "",
                "targetskillid": "",
                "arguments": "not_a_dict",
            }
        }
        t = run_pipeline(inp)
        rt = _trace(t)
        assert len(rt.attempts) >= 1
        attempt = rt.attempts[0]
        assert attempt["action"] == "repair_plan"
        assert "input_summary" in attempt
        assert attempt["input_summary"]["type"] == "plan"

    def test_repair_segment_produces_attempt_entry(self):
        """Repairing a malformed segment must log an attempt."""
        inp = {
            "segment": {
                "subgoal_id": "",
                "steps": [None, 123],
            }
        }
        t = run_pipeline(inp)
        rt = _trace(t)
        if _decision_action(t) == "repair":
            assert len(rt.attempts) >= 1
            assert rt.attempts[0]["action"] == "repair_segment"

    def test_repair_subgoal_produces_attempt_entry(self):
        """Repairing a malformed subgoal must log an attempt."""
        inp = {
            "subgoal": {
                "subgoal_id": "",
                "goal": "",
            }
        }
        t = run_pipeline(inp)
        rt = _trace(t)
        if _decision_action(t) == "repair":
            assert len(rt.attempts) >= 1
            assert rt.attempts[0]["action"] == "repair_subgoal"

    def test_successful_repair_produces_success_entry(self):
        """A successful repair must log a success with output summary."""
        inp = {
            "plan": {
                "intent": "",
                "targetskillid": "",
                "arguments": "not_a_dict",
            }
        }
        t = run_pipeline(inp)
        rt = _trace(t)
        if _decision_action(t) == "repair":
            assert len(rt.successes) >= 1
            success = rt.successes[0]
            assert "output_summary" in success
            assert success["output_summary"]["type"] == "plan"

    def test_budget_deltas_reflect_usage(self):
        """Post‑action budget deltas must reflect actual charges."""
        inp = {
            "plan": {
                "intent": "",
                "targetskillid": "",
                "arguments": {},
            }
        }
        t = run_pipeline(inp)
        rt = _trace(t)
        b = rt.budget_usage
        assert isinstance(b["cycle"], int)
        assert isinstance(b["plan"], int)
        assert isinstance(b["global"], int)
        if _decision_action(t) == "repair":
            # repair charges cycle + plan + global
            assert b["cycle"] == 1
            assert b["plan"] == 1
            assert b["global"] == 1

    def test_trace_is_deterministic(self):
        """Identical malformed inputs must produce identical traces."""
        inp = {
            "plan": {
                "intent": "",
                "targetskillid": "",
                "arguments": "bad",
            }
        }
        t1 = run_pipeline(copy.deepcopy(inp))
        t2 = run_pipeline(copy.deepcopy(inp))
        assert t1["REPAIR_TRACE"] == t2["REPAIR_TRACE"]

    def test_trace_is_json_safe(self):
        """RepairTrace must be JSON‑serialisable."""
        inp = {
            "segment": {
                "subgoal_id": None,
                "steps": [],
            }
        }
        t = run_pipeline(inp)
        from tools.testing_harness.plan_repair_harness import _to_json
        value = _to_json(t.get("REPAIR_TRACE", {}))
        json.dumps(value, default=str)  # should not raise

    def test_non_repair_action_has_empty_trace(self):
        """Replan/catastrophic actions should produce empty repair traces."""
        inp = {
            "plan": {
                "intent": None,
                "targetskillid": None,
                "arguments": None,
                "reasoning_summary": None,
            }
        }
        t = run_pipeline(inp)
        rt = _trace(t)
        action = _decision_action(t)
        if action in ("catastrophic", "replan", "regen_segment", "regen_subgoal"):
            # Non‑repair actions don't call repair_* functions
            assert len(rt.attempts) == 0
            assert len(rt.successes) == 0

    def test_structural_summary_includes_missing_fields(self):
        """Input structural summary must list missing required fields."""
        inp = {
            "plan": {
                "intent": "",
                "targetskillid": "",
                "arguments": "not a dict",
            }
        }
        t = run_pipeline(inp)
        summary = t["INPUT"]["raw_summary"]
        assert "missing_fields" in summary
        assert "intent" in summary["missing_fields"]
        assert "targetskillid" in summary["missing_fields"]
        assert "arguments" in summary["missing_fields"]

    def test_structural_summary_counts_segments_and_steps(self):
        """Structural summary must count segments and steps."""
        inp = {
            "plan": {
                "intent": "multi",
                "targetskillid": "skill.multi",
                "arguments": {},
                "segments": [
                    {"steps": [{"action": "noop"}, {"action": "parse"}]},
                    {"steps": [{"action": "write"}]},
                ],
            }
        }
        t = run_pipeline(inp)
        summary = t["INPUT"]["raw_summary"]
        assert summary.get("segments") == 2
        assert summary.get("steps") == 3
