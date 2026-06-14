"""
Phase 5.4 — Agent → Platform Job Interface Unit Tests
======================================================

Tests for ``JobDispatchResult`` and ``dispatch_action_intents()``.

These tests verify:
- ``JobDispatchResult`` structure and defaults
- ``dispatch_action_intents()`` happy path (CALL_TOOL, S4_JOB, AGENT_STEP)
- error handling (S1 errors, unsupported intents, missing submitter, submitter raises)
- the ``_translate_intent_to_channel_message`` translation fidelity
"""

from __future__ import annotations

from typing import Any, Dict
from unittest import mock

import pytest

from src.agent.activation import (
    ActivatedAgentContext,
    ActivationContext,
    ActivationEnvelope,
)
from src.agent.cognitive_loop import CognitiveLoopResult
from src.agent.contracts import (
    ACTION_AGENT_STEP_INTENT,
    ACTION_CALL_TOOL_INTENT,
    ACTION_REQUEST_S4_JOB_INTENT,
    ActionIntent,
    AgentMessage,
)
from src.agent.job_interface import (
    JobDispatchResult,
    _translate_intent_to_channel_message,
    dispatch_action_intents,
)
from src.agent.registry import (
    CAP_CONVERSATIONAL,
    CAP_JOB_SUBMISSION,
    CAP_TOOL_USE,
    AgentConstraints,
    AgentIdentity,
    AgentMetadata,
)
from src.platform.transport.normalization import ChannelMessage


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
    capabilities: list[str] | None = None,
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
    agent_id: str = "test-agent",
    channel: str = "cli",
    capabilities: list[str] | None = None,
) -> ActivatedAgentContext:
    caps = capabilities or [CAP_CONVERSATIONAL]
    metadata = _make_metadata(capabilities=caps, agent_id=agent_id)
    msg = AgentMessage(
        message="Hello",
        context={"channel": channel},
        capabilities=caps,
    )
    env = ActivationEnvelope(
        agent_id=agent_id,
        message=msg,
        activation_context={
            "timestamp": "2024-01-01T00:00:00Z",
            "channel": channel,
            "correlation_id": "test-correlation-id",
            "trace_id": "test-trace-id",
        },
    )
    ctx = ActivationContext(
        agent_metadata=metadata,
        resolved_capabilities=caps,
        conversation_history=[],
        system_constraints={
            "max_tokens": 4096,
            "timeout_ms": 30000,
            "sandbox": "none",
        },
    )
    return ActivatedAgentContext(envelope=env, context=ctx)


def _make_call_tool_intent(tool: str = "test_tool") -> ActionIntent:
    return ActionIntent(
        type=ACTION_CALL_TOOL_INTENT,
        payload={"tool": tool, "args": {"key": "value"}},
    )


def _make_s4_job_intent(job_type: str = "test_job") -> ActionIntent:
    return ActionIntent(
        type=ACTION_REQUEST_S4_JOB_INTENT,
        payload={"job_type": job_type, "params": {"key": "value"}},
    )


def _make_step_intent() -> ActionIntent:
    return ActionIntent(
        type=ACTION_AGENT_STEP_INTENT,
        payload={"reasoning": "conversational_reply"},
    )


# ══════════════════════════════════════════════════════════════════════════════
# JobDispatchResult validation
# ══════════════════════════════════════════════════════════════════════════════


class TestJobDispatchResult:
    """JobDispatchResult is a frozen dataclass with sensible defaults."""

    def test_defaults(self):
        """Fully default-constructed result."""
        result = JobDispatchResult()
        assert result.dispatched_jobs == {}
        assert result.terminal_intents == []
        assert result.errors == []

    def test_happy_path(self):
        """Result with all fields populated."""
        intent = _make_step_intent()
        result = JobDispatchResult(
            dispatched_jobs={"job-1": _make_call_tool_intent()},
            terminal_intents=[intent],
            errors=[("ACTION_AGENT_STEP_INTENT", "something went wrong")],
        )
        assert len(result.dispatched_jobs) == 1
        assert result.terminal_intents == [intent]
        assert len(result.errors) == 1
        assert result.errors[0][0] == "ACTION_AGENT_STEP_INTENT"

    def test_is_frozen(self):
        """Cannot mutate fields after construction."""
        result = JobDispatchResult()
        with pytest.raises(AttributeError):
            result.dispatched_jobs = {}  # type: ignore[misc]


# ══════════════════════════════════════════════════════════════════════════════
# dispatch_action_intents — Happy paths
# ══════════════════════════════════════════════════════════════════════════════


