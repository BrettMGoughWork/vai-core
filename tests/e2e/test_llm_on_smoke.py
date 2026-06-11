"""
Phase 2.14.7 — LLM-On Smoke Test
=================================

Verifies that the real LLM backend (behind the kill‑switch) does
not cause catastrophic failure.  This is a **contract integrity**
test — it does not evaluate LLM semantics.

Tests:
  1. Kill‑switch active → call_s1_backend returns S1Error
  2. LLM‑on flow (simulated via stubbed validation) preserves trace structure
  3. Structured errors surface on invalid LLM responses
  4. S2 state machine remains intact regardless of backend

The real LLM backend is stubbed in this phase — we simulate the
validation path without calling a live provider.
"""

from __future__ import annotations

import json
from typing import Dict, Any

import pytest

from src.strategy.planning.s1_contract.types import (
    PromptRequest,
    PromptResponse,
    S1Error,
)
from src.strategy.planning.s1_contract.s1_client import call_s1_backend
from src.strategy.planning.s1_contract.s1_real_client import (
    ENABLE_REAL_LLM,
    S1RealLLMError,
    call_llm,
)
from src.strategy.planning.s1_contract.s1_response_validator import (
    validate_llm_response,
)
from src.strategy.planning.s1_contract.validators import (
    validate_prompt_request,
    validate_prompt_response,
)
from tests.e2e.helpers import (
    plan_1_1,
    run_agent_for_cycles,
    extract_trace,
    validate_trace_structure,
    is_json_safe,
    assert_no_raw_strings,
    assert_errors_structured,
)


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════


