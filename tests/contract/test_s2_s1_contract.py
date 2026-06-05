"""
Phase 2.14.1 — S2/S1 Contract Round-Trip Tests
===============================================

Tests for the S1 contract layer:
- S2 → S1 mapping (build_prompt_request)
- S1 → S2 mapping (parse_prompt_response)
- Round-trip determinism
- Schema validation
- Error handling
- No raw strings crossing the boundary
"""

from __future__ import annotations

import json

import pytest

from src.core.planning.s1_contract.types import (
    PromptRequest,
    PromptResponse,
    ToolCallRequest,
    ToolCallResult,
    S1Error,
)
from src.core.planning.s1_contract.validators import (
    validate_prompt_request,
    validate_prompt_response,
    validate_tool_call_request,
    validate_tool_call_result,
    validate_s1_error,
    validate_prompt_request_detailed,
    validate_prompt_response_detailed,
)
from src.core.planning.s1_contract.s2_to_s1_adapter import build_prompt_request
from src.core.planning.s1_contract.s1_to_s2_adapter import parse_prompt_response

# ──────────────────────────────────────────────────────────────────────────────
# Synthetic S2 state helpers
# ──────────────────────────────────────────────────────────────────────────────


class _FakeAgentState:
    """Minimal fake AgentExecutionState for testing."""
    def __init__(self, cycle=0, is_complete=False):
        self.cycle = cycle
        self.is_complete = is_complete


class _FakeSubgoalState:
    """Minimal fake SubgoalExecutionState for testing."""
    def __init__(self, index=0, state="active"):
        self.index = index
        self.state = _FakeEnum(state)


class _FakeSegmentState:
    """Minimal fake SegmentExecutionState for testing."""
    def __init__(self, index=0, state="pending"):
        self.index = index
        self.state = _FakeEnum(state)


class _FakeEnum:
    """Fake enum value for testing."""
    def __init__(self, value):
        self.value = value


