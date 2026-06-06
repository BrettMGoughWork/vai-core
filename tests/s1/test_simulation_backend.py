"""
Phase 2.14.3 — Simulation Backend Tests
========================================

Tests for:
- Deterministic drift detection
- Deterministic repair proposals
- Deterministic reflection summaries
- Deterministic plan shaping
- Backend routing (simulation vs real_llm)
- Schema correctness of all outputs
- No raw strings, no randomness, no I/O
"""

from __future__ import annotations

import json

import pytest

from src.core.planning.s1_contract.types import PromptRequest, PromptResponse, S1Error
from src.core.planning.s1_contract.s1_simulation_backend import (
    simulate_prompt_response,
    _detect_missing_fields,
    _detect_malformed_shapes,
    _generate_repair_proposals,
    _compute_reflection,
    _compute_plan_shaping,
)
from src.core.planning.s1_contract.s1_client import call_s1_backend
from src.core.planning.s1_contract.validators import (
    validate_prompt_response,
    validate_prompt_response_detailed,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _make_valid_request(**overrides) -> PromptRequest:
    """Create a minimally valid PromptRequest for testing.

    Any override kwarg replaces the corresponding field.
    """
    defaults = {
        "prompt": {"instruction": "Execute the current subgoal and segment."},
        "memory": {"cycle": 0},
        "plan_context": {
            "subgoal": {"index": 0, "state": "pending"},
            "segment": {"index": 0, "state": "pending"},
        },
        "tool_context": [],
    }
    merged = {**defaults, **overrides}
    return PromptRequest(**merged)


def _is_json_safe(obj) -> bool:
    """Return True if obj can be round-tripped through json.dumps."""
    try:
        json.dumps(obj)
        return True
    except (TypeError, ValueError):
        return False


# ──────────────────────────────────────────────────────────────────────────────
# 1. Deterministic drift detection
# ──────────────────────────────────────────────────────────────────────────────


class TestDeterministicDrift:
    """Same PromptRequest → same drift signals every time. No randomness."""

    def test_clean_request_no_drift(self):
        """A fully valid request produces no drift signals."""
        req = _make_valid_request()
        resp = simulate_prompt_response(req)
        assert resp.output["drift_detected"] is False
        assert resp.output["drift_detail"] == []

    def test_same_input_same_drift_10_runs(self):
        """Running the same request 10 times produces identical drift."""
        req = _make_valid_request(
            plan_context={"subgoal": None, "segment": None}  # triggers drift
        )
        results = [simulate_prompt_response(req) for _ in range(10)]
        for r in results[1:]:
            assert r.output == results[0].output
            assert r.to_dict() == results[0].to_dict()

    def test_deterministic_drift_type(self):
        """Missing prompt always produces 'missing_prompt' drift type."""
        req = _make_valid_request(prompt={})
        resp = simulate_prompt_response(req)
        assert resp.output["drift_detected"] is True
        types = [s["drift_type"] for s in resp.output["drift_detail"]]
        assert "missing_prompt" in types

    def test_missing_memory_not_a_dict(self):
        """Non-dict memory produces 'missing_memory' drift."""
        req = _make_valid_request(memory=None)
        resp = simulate_prompt_response(req)
        types = [s["drift_type"] for s in resp.output["drift_detail"]]
        assert "missing_memory" in types

    def test_missing_subgoal_index(self):
        """Null subgoal index produces drift."""
        req = _make_valid_request()
        req.plan_context["subgoal"]["index"] = None
        resp = simulate_prompt_response(req)
        types = [s["drift_type"] for s in resp.output["drift_detail"]]
        assert "missing_subgoal_index" in types

    def test_missing_segment_state(self):
        """Null segment state produces drift."""
        req = _make_valid_request()
        req.plan_context["segment"]["state"] = None
        resp = simulate_prompt_response(req)
        types = [s["drift_type"] for s in resp.output["drift_detail"]]
        assert "missing_segment_state" in types

    def test_invalid_subgoal_state(self):
        """An unrecognised lifecycle state produces 'invalid_state' drift."""
        req = _make_valid_request()
        req.plan_context["subgoal"]["state"] = "flying"
        resp = simulate_prompt_response(req)
        types = [s["drift_type"] for s in resp.output["drift_detail"]]
        assert "invalid_state" in types

    def test_non_integer_index(self):
        """A float index that is not a whole number produces drift."""
        req = _make_valid_request()
        req.plan_context["subgoal"]["index"] = 1.5
        resp = simulate_prompt_response(req)
        types = [s["drift_type"] for s in resp.output["drift_detail"]]
        assert "non_integer_index" in types


# ──────────────────────────────────────────────────────────────────────────────
# 2. Deterministic repair proposals
# ──────────────────────────────────────────────────────────────────────────────


class TestDeterministicRepair:
    """Repair proposals are deterministic and match drift signals."""

    def test_missing_prompt_repaired(self):
        """Missing prompt → fill_default repair."""
        req = _make_valid_request(prompt={})
        resp = simulate_prompt_response(req)
        repairs = resp.output["repairs"]
        assert any(r["target"] == "prompt" and r["action"] == "fill_default" for r in repairs)

    def test_missing_plan_context_repaired(self):
        """Missing plan_context → fill_default repair."""
        req = _make_valid_request(plan_context=None)
        resp = simulate_prompt_response(req)
        repairs = resp.output["repairs"]
        assert any(r["target"] == "plan_context" for r in repairs)

    def test_invalid_state_normalized(self):
        """Invalid state → normalize repair to 'pending'."""
        req = _make_valid_request()
        req.plan_context["segment"]["state"] = "flying"
        resp = simulate_prompt_response(req)
        repairs = resp.output["repairs"]
        matching = [r for r in repairs if r["action"] == "normalize" and r["replacement"] == "pending"]
        assert len(matching) >= 1

    def test_no_drift_no_repairs(self):
        """Clean request → empty repairs list."""
        req = _make_valid_request()
        resp = simulate_prompt_response(req)
        assert resp.output["repairs"] == []

    def test_repairs_are_deterministic(self):
        """Same input produces identical repairs every time."""
        req = _make_valid_request(plan_context={})
        results = [simulate_prompt_response(req) for _ in range(5)]
        for r in results[1:]:
            assert r.output["repairs"] == results[0].output["repairs"]


# ──────────────────────────────────────────────────────────────────────────────
# 3. Deterministic reflection summaries
# ──────────────────────────────────────────────────────────────────────────────


class TestDeterministicReflection:
    """Reflection summaries are deterministic and based on plan_context."""

    def test_pending_segment_progress_zero(self):
        """Pending segment → progress 0.0, not complete."""
        req = _make_valid_request()
        req.plan_context["segment"]["state"] = "pending"
        resp = simulate_prompt_response(req)
        assert resp.output["progress"] == 0.0
        assert resp.output["is_complete"] is False

    def test_running_segment_progress_half(self):
        """Running segment → progress 0.5."""
        req = _make_valid_request()
        req.plan_context["segment"]["state"] = "running"
        resp = simulate_prompt_response(req)
        assert resp.output["progress"] == 0.5

    def test_completed_segment_is_complete(self):
        """Completed segment → progress 1.0, is_complete True."""
        req = _make_valid_request()
        req.plan_context["segment"]["state"] = "completed"
        resp = simulate_prompt_response(req)
        assert resp.output["progress"] == 1.0
        assert resp.output["is_complete"] is True

    def test_failed_segment_progress_zero(self):
        """Failed segment → progress 0.0."""
        req = _make_valid_request()
        req.plan_context["segment"]["state"] = "failed"
        resp = simulate_prompt_response(req)
        assert resp.output["progress"] == 0.0

    def test_drift_lowers_confidence(self):
        """When drift is present, confidence is 0.85 instead of 0.95."""
        clean = _make_valid_request()
        clean_resp = simulate_prompt_response(clean)
        assert clean_resp.output["confidence"] == 0.95

        drift_req = _make_valid_request(prompt={})
        drift_resp = simulate_prompt_response(drift_req)
        assert drift_resp.output["confidence"] == 0.85

    def test_next_action_for_repair_state(self):
        """Needs_repair → next_action is 'repair'."""
        req = _make_valid_request()
        req.plan_context["segment"]["state"] = "needs_repair"
        resp = simulate_prompt_response(req)
        assert resp.output["next_action"] == "repair"


# ──────────────────────────────────────────────────────────────────────────────
# 4. Deterministic plan shaping
# ──────────────────────────────────────────────────────────────────────────────


class TestDeterministicPlanShaping:
    """Plan shaping is always empty in simulation mode."""

    def test_shaping_is_empty(self):
        """Simulation backend produces empty plan shaping."""
        req = _make_valid_request()
        resp = simulate_prompt_response(req)
        assert resp.output["shaped"] == True
        assert resp.output["steps"] == []
        assert resp.output["segments"] == []

    def test_shaping_deterministic(self):
        """Plan shaping is identical across runs."""
        req = _make_valid_request()
        results = [simulate_prompt_response(req) for _ in range(5)]
        for r in results[1:]:
            assert r.output["shaped"] == results[0].output["shaped"]
            assert r.output["steps"] == results[0].output["steps"]


# ──────────────────────────────────────────────────────────────────────────────
# 5. Backend routing
# ──────────────────────────────────────────────────────────────────────────────


class TestBackendRouting:
    """Backend selection routes to the correct implementation."""

    def test_simulation_backend(self):
        """backend='simulation' → simulation backend."""
        req = _make_valid_request()
        resp = call_s1_backend(req, backend="simulation")
        assert isinstance(resp, PromptResponse)
        assert "drift_detected" in resp.output

    def test_real_llm_stubbed(self):
        """backend='real_llm' → S1Error from kill-switch (real LLM disabled by default)."""
        req = _make_valid_request()
        resp = call_s1_backend(req, backend="real_llm")
        # Kill-switch is active → returns structured S1Error, not a live call
        assert isinstance(resp, S1Error)
        assert resp.type == "real_llm_disabled"
        assert "Kill-switch" in resp.message

    def test_real_llm_deterministic(self):
        """The real_llm stub is also deterministic."""
        req = _make_valid_request()
        r1 = call_s1_backend(req, backend="real_llm")
        r2 = call_s1_backend(req, backend="real_llm")
        assert r1.to_dict() == r2.to_dict()

    def test_unknown_backend_raises(self):
        """Unknown backend raises ValueError."""
        req = _make_valid_request()
        with pytest.raises(ValueError, match="Unknown backend"):
            call_s1_backend(req, backend="gpt5")

    def test_default_backend_is_simulation(self):
        """Default backend (no arg) is 'simulation'."""
        req = _make_valid_request()
        resp = call_s1_backend(req)
        assert isinstance(resp, PromptResponse)

    def test_simulation_different_from_real_llm(self):
        """Simulation and real_llm produce different responses."""
        req = _make_valid_request()
        sim = call_s1_backend(req, backend="simulation")
        real = call_s1_backend(req, backend="real_llm")
        # They should not be identical — simulation has progress info, stub doesn't
        assert sim.to_dict() != real.to_dict()


# ──────────────────────────────────────────────────────────────────────────────
# 6. Schema correctness
# ──────────────────────────────────────────────────────────────────────────────


class TestSchemaCorrectness:
    """All PromptResponse outputs are schema-valid."""

    def test_clean_response_valid(self):
        """Clean response passes validation."""
        req = _make_valid_request()
        resp = simulate_prompt_response(req)
        assert validate_prompt_response(resp) is True

    def test_drift_response_valid(self):
        """Response with drift passes validation."""
        req = _make_valid_request(prompt={})
        resp = simulate_prompt_response(req)
        assert validate_prompt_response(resp) is True

    def test_no_raw_strings_in_output(self):
        """All values in .output dict are JSON-safe primitives."""
        req = _make_valid_request()
        resp = simulate_prompt_response(req)
        output = resp.output
        assert _is_json_safe(output), f"Output is not JSON-safe: {type(output)}"

    def test_no_missing_required_fields(self):
        """All required PromptResponse fields are present."""
        req = _make_valid_request()
        resp = simulate_prompt_response(req)
        assert resp.output is not None
        assert isinstance(resp.tool_calls, list)
        assert isinstance(resp.errors, list)

    def test_no_nulls_in_required_fields(self):
        """Required fields are not null."""
        req = _make_valid_request()
        resp = simulate_prompt_response(req)
        assert resp.output is not None
        assert resp.tool_calls is not None
        assert resp.errors is not None

    def test_detailed_validation_passes(self):
        """Detailed validation returns no issues for clean response."""
        req = _make_valid_request()
        resp = simulate_prompt_response(req)
        issues = validate_prompt_response_detailed(resp)
        assert issues["valid"] is True, f"Unexpected issues: {issues}"
        assert len(issues["errors"]) == 0, f"Validation errors: {issues['errors']}"

    def test_drift_response_detailed_validation(self):
        """Even with drift, the response schema is valid."""
        req = _make_valid_request(prompt={}, plan_context=None)
        resp = simulate_prompt_response(req)
        issues = validate_prompt_response_detailed(resp)
        assert issues["valid"] is True, f"Schema issues despite drift: {issues}"
        assert len(issues["errors"]) == 0, f"Validation errors: {issues['errors']}"

    def test_output_is_json_serializable(self):
        """The entire output dict serializes to JSON without error."""
        req = _make_valid_request()
        resp = simulate_prompt_response(req)
        # full response to_dict
        d = resp.to_dict()
        s = json.dumps(d)
        assert isinstance(s, str)
        assert len(s) > 0


# ──────────────────────────────────────────────────────────────────────────────
# 7. Pure function property tests
# ──────────────────────────────────────────────────────────────────────────────


class TestPureFunctionProperties:
    """Simulation backend functions are pure (no side effects, no I/O)."""

    def test_input_not_mutated(self):
        """simulate_prompt_response does not mutate the input."""
        req = _make_valid_request()
        req_copy = _make_valid_request()
        simulate_prompt_response(req)
        assert req.to_dict() == req_copy.to_dict()

    def test_helper_detect_missing_pure(self):
        """_detect_missing_fields is pure."""
        req = _make_valid_request()
        before = req.to_dict()
        _detect_missing_fields(req)
        assert req.to_dict() == before

    def test_helper_generate_repairs_pure(self):
        """_generate_repair_proposals is pure."""
        req = _make_valid_request()
        signals = _detect_missing_fields(req)
        before = req.to_dict()
        _generate_repair_proposals(req, signals)
        assert req.to_dict() == before

    def test_call_s1_backend_does_not_mutate(self):
        """call_s1_backend does not mutate the request."""
        req = _make_valid_request()
        before = req.to_dict()
        call_s1_backend(req, backend="simulation")
        assert req.to_dict() == before


# ──────────────────────────────────────────────────────────────────────────────
# 8. Edge case tests
# ──────────────────────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Boundary and edge-case behaviour."""

    def test_empty_prompt(self):
        """Empty prompt dict produces drift."""
        req = _make_valid_request(prompt={})
        resp = simulate_prompt_response(req)
        assert resp.output["drift_detected"] is True

    def test_empty_memory_ok(self):
        """Empty memory dict is valid (not missing)."""
        req = _make_valid_request(memory={})
        resp = simulate_prompt_response(req)
        assert resp.output["drift_detected"] is False

    def test_index_zero_is_valid(self):
        """Index 0 is valid (falsy but not None)."""
        req = _make_valid_request()
        req.plan_context["subgoal"]["index"] = 0
        resp = simulate_prompt_response(req)
        types = [s["drift_type"] for s in resp.output["drift_detail"]]
        assert "missing_subgoal_index" not in types

    def test_index_negative_one_is_valid(self):
        """Index -1 is valid (used as 'no current' sentinel)."""
        req = _make_valid_request()
        req.plan_context["subgoal"]["index"] = -1
        resp = simulate_prompt_response(req)
        types = [s["drift_type"] for s in resp.output["drift_detail"]]
        assert "missing_subgoal_index" not in types

    def test_all_catastrophic(self):
        """Multiple severe issues → all drift signals present."""
        req = _make_valid_request(prompt={}, plan_context=None, memory=None)
        resp = simulate_prompt_response(req)
        assert resp.output["drift_detected"] is True
        assert len(resp.output["drift_detail"]) >= 3
        assert len(resp.output["repairs"]) >= 3

    def test_tool_calls_always_empty(self):
        """Simulation backend never requests tool calls."""
        req = _make_valid_request()
        resp = simulate_prompt_response(req)
        assert resp.tool_calls == []

    def test_errors_always_empty(self):
        """Simulation backend never emits errors."""
        req = _make_valid_request()
        resp = simulate_prompt_response(req)
        assert resp.errors == []