def _make_request() -> PromptRequest:
    """Build a minimal valid PromptRequest for smoke testing."""
    return PromptRequest(
        prompt={"instruction": "smoke-test"},
        memory={},
        plan_context={
            "subgoal": {"index": 0, "state": "pending"},
            "segment": {"index": 0, "state": "pending"},
        },
        tool_context=[],
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. Kill‑switch guard
# ══════════════════════════════════════════════════════════════════════════════


class TestKillSwitch:
    """Verify the kill‑switch prevents real LLM usage."""

    def test_kill_switch_defaults_off(self):
        """ENABLE_REAL_LLM must default to False."""
        assert ENABLE_REAL_LLM is False, (
            "Kill‑switch ENABLE_REAL_LLM must default to False. "
            "It should only be enabled after the readiness checklist passes."
        )

    def test_real_llm_backend_blocked_by_kill_switch(self):
        """backend='real_llm' returns S1Error when kill‑switch is active."""
        request = _make_request()
        result = call_s1_backend(request, backend="real_llm")

        assert isinstance(result, S1Error), (
            f"Expected S1Error when kill‑switch active, got {type(result).__name__}"
        )
        assert result.type == "real_llm_disabled", (
            f"Expected error type 'real_llm_disabled', got '{result.type}'"
        )
        assert "Kill-switch" in result.message or "kill-switch" in result.message.lower()

    def test_call_llm_raises_when_disabled(self):
        """call_llm() must raise RuntimeError when ENABLE_REAL_LLM is False."""
        request = _make_request()
        with pytest.raises(RuntimeError, match="disabled|False"):
            call_llm(request)


# ══════════════════════════════════════════════════════════════════════════════
# 2. Contract integrity (stubbed real_llm path)
# ══════════════════════════════════════════════════════════════════════════════


class TestLLMOnContractIntegrity:
    """Verify the real_llm validation pipeline preserves contract integrity.

    These tests exercise the full validation path by feeding synthetic
    raw JSON through validate_llm_response (which is what the real S1
    client path does after call_llm returns).
    """

    def test_valid_json_accepted(self):
        """Valid JSON matching schema produces PromptResponse."""
        valid_json = json.dumps({
            "drift_detected": False,
            "drift_type": None,
            "drift_severity": "minor",
            "drift_detail": [],
            "repairs": [],
            "quality": {"below_threshold": False},
            "structural_deviation": {},
            "progress": 0.0,
            "is_complete": False,
            "confidence": 0.5,
            "next_action": "continue",
            "blockers": [],
            "shaped": False,
            "steps": [],
            "segments": [],
        })
        result = validate_llm_response(valid_json)
        assert isinstance(result, PromptResponse), (
            f"Expected PromptResponse, got {type(result).__name__}"
        )
        assert result.output["drift_detected"] is False

    def test_invalid_json_returns_s1error(self):
        """Non-JSON text returns S1Error, not crash."""
        result = validate_llm_response("This is not JSON at all!")
        assert isinstance(result, S1Error)
        assert result.type == "invalid_s1_response"

    def test_malformed_json_returns_s1error(self):
        """Malformed JSON (trailing comma) returns S1Error."""
        result = validate_llm_response('{"drift_detected": false,}')
        assert isinstance(result, S1Error)
        assert result.type == "invalid_s1_response"

    def test_missing_required_fields_returns_s1error(self):
        """JSON object missing required fields returns S1Error."""
        result = validate_llm_response('{"drift_detected": false}')
        assert isinstance(result, S1Error)
        assert result.type == "invalid_s1_response"

    def test_json_array_returns_s1error(self):
        """JSON array (not object) returns S1Error."""
        result = validate_llm_response('[{"drift_detected": false}]')
        assert isinstance(result, S1Error)
        assert result.type == "invalid_s1_response"

    def test_empty_string_returns_s1error(self):
        """Empty string returns S1Error."""
        result = validate_llm_response("")
        assert isinstance(result, S1Error)
        assert result.type == "invalid_s1_response"


# ══════════════════════════════════════════════════════════════════════════════
# 3. S2 state machine intact
# ══════════════════════════════════════════════════════════════════════════════


class TestS2StateMachineIntact:
    """Verify S2 state machine works identically regardless of backend."""

    def test_simulation_backend_produces_valid_trace(self):
        """Full S2→S1→S2 loop with simulation backend produces valid trace."""
        subgoals, segments = plan_1_1()
        result = run_agent_for_cycles(subgoals, segments, max_cycles=3)

        assert result is not None, "Agent loop should not return None"
        trace = extract_trace(result)
        assert trace is not None, "Trace extraction should not return None"

        # Trace must be valid (structural check only)
        errors = validate_trace_structure(trace)
        assert len(errors) == 0, f"Trace validation errors: {errors}"

        # No raw strings across boundary
        assert_no_raw_strings(trace)

    def test_real_llm_error_path_preserves_state(self):
        """When real_llm returns S1Error, S2 state must not be corrupted."""
        request = _make_request()

        # Get a valid response from simulation as baseline
        sim_result = call_s1_backend(request, backend="simulation")
        assert isinstance(sim_result, PromptResponse)

        # real_llm should return S1Error (kill‑switch active)
        llm_result = call_s1_backend(request, backend="real_llm")
        assert isinstance(llm_result, S1Error)

        # Simulation result must still be valid (no side effects)
        sim_result2 = call_s1_backend(request, backend="simulation")
        assert isinstance(sim_result2, PromptResponse)
        assert sim_result2.output == sim_result.output, (
            "Simulation backend must be deterministic and unaffected by real_llm errors"
        )

    def test_structured_errors_well_formed(self):
        """All S1Error instances must have well-formed structure."""
        # Collect errors from various invalid inputs
        invalid_inputs = [
            "",                                     # empty
            "not json",                             # non-JSON
            '{"incomplete": true',                   # truncated
            "null",                                  # JSON null
            "42",                                    # JSON number
        ]

        for raw in invalid_inputs:
            result = validate_llm_response(raw)
            assert isinstance(result, S1Error), (
                f"validate_llm_response({raw!r}) should return S1Error"
            )
            assert result.type, "S1Error.type must not be empty"
            assert result.message, "S1Error.message must not be empty"

    def test_kill_switch_error_well_formed(self):
        """Kill‑switch S1Error must have all required fields."""
        request = _make_request()
        result = call_s1_backend(request, backend="real_llm")

        assert isinstance(result, S1Error)
        assert result.type == "real_llm_disabled"
        assert result.message
        assert isinstance(result.details, dict)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Trace stability across backends
# ══════════════════════════════════════════════════════════════════════════════


class TestTraceStability:
    """Verify traces are stable and deterministic across runs."""

    def test_simulation_trace_deterministic(self):
        """Same inputs to simulation must produce same trace every time."""
        subgoals, segments = plan_1_1()

        r1 = run_agent_for_cycles(subgoals, segments, max_cycles=2)
        r2 = run_agent_for_cycles(subgoals, segments, max_cycles=2)

        t1 = extract_trace(r1)
        t2 = extract_trace(r2)

        assert t1 == t2, (
            "Simulation backend traces must be deterministic across runs"
        )

    def test_simulation_trace_json_safe(self):
        """S2/S1 boundary payloads (PromptRequest/PromptResponse) must be JSON-safe."""
        subgoals, segments = plan_1_1()
        result = run_agent_for_cycles(subgoals, segments, max_cycles=2)
        trace = extract_trace(result)

        td = trace.to_dict()

        # Check all PromptRequest/PromptResponse payloads in the trace cycles
        for cycle in td.get("cycles", []):
            request = cycle.get("s1_request")
            if request is not None:
                assert is_json_safe(request), (
                    f"PromptRequest in cycle is not JSON-safe"
                )
            response = cycle.get("s1_response")
            if response is not None:
                assert is_json_safe(response), (
                    f"PromptResponse in cycle is not JSON-safe"
                )