class TestDispatchHappyPath:
    """dispatch_action_intents() dispatches supported intents correctly."""

    def test_call_tool_intent_dispatched(self):
        """ACTION_CALL_TOOL_INTENT → job submitted → in dispatched_jobs."""
        context = _make_activated_context(capabilities=[CAP_CONVERSATIONAL, CAP_TOOL_USE])
        intent = _make_call_tool_intent()
        result = CognitiveLoopResult(
            thought={"is_complete": False, "reasoning": "call a tool"},
            action_intents=[intent],
            confidence=0.9,
        )

        submitter = mock.Mock(return_value="job-123")
        dispatch_result = dispatch_action_intents(result, context, submit_job_callable=submitter)

        assert len(dispatch_result.dispatched_jobs) == 1
        assert "job-123" in dispatch_result.dispatched_jobs
        assert dispatch_result.dispatched_jobs["job-123"] is intent
        assert dispatch_result.terminal_intents == []
        assert dispatch_result.errors == []
        submitter.assert_called_once()

    def test_s4_job_intent_dispatched(self):
        """ACTION_REQUEST_S4_JOB_INTENT → job submitted → in dispatched_jobs."""
        context = _make_activated_context(capabilities=[CAP_CONVERSATIONAL, CAP_JOB_SUBMISSION])
        intent = _make_s4_job_intent()
        result = CognitiveLoopResult(
            thought={"is_complete": False, "reasoning": "submit a job"},
            action_intents=[intent],
            confidence=0.85,
        )

        submitter = mock.Mock(return_value="job-456")
        dispatch_result = dispatch_action_intents(result, context, submit_job_callable=submitter)

        assert len(dispatch_result.dispatched_jobs) == 1
        assert dispatch_result.dispatched_jobs["job-456"] is intent
        assert dispatch_result.errors == []
        submitter.assert_called_once()

    def test_step_intent_is_terminal(self):
        """ACTION_AGENT_STEP_INTENT → no job → goes to terminal_intents."""
        context = _make_activated_context()
        intent = _make_step_intent()
        result = CognitiveLoopResult(
            thought={"is_complete": True, "reasoning": "done"},
            action_intents=[intent],
            confidence=0.95,
        )

        dispatch_result = dispatch_action_intents(result, context, submit_job_callable=mock.Mock())

        assert dispatch_result.dispatched_jobs == {}
        assert dispatch_result.terminal_intents == [intent]
        assert dispatch_result.errors == []

    def test_multiple_intents_mixed(self):
        """Mixed intents are dispatched correctly."""
        context = _make_activated_context(capabilities=[CAP_CONVERSATIONAL, CAP_TOOL_USE, CAP_JOB_SUBMISSION])
        tool_intent = _make_call_tool_intent()
        job_intent = _make_s4_job_intent()
        step_intent = _make_step_intent()

        result = CognitiveLoopResult(
            thought={"is_complete": False, "reasoning": "various work"},
            action_intents=[tool_intent, step_intent, job_intent],
            confidence=0.8,
        )

        submitter = mock.Mock(side_effect=["job-001", "job-002"])
        dispatch_result = dispatch_action_intents(result, context, submit_job_callable=submitter)

        assert len(dispatch_result.dispatched_jobs) == 2
        assert dispatch_result.terminal_intents == [step_intent]
        assert dispatch_result.errors == []

    def test_empty_intents(self):
        """Empty intent list → everything empty."""
        context = _make_activated_context()
        result = CognitiveLoopResult(
            thought={"is_complete": True, "reasoning": "nothing to do"},
            action_intents=[],
            confidence=1.0,
        )

        dispatch_result = dispatch_action_intents(result, context, submit_job_callable=mock.Mock())

        assert dispatch_result.dispatched_jobs == {}
        assert dispatch_result.terminal_intents == []
        assert dispatch_result.errors == []


# ══════════════════════════════════════════════════════════════════════════════
# dispatch_action_intents — Error & edge-case paths
# ══════════════════════════════════════════════════════════════════════════════


