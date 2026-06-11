"""Phase 2.14.2 — S1 Adapter Layer Tests.

Tests for:
- S2→S1 adapter validation (validate_s2_to_s1, validate_s2_to_s1_detailed)
- S1→S2 adapter validation (validate_s1_to_s2, validate_s1_to_s2_detailed)
- S2→S1 adapter: build PromptRequest from synthetic S2 state
- S1→S2 adapter: parse PromptResponse into S2 updates
- Round-trip: S2 state → PromptRequest → PromptResponse → S2 updates
- Error handling: malformed PromptResponse, missing fields, unexpected tool calls
"""

import pytest
from src.strategy.planning.s1_contract import (
    PromptRequest,
    PromptResponse,
    ToolCallRequest,
    ToolCallResult,
    S1Error,
    build_prompt_request,
    parse_prompt_response,
    validate_s2_to_s1,
    validate_s2_to_s1_detailed,
    validate_s1_to_s2,
    validate_s1_to_s2_detailed,
)


# ── Fake S2 state objects (avoid importing full S2 modules) ──

class _FakeAgentState:
    def __init__(self, cycle=0, is_complete=False):
        self.cycle = cycle
        self.is_complete = is_complete


class _FakeSubgoalState:
    def __init__(self, index=0, state="pending"):
        self.index = index
        self.state = state


class _FakeSegmentState:
    def __init__(self, index=0, state="pending"):
        self.index = index
        self.state = state


def _make_synthetic_memory():
    return {
        "drift": [],
        "repair": [],
        "reflection": [],
    }


def _make_tool_schemas():
    return [
        {"name": "run_code", "description": "Execute Python code", "parameters": {"code": "string"}},
        {"name": "read_file", "description": "Read a file", "parameters": {"path": "string"}},
    ]


# ═══════════════════════════════════════════════════════════════
# S2→S1 Adapter Validation
# ═══════════════════════════════════════════════════════════════