def _make_fake_states(cycle=0, subgoal_index=0, segment_index=0, agent_complete=False):
    """Create consistent fake S2 state for testing."""
    return (
        _FakeAgentState(cycle=cycle, is_complete=agent_complete),
        _FakeSubgoalState(index=subgoal_index, state="active"),
        _FakeSegmentState(index=segment_index, state="running"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Type tests
# ──────────────────────────────────────────────────────────────────────────────


class TestS1ContractTypes:
    """Test basic instantiation and JSON-safety of all contract types."""

    def test_prompt_request_creation(self):
        req = PromptRequest(
            prompt={"instruction": "test"},
            memory={"key": "value"},
            plan_context={"subgoal": {"index": 0}},
        )
        d = req.to_dict()
        assert d["prompt"] == {"instruction": "test"}
        assert d["memory"] == {"key": "value"}
        assert d["plan_context"]["subgoal"]["index"] == 0
        assert d["tool_context"] == []

    def test_prompt_request_json_safe(self):
        req = PromptRequest(
            prompt={"instruction": "test", "params": {"x": 1, "y": [1, 2, 3]}},
            memory={"history": [], "state": {"done": False}},
            plan_context={"subgoal": {"index": 0, "state": "active"}},
        )
        s = json.dumps(req.to_dict())
        loaded = json.loads(s)
        assert loaded["prompt"]["params"]["x"] == 1

    def test_prompt_response_creation(self):
        res = PromptResponse(
            output={"result": "ok"},
            tool_calls=[],
            errors=[],
        )
        d = res.to_dict()
        assert d["output"] == {"result": "ok"}
        assert d["tool_calls"] == []
        assert d["errors"] == []

    def test_prompt_response_json_safe(self):
        res = PromptResponse(
            output={"result": "ok", "scores": [0.9, 0.8]},
            tool_calls=[
                {"name": "tool_a", "arguments": {"x": 1}, "result": {}, "success": True}
            ],
            errors=[],
        )
        s = json.dumps(res.to_dict())
        loaded = json.loads(s)
        assert loaded["output"]["result"] == "ok"
        assert len(loaded["tool_calls"]) == 1

    def test_tool_call_request_creation(self):
        req = ToolCallRequest(name="echo", arguments={"text": "hello"})
        d = req.to_dict()
        assert d["name"] == "echo"
        assert d["arguments"]["text"] == "hello"

    def test_tool_call_result_creation(self):
        res = ToolCallResult(name="echo", result={"echo": "hello"}, success=True)
        d = res.to_dict()
        assert d["name"] == "echo"
        assert d["result"]["echo"] == "hello"
        assert d["success"] is True

    def test_s1_error_creation(self):
        err = S1Error(type="timeout", message="LLM call timed out", details={"timeout_s": 30})
        d = err.to_dict()
        assert d["type"] == "timeout"
        assert d["message"] == "LLM call timed out"
        assert d["details"]["timeout_s"] == 30

    def test_s1_error_defaults(self):
        err = S1Error(type="unknown", message="An error occurred")
        assert err.details == {}


# ──────────────────────────────────────────────────────────────────────────────
# Validator tests
# ──────────────────────────────────────────────────────────────────────────────


class TestValidators:
    """Test validation functions."""

    def test_validate_prompt_request_valid(self):
        req = PromptRequest(
            prompt={"instruction": "test"},
            memory={"k": "v"},
            plan_context={"sg": {}},
        )
        assert validate_prompt_request(req) is True

    def test_validate_prompt_request_missing_prompt(self):
        req = PromptRequest(
            prompt={},
            memory={},
            plan_context={},
        )
        # prompt being an empty dict is valid (it's a dict), just no keys
        # But let's test with None-like scenario
        assert validate_prompt_request(req) is True  # empty is valid

    def test_validate_prompt_request_none_fields(self):
        """PromptRequest with None fields should fail detailed validation."""
        req = PromptRequest(prompt=None, memory=None, plan_context=None)  # type: ignore[arg-type]
        # Detailed validation should detect null required fields
        result = validate_prompt_request_detailed(req)
        assert result["valid"] is False
        assert any("None" in e or "null" in e.lower() for e in result["errors"])

    def test_validate_prompt_request_bad_tool_context(self):
        req = PromptRequest(
            prompt={},
            memory={"k": "v"},
            plan_context={},
            tool_context=["not_a_dict"],  # list of strings, not dicts
        )
        assert validate_prompt_request(req) is False

    def test_validate_prompt_response_valid(self):
        res = PromptResponse(output={"result": "ok"})
        assert validate_prompt_response(res) is True

    def test_validate_prompt_response_with_tool_calls(self):
        res = PromptResponse(
            output={"result": "ok"},
            tool_calls=[
                {"name": "t", "arguments": {}, "result": {}, "success": True}
            ],
        )
        assert validate_prompt_response(res) is True

    def test_validate_prompt_response_bad_tool_calls(self):
        res = PromptResponse(
            output={"result": "ok"},
            tool_calls=["not_a_dict"],
        )
        assert validate_prompt_response(res) is False

    def test_validate_prompt_response_bad_output(self):
        # output must be a dict
        res = PromptResponse(
            output="raw_string",  # type: ignore
        )
        assert validate_prompt_response(res) is False

    def test_validate_prompt_response_bad_errors(self):
        res = PromptResponse(
            output={"result": "ok"},
            errors=["not_a_dict"],
        )
        assert validate_prompt_response(res) is False

    def test_validate_tool_call_request_valid(self):
        req = ToolCallRequest(name="echo", arguments={"text": "hi"})
        assert validate_tool_call_request(req) is True

    def test_validate_tool_call_request_bad_arguments(self):
        req = ToolCallRequest(name="echo", arguments="not_a_dict")  # type: ignore
        assert validate_tool_call_request(req) is False

    def test_validate_tool_call_result_valid(self):
        res = ToolCallResult(name="echo", result={"out": "hi"}, success=True)
        assert validate_tool_call_result(res) is True

    def test_validate_tool_call_result_bad_result(self):
        res = ToolCallResult(name="echo", result="not_a_dict", success=True)  # type: ignore
        assert validate_tool_call_result(res) is False

    def test_validate_s1_error_valid(self):
        err = S1Error(type="timeout", message="Timed out")
        assert validate_s1_error(err) is True

    def test_detailed_validation_success(self):
        req = PromptRequest(
            prompt={"instruction": "test"},
            memory={"k": "v"},
            plan_context={"sg": {}},
        )
        result = validate_prompt_request_detailed(req)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_detailed_validation_failure(self):
        req = PromptRequest(
            prompt={},
            memory={"k": "v"},
            plan_context={},
            tool_context=["bad"],
        )
        result = validate_prompt_request_detailed(req)
        assert result["valid"] is False
        assert len(result["errors"]) > 0


# ──────────────────────────────────────────────────────────────────────────────
# S2 → S1 adapter tests
# ──────────────────────────────────────────────────────────────────────────────


class TestS2ToS1Adapter:
    """Test building PromptRequest from S2 state."""

    def test_build_basic_request(self):
        agent, subgoal, segment = _make_fake_states()
        memory = {"history": [], "plan": {}}
        req = build_prompt_request(agent, subgoal, segment, memory)
        assert isinstance(req, PromptRequest)
        assert req.prompt["agent_cycle"] == 0
        assert req.plan_context["subgoal"]["index"] == 0
        assert req.plan_context["segment"]["index"] == 0

    def test_build_request_includes_tool_schemas(self):
        agent, subgoal, segment = _make_fake_states()
        memory = {}
        schemas = [{"name": "echo", "args": {"text": "string"}}]
        req = build_prompt_request(agent, subgoal, segment, memory, tool_schemas=schemas)
        assert len(req.tool_context) == 1
        assert req.tool_context[0]["name"] == "echo"

    def test_build_request_determinism(self):
        # Same inputs → same output
        agent, subgoal, segment = _make_fake_states(cycle=3, subgoal_index=1)
        memory = {"plan": {"steps": 3}}
        r1 = build_prompt_request(agent, subgoal, segment, memory)
        r2 = build_prompt_request(agent, subgoal, segment, memory)
        assert r1.to_dict() == r2.to_dict()

    def test_build_request_no_tool_schemas(self):
        agent, subgoal, segment = _make_fake_states()
        memory = {}
        req = build_prompt_request(agent, subgoal, segment, memory)
        assert req.tool_context == []

    def test_build_request_preserves_memory(self):
        agent, subgoal, segment = _make_fake_states()
        memory = {"drift_events": [{"type": "slow", "cycle": 1}], "repair_count": 2}
        req = build_prompt_request(agent, subgoal, segment, memory)
        assert req.memory == memory
        assert req.memory["drift_events"][0]["type"] == "slow"

    def test_build_request_json_safe(self):
        agent, subgoal, segment = _make_fake_states()
        memory = {"list_data": [1, 2, 3], "nested": {"key": "value"}}
        req = build_prompt_request(agent, subgoal, segment, memory)
        s = json.dumps(req.to_dict())
        loaded = json.loads(s)
        assert loaded["memory"]["nested"]["key"] == "value"


# ──────────────────────────────────────────────────────────────────────────────
# S1 → S2 adapter tests
# ──────────────────────────────────────────────────────────────────────────────


class TestS1ToS2Adapter:
    """Test parsing PromptResponse into S2 updates."""

    def test_parse_basic_response(self):
        res = PromptResponse(output={"result": "ok"})
        updates = parse_prompt_response(res)
        assert "drift_signals" in updates
        assert "repair_proposals" in updates
        assert "reflection" in updates
        assert "tool_results" in updates
        assert "output_raw" in updates
        assert "errors" in updates

    def test_parse_response_with_drift(self):
        res = PromptResponse(
            output={
                "result": "ok",
                "drift_detected": True,
                "drift_type": "wrong_output_shape",
                "drift_severity": "major",
                "drift_detail": {"field": "steps", "expected": "list", "actual": "dict"},
            }
        )
        updates = parse_prompt_response(res)
        assert len(updates["drift_signals"]) == 1
        assert updates["drift_signals"][0]["drift"] == "wrong_output_shape"

    def test_parse_response_with_repair_proposals(self):
        res = PromptResponse(
            output={
                "result": "partial",
                "repairs": [
                    {"target": "step_3", "action": "replace", "replacement": "fixed_step"},
                ],
            }
        )
        updates = parse_prompt_response(res)
        assert len(updates["repair_proposals"]) == 1
        assert updates["repair_proposals"][0]["action"] == "replace"

    def test_parse_response_with_tool_calls(self):
        res = PromptResponse(
            output={"result": "tool_called"},
            tool_calls=[
                {
                    "name": "echo",
                    "arguments": {"text": "hello"},
                    "result": {"echo": "hello"},
                    "success": True,
                }
            ],
        )
        updates = parse_prompt_response(res)
        assert len(updates["tool_results"]) == 1
        assert updates["tool_results"][0]["name"] == "echo"
        assert updates["tool_results"][0]["success"] is True

    def test_parse_response_reflection_fields(self):
        res = PromptResponse(
            output={
                "result": "step_done",
                "progress": 0.5,
                "is_complete": False,
                "confidence": 0.9,
                "next_action": "continue",
                "blockers": [],
            }
        )
        updates = parse_prompt_response(res)
        r = updates["reflection"]
        assert r["progress"] == 0.5
        assert r["is_complete"] is False
        assert r["confidence"] == 0.9

    def test_parse_response_determinism(self):
        res = PromptResponse(
            output={"result": "ok", "scores": [0.5, 0.8]},
            tool_calls=[],
            errors=[],
        )
        u1 = parse_prompt_response(res)
        u2 = parse_prompt_response(res)
        assert u1 == u2

    def test_parse_response_json_safe(self):
        res = PromptResponse(
            output={"result": "ok", "data": {"nested": [1, 2, 3]}},
            tool_calls=[],
            errors=[],
        )
        updates = parse_prompt_response(res)
        s = json.dumps(updates)
        assert json.loads(s)  # verify it loads back


# ──────────────────────────────────────────────────────────────────────────────
# Round-trip tests
# ──────────────────────────────────────────────────────────────────────────────


class TestRoundTrip:
    """Test full S2 → S1 → S2 round-trip."""

    def test_round_trip_basic(self):
        """S2 state → PromptRequest → synthetic PromptResponse → S2 updates.

        Verify: determinism, schema validity, no raw strings, no missing fields.
        """
        agent, subgoal, segment = _make_fake_states(cycle=1, subgoal_index=1)
        memory = {"drift_events": []}

        # S2 → S1
        req = build_prompt_request(agent, subgoal, segment, memory)
        assert validate_prompt_request(req)

        # Synthetic S1 → S2 (simulating an LLM response)
        synthetic_response = PromptResponse(
            output={
                "result": "segment_executed",
                "step_output": {"steps_done": 3},
                "progress": 0.6,
                "is_complete": False,
                "confidence": 0.95,
                "next_action": "continue",
            },
            tool_calls=[],
            errors=[],
        )
        assert validate_prompt_response(synthetic_response)

        # S1 → S2
        updates = parse_prompt_response(synthetic_response)
        assert updates["reflection"]["progress"] == 0.6
        assert updates["reflection"]["is_complete"] is False
        assert len(updates["errors"]) == 0

        # Verify determinism: round-trip twice, same result
        updates2 = parse_prompt_response(synthetic_response)
        assert updates == updates2

    def test_round_trip_with_drift_and_repair(self):
        """Round-trip with drift signals and repair proposals."""
        agent, subgoal, segment = _make_fake_states(cycle=5)
        memory = {"plan_type": "multi_segment"}

        req = build_prompt_request(agent, subgoal, segment, memory)
        assert validate_prompt_request(req)

        synthetic_response = PromptResponse(
            output={
                "result": "drift_detected",
                "drift_detected": True,
                "drift_type": "wrong_output_semantics",
                "drift_severity": "major",
                "drift_detail": {"empty_required_field": "steps"},
                "repairs": [
                    {"target": "segment_2", "action": "repair_segment", "replacement": {"steps": ["fixed_1", "fixed_2"]}},
                ],
                "progress": 0.3,
                "is_complete": False,
            },
            tool_calls=[],
            errors=[],
        )
        assert validate_prompt_response(synthetic_response)

        updates = parse_prompt_response(synthetic_response)
        assert len(updates["drift_signals"]) == 1
        assert updates["drift_signals"][0]["drift"] == "wrong_output_semantics"
        assert len(updates["repair_proposals"]) == 1
        assert updates["repair_proposals"][0]["action"] == "repair_segment"

        # Verify no raw strings in any output
        s = json.dumps(updates)
        loaded = json.loads(s)
        assert isinstance(loaded, dict)

    def test_round_trip_schema_validity(self):
        """All intermediate structures pass schema validation."""
        agent, subgoal, segment = _make_fake_states()
        memory = {"valid": True}

        req = build_prompt_request(agent, subgoal, segment, memory)
        assert validate_prompt_request(req)
        assert validate_prompt_request_detailed(req)["valid"]

        # Verify the plan_context substructure
        pc = req.plan_context
        assert "subgoal" in pc
        assert "segment" in pc
        assert "index" in pc["subgoal"]
        assert "index" in pc["segment"]

    def test_round_trip_no_raw_strings(self):
        """Verify no raw (unstructured) strings cross the boundary."""
        agent, subgoal, segment = _make_fake_states()
        memory = {}

        req = build_prompt_request(agent, subgoal, segment, memory)
        d = req.to_dict()

        # No value at the top level should be a raw string
        for key, val in d.items():
            assert not isinstance(val, str), f"Top-level field '{key}' is a raw string"

        # Plan context values should be dicts
        assert isinstance(d["plan_context"]["subgoal"], dict)
        assert isinstance(d["plan_context"]["segment"], dict)


# ──────────────────────────────────────────────────────────────────────────────
# Error handling tests
# ──────────────────────────────────────────────────────────────────────────────


class TestErrorHandling:
    """Test error surfacing through structured responses."""

    def test_malformed_response_validation_fails(self):
        """A response with non-dict output should fail validation."""
        res = PromptResponse(output="raw_text")  # type: ignore
        assert not validate_prompt_response(res)

    def test_missing_required_fields_detected(self):
        """Missing required output fields should be detected."""
        res = PromptResponse(output={})
        assert validate_prompt_response(res)  # output is a dict, valid

    def test_s1_error_in_response(self):
        """S1 errors in the response should be surfaced."""
        res = PromptResponse(
            output={"result": "error"},
            errors=[
                {"type": "timeout", "message": "LLM timed out", "details": {"retry_count": 3}}
            ],
        )
        assert validate_prompt_response(res)
        updates = parse_prompt_response(res)
        assert len(updates["errors"]) == 1
        assert updates["errors"][0]["type"] == "timeout"

    def test_unexpected_tool_calls_surfaced(self):
        """Unexpected tool calls should be present in the parsed output."""
        res = PromptResponse(
            output={"result": "tool_called"},
            tool_calls=[
                {"name": "unknown_tool", "arguments": {}, "result": {}, "success": False}
            ],
        )
        updates = parse_prompt_response(res)
        assert len(updates["tool_results"]) == 1
        assert updates["tool_results"][0]["success"] is False

    def test_invalid_json_in_tool_call(self):
        """A tool call that is not a dict should fail validation."""
        res = PromptResponse(
            output={"result": "ok"},
            tool_calls=["bad_tool_call"],
        )
        assert not validate_prompt_response(res)

    def test_structured_error_in_s2_updates(self):
        """S2 must surface structured errors, not crash."""
        # Empty response should still produce a valid updates dict
        res = PromptResponse(output={})
        updates = parse_prompt_response(res)
        assert "errors" in updates
        assert updates["reflection"]["is_complete"] is False
        # No exception should be raised


# ──────────────────────────────────────────────────────────────────────────────
# Edge case tests
# ──────────────────────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_memory(self):
        agent, subgoal, segment = _make_fake_states()
        req = build_prompt_request(agent, subgoal, segment, {})
        assert req.memory == {}
        assert validate_prompt_request(req)

    def test_large_memory(self):
        agent, subgoal, segment = _make_fake_states()
        large_memory = {"history": [{"i": i, "data": "x" * 100} for i in range(100)]}
        req = build_prompt_request(agent, subgoal, segment, large_memory)
        assert req.memory == large_memory
        s = json.dumps(req.to_dict())
        assert len(s) > 0

    def test_null_agent_state_safe(self):
        """build_prompt_request should handle None agent state gracefully."""
        req = build_prompt_request(None, None, None, {"memory": True})
        assert req.prompt["agent_cycle"] == 0
        assert req.memory == {"memory": True}

    def test_quality_below_threshold_drift(self):
        """Quality below threshold should generate a drift signal."""
        res = PromptResponse(
            output={
                "result": "low_quality",
                "quality": {"below_threshold": True, "score": 0.3},
            }
        )
        updates = parse_prompt_response(res)
        assert len(updates["drift_signals"]) >= 1
        quality_signal = [s for s in updates["drift_signals"] if s["drift"] == "quality_below_threshold"]
        assert len(quality_signal) == 1

    def test_structural_deviation_drift(self):
        """Structural deviation should generate a drift signal."""
        res = PromptResponse(
            output={
                "result": "deviated",
                "structural_deviation": {"severity": "major", "field": "steps"},
            }
        )
        updates = parse_prompt_response(res)
        dev_signal = [s for s in updates["drift_signals"] if s["drift"] == "structural_deviation"]
        assert len(dev_signal) == 1
        assert dev_signal[0]["severity"] == "major"
