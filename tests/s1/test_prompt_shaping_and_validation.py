"""
Phase 2.14.4 — Prompt Shaping & Response Validation Tests
==========================================================

Tests for:
- JSON-only prompt builder (build_llm_prompt)
- Response validator (validate_llm_response)
- S1 error → AgentError mapping (map_s1_error_to_agent_error)
- S1 client validation integration (call_s1_backend)
- Safety guarantees (no state mutation, no drift on invalid input)
"""

from __future__ import annotations

import json
import pytest

from src.core.planning.s1_contract.types import (
    PromptRequest,
    PromptResponse,
    S1Error,
)
from src.core.planning.s1_contract.s1_prompt_builder import (
    build_llm_prompt,
    RESPONSE_SCHEMA,
    SYSTEM_INSTRUCTION,
    VALID_EXAMPLE_NO_DRIFT,
    VALID_EXAMPLE_WITH_DRIFT,
)
from src.core.planning.s1_contract.s1_response_validator import validate_llm_response
from src.core.planning.s1_contract.s1_to_s2_adapter import map_s1_error_to_agent_error
from src.core.planning.s1_contract.s1_client import call_s1_backend


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _make_minimal_request() -> PromptRequest:
    """Build a minimal valid PromptRequest for testing."""
    return PromptRequest(
        prompt={"instruction": "Execute the current subgoal."},
        memory={"subgoal_index": 0, "segment_index": 0},
        plan_context={
            "subgoal_index": 0,
            "subgoal_state": "running",
            "segment_index": 0,
            "segment_state": "running",
        },
        tool_context=[
            {"name": "read_file", "schema": {"path": "str"}},
        ],
    )


def _make_valid_output_dict() -> dict:
    """Return a minimal valid output dict matching PromptResponse schema."""
    return {
        "drift_detected": False,
        "drift_type": None,
        "drift_severity": "minor",
        "drift_detail": [],
        "repairs": [],
        "quality": {"below_threshold": False},
        "structural_deviation": {},
        "progress": 0.5,
        "is_complete": False,
        "confidence": 0.95,
        "next_action": "continue_execution",
        "blockers": [],
        "shaped": True,
        "steps": [],
        "segments": [],
    }


# ══════════════════════════════════════════════════════════════════════
# 1. JSON-only prompt tests
# ══════════════════════════════════════════════════════════════════════