class TestValidateS2ToS1:
    """Tests for validate_s2_to_s1 and validate_s2_to_s1_detailed."""

    def test_valid_request_passes(self):
        """A well-formed PromptRequest passes adapter validation."""
        req = build_prompt_request(
            agent_state=_FakeAgentState(),
            subgoal_state=_FakeSubgoalState(),
            segment_state=_FakeSegmentState(),
            memory=_make_synthetic_memory(),
            tool_schemas=_make_tool_schemas(),
        )
        assert validate_s2_to_s1(req) is True

    def test_valid_detailed_no_errors(self):
        """Detailed validation returns no errors for valid request."""
        req = build_prompt_request(
            agent_state=_FakeAgentState(),
            subgoal_state=_FakeSubgoalState(),
            segment_state=_FakeSegmentState(),
            memory=_make_synthetic_memory(),
            tool_schemas=_make_tool_schemas(),
        )
        result = validate_s2_to_s1_detailed(req)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_none_request_fails(self):
        """None is not a valid PromptRequest."""
        assert validate_s2_to_s1(None) is False

    def test_none_detailed(self):
        """Detailed validation reports None."""
        result = validate_s2_to_s1_detailed(None)
        assert result["valid"] is False
        assert any("None" in e for e in result["errors"])

    def test_empty_prompt_fails(self):
        """Empty prompt dict fails."""
        req = build_prompt_request(
            agent_state=_FakeAgentState(),
            subgoal_state=_FakeSubgoalState(),
            segment_state=_FakeSegmentState(),
            memory=_make_synthetic_memory(),
            tool_schemas=_make_tool_schemas(),
        )
        req.prompt = {}
        assert validate_s2_to_s1(req) is False

    def test_empty_prompt_detailed(self):
        """Detailed validation reports empty prompt."""
        req = build_prompt_request(
            agent_state=_FakeAgentState(),
            subgoal_state=_FakeSubgoalState(),
            segment_state=_FakeSegmentState(),
            memory=_make_synthetic_memory(),
            tool_schemas=_make_tool_schemas(),
        )
        req.prompt = {}
        result = validate_s2_to_s1_detailed(req)
        assert result["valid"] is False
        assert any("prompt" in e.lower() for e in result["errors"])

    def test_missing_memory_fails(self):
        """None memory fails."""
        req = build_prompt_request(
            agent_state=_FakeAgentState(),
            subgoal_state=_FakeSubgoalState(),
            segment_state=_FakeSegmentState(),
            memory={},
            tool_schemas=[],
        )
        req.memory = None
        assert validate_s2_to_s1(req) is False

    def test_missing_plan_context_fails(self):
        """None plan_context fails."""
        req = build_prompt_request(
            agent_state=_FakeAgentState(),
            subgoal_state=_FakeSubgoalState(),
            segment_state=_FakeSegmentState(),
            memory=_make_synthetic_memory(),
            tool_schemas=[],
        )
        req.plan_context = None
        assert validate_s2_to_s1(req) is False

    def test_invalid_subgoal_section(self):
        """plan_context.subgoal must be a dict with index(int) + state(str)."""
        req = build_prompt_request(
            agent_state=_FakeAgentState(),
            subgoal_state=_FakeSubgoalState(),
            segment_state=_FakeSegmentState(),
            memory=_make_synthetic_memory(),
            tool_schemas=[],
        )
        req.plan_context["subgoal"] = "not_a_dict"
        assert validate_s2_to_s1(req) is False

    def test_subgoal_missing_index_field(self):
        """plan_context.subgoal with missing index fails."""
        req = build_prompt_request(
            agent_state=_FakeAgentState(),
            subgoal_state=_FakeSubgoalState(),
            segment_state=_FakeSegmentState(),
            memory=_make_synthetic_memory(),
            tool_schemas=[],
        )
        req.plan_context["subgoal"] = {"state": "active"}
        assert validate_s2_to_s1(req) is False

    def test_segment_missing_state_field(self):
        """plan_context.segment with missing state fails."""
        req = build_prompt_request(
            agent_state=_FakeAgentState(),
            subgoal_state=_FakeSubgoalState(),
            segment_state=_FakeSegmentState(),
            memory=_make_synthetic_memory(),
            tool_schemas=[],
        )
        req.plan_context["segment"] = {"index": 0}
        assert validate_s2_to_s1(req) is False

    def test_no_tool_context_is_ok(self):
        """Empty tool_context list is valid."""
        req = build_prompt_request(
            agent_state=_FakeAgentState(),
            subgoal_state=_FakeSubgoalState(),
            segment_state=_FakeSegmentState(),
            memory=_make_synthetic_memory(),
            tool_schemas=[],
        )
        assert validate_s2_to_s1(req) is True

    def test_request_is_json_safe(self):
        """Valid request serializes to JSON."""
        req = build_prompt_request(
            agent_state=_FakeAgentState(),
            subgoal_state=_FakeSubgoalState(),
            segment_state=_FakeSegmentState(),
            memory=_make_synthetic_memory(),
            tool_schemas=_make_tool_schemas(),
        )
        import json
        serialized = json.dumps(req.to_dict())
        assert isinstance(serialized, str)
        # Round-trip back
        reloaded = json.loads(serialized)
        assert reloaded["plan_context"]["subgoal"]["index"] == 0

    def test_no_raw_s2_objects(self):
        """PromptRequest must contain only JSON-safe primitives."""
        req = build_prompt_request(
            agent_state=_FakeAgentState(),
            subgoal_state=_FakeSubgoalState(),
            segment_state=_FakeSegmentState(),
            memory=_make_synthetic_memory(),
            tool_schemas=_make_tool_schemas(),
        )
        d = req.to_dict()
        # Walk all values and assert no non-primitive types
        def _walk(v, path=""):
            if isinstance(v, dict):
                for k, val in v.items():
                    _walk(val, f"{path}.{k}")
            elif isinstance(v, list):
                for i, val in enumerate(v):
                    _walk(val, f"{path}[{i}]")
            elif isinstance(v, (int, float, str, bool, type(None))):
                pass
            else:
                pytest.fail(f"Non-JSON-safe value at {path}: {type(v).__name__} = {v!r}")
        _walk(d)

    def test_deterministic_output(self):
        """build_prompt_request returns identical output for same inputs."""
        req1 = build_prompt_request(
            agent_state=_FakeAgentState(cycle=1),
            subgoal_state=_FakeSubgoalState(index=0, state="active"),
            segment_state=_FakeSegmentState(index=2, state="running"),
            memory=_make_synthetic_memory(),
            tool_schemas=_make_tool_schemas(),
        )
        req2 = build_prompt_request(
            agent_state=_FakeAgentState(cycle=1),
            subgoal_state=_FakeSubgoalState(index=0, state="active"),
            segment_state=_FakeSegmentState(index=2, state="running"),
            memory=_make_synthetic_memory(),
            tool_schemas=_make_tool_schemas(),
        )
        assert req1.to_dict() == req2.to_dict()

    def test_subgoal_index_tracks_state(self):
        """plan_context.subgoal.index reflects subgoal state index."""
        req = build_prompt_request(
            agent_state=_FakeAgentState(),
            subgoal_state=_FakeSubgoalState(index=3),
            segment_state=_FakeSegmentState(),
            memory=_make_synthetic_memory(),
            tool_schemas=[],
        )
        assert req.plan_context["subgoal"]["index"] == 3

    def test_segment_index_tracks_state(self):
        """plan_context.segment.index reflects segment state index."""
        req = build_prompt_request(
            agent_state=_FakeAgentState(),
            subgoal_state=_FakeSubgoalState(),
            segment_state=_FakeSegmentState(index=5),
            memory=_make_synthetic_memory(),
            tool_schemas=[],
        )
        assert req.plan_context["segment"]["index"] == 5

    def test_state_enum_is_string(self):
        """State values in plan_context are strings, not enum objects."""
        req = build_prompt_request(
            agent_state=_FakeAgentState(),
            subgoal_state=_FakeSubgoalState(state="active"),
            segment_state=_FakeSegmentState(state="running"),
            memory=_make_synthetic_memory(),
            tool_schemas=[],
        )
        subgoal_state = req.plan_context["subgoal"]["state"]
        segment_state = req.plan_context["segment"]["state"]
        assert isinstance(subgoal_state, str)
        assert isinstance(segment_state, str)


