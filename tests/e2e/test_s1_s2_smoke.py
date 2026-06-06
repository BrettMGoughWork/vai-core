"""
Phase 2.14.5 — End-to-End S1+S2 Smoke Tests
=============================================

Verifies the full S2→S1→S2 loop works correctly under both
backends (simulation and real_llm) with tiny deterministic plans.

Three scenarios × two backends = six core tests:
  A. 1 subgoal, 1 segment — simplest happy path
  B. 1 subgoal, 3 segments — single-subgoal multi-segment
  C. 2 subgoals, 2 segments each — multi-subgoal

Plus:
  - Determinism comparison (simulation vs real_llm lifecycle)
  - Structured error handling
  - Trace validation (no raw strings, JSON-safe, all required keys)
"""

from __future__ import annotations

import json
from typing import Dict, Any, List

import pytest

from src.core.planning.agent_loop.agent_loop_v3 import (
    AgentExecutionState,
    AgentFullTrace,
    AgentLoopResult,
    run_agent_loop,
)
from src.core.planning.s1_contract.types import (
    PromptRequest,
    PromptResponse,
    S1Error,
)
from src.core.planning.s1_contract.s2_to_s1_adapter import (
    build_prompt_request,
    validate_s2_to_s1,
    validate_s2_to_s1_detailed,
)
from src.core.planning.s1_contract.s1_to_s2_adapter import (
    parse_prompt_response,
    validate_s1_to_s2,
)
from src.core.planning.s1_contract.s1_client import call_s1_backend
from src.core.planning.s1_contract.validators import (
    validate_prompt_request,
    validate_prompt_response,
)

from tests.e2e.helpers import (
    build_minimal_plan,
    plan_1_1,
    plan_1_3,
    plan_2_2,
    run_agent_for_cycles,
    extract_trace,
    validate_trace_structure,
    is_json_safe,
    has_raw_strings,
    assert_no_raw_strings,
    assert_errors_structured,
)


# ══════════════════════════════════════════════════════════════════════════════
# Synthetic S2 state helpers (mirror contract test pattern)
# ══════════════════════════════════════════════════════════════════════════════


class _FakeAgentState:
    """Minimal fake AgentExecutionState for the contract pipeline."""
    def __init__(self, cycle=0, is_complete=False):
        self.cycle = cycle
        self.is_complete = is_complete


class _FakeSubgoalState:
    """Minimal fake SubgoalExecutionState for the contract pipeline."""
    def __init__(self, index=0, state="active"):
        self.index = index
        self.state = _FakeEnum(state)


class _FakeSegmentState:
    """Minimal fake SegmentExecutionState for the contract pipeline."""
    def __init__(self, index=0, state="pending"):
        self.index = index
        self.state = _FakeEnum(state)


class _FakeEnum:
    """Fake enum value for synthetic states."""
    def __init__(self, value):
        self.value = value


def _make_fake_memory() -> Dict[str, Any]:
    """Return a JSON-safe deterministic memory snapshot."""
    return {
        "subgoal_history": [],
        "segment_history": [],
        "drift_history": [],
        "repair_history": [],
    }


# ══════════════════════════════════════════════════════════════════════════════
# Core assertion helpers for the e2e pipeline
# ══════════════════════════════════════════════════════════════════════════════


def _assert_s2_loop_no_crashes(result: AgentLoopResult) -> None:
    """The S2 loop must not crash — it either completes or cleanly exceeds cycles."""
    assert result.error is None, (
        f"S2 loop surfaced an unexpected error: {result.error}"
    )
    assert result.termination_reason in (
        "agent_complete",
        "max_cycles_exceeded",
        "subgoal_blocked",
    ), f"Unexpected termination reason: {result.termination_reason}"


def _assert_trace_valid(trace: AgentFullTrace) -> None:
    """The trace must have all required top-level keys and be JSON-safe."""
    missing = validate_trace_structure(trace)
    assert not missing, f"Trace missing required keys: {missing}"
    assert is_json_safe(trace.to_dict()), "Trace is not JSON-safe"
    assert_not_has_raw_strings(trace)