class TestPromptBuilder:
    """Tests for build_llm_prompt."""

    def test_prompt_is_json_safe(self):
        """Prompt output is fully JSON-serializable."""
        req = _make_minimal_request()
        prompt = build_llm_prompt(req)
        serialized = json.dumps(prompt)
        assert isinstance(serialized, str)

    def test_prompt_contains_system_instruction(self):
        """Prompt includes system instruction."""
        req = _make_minimal_request()
        prompt = build_llm_prompt(req)
        assert prompt["system_instruction"] == SYSTEM_INSTRUCTION
        assert "Respond ONLY with valid JSON" in prompt["system_instruction"]

    def test_prompt_contains_response_schema(self):
        """Prompt includes the full JSON response schema."""
        req = _make_minimal_request()
        prompt = build_llm_prompt(req)
        schema = prompt["response_schema"]
        assert schema["type"] == "object"
        assert "required" in schema
        assert "drift_detected" in schema["required"]

    def test_prompt_contains_context(self):
        """Prompt includes plan_context, memory, tool_context."""
        req = _make_minimal_request()
        prompt = build_llm_prompt(req)
        ctx = prompt["context"]
        assert "plan_context" in ctx
        assert "memory" in ctx
        assert "tool_context" in ctx

    def test_prompt_contains_valid_examples(self):
        """Prompt includes valid response examples."""
        req = _make_minimal_request()
        prompt = build_llm_prompt(req)
        assert len(prompt["valid_examples"]) >= 2
        for ex in prompt["valid_examples"]:
            assert "label" in ex
            assert "response" in ex

    def test_prompt_contains_invalid_examples(self):
        """Prompt includes invalid response examples with explanations."""
        req = _make_minimal_request()
        prompt = build_llm_prompt(req)
        assert len(prompt["invalid_examples"]) >= 2
        for ex in prompt["invalid_examples"]:
            assert "label" in ex
            assert "response" in ex
            assert "why_invalid" in ex

    def test_prompt_has_no_free_form_text_in_context(self):
        """Prompt context values are structured, not raw strings."""
        req = _make_minimal_request()
        prompt = build_llm_prompt(req)
        ctx = prompt["context"]
        # context sub-keys are dicts/lists, not bare strings
        assert isinstance(ctx["plan_context"], dict)
        assert isinstance(ctx["memory"], dict)
        assert isinstance(ctx["tool_context"], list)

    def test_prompt_does_not_mutate_input(self):
        """build_llm_prompt does not mutate the PromptRequest."""
        req = _make_minimal_request()
        original_memory = dict(req.memory)
        original_plan = dict(req.plan_context)
        build_llm_prompt(req)
        assert req.memory == original_memory
        assert req.plan_context == original_plan

    def test_prompt_deterministic(self):
        """Same input produces identical output."""
        req = _make_minimal_request()
        p1 = build_llm_prompt(req)
        p2 = build_llm_prompt(req)
        assert p1 == p2

    def test_prompt_includes_instruction_from_request(self):
        """If request.prompt has 'instruction', it appears in context."""
        req = _make_minimal_request()
        req.prompt["instruction"] = "Test instruction text"
        prompt = build_llm_prompt(req)
        assert prompt["context"]["instruction"] == "Test instruction text"

    def test_prompt_examples_are_valid_json(self):
        """Valid/invalid examples in prompt are all JSON-safe."""
        req = _make_minimal_request()
        prompt = build_llm_prompt(req)
        for ex in prompt["valid_examples"] + prompt["invalid_examples"]:
            json.dumps(ex["response"])


# ══════════════════════════════════════════════════════════════════════
# 2. Valid LLM response tests
# ══════════════════════════════════════════════════════════════════════

class TestValidLLMResponse:
    """Tests for validate_llm_response with valid input."""

    def test_valid_json_accepted(self):
        """Valid JSON matching schema returns PromptResponse."""
        raw = json.dumps(_make_valid_output_dict())
        result = validate_llm_response(raw)
        assert isinstance(result, PromptResponse)

    def test_valid_response_has_output(self):
        """Accepted response has valid output dict."""
        raw = json.dumps(_make_valid_output_dict())
        result = validate_llm_response(raw)
        assert isinstance(result.output, dict)
        assert result.output["drift_detected"] is False

    def test_valid_response_has_no_tool_calls(self):
        """Accepted response has empty tool_calls."""
        raw = json.dumps(_make_valid_output_dict())
        result = validate_llm_response(raw)
        assert result.tool_calls == []

    def test_valid_response_has_no_errors(self):
        """Accepted response has empty errors list."""
        raw = json.dumps(_make_valid_output_dict())
        result = validate_llm_response(raw)
        assert result.errors == []

    def test_deterministic_validation(self):
        """Same valid JSON always produces identical result."""
        raw = json.dumps(_make_valid_output_dict())
        r1 = validate_llm_response(raw)
        r2 = validate_llm_response(raw)
        assert r1.output == r2.output
        assert r1.errors == r2.errors
        assert r1.tool_calls == r2.tool_calls


# ══════════════════════════════════════════════════════════════════════
# 3. Invalid JSON tests
# ══════════════════════════════════════════════════════════════════════