# ═══════════════════════════════════════════════════════════════
# S1→S2 Adapter Validation
# ═══════════════════════════════════════════════════════════════

class TestValidateS1ToS2:
    """Tests for validate_s1_to_s2 and validate_s1_to_s2_detailed."""

    def _make_valid_response(self) -> PromptResponse:
        return PromptResponse(
            output={
                "drift_signals": [],
                "repair_proposals": [],
                "reflection": {"progress": 0.5, "is_complete": False},
            },
            tool_calls=[
                {"name": "run_code", "arguments": {"code": "print(1)"}},
            ],
            errors=[],
        )

    def test_valid_response_passes(self):
        """A well-formed PromptResponse passes adapter validation."""
        resp = self._make_valid_response()
        assert validate_s1_to_s2(resp) is True

    def test_valid_detailed_no_errors(self):
        """Detailed validation returns no errors for valid response."""
        resp = self._make_valid_response()
        result = validate_s1_to_s2_detailed(resp)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_none_response_fails(self):
        """None is not a valid PromptResponse."""
        assert validate_s1_to_s2(None) is False

    def test_empty_output_fails(self):
        """Empty output dict fails."""
        resp = self._make_valid_response()
        resp.output = {}
        assert validate_s1_to_s2(resp) is False

    def test_output_none_fails(self):
        """None output fails."""
        resp = self._make_valid_response()
        resp.output = None
        assert validate_s1_to_s2(resp) is False

    def test_raw_text_only_fails(self):
        """Output containing only raw_text is rejected."""
        resp = PromptResponse(
            output={"raw_text": "some text"},
            tool_calls=[],
            errors=[],
        )
        assert validate_s1_to_s2(resp) is False

    def test_raw_text_with_other_fields_passes(self):
        """Output with raw_text AND other structured fields passes."""
        resp = PromptResponse(
            output={
                "raw_text": "some text",
                "drift_signals": [{"type": "WRONG_CAPABILITY"}],
            },
            tool_calls=[],
            errors=[],
        )
        assert validate_s1_to_s2(resp) is True

    def test_tool_call_missing_name_fails(self):
        """Tool call missing 'name' key fails."""
        resp = self._make_valid_response()
        resp.tool_calls = [{"arguments": {}}]
        assert validate_s1_to_s2(resp) is False

    def test_tool_call_not_dict_fails(self):
        """Tool call that's not a dict fails."""
        resp = self._make_valid_response()
        resp.tool_calls = ["not_a_dict"]
        assert validate_s1_to_s2(resp) is False

    def test_error_entry_missing_type_fails(self):
        """Error entry missing 'type' key fails."""
        resp = self._make_valid_response()
        resp.errors = [{"message": "something wrong"}]
        assert validate_s1_to_s2(resp) is False

    def test_error_entry_missing_message_fails(self):
        """Error entry missing 'message' key fails."""
        resp = self._make_valid_response()
        resp.errors = [{"type": "error_type", "extra": "data"}]
        assert validate_s1_to_s2(resp) is False

    def test_empty_tool_calls_is_ok(self):
        """Empty tool_calls list is valid."""
        resp = self._make_valid_response()
        resp.tool_calls = []
        assert validate_s1_to_s2(resp) is True

    def test_empty_errors_is_ok(self):
        """Empty errors list is valid."""
        resp = self._make_valid_response()
        resp.errors = []
        assert validate_s1_to_s2(resp) is True

    def test_response_is_json_safe(self):
        """Valid response serializes to JSON."""
        resp = self._make_valid_response()
        import json
        serialized = json.dumps(resp.to_dict())
        assert isinstance(serialized, str)
        reloaded = json.loads(serialized)
        assert reloaded["output"]["reflection"]["progress"] == 0.5