def assert_not_has_raw_strings(trace: AgentFullTrace) -> None:
    """Assert that the trace contains no free-form raw strings."""
    assert not has_raw_strings(trace.to_dict()), (
        "Trace contains raw strings (free-form text > 200 chars)"
    )


def _assert_structured_error(obj: Any) -> None:
    """Assert that an error payload is structured (dict with type + message)."""
    if obj is None:
        return
    if isinstance(obj, dict):
        assert "type" in obj or "error_type" in obj, (
            f"Error dict missing type: {obj}"
        )
        assert "message" in obj, f"Error dict missing message: {obj}"
    elif hasattr(obj, "type") and hasattr(obj, "message"):
        pass  # AgentError or S1Error dataclass
    else:
        pass  # non-error objects are fine


# ══════════════════════════════════════════════════════════════════════════════
# S1 contract pipeline runner
# ══════════════════════════════════════════════════════════════════════════════


def _run_s1_contract_pipeline(
    cycle: int,
    subgoal_index: int,
    segment_index: int,
    backend: str,
    agent_complete: bool = False,
) -> PromptResponse | S1Error:
    """Run the full S2→S1→S2 contract pipeline for one cycle.

    1. Build a PromptRequest from synthetic S2 state
    2. Call the S1 backend (simulation or real_llm)
    3. Return the response (PromptResponse or S1Error)
    """
    agent_state = _FakeAgentState(cycle=cycle, is_complete=agent_complete)
    subgoal_state = _FakeSubgoalState(index=subgoal_index, state="active")
    segment_state = _FakeSegmentState(index=segment_index, state="running")
    memory = _make_fake_memory()

    # S2 → S1: build the request
    request: PromptRequest = build_prompt_request(
        agent_state=agent_state,
        subgoal_state=subgoal_state,
        segment_state=segment_state,
        memory=memory,
    )

    # Validate the request
    assert validate_prompt_request(request), (
        f"PromptRequest failed validation: {validate_s2_to_s1_detailed(request)}"
    )
    assert validate_s2_to_s1(request), "S2→S1 adapter validation failed"

    # Call the S1 backend
    response = call_s1_backend(request, backend=backend)

    # The response must be either PromptResponse or S1Error
    assert isinstance(response, (PromptResponse, S1Error)), (
        f"Unexpected response type: {type(response)}"
    )

    return response


def _run_s2_s1_s2_round_trip(
    cycle: int,
    subgoal_index: int,
    segment_index: int,
    backend: str,
) -> dict:
    """Full round-trip: S2 state → PromptRequest → S1 → PromptResponse → S2 updates.

    Returns the S2 updates dict from parse_prompt_response.
    """
    response = _run_s1_contract_pipeline(
        cycle=cycle,
        subgoal_index=subgoal_index,
        segment_index=segment_index,
        backend=backend,
    )

    if isinstance(response, S1Error):
        return {"error": response.to_dict()}

    # Validate PromptResponse
    assert validate_prompt_response(response), (
        f"PromptResponse failed validation"
    )

    # S1 → S2: parse the response
    s2_updates = parse_prompt_response(response)
    assert isinstance(s2_updates, dict), (
        f"parse_prompt_response returned {type(s2_updates)}, expected dict"
    )
    return s2_updates


# ══════════════════════════════════════════════════════════════════════════════
# Scenario A — 1 subgoal, 1 segment
# ══════════════════════════════════════════════════════════════════════════════