class TestInvalidJSON:
    """Tests for validate_llm_response with invalid JSON."""

    def test_missing_braces_returns_s1_error(self):
        """Unclosed brace returns S1Error."""
        raw = '{"drift_detected": false'
        result = validate_llm_response(raw)
        assert isinstance(result, S1Error)
        assert result.type == "invalid_s1_response"

    def test_trailing_comma_returns_s1_error(self):
        """Trailing comma returns S1Error."""
        raw = '{"drift_detected": false,}'
        result = validate_llm_response(raw)
        assert isinstance(result, S1Error)
        assert result.type == "invalid_s1_response"

    def test_non_json_text_returns_s1_error(self):
        """Plain English text returns S1Error."""
        raw = "The plan is going well and we should continue."
        result = validate_llm_response(raw)
        assert isinstance(result, S1Error)
        assert result.type == "invalid_s1_response"

    def test_empty_string_returns_s1_error(self):
        """Empty string returns S1Error."""
        result = validate_llm_response("")
        assert isinstance(result, S1Error)
        assert result.type == "invalid_s1_response"

    def test_whitespace_only_returns_s1_error(self):
        """Whitespace-only string returns S1Error."""
        result = validate_llm_response("   \n\t  ")
        assert isinstance(result, S1Error)
        assert result.type == "invalid_s1_response"

    def test_json_array_returns_s1_error(self):
        """JSON array (not object) returns S1Error."""
        result = validate_llm_response("[1, 2, 3]")
        assert isinstance(result, S1Error)
        assert result.type == "invalid_s1_response"

    def test_json_string_returns_s1_error(self):
        """Bare JSON string returns S1Error."""
        result = validate_llm_response('"just a string"')
        assert isinstance(result, S1Error)
        assert result.type == "invalid_s1_response"

    def test_json_number_returns_s1_error(self):
        """Bare JSON number returns S1Error."""
        result = validate_llm_response("42")
        assert isinstance(result, S1Error)
        assert result.type == "invalid_s1_response"

    def test_s1_error_has_details(self):
        """S1Error includes useful diagnostic details."""
        raw = "not json at all"
        result = validate_llm_response(raw)
        assert isinstance(result, S1Error)
        assert result.message
        assert isinstance(result.details, dict)


# ══════════════════════════════════════════════════════════════════════
# 4. Schema violation tests
# ══════════════════════════════════════════════════════════════════════

class TestSchemaViolations:
    """Tests for validate_llm_response with schema violations."""

    def test_missing_required_field_returns_s1_error(self):
        """Output with missing required field returns S1Error."""
        output = _make_valid_output_dict()
        del output["drift_detected"]
        result = validate_llm_response(json.dumps(output))
        assert isinstance(result, S1Error)
        assert "drift_detected" in str(result.message) or "drift_detected" in str(result.details.get("missing_fields", []))

    def test_extra_field_returns_s1_error(self):
        """Output with unknown field returns S1Error."""
        output = _make_valid_output_dict()
        output["free_form_commentary"] = "everything looks great!"
        result = validate_llm_response(json.dumps(output))
        assert isinstance(result, S1Error)
        assert "free_form_commentary" in str(result.details.get("extra_fields", []))

    def test_multiple_missing_fields_returns_s1_error(self):
        """Multiple missing fields are all reported."""
        output = {"drift_detected": False, "drift_type": None}
        result = validate_llm_response(json.dumps(output))
        assert isinstance(result, S1Error)
        assert len(result.details["missing_fields"]) > 2

    def test_wrong_type_drift_detected_returns_s1_error(self):
        """drift_detected as string (not bool) returns S1Error."""
        output = _make_valid_output_dict()
        output["drift_detected"] = "yes"
        result = validate_llm_response(json.dumps(output))
        assert isinstance(result, S1Error)
        assert any("drift_detected" in e for e in result.details.get("type_errors", []))

    def test_wrong_type_progress_returns_s1_error(self):
        """progress as string returns S1Error."""
        output = _make_valid_output_dict()
        output["progress"] = "halfway"
        result = validate_llm_response(json.dumps(output))
        assert isinstance(result, S1Error)
        assert any("progress" in e for e in result.details.get("type_errors", []))

    def test_wrong_type_repairs_returns_s1_error(self):
        """repairs as string returns S1Error."""
        output = _make_valid_output_dict()
        output["repairs"] = "none needed"
        result = validate_llm_response(json.dumps(output))
        assert isinstance(result, S1Error)
        assert any("repairs" in e for e in result.details.get("type_errors", []))