# ═══════════════════════════════════════════════════════════════
# S1→S2 Adapter Output Tests
# ═══════════════════════════════════════════════════════════════

class TestS1ToS2Adapter:
    """Tests for parse_prompt_response output correctness."""

    def test_parses_drift_signals_from_output(self):
        """Drift signals in output are extracted correctly."""
        response = PromptResponse(
            output={
                "drift_detected": True,
                "drift_type": "WRONG_CAPABILITY",
                "quality": {"below_threshold": True},
                "structural_deviation": {"severity": "error"},
            },
            tool_calls=[],
            errors=[],
        )
        result = parse_prompt_response(response)
        signals = result["drift_signals"]
        assert len(signals) == 3  # drift_detected + quality.below_threshold + structural_deviation
        types_found = [s["drift"] for s in signals]
        assert "WRONG_CAPABILITY" in types_found
        assert "quality_below_threshold" in types_found
        assert "structural_deviation" in types_found

    def test_parses_repair_proposals_from_output(self):
        """Repair proposals in output are extracted correctly."""
        response = PromptResponse(
            output={
                "repairs": [
                    {"target": "missing_key", "action": "add_field", "replacement": "default_value"},
                ],
            },
            tool_calls=[],
            errors=[],
        )
        result = parse_prompt_response(response)
        proposals = result["repair_proposals"]
        assert len(proposals) == 1
        assert proposals[0]["action"] == "add_field"
        assert proposals[0]["target"] == "missing_key"

    def test_parses_reflection_from_output(self):
        """Reflection summary is extracted from output."""
        response = PromptResponse(
            output={
                "progress": 0.8,
                "drift": False,
                "repair": False,
                "is_complete": False,
            },
            tool_calls=[],
            errors=[],
        )
        result = parse_prompt_response(response)
        reflection = result["reflection"]
        assert reflection["progress"] == 0.8
        assert reflection["is_complete"] is False

    def test_parses_tool_calls(self):
        """Tool calls are extracted from response."""
        response = PromptResponse(
            output={},
            tool_calls=[
                {"name": "run_code", "arguments": {"code": "x = 1"}},
                {"name": "read_file", "arguments": {"path": "/tmp/test.py"}},
            ],
            errors=[],
        )
        result = parse_prompt_response(response)
        tool_results = result["tool_results"]
        assert len(tool_results) == 2
        assert tool_results[0]["name"] == "run_code"
        assert tool_results[1]["name"] == "read_file"

    def test_parses_errors_from_response(self):
        """Errors in response.errors are extracted."""
        response = PromptResponse(
            output={},
            tool_calls=[],
            errors=[
                {"type": "parse_error", "message": "Invalid JSON in step 3"},
            ],
        )
        result = parse_prompt_response(response)
        errors = result["errors"]
        assert len(errors) == 1
        assert errors[0]["type"] == "parse_error"

    def test_empty_output_produces_empty_lists(self):
        """Empty output yields empty lists for signals/proposals, defaults for reflection."""
        response = PromptResponse(
            output={},
            tool_calls=[],
            errors=[],
        )
        result = parse_prompt_response(response)
        assert result["drift_signals"] == []
        assert result["repair_proposals"] == []
        # Reflection always returns a dict with defaults, not empty
        assert isinstance(result["reflection"], dict)
        assert result["reflection"]["progress"] is None
        assert result["reflection"]["is_complete"] is False
        assert result["tool_results"] == []
        assert result["errors"] == []

    def test_output_raw_preserved(self):
        """output_raw contains the full output dict."""
        response = PromptResponse(
            output={"custom_field": "custom_value"},
            tool_calls=[],
            errors=[],
        )
        result = parse_prompt_response(response)
        assert result["output_raw"] == {"custom_field": "custom_value"}