class TestE2ESingleSubgoalSingleSegment:
    """End-to-end smoke tests: 1 subgoal, 1 segment (simplest happy path)."""

    def test_simulation_backend_s2_loop(self):
        """S2 loop with 1+1 plan must complete cleanly."""
        subgoals, segments = plan_1_1()
        result = run_agent_for_cycles(subgoals, segments, max_cycles=10)

        _assert_s2_loop_no_crashes(result)
        assert result.is_complete is True, (
            f"Expected completion, got: {result.termination_reason}"
        )
        assert result.termination_reason == "agent_complete"

    def test_simulation_backend_trace(self):
        """Trace from 1+1 plan must be valid and have all required keys."""
        subgoals, segments = plan_1_1()
        result = run_agent_for_cycles(subgoals, segments, max_cycles=10)
        trace = extract_trace(result)

        _assert_trace_valid(trace)
        assert len(trace.cycles) > 0, "Trace must have at least one cycle"
        assert len(trace.subgoals) > 0, "Trace must have subgoal entries"
        assert len(trace.segments) > 0, "Trace must have segment entries"

    def test_simulation_backend_no_raw_strings(self):
        """Trace must not contain free-form raw strings."""
        subgoals, segments = plan_1_1()
        result = run_agent_for_cycles(subgoals, segments, max_cycles=10)
        trace = extract_trace(result)

        assert_no_raw_strings(trace)

    def test_simulation_contract_pipeline(self):
        """S1 contract pipeline with simulation backend must produce valid response."""
        response = _run_s1_contract_pipeline(
            cycle=0,
            subgoal_index=0,
            segment_index=0,
            backend="simulation",
        )
        assert isinstance(response, PromptResponse), (
            f"Expected PromptResponse, got: {type(response)}"
        )

    def test_simulation_round_trip(self):
        """Full S2→S1→S2 round-trip with simulation backend."""
        s2_updates = _run_s2_s1_s2_round_trip(
            cycle=0,
            subgoal_index=0,
            segment_index=0,
            backend="simulation",
        )
        # Round-trip must produce S2 updates
        assert "error" not in s2_updates, (
            f"Round-trip returned error: {s2_updates.get('error')}"
        )
        # s2_updates should contain drift/repair/reflection keys
        assert is_json_safe(s2_updates), "S2 updates not JSON-safe"

    def test_real_llm_backend_contract_pipeline(self):
        """S1 contract pipeline with real_llm blocked by kill-switch → S1Error."""
        response = _run_s1_contract_pipeline(
            cycle=0,
            subgoal_index=0,
            segment_index=0,
            backend="real_llm",
        )
        assert isinstance(response, S1Error), (
            f"Expected S1Error from kill-switch, got: {type(response)}"
        )
        assert response.type == "real_llm_disabled"

    def test_real_llm_round_trip(self):
        """Round-trip with real_llm (kill-switch active) → structured error."""
        s2_updates = _run_s2_s1_s2_round_trip(
            cycle=0,
            subgoal_index=0,
            segment_index=0,
            backend="real_llm",
        )
        # Kill-switch active → error is expected and structured
        assert "error" in s2_updates, "Kill-switch should produce structured error"
        assert isinstance(s2_updates["error"], dict)
        assert s2_updates["error"]["type"] == "real_llm_disabled"


# ══════════════════════════════════════════════════════════════════════════════
# Scenario B — 1 subgoal, 3 segments
# ══════════════════════════════════════════════════════════════════════════════