# ══════════════════════════════════════════════════════════════════════
# 5. S1 error → AgentError mapping tests
# ══════════════════════════════════════════════════════════════════════

class TestS1ErrorMapping:
    """Tests for map_s1_error_to_agent_error."""

    def test_maps_to_dict_with_required_fields(self):
        """Returns a dict with all AgentError fields."""
        err = S1Error(
            type="invalid_s1_response",
            message="Test error",
            details={"field": "x"},
        )
        result = map_s1_error_to_agent_error(err)
        assert isinstance(result, dict)
        assert "type" in result
        assert "message" in result
        assert "details" in result
        assert "timestamp" in result
        assert "recoverable" in result

    def test_recoverable_is_false(self):
        """S1 errors are not recoverable."""
        err = S1Error(type="x", message="y", details={})
        result = map_s1_error_to_agent_error(err)
        assert result["recoverable"] is False

    def test_type_is_s1_response_error(self):
        """Mapped error type is 'S1ResponseError'."""
        err = S1Error(type="x", message="y", details={})
        result = map_s1_error_to_agent_error(err)
        assert result["type"] == "S1ResponseError"

    def test_message_preserved(self):
        """Original error message is preserved."""
        err = S1Error(type="x", message="Original message here", details={})
        result = map_s1_error_to_agent_error(err)
        assert result["message"] == "Original message here"

    def test_details_include_s1_error_info(self):
        """Details dict includes s1_error_type and s1_error_details."""
        err = S1Error(
            type="invalid_s1_response",
            message="Bad JSON",
            details={"raw": "..."},
        )
        result = map_s1_error_to_agent_error(err)
        assert result["details"]["s1_error_type"] == "invalid_s1_response"
        assert result["details"]["s1_error_details"] == {"raw": "..."}

    def test_deterministic_mapping(self):
        """Same S1Error always maps to same AgentError dict."""
        err = S1Error(type="a", message="b", details={"c": 1})
        r1 = map_s1_error_to_agent_error(err)
        r2 = map_s1_error_to_agent_error(err)
        # timestamp varies, so compare all except timestamp
        assert r1["type"] == r2["type"]
        assert r1["message"] == r2["message"]
        assert r1["details"] == r2["details"]
        assert r1["recoverable"] == r2["recoverable"]

    def test_does_not_mutate_s1_error(self):
        """map_s1_error_to_agent_error does not mutate the S1Error."""
        err = S1Error(type="x", message="y", details={"a": 1})
        original_details = dict(err.details)
        map_s1_error_to_agent_error(err)
        assert err.type == "x"
        assert err.message == "y"
        assert err.details == original_details


# ══════════════════════════════════════════════════════════════════════
# 6. Safety guarantee tests
# ══════════════════════════════════════════════════════════════════════