# ═══════════════════════════════════════════════════════════════
# Round-Trip Tests
# ═══════════════════════════════════════════════════════════════

class TestRoundTrip:
    """Round-trip: S2 state → PromptRequest → synthetic PromptResponse → S2 updates."""

    def test_round_trip_preserves_state(self):
        """Round-trip starting from S2 state produces deterministic S2 updates."""
        agent = _FakeAgentState(cycle=1)
        subgoal = _FakeSubgoalState(index=0, state="active")
        segment = _FakeSegmentState(index=2, state="running")
        memory = _make_synthetic_memory()
        tool_schemas = _make_tool_schemas()

        # S2 → S1
        req = build_prompt_request(agent, subgoal, segment, memory, tool_schemas)
        assert validate_s2_to_s1(req) is True

        # Synthetic S1 response (simulating what S1 would return)
        response = PromptResponse(
            output={
                "drift_detected": True,
                "drift_type": "WRONG_OUTPUT_SHAPE",
                "progress": 0.3,
                "is_complete": False,
            },
            tool_calls=[
                {"name": "run_code", "arguments": {"code": "validate()"}},
            ],
            errors=[],
        )
        assert validate_s1_to_s2(response) is True

        # S1 → S2
        result = parse_prompt_response(response)
        assert len(result["drift_signals"]) == 1
        assert result["drift_signals"][0]["drift"] == "WRONG_OUTPUT_SHAPE"
        assert result["reflection"]["progress"] == 0.3
        assert len(result["tool_results"]) == 1

    def test_round_trip_deterministic(self):
        """Two round-trips with same inputs produce identical results."""
        def _round_trip():
            req = build_prompt_request(
                _FakeAgentState(),
                _FakeSubgoalState(),
                _FakeSegmentState(),
                _make_synthetic_memory(),
                _make_tool_schemas(),
            )
            response = PromptResponse(
                output={"drift_signals": [{"type": "WRONG_CAPABILITY"}]},
                tool_calls=[{"name": "run_code", "arguments": {"code": "1+1"}}],
                errors=[],
            )
            return parse_prompt_response(response)

        result1 = _round_trip()
        result2 = _round_trip()
        assert result1 == result2

    def test_round_trip_no_raw_strings(self):
        """No raw strings cross the boundary in either direction."""
        req = build_prompt_request(
            _FakeAgentState(),
            _FakeSubgoalState(),
            _FakeSegmentState(),
            _make_synthetic_memory(),
            _make_tool_schemas(),
        )
        # PromptRequest must be fully structured
        req_dict = req.to_dict()
        assert isinstance(req_dict["plan_context"], dict)
        assert isinstance(req_dict["plan_context"]["subgoal"], dict)

        # Response must be fully structured too
        response = PromptResponse(
            output={"repair_proposals": [{"action": "fix"}]},
            tool_calls=[],
            errors=[],
        )
        resp_dict = response.to_dict()
        assert isinstance(resp_dict["output"], dict)


# ═══════════════════════════════════════════════════════════════
# Error Handling Tests
# ═══════════════════════════════════════════════════════════════