class TestDispatchErrors:
    """dispatch_action_intents() handles errors gracefully."""

    def test_cognitive_loop_errors_returns_early(self):
        """If CognitiveLoopResult has errors, dispatch returns them immediately."""
        context = _make_activated_context()
        result = CognitiveLoopResult(
            thought={"is_complete": False, "reasoning": "errored"},
            action_intents=[],
            confidence=0.0,
            errors=[ValueError("S1 failed"), RuntimeError("timeout")],
        )

        dispatch_result = dispatch_action_intents(
            result,
            context,
            submit_job_callable=mock.Mock(),
        )

        assert dispatch_result.dispatched_jobs == {}
        assert dispatch_result.terminal_intents == []
        assert len(dispatch_result.errors) == 2
        assert all(e[0] == "cognitive_loop" for e in dispatch_result.errors)

    def test_submitter_raises_error(self):
        """submitter exception → error recorded, dispatch continues."""
        context = _make_activated_context()
        intents = [
            _make_call_tool_intent("tool_1"),
            _make_call_tool_intent("tool_2"),
        ]
        result = CognitiveLoopResult(
            thought={"is_complete": False, "reasoning": "call two tools"},
            action_intents=intents,
            confidence=0.9,
        )

        def _failing_submitter(msg: ChannelMessage) -> str:
            action_intent = msg.input.get("action_intent", {})
            if isinstance(action_intent, dict) and action_intent.get("payload", {}).get("tool") == "tool_1":
                raise RuntimeError("Queue full")
            return "job-002"

        dispatch_result = dispatch_action_intents(
            result, context, submit_job_callable=_failing_submitter,
        )

        assert len(dispatch_result.dispatched_jobs) == 1
        assert len(dispatch_result.errors) == 1
        assert dispatch_result.errors[0][0] == ACTION_CALL_TOOL_INTENT
        assert "Queue full" in dispatch_result.errors[0][1]

    def test_no_submitter_provided(self):
        """No submitter → error for actionable intents."""
        context = _make_activated_context()
        intent = _make_call_tool_intent()
        result = CognitiveLoopResult(
            thought={"is_complete": False, "reasoning": "need to call tool"},
            action_intents=[intent],
            confidence=0.9,
        )

        dispatch_result = dispatch_action_intents(result, context, submit_job_callable=None)

        assert dispatch_result.dispatched_jobs == {}
        assert len(dispatch_result.errors) == 1
        assert "No submit_job_callable provided" in dispatch_result.errors[0][1]
        assert dispatch_result.errors[0][0] == ACTION_CALL_TOOL_INTENT

    def test_unsupported_intent_type(self):
        """Unknown intent type → error recorded."""
        context = _make_activated_context()
        # Bypass frozen dataclass + validation to test unsupported type handling.
        bad_intent = object.__new__(ActionIntent)
        object.__setattr__(bad_intent, "type", "UNKNOWN_INTENT_TYPE")
        object.__setattr__(bad_intent, "payload", {})
        object.__setattr__(bad_intent, "description", "")
        result = CognitiveLoopResult(
            thought={"is_complete": False, "reasoning": "unknown intent"},
            action_intents=[bad_intent],
            confidence=0.5,
        )

        dispatch_result = dispatch_action_intents(
            result, context, submit_job_callable=mock.Mock(),
        )

        assert dispatch_result.dispatched_jobs == {}
        assert len(dispatch_result.errors) == 1
        assert "Unsupported intent type" in dispatch_result.errors[0][1]

    def test_no_submitter_and_step_intent_ok(self):
        """Step intents are terminal even without a submitter."""
        context = _make_activated_context()
        step_intent = _make_step_intent()
        result = CognitiveLoopResult(
            thought={"is_complete": True, "reasoning": "done"},
            action_intents=[step_intent],
            confidence=0.95,
        )

        dispatch_result = dispatch_action_intents(result, context, submit_job_callable=None)

        assert dispatch_result.terminal_intents == [step_intent]
        assert dispatch_result.dispatched_jobs == {}
        assert dispatch_result.errors == []


# ══════════════════════════════════════════════════════════════════════════════
# Channel message translation
# ══════════════════════════════════════════════════════════════════════════════


class TestChannelMessageTranslation:
    """The internal ``_translate_intent_to_channel_message`` produces correct
    ``ChannelMessage`` instances."""

    def test_channel_from_context(self):
        """Channel is sourced from the activation context."""
        ctx = _make_activated_context(channel="http")
        intent = _make_call_tool_intent()
        msg = _translate_intent_to_channel_message(intent, ctx)
        assert msg.channel == "http"

    def test_default_channel_when_missing(self):
        """Falls back to 'system' if channel is absent in context."""
        metadata = _make_metadata()
        agent_msg = AgentMessage(
            message="Hi",
            context={},
            capabilities=[CAP_CONVERSATIONAL],
        )
        env = ActivationEnvelope(
            agent_id="test-agent",
            message=agent_msg,
            activation_context={
                "timestamp": "2024-01-01T00:00:00Z",
                # no "channel" key
                "correlation_id": "test-correlation-id",
                "trace_id": "test-trace-id",
            },
        )
        ctx = ActivationContext(
            agent_metadata=metadata,
            resolved_capabilities=[CAP_CONVERSATIONAL],
            conversation_history=[],
            system_constraints={},
        )
        aac = ActivatedAgentContext(envelope=env, context=ctx)
        intent = _make_call_tool_intent()
        result = _translate_intent_to_channel_message(intent, aac)
        assert result.channel == "system"

    def test_source_in_metadata(self):
        """Source is set in metadata, derived from agent_id."""
        ctx = _make_activated_context(agent_id="my-custom-agent")
        intent = _make_call_tool_intent()
        msg = _translate_intent_to_channel_message(intent, ctx)
        assert msg.metadata.get("source") == "agent/my-custom-agent"

    def test_intent_serialised_in_input(self):
        """The action intent is serialised into the message input."""
        ctx = _make_activated_context()
        intent = _make_call_tool_intent(tool="my_tool")
        msg = _translate_intent_to_channel_message(intent, ctx)
        assert "action_intent" in msg.input
        assert msg.input["action_intent"]["payload"]["tool"] == "my_tool"

    def test_intent_contains_correct_type(self):
        """Serialised intent includes the original action type."""
        ctx = _make_activated_context()
        plain_intent = ActionIntent(
            type=ACTION_CALL_TOOL_INTENT,
            payload={"tool": "plain"},
        )
        msg = _translate_intent_to_channel_message(plain_intent, ctx)
        assert msg.input["action_intent"]["type"] == ACTION_CALL_TOOL_INTENT