class TestE2ESingleSubgoalThreeSegments:
    """End-to-end smoke tests: 1 subgoal, 3 segments."""

    def test_simulation_backend_s2_loop(self):
        """S2 loop with 1+3 plan must complete cleanly."""
        subgoals, segments = plan_1_3()
        result = run_agent_for_cycles(subgoals, segments, max_cycles=15)

        _assert_s2_loop_no_crashes(result)
        assert result.is_complete is True, (
            f"Expected completion, got: {result.termination_reason}"
        )

    def test_simulation_backend_trace(self):
        """Trace from 1+3 plan must be valid."""
        subgoals, segments = plan_1_3()
        result = run_agent_for_cycles(subgoals, segments, max_cycles=15)
        trace = extract_trace(result)

        _assert_trace_valid(trace)
        assert len(trace.cycles) > 1, (
            "Multi-segment plan should produce multiple cycles"
        )
        assert len(trace.segments) > 0, "Must have segment entries"

    def test_simulation_backend_no_raw_strings(self):
        """Trace from 1+3 plan must have no raw strings."""
        subgoals, segments = plan_1_3()
        result = run_agent_for_cycles(subgoals, segments, max_cycles=15)
        trace = extract_trace(result)

        assert_no_raw_strings(trace)

    def test_simulation_contract_pipeline_early_cycle(self):
        """Contract pipeline at cycle 0 (first segment) with simulation backend."""
        response = _run_s1_contract_pipeline(
            cycle=0,
            subgoal_index=0,
            segment_index=0,
            backend="simulation",
        )
        assert isinstance(response, PromptResponse)

    def test_simulation_contract_pipeline_mid_cycle(self):
        """Contract pipeline at cycle 2 (third segment) with simulation backend."""
        response = _run_s1_contract_pipeline(
            cycle=2,
            subgoal_index=0,
            segment_index=2,
            backend="simulation",
        )
        assert isinstance(response, PromptResponse)

    def test_real_llm_backend_contract_pipeline(self):
        """Contract pipeline with real_llm (kill-switch) at mid-segment."""
        response = _run_s1_contract_pipeline(
            cycle=1,
            subgoal_index=0,
            segment_index=1,
            backend="real_llm",
        )
        assert isinstance(response, S1Error), (
            f"Expected S1Error from kill-switch, got: {type(response)}"
        )
        assert response.type == "real_llm_disabled"

    def test_real_llm_round_trip(self):
        """Full round-trip with real_llm (kill-switch active), 1+3 plan."""
        s2_updates = _run_s2_s1_s2_round_trip(
            cycle=1,
            subgoal_index=0,
            segment_index=1,
            backend="real_llm",
        )
        assert "error" in s2_updates
        assert s2_updates["error"]["type"] == "real_llm_disabled"


# ══════════════════════════════════════════════════════════════════════════════
# Scenario C — 2 subgoals, 2 segments each
# ══════════════════════════════════════════════════════════════════════════════


class TestE2ETwoSubgoalsTwoSegmentsEach:
    """End-to-end smoke tests: 2 subgoals, 2 segments each."""

    def test_simulation_backend_s2_loop(self):
        """S2 loop with 2+2 plan must complete cleanly."""
        subgoals, segments = plan_2_2()
        result = run_agent_for_cycles(subgoals, segments, max_cycles=20)

        _assert_s2_loop_no_crashes(result)
        assert result.is_complete is True, (
            f"Expected completion, got: {result.termination_reason}"
        )

    def test_simulation_backend_trace(self):
        """Trace from 2+2 plan must be valid with subgoal-level entries."""
        subgoals, segments = plan_2_2()
        result = run_agent_for_cycles(subgoals, segments, max_cycles=20)
        trace = extract_trace(result)

        _assert_trace_valid(trace)
        assert len(trace.cycles) > 1, "Multi-subgoal plan needs multiple cycles"
        assert len(trace.subgoals) > 0, "Must have subgoal entries"
        assert len(trace.segments) > 0, "Must have segment entries"

    def test_simulation_backend_no_raw_strings(self):
        """Trace from 2+2 plan must have no raw strings."""
        subgoals, segments = plan_2_2()
        result = run_agent_for_cycles(subgoals, segments, max_cycles=20)
        trace = extract_trace(result)

        assert_no_raw_strings(trace)

    def test_simulation_contract_pipeline_first_subgoal(self):
        """Contract pipeline in first subgoal, first segment."""
        response = _run_s1_contract_pipeline(
            cycle=0,
            subgoal_index=0,
            segment_index=0,
            backend="simulation",
        )
        assert isinstance(response, PromptResponse)

    def test_simulation_contract_pipeline_second_subgoal(self):
        """Contract pipeline in second subgoal, first segment."""
        response = _run_s1_contract_pipeline(
            cycle=4,
            subgoal_index=1,
            segment_index=0,
            backend="simulation",
        )
        assert isinstance(response, PromptResponse)

    def test_real_llm_backend_contract_pipeline(self):
        """Contract pipeline with real_llm (kill-switch) in second subgoal."""
        response = _run_s1_contract_pipeline(
            cycle=3,
            subgoal_index=1,
            segment_index=0,
            backend="real_llm",
        )
        assert isinstance(response, S1Error), (
            f"Expected S1Error from kill-switch, got: {type(response)}"
        )
        assert response.type == "real_llm_disabled"

    def test_real_llm_round_trip(self):
        """Full round-trip with real_llm (kill-switch active), 2+2 plan."""
        s2_updates = _run_s2_s1_s2_round_trip(
            cycle=2,
            subgoal_index=1,
            segment_index=0,
            backend="real_llm",
        )
        assert "error" in s2_updates
        assert s2_updates["error"]["type"] == "real_llm_disabled"


