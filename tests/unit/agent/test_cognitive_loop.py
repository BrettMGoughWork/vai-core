"""
Phase 5.3 — Cognitive Loop Unit Tests
======================================

Tests for the S5.3 cognitive loop orchestrator.

These tests verify:
- CognitiveLoopResult validation (happy + error paths)
- build_prompt_request() adapter mapping
- validate_prompt_response_for_s5() validation
- run_cognitive_loop() happy path (simulation backend)
- S1 error handling + retry
- Skill invocation via S3 adapter
- Max iterations guard
- Fallback on invalid response
- Edge: activated agent context, empty capabilities
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest

from src.agent.activation import (
    ActivatedAgentContext,
    ActivationContext,
    ActivationEnvelope,
)
from src.agent.cognitive_loop import (
    CONFIDENCE_FALLBACK,
    CognitiveLoopResult,
    _make_fallback_result,
    _produce_action_intents,
    _SAFE_FALLBACK_THOUGHT,
    build_prompt_request,
    run_cognitive_loop,
    validate_prompt_response_for_s5,
)
from src.agent.contracts import (
    ACTION_AGENT_STEP_INTENT,
    ACTION_CALL_TOOL_INTENT,
    ACTION_REQUEST_S4_JOB_INTENT,
    ActionIntent,
    AgentMessage,
)
from src.agent.registry import (
    CAP_CONVERSATIONAL,
    CAP_TOOL_USE,
    CAP_JOB_SUBMISSION,
    AgentConstraints,
    AgentIdentity,
    AgentMetadata,
    AgentRegistry,
)
from src.capabilities.contracts import SkillCallRequest, SkillResult
from src.strategy.planning.s1_contract.types import PromptRequest, PromptResponse, S1Error


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _make_identity(
    agent_id: str = "test-agent",
    name: str = "Test Agent",
) -> AgentIdentity:
    return AgentIdentity(
        agent_id=agent_id,
        name=name,
        description="A test agent",
        version="1.0.0",
    )


def _make_metadata(
    capabilities: Optional[List[str]] = None,
    agent_id: str = "test-agent",
    name: str = "Test Agent",
) -> AgentMetadata:
    return AgentMetadata(
        identity=_make_identity(agent_id=agent_id, name=name),
        capabilities=capabilities or [CAP_CONVERSATIONAL],
        inputs=["text"],
        outputs=["text", "action_intents"],
        constraints=AgentConstraints(max_tokens=4096, timeout_ms=30000),
    )


def _make_activated_context(
    message_text: str = "Hello",
    capabilities: Optional[List[str]] = None,
    agent_id: str = "test-agent",
    agent_name: str = "Test Agent",
) -> ActivatedAgentContext:
    """Build a minimal ``ActivatedAgentContext`` for tests."""
    metadata = _make_metadata(
        capabilities=capabilities or [CAP_CONVERSATIONAL],
        agent_id=agent_id,
        name=agent_name,
    )
    msg = AgentMessage(
        message=message_text,
        context={"channel": "cli"},
        capabilities=capabilities or [CAP_CONVERSATIONAL],
    )
    registry = AgentRegistry()
    from src.agent.activation import activate_agent
    return activate_agent(agent_id, msg, registry)


def _make_activated_context_from_scratch(
    agent_id: str = "test-agent",
    message_text: str = "Hello",
    capabilities: Optional[List[str]] = None,
) -> ActivatedAgentContext:
    """Build context without relying on activate_agent for isolation."""
    caps = capabilities or [CAP_CONVERSATIONAL]
    metadata = _make_metadata(capabilities=caps, agent_id=agent_id)
    msg = AgentMessage(
        message=message_text,
        context={"channel": "cli"},
        capabilities=caps,
    )
    env = ActivationEnvelope(
        agent_id=agent_id,
        message=msg,
        activation_context={
            "timestamp": "2024-01-01T00:00:00Z",
            "channel": "cli",
            "correlation_id": str(uuid.uuid4()),
            "trace_id": str(uuid.uuid4()),
        },
    )
    ctx = ActivationContext(
        agent_metadata=metadata,
        resolved_capabilities=caps,
        conversation_history=[],
        system_constraints={"max_tokens": 4096, "timeout_ms": 30000, "sandbox": "none"},
    )
    return ActivatedAgentContext(envelope=env, context=ctx)


# ══════════════════════════════════════════════════════════════════════════════
# CognitiveLoopResult validation
# ══════════════════════════════════════════════════════════════════════════════


class TestCognitiveLoopResultValidation:
    """CognitiveLoopResult is a frozen dataclass with __post_init__ validation."""

    def test_happy_path(self):
        result = CognitiveLoopResult(
            thought={"is_complete": True, "reasoning": "done"},
            action_intents=[
                ActionIntent(
                    type=ACTION_AGENT_STEP_INTENT,
                    payload={"reasoning": "conversational_reply"},
                )
            ],
            confidence=0.95,
            errors=[],
            iteration_count=1,
        )
        assert result.thought["is_complete"] is True
        assert len(result.action_intents) == 1
        assert result.confidence == 0.95
        assert result.iteration_count == 1

    def test_defaults(self):
        result = CognitiveLoopResult()
        assert result.thought == {}
        assert result.action_intents == []
        assert result.skill_results == []
        assert result.confidence == CONFIDENCE_FALLBACK
        assert result.errors == []
        assert result.iteration_count == 0

    def test_thought_must_be_dict(self):
        with pytest.raises(ValueError, match="thought must be a dict"):
            CognitiveLoopResult(thought="not a dict")  # type: ignore

    def test_action_intents_must_be_list(self):
        with pytest.raises(ValueError, match="action_intents must be a list"):
            CognitiveLoopResult(action_intents="not a list")  # type: ignore

    def test_confidence_out_of_range_high(self):
        with pytest.raises(ValueError, match="confidence must be in"):
            CognitiveLoopResult(confidence=1.5)

    def test_confidence_out_of_range_low(self):
        with pytest.raises(ValueError, match="confidence must be in"):
            CognitiveLoopResult(confidence=-0.1)

    def test_iteration_count_negative(self):
        with pytest.raises(ValueError, match="iteration_count must be >= 0"):
            CognitiveLoopResult(iteration_count=-1)


# ══════════════════════════════════════════════════════════════════════════════
# build_prompt_request
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildPromptRequest:
    """S5→S1 adapter: maps ActivatedAgentContext → PromptRequest."""

    def test_happy_path(self):
        ctx = _make_activated_context_from_scratch(
            agent_id="my-agent",
            message_text="What can you do?",
            capabilities=[CAP_CONVERSATIONAL, CAP_TOOL_USE],
        )
        request = build_prompt_request(ctx)

        assert isinstance(request, PromptRequest)
        assert request.prompt["agent_id"] == "my-agent"
        assert request.prompt["message"] == "What can you do?"
        assert CAP_CONVERSATIONAL in request.prompt["capabilities"]
        assert CAP_TOOL_USE in request.prompt["capabilities"]
        assert request.memory == {"conversation_history": []}
        assert request.tool_context == []

    def test_plan_context_contains_metadata(self):
        ctx = _make_activated_context_from_scratch(agent_id="agent-x")
        request = build_prompt_request(ctx)

        pc = request.plan_context
        assert pc["agent_metadata"]["name"] == "Test Agent"
        assert pc["agent_metadata"]["description"] == "A test agent"
        assert pc["routing_hints"] == {}
        assert pc["channel_metadata"] == {}

    def test_conversation_history_included(self):
        history = [{"role": "user", "content": "hi"}]
        msg = AgentMessage(
            message="Hello",
            context={"channel": "cli"},
            capabilities=[CAP_CONVERSATIONAL],
        )
        metadata = _make_metadata(capabilities=[CAP_CONVERSATIONAL])
        env = ActivationEnvelope(
            agent_id="test-agent",
            message=msg,
            activation_context={
                "timestamp": "2024-01-01T00:00:00Z",
                "channel": "cli",
                "correlation_id": str(uuid.uuid4()),
                "trace_id": str(uuid.uuid4()),
            },
        )
        ctx = ActivationContext(
            agent_metadata=metadata,
            resolved_capabilities=[CAP_CONVERSATIONAL],
            conversation_history=history,
            system_constraints={"max_tokens": 0, "timeout_ms": 0, "sandbox": "none"},
        )
        context = ActivatedAgentContext(envelope=env, context=ctx)
        request = build_prompt_request(context)

        assert request.memory["conversation_history"] == history

    def test_serialises_to_json_safe(self):
        ctx = _make_activated_context_from_scratch()
        request = build_prompt_request(ctx)
        # Should not raise
        json.dumps(request.to_dict())


# ══════════════════════════════════════════════════════════════════════════════
# validate_prompt_response_for_s5
# ══════════════════════════════════════════════════════════════════════════════


class TestValidatePromptResponseForS5:
    """S5-specific PromptResponse validation (lighter than S2's)."""

    def test_valid_response(self):
        response = PromptResponse(
            output={"is_complete": True, "confidence": 0.9},
        )
        assert validate_prompt_response_for_s5(response) is True

    def test_none_response(self):
        assert validate_prompt_response_for_s5(None) is False  # type: ignore

    def test_non_dict_output(self):
        response = PromptResponse(output="not a dict")  # type: ignore
        assert validate_prompt_response_for_s5(response) is False

    def test_empty_output_dict(self):
        response = PromptResponse(output={})
        # Valid — empty dict is still a dict and JSON-safe
        assert validate_prompt_response_for_s5(response) is True

    def test_non_json_safe_output(self):
        response = PromptResponse(output={"bad": object()})  # type: ignore
        assert validate_prompt_response_for_s5(response) is False


# ══════════════════════════════════════════════════════════════════════════════
# _produce_action_intents
# ══════════════════════════════════════════════════════════════════════════════


class TestProduceActionIntents:
    """Action intent production from model thought + capabilities."""

    def test_is_complete_produces_step_intent(self):
        intents = _produce_action_intents(
            {"is_complete": True},
            [CAP_CONVERSATIONAL, CAP_TOOL_USE],
        )
        assert len(intents) == 1
        assert intents[0].type == ACTION_AGENT_STEP_INTENT
        assert intents[0].payload["reasoning"] == "conversational_reply"

    def test_conversational_capability(self):
        intents = _produce_action_intents(
            {"is_complete": False},
            [CAP_CONVERSATIONAL],
        )
        assert len(intents) >= 1
        assert intents[0].type == ACTION_AGENT_STEP_INTENT

    def test_tool_use_capability(self):
        intents = _produce_action_intents(
            {"is_complete": False},
            [CAP_TOOL_USE],
        )
        types = {i.type for i in intents}
        assert ACTION_CALL_TOOL_INTENT in types

    def test_job_submission_capability(self):
        intents = _produce_action_intents(
            {"is_complete": False},
            [CAP_JOB_SUBMISSION],
        )
        types = {i.type for i in intents}
        assert ACTION_REQUEST_S4_JOB_INTENT in types

    def test_fallback_with_no_capabilities(self):
        intents = _produce_action_intents(
            {"is_complete": False},
            [],
        )
        assert len(intents) == 1
        assert intents[0].type == ACTION_AGENT_STEP_INTENT

    def test_multiple_capabilities_produce_multiple_intents(self):
        intents = _produce_action_intents(
            {"is_complete": False},
            [CAP_TOOL_USE, CAP_JOB_SUBMISSION],
        )
        types = {i.type for i in intents}
        assert ACTION_CALL_TOOL_INTENT in types
        assert ACTION_REQUEST_S4_JOB_INTENT in types


# ══════════════════════════════════════════════════════════════════════════════
# run_cognitive_loop — happy path
# ══════════════════════════════════════════════════════════════════════════════


class TestRunCognitiveLoopHappyPath:
    """Cognitive loop with simulation backend — normal execution."""

    def test_basic_execution(self):
        """Happy path: loop produces a CognitiveLoopResult."""
        ctx = _make_activated_context_from_scratch(
            agent_id="test-agent",
            message_text="Hello",
            capabilities=[CAP_CONVERSATIONAL],
        )
        result = run_cognitive_loop(ctx)

        assert isinstance(result, CognitiveLoopResult)
        assert result.thought != {}
        assert len(result.action_intents) >= 1
        assert result.confidence > 0.0
        assert result.errors == []
        assert result.iteration_count >= 1

    def test_action_intents_are_valid(self):
        """All produced action intents pass validation."""
        ctx = _make_activated_context_from_scratch(
            capabilities=[CAP_CONVERSATIONAL, CAP_TOOL_USE],
        )
        result = run_cognitive_loop(ctx)

        for intent in result.action_intents:
            assert intent.type in ("call_tool_intent", "request_s4_job_intent", "agent_step_intent")

    def test_includes_thought_from_simulation(self):
        """Thought contains the simulation backend output."""
        ctx = _make_activated_context_from_scratch()
        result = run_cognitive_loop(ctx)

        assert "is_complete" in result.thought
        assert "confidence" in result.thought

    def test_respects_max_iterations(self):
        """Loop respects the max_iterations bound."""
        ctx = _make_activated_context_from_scratch()
        result = run_cognitive_loop(ctx, max_iterations=1)

        assert result.iteration_count <= 1

    def test_type_error_on_bad_context(self):
        """Raises TypeError if context is not ActivatedAgentContext."""
        with pytest.raises(TypeError, match="context must be an ActivatedAgentContext"):
            run_cognitive_loop("not a context")  # type: ignore

    def test_value_error_on_bad_max_iterations(self):
        """Raises ValueError if max_iterations < 1."""
        ctx = _make_activated_context_from_scratch()
        with pytest.raises(ValueError, match="max_iterations must be >= 1"):
            run_cognitive_loop(ctx, max_iterations=0)


# ══════════════════════════════════════════════════════════════════════════════
# run_cognitive_loop — error handling
# ══════════════════════════════════════════════════════════════════════════════


class TestRunCognitiveLoopErrors:
    """Cognitive loop handles S1 errors gracefully (never crashes)."""

    def test_s1_error_fallback(self):
        """When S1 returns S1Error, the loop falls back to safe result."""
        ctx = _make_activated_context_from_scratch()

        with mock.patch(
            "src.agent.cognitive_loop.call_runtime_backend",
            return_value=S1Error(
                type="timeout",
                message="S1 timed out",
            ),
        ):
            result = run_cognitive_loop(ctx)

        assert result.errors != []
        # Fallback should still have a thought and action intents
        assert result.thought != {}
        assert len(result.action_intents) >= 1
        assert result.confidence == 0.0

    def test_s1_error_retry_then_succeed(self):
        """S1 error triggers a retry; if retry succeeds, loop continues."""
        ctx = _make_activated_context_from_scratch()
        from src.runtime.interfaces import call_runtime_backend

        # Build a PromptRequest and call the real backend for a success response
        request = build_prompt_request(ctx)
        success_response = call_runtime_backend(request, backend="simulation")

        call_count: list[int] = [0]

        def _side_effect(req, backend="simulation"):
            call_count[0] += 1
            if call_count[0] == 1:
                return S1Error(type="timeout", message="First attempt failed")
            return success_response

        with mock.patch(
            "src.agent.cognitive_loop.call_runtime_backend",
            side_effect=_side_effect,
        ):
            result = run_cognitive_loop(ctx)

        # Should have succeeded after retry
        assert result.thought != {}
        assert result.errors == []  # retry succeeded, no persistent error

    def test_invalid_response_fallback(self):
        """When S1 returns an invalid (non-JSON-safe) response, fallback."""
        ctx = _make_activated_context_from_scratch()

        with mock.patch(
            "src.agent.cognitive_loop.call_runtime_backend",
            return_value=PromptResponse(output={"bad": object()}),
        ):
            result = run_cognitive_loop(ctx)

        assert len(result.errors) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# run_cognitive_loop — skill invocation
# ══════════════════════════════════════════════════════════════════════════════


class FakeSkillRunner:
    """Deterministic fake SkillRunner for testing S5→S3 adapter."""

    def __init__(self):
        self.calls: List[SkillCallRequest] = []

    def execute(self, request: SkillCallRequest) -> SkillResult:
        self.calls.append(request)
        return SkillResult(
            request_id=request.request_id,
            success=True,
            output={"result": f"executed {request.skill_name}"},
        )


class TestRunCognitiveLoopSkills:
    """Cognitive loop can invoke skills via S3 adapter."""

    def test_skill_not_invoked_without_runner(self):
        """Without a SkillRunner, skills are not invoked (no crash)."""
        ctx = _make_activated_context_from_scratch()
        result = run_cognitive_loop(ctx, skill_runner=None)
        assert result.skill_results == []

    def test_skill_not_invoked_when_no_skill_refs(self):
        """With a SkillRunner but no skill_refs in thought, no skills called."""
        runner = FakeSkillRunner()
        ctx = _make_activated_context_from_scratch()
        result = run_cognitive_loop(ctx, skill_runner=runner)

        assert runner.calls == []  # no skill_refs in simulation output
        assert result.skill_results == []

    def test_skill_refs_in_thought_triggers_invocation(self):
        """When thought contains skill_refs, S5→S3 adapter invokes them."""
        runner = FakeSkillRunner()
        ctx = _make_activated_context_from_scratch()

        # Inject skill_refs into the simulation output by patching call_runtime_backend
        skill_response = PromptResponse(
            output={
                "is_complete": True,
                "confidence": 0.9,
                "skill_refs": [
                    {"skill_name": "test_skill", "arguments": {"arg1": "val1"}},
                ],
            },
        )

        with mock.patch(
            "src.agent.cognitive_loop.call_runtime_backend",
            return_value=skill_response,
        ):
            result = run_cognitive_loop(ctx, skill_runner=runner)

        assert len(runner.calls) == 1
        assert runner.calls[0].skill_name == "test_skill"
        assert runner.calls[0].arguments == {"arg1": "val1"}
        assert len(result.skill_results) == 1
        assert result.skill_results[0]["success"] is True

    def test_skill_invocation_failure_does_not_crash_loop(self):
        """When a skill call fails, the loop logs the error and continues."""
        class FailingSkillRunner:
            def execute(self, request):
                return SkillResult(
                    request_id=request.request_id,
                    success=False,
                    error="Skill crashed",
                )

        ctx = _make_activated_context_from_scratch()
        skill_response = PromptResponse(
            output={
                "is_complete": True,
                "confidence": 0.9,
                "skill_refs": [
                    {"skill_name": "failing_skill", "arguments": {}},
                ],
            },
        )

        with mock.patch(
            "src.agent.cognitive_loop.call_runtime_backend",
            return_value=skill_response,
        ):
            result = run_cognitive_loop(ctx, skill_runner=FailingSkillRunner())

        assert len(result.skill_results) == 1
        assert result.skill_results[0]["success"] is False


# ══════════════════════════════════════════════════════════════════════════════
# _make_fallback_result
# ══════════════════════════════════════════════════════════════════════════════


class TestMakeFallbackResult:
    """Fallback result factory produces safe outputs."""

    def test_fallback_has_safe_thought(self):
        result = _make_fallback_result([{"type": "error", "message": "something failed"}])
        assert result.thought == _SAFE_FALLBACK_THOUGHT
        assert result.confidence == 0.0
        assert len(result.errors) == 1
        assert result.iteration_count == 0

    def test_fallback_has_action_intent(self):
        result = _make_fallback_result([])
        assert len(result.action_intents) == 1
        assert result.action_intents[0].type == ACTION_AGENT_STEP_INTENT


# ══════════════════════════════════════════════════════════════════════════════
# Integration: full stack
# ══════════════════════════════════════════════════════════════════════════════


class TestIntegration:
    """End-to-end: wire S5.0 + S5.1 + S5.2 + S5.3 together."""

    def test_activate_then_cognitive_loop(self):
        """Full flow: register → activate → cognitive loop."""
        # Register
        registry = AgentRegistry()
        metadata = _make_metadata(
            agent_id="integration-agent",
            name="Integration Agent",
            capabilities=[CAP_CONVERSATIONAL, CAP_TOOL_USE],
        )
        registry.register_agent(metadata)

        # Activate
        message = AgentMessage(
            message="Run integration test",
            context={"channel": "cli"},
            capabilities=[CAP_CONVERSATIONAL, CAP_TOOL_USE],
        )
        from src.agent.activation import activate_agent

        context = activate_agent(
            agent_id="integration-agent",
            message=message,
            registry=registry,
            channel="cli",
        )

        # Cognitive loop
        result = run_cognitive_loop(context)

        assert isinstance(result, CognitiveLoopResult)
        assert result.thought != {}
        assert len(result.action_intents) >= 1
        assert result.iteration_count >= 1

        # Should have at least one tool use intent
        types = {i.type for i in result.action_intents}
        assert ACTION_CALL_TOOL_INTENT in types or ACTION_AGENT_STEP_INTENT in types

    def test_deterministic_output(self):
        """Same inputs should produce same outputs (simulation backend)."""
        ctx = _make_activated_context_from_scratch(
            agent_id="deterministic-test",
            message_text="Test determinism",
            capabilities=[CAP_CONVERSATIONAL],
        )

        result1 = run_cognitive_loop(ctx)
        result2 = run_cognitive_loop(ctx)

        # Both should have the same structure and values
        assert result1.thought == result2.thought
        assert result1.action_intents == result2.action_intents
        assert result1.confidence == result2.confidence