class TestAdapterErrorHandling:
    """Adapters must surface structured errors, not crash."""

    def test_malformed_prompt_response_no_output_field(self):
        """PromptResponse with None output is caught by validator."""
        response = PromptResponse(
            output={"drift_signals": []},
            tool_calls=[],
            errors=[],
        )
        response.output = None
        assert validate_s1_to_s2(response) is False

    def test_malformed_output_non_dict(self):
        """PromptResponse.output as string fails validation."""
        response = PromptResponse(
            output={"drift_signals": []},
            tool_calls=[],
            errors=[],
        )
        response.output = "just_a_string"
        assert validate_s1_to_s2(response) is False

    def test_parse_does_not_mutate_response(self):
        """parse_prompt_response never mutates the input."""
        response = PromptResponse(
            output={"drift_signals": [{"type": "TEST"}]},
            tool_calls=[{"name": "test", "arguments": {}}],
            errors=[{"type": "warn", "message": "test"}],
        )
        original_dict = response.to_dict()
        parse_prompt_response(response)
        assert response.to_dict() == original_dict

    def test_unexpected_tool_call_fields_are_tolerated(self):
        """Tool calls with unexpected fields still parse (extra fields ignored)."""
        response = PromptResponse(
            output={},
            tool_calls=[
                {"name": "test", "arguments": {}, "unexpected_field": "value"},
            ],
            errors=[],
        )
        result = parse_prompt_response(response)
        assert len(result["tool_results"]) == 1
        assert result["tool_results"][0]["name"] == "test"
        # Unexpected fields are not forwarded (adapter only maps known keys)
        assert result["tool_results"][0]["arguments"] == {}

    def test_empty_response_does_not_crash(self):
        """Minimal valid response parses without error."""
        response = PromptResponse(
            output={"some": "data"},
            tool_calls=[],
            errors=[],
        )
        result = parse_prompt_response(response)
        assert isinstance(result, dict)
        assert "drift_signals" in result
        assert "repair_proposals" in result
        assert "reflection" in result

    def test_build_prompt_request_deterministic_with_various_states(self):
        """build_prompt_request is deterministic across different state combinations."""
        for cycle in [0, 1, 5]:
            req1 = build_prompt_request(
                _FakeAgentState(cycle=cycle),
                _FakeSubgoalState(),
                _FakeSegmentState(),
                _make_synthetic_memory(),
                [],
            )
            req2 = build_prompt_request(
                _FakeAgentState(cycle=cycle),
                _FakeSubgoalState(),
                _FakeSegmentState(),
                _make_synthetic_memory(),
                [],
            )
            assert req1.to_dict() == req2.to_dict()

    def test_invalid_json_in_output_field_handled(self):
        """Non-serializable objects in output are caught by validation."""
        response = PromptResponse(
            output={"drift_signals": []},
            tool_calls=[],
            errors=[],
        )
        # Insert a non-serializable object
        response.output["bad"] = object()
        assert validate_s1_to_s2(response) is False


# ═══════════════════════════════════════════════════════════════
# Edge Cases
# ═══════════════════════════════════════════════════════════════

class TestAdapterEdgeCases:
    """Edge case tests for adapter layer."""

    def test_large_memory_is_json_safe(self):
        """Large memory dict is still JSON-safe."""
        memory = {
            "drift": [{"type": f"signal_{i}"} for i in range(100)],
            "repair": [{"action": f"repair_{i}"} for i in range(100)],
            "reflection": [{"note": f"reflection_{i}"} for i in range(100)],
        }
        req = build_prompt_request(
            _FakeAgentState(),
            _FakeSubgoalState(),
            _FakeSegmentState(),
            memory,
            [],
        )
        assert validate_s2_to_s1(req) is True

    def test_deeply_nested_output(self):
        """Deeply nested output dict is validated correctly."""
        nested = {"a": {"b": {"c": {"d": {"e": "value"}}}}}
        response = PromptResponse(
            output=nested,
            tool_calls=[],
            errors=[],
        )
        assert validate_s1_to_s2(response) is True

    def test_tool_schemas_preserved(self):
        """Tool schemas pass through the adapter correctly."""
        schemas = [
            {"name": "tool_a", "description": "Tool A", "parameters": {"x": "int"}},
            {"name": "tool_b", "description": "Tool B", "parameters": {"y": "str"}},
        ]
        req = build_prompt_request(
            _FakeAgentState(),
            _FakeSubgoalState(),
            _FakeSegmentState(),
            _make_synthetic_memory(),
            schemas,
        )
        assert len(req.tool_context) == 2
        assert req.tool_context[0]["name"] == "tool_a"
        assert req.tool_context[1]["name"] == "tool_b"

    def test_none_memory_is_passed_through(self):
        """None memory stays None (validator catches it)."""
        req = build_prompt_request(
            _FakeAgentState(),
            _FakeSubgoalState(),
            _FakeSegmentState(),
            None,
            [],
        )
        # Adapter passes memory through as-is
        assert req.memory is None
        # Validator correctly flags this as invalid
        assert validate_s2_to_s1(req) is False