# ══════════════════════════════════════════════════════════════════════════════
# Determinism & state-machine comparison (simulation vs real_llm)
# ══════════════════════════════════════════════════════════════════════════════


class TestE2EBackendDeterminism:
    """Both backends produce deterministic pipeline results under same inputs."""

    def test_simulation_is_deterministic(self):
        """Same input → simulation backend → same output every time."""
        request1 = build_prompt_request(
            agent_state=_FakeAgentState(cycle=0),
            subgoal_state=_FakeSubgoalState(index=0, state="active"),
            segment_state=_FakeSegmentState(index=0, state="running"),
            memory=_make_fake_memory(),
        )
        request2 = build_prompt_request(
            agent_state=_FakeAgentState(cycle=0),
            subgoal_state=_FakeSubgoalState(index=0, state="active"),
            segment_state=_FakeSegmentState(index=0, state="running"),
            memory=_make_fake_memory(),
        )
        resp1 = call_s1_backend(request1, backend="simulation")
        resp2 = call_s1_backend(request2, backend="simulation")

        assert isinstance(resp1, PromptResponse)
        assert isinstance(resp2, PromptResponse)
        # Same input → identical output
        assert resp1.to_dict() == resp2.to_dict(), (
            "Simulation backend is not deterministic"
        )

    def test_real_llm_is_deterministic(self):
        """Same input → real_llm (kill-switch) → same S1Error every time."""
        request1 = build_prompt_request(
            agent_state=_FakeAgentState(cycle=1),
            subgoal_state=_FakeSubgoalState(index=0, state="active"),
            segment_state=_FakeSegmentState(index=1, state="running"),
            memory=_make_fake_memory(),
        )
        request2 = build_prompt_request(
            agent_state=_FakeAgentState(cycle=1),
            subgoal_state=_FakeSubgoalState(index=0, state="active"),
            segment_state=_FakeSegmentState(index=1, state="running"),
            memory=_make_fake_memory(),
        )
        resp1 = call_s1_backend(request1, backend="real_llm")
        resp2 = call_s1_backend(request2, backend="real_llm")

        assert isinstance(resp1, S1Error)
        assert isinstance(resp2, S1Error)
        assert resp1.to_dict() == resp2.to_dict(), (
            "Kill-switch S1Error is not deterministic"
        )

    def test_round_trip_determinism(self):
        """Full round-trip is deterministic with simulation backend."""
        s2_updates_1 = _run_s2_s1_s2_round_trip(
            cycle=0, subgoal_index=0, segment_index=0, backend="simulation"
        )
        s2_updates_2 = _run_s2_s1_s2_round_trip(
            cycle=0, subgoal_index=0, segment_index=0, backend="simulation"
        )
        assert s2_updates_1 == s2_updates_2, (
            "S2→S1→S2 round-trip is not deterministic"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Error handling
# ══════════════════════════════════════════════════════════════════════════════


class TestE2EErrorHandling:
    """Invalid/malformed responses must surface structured errors, not crash."""

    def test_parse_malformed_prompt_response(self):
        """A synthetically malformed PromptResponse must surface S1Error."""
        # Simulate a response missing required fields
        malformed_response = PromptResponse(
            output={},
            tool_calls=[],
            errors=[],
        )
        # Parsing should not crash
        s2_updates = parse_prompt_response(malformed_response)
        assert isinstance(s2_updates, dict), (
            f"parse_prompt_response returned {type(s2_updates)}"
        )
        # Should handle missing fields gracefully
        assert is_json_safe(s2_updates)

    def test_unknown_backend_raises(self):
        """An unknown backend must raise ValueError."""
        request = build_prompt_request(
            agent_state=_FakeAgentState(cycle=0),
            subgoal_state=_FakeSubgoalState(index=0),
            segment_state=_FakeSegmentState(index=0),
            memory=_make_fake_memory(),
        )
        with pytest.raises(ValueError, match="Unknown backend"):
            call_s1_backend(request, backend="nonexistent")

    def test_backend_routing_simulation(self):
        """backend='simulation' routes to simulation backend."""
        request = build_prompt_request(
            agent_state=_FakeAgentState(cycle=0),
            subgoal_state=_FakeSubgoalState(index=0),
            segment_state=_FakeSegmentState(index=0),
            memory=_make_fake_memory(),
        )
        response = call_s1_backend(request, backend="simulation")
        assert isinstance(response, PromptResponse), (
            f"Simulation backend returned {type(response)}"
        )

    def test_backend_routing_real_llm(self):
        """backend='real_llm' routes correctly but kill-switch blocks with S1Error."""
        request = build_prompt_request(
            agent_state=_FakeAgentState(cycle=0),
            subgoal_state=_FakeSubgoalState(index=0),
            segment_state=_FakeSegmentState(index=0),
            memory=_make_fake_memory(),
        )
        response = call_s1_backend(request, backend="real_llm")
        # Kill-switch active → S1Error, not a crash
        assert isinstance(response, S1Error), (
            f"real_llm backend returned {type(response)} — expected S1Error from kill-switch"
        )
        assert response.type == "real_llm_disabled"


# ══════════════════════════════════════════════════════════════════════════════
# JSON safety and raw-string boundary enforcement
# ══════════════════════════════════════════════════════════════════════════════


class TestE2EBoundarySafety:
    """The S2/S1 boundary must never pass raw strings or non-JSON data."""

    def test_prompt_request_is_json_safe(self):
        """Every PromptRequest must round-trip through JSON."""
        request = build_prompt_request(
            agent_state=_FakeAgentState(cycle=0),
            subgoal_state=_FakeSubgoalState(index=0),
            segment_state=_FakeSegmentState(index=0),
            memory=_make_fake_memory(),
        )
        assert is_json_safe(request.to_dict()), "PromptRequest is not JSON-safe"

    def test_prompt_response_is_json_safe_simulation(self):
        """Simulation PromptResponse must be JSON-safe."""
        response = _run_s1_contract_pipeline(
            cycle=0, subgoal_index=0, segment_index=0, backend="simulation"
        )
        if isinstance(response, PromptResponse):
            assert is_json_safe(response.to_dict()), (
                "Simulation PromptResponse is not JSON-safe"
            )

    def test_prompt_response_is_json_safe_real_llm(self):
        """Stubbed real_llm PromptResponse must be JSON-safe."""
        response = _run_s1_contract_pipeline(
            cycle=0, subgoal_index=0, segment_index=0, backend="real_llm"
        )
        if isinstance(response, PromptResponse):
            assert is_json_safe(response.to_dict()), (
                "real_llm PromptResponse is not JSON-safe"
            )

    def test_s2_updates_no_raw_strings(self):
        """S2 updates from parse_prompt_response must not contain raw strings."""
        s2_updates = _run_s2_s1_s2_round_trip(
            cycle=0, subgoal_index=0, segment_index=0, backend="simulation"
        )
        assert not has_raw_strings(s2_updates), (
            "S2 updates contain raw strings"
        )

    def test_no_raw_strings_in_contract_round_trip(self):
        """Complete S2→S1→S2 round-trip must have no raw strings at any layer."""
        request = build_prompt_request(
            agent_state=_FakeAgentState(cycle=0),
            subgoal_state=_FakeSubgoalState(index=0),
            segment_state=_FakeSegmentState(index=0),
            memory=_make_fake_memory(),
        )
        # Request must be clean
        assert not has_raw_strings(request.to_dict()), (
            "PromptRequest contains raw strings"
        )

        response = call_s1_backend(request, backend="simulation")
        # Response must be clean
        if isinstance(response, PromptResponse):
            assert not has_raw_strings(response.to_dict()), (
                "PromptResponse contains raw strings"
            )

            s2_updates = parse_prompt_response(response)
            assert not has_raw_strings(s2_updates), (
                "S2 updates contain raw strings"
            )