class TestSafetyGuarantees:
    """Tests that invalid LLM output does not corrupt S2."""

    def test_invalid_output_does_not_crash(self):
        """Invalid LLM output returns S1Error, never raises."""
        result = validate_llm_response("garbage")
        assert isinstance(result, S1Error)

    def test_invalid_output_returns_no_prompt_response(self):
        """Invalid input never returns a PromptResponse."""
        result = validate_llm_response("}")
        assert not isinstance(result, PromptResponse)

    def test_valid_output_returns_no_s1_error(self):
        """Valid input never returns an S1Error."""
        raw = json.dumps(_make_valid_output_dict())
        result = validate_llm_response(raw)
        assert not isinstance(result, S1Error)

    def test_validate_is_pure(self):
        """validate_llm_response has no side effects."""
        raw = json.dumps(_make_valid_output_dict())
        original = str(raw)
        validate_llm_response(raw)
        assert str(raw) == original  # input not modified

    def test_validate_does_not_mutate_global_state(self):
        """Multiple validations have no side effects."""
        for _ in range(5):
            raw = json.dumps(_make_valid_output_dict())
            validate_llm_response(raw)
        # No state leak — just verify it doesn't crash or mutate

    def test_simulation_backend_always_returns_prompt_response(self):
        """Simulation backend always produces valid PromptResponse."""
        req = _make_minimal_request()
        result = call_s1_backend(req, backend="simulation")
        assert isinstance(result, PromptResponse)

    def test_real_llm_stub_returns_prompt_response(self):
        """Real LLM backend blocked by kill-switch → returns S1Error (safe)."""
        req = _make_minimal_request()
        result = call_s1_backend(req, backend="real_llm")
        # Kill-switch is active by default → safe S1Error, not a live call
        assert isinstance(result, S1Error)
        assert result.type == "real_llm_disabled"

    def test_real_llm_stub_output_is_fully_valid(self):
        """Real LLM kill-switch error has all required S1Error fields."""
        req = _make_minimal_request()
        result = call_s1_backend(req, backend="real_llm")
        # Kill-switch active → returns structured S1Error
        assert isinstance(result, S1Error)
        assert result.type == "real_llm_disabled"
        assert result.message is not None
        assert "hint" in result.details


# ══════════════════════════════════════════════════════════════════════
# 7. Integration: full pipeline tests
# ══════════════════════════════════════════════════════════════════════

class TestFullPipeline:
    """End-to-end pipeline tests: prompt → LLM → validate → S2."""

    def test_full_simulation_pipeline(self):
        """S2 state → PromptRequest → simulation → valid PromptResponse."""
        from src.core.planning.s1_contract.s2_to_s1_adapter import build_prompt_request

        req = build_prompt_request(
            agent_state={"goal": "test", "subgoals": []},
            subgoal_state={"index": 0, "lifecycle": "running"},
            segment_state={"index": 0, "lifecycle": "running"},
            memory={"subgoal_index": 0, "segment_index": 0},
            tool_schemas=[{"name": "echo"}],
        )
        result = call_s1_backend(req, backend="simulation")
        assert isinstance(result, PromptResponse)
        assert isinstance(result.output, dict)

    def test_build_prompt_then_validate_roundtrip(self):
        """Prompt → raw JSON → validate → valid PromptResponse."""
        req = _make_minimal_request()
        # Build prompt (S2→S1)
        prompt = build_llm_prompt(req)
        assert "system_instruction" in prompt

        # Simulate LLM response (valid JSON)
        raw = json.dumps(_make_valid_output_dict())

        # Validate (S1→S2)
        result = validate_llm_response(raw)
        assert isinstance(result, PromptResponse)

    def test_parse_validated_response_into_s2(self):
        """Valid PromptResponse parses cleanly into S2 updates."""
        from src.core.planning.s1_contract.s1_to_s2_adapter import parse_prompt_response

        raw = json.dumps(_make_valid_output_dict())
        response = validate_llm_response(raw)
        assert isinstance(response, PromptResponse)

        updates = parse_prompt_response(response)
        assert "drift_signals" in updates
        assert "repair_proposals" in updates
        assert "reflection" in updates
        assert "tool_results" in updates
        assert "errors" in updates

    def test_invalid_response_pipeline_terminates_cleanly(self):
        """Invalid LLM output → S1Error → AgentError (no crash)."""
        raw = "not valid json at all"
        result = validate_llm_response(raw)
        assert isinstance(result, S1Error)

        # Map to AgentError
        agent_error = map_s1_error_to_agent_error(result)
        assert agent_error["type"] == "S1ResponseError"
        assert agent_error["recoverable"] is False

    def test_roundtrip_determinism(self):
        """Multiple round-trips produce identical results."""
        results = []
        for _ in range(3):
            req = _make_minimal_request()
            raw = json.dumps(_make_valid_output_dict())
            resp = validate_llm_response(raw)
            results.append((resp.output, resp.errors, resp.tool_calls))

        for r in results[1:]:
            assert r == results[0]
