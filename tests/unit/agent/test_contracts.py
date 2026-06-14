"""
Tests for Phase 5.0 — S5 Conversational Response Contract.

Covers AgentMessage, AgentResponse, ActionIntent, and the JSON‑compatibility
validator.  S5 emits only declarative intents — never executable instructions,
S1 schemas, S4 envelopes, or planner structures.
"""

from __future__ import annotations

import pytest

from src.agent.contracts import (
    ACTION_AGENT_STEP_INTENT,
    ACTION_CALL_TOOL_INTENT,
    ACTION_REQUEST_S4_JOB_INTENT,
    S5_CONTRACT_VERSION,
    ActionIntent,
    AgentMessage,
    AgentResponse,
)


# ===========================================================================
# ActionIntent
# ===========================================================================


class TestActionIntent:
    def test_call_tool_intent(self) -> None:
        intent = ActionIntent(
            type=ACTION_CALL_TOOL_INTENT,
            payload={"tool": "read_file", "args": {"path": "/tmp/x"}},
            description="Read a file",
        )
        assert intent.type == ACTION_CALL_TOOL_INTENT
        assert intent.payload["tool"] == "read_file"
        assert intent.description == "Read a file"

    def test_request_s4_job_intent(self) -> None:
        intent = ActionIntent(
            type=ACTION_REQUEST_S4_JOB_INTENT,
            payload={"job_type": "execute", "params": {"cmd": "ls"}},
        )
        assert intent.type == ACTION_REQUEST_S4_JOB_INTENT
        assert intent.payload["job_type"] == "execute"

    def test_agent_step_intent(self) -> None:
        intent = ActionIntent(
            type=ACTION_AGENT_STEP_INTENT,
            payload={"steps": ["analyze", "summarize"]},
        )
        assert intent.type == ACTION_AGENT_STEP_INTENT

    def test_default_payload_and_description(self) -> None:
        intent = ActionIntent(type=ACTION_CALL_TOOL_INTENT)
        assert intent.payload == {}
        assert intent.description == ""

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="action_intent.type"):
            ActionIntent(type="execute")

    def test_non_dict_payload_raises(self) -> None:
        with pytest.raises(ValueError, match="action_intent.payload"):
            ActionIntent(type=ACTION_CALL_TOOL_INTENT, payload="not-a-dict")  # type: ignore[arg-type]

    def test_is_frozen(self) -> None:
        intent = ActionIntent(type=ACTION_CALL_TOOL_INTENT)
        with pytest.raises(Exception):
            intent.type = "other"  # type: ignore[misc]

    def test_payload_must_be_json_compatible(self) -> None:
        with pytest.raises(ValueError, match="action_intent.payload"):
            ActionIntent(
                type=ACTION_CALL_TOOL_INTENT,
                payload={"fn": lambda: None},  # type: ignore[dict-item]
            )


# ===========================================================================
# AgentMessage
# ===========================================================================


class TestAgentMessage:
    def test_minimal_construction(self) -> None:
        msg = AgentMessage(message="hello")
        assert msg.message == "hello"
        assert msg.context == {}
        assert msg.capabilities == []
        assert msg.contract_version == S5_CONTRACT_VERSION

    def test_full_construction(self) -> None:
        msg = AgentMessage(
            message="list all files",
            context={
                "channel": "cli",
                "correlation_id": "abc-123",
                "history": [{"role": "user", "content": "hi"}],
            },
            capabilities=["file_read", "file_write"],
        )
        assert msg.message == "list all files"
        assert msg.context["channel"] == "cli"
        assert "file_read" in msg.capabilities

    def test_empty_message_raises(self) -> None:
        with pytest.raises(ValueError, match="message must be non-empty"):
            AgentMessage(message="")

    def test_non_dict_context_raises(self) -> None:
        with pytest.raises(ValueError, match="context must be a dict"):
            AgentMessage(message="hi", context="not-a-dict")  # type: ignore[arg-type]

    def test_non_list_capabilities_raises(self) -> None:
        with pytest.raises(ValueError, match="capabilities must be a list"):
            AgentMessage(message="hi", capabilities="file_read")  # type: ignore[arg-type]

    def test_empty_contract_version_raises(self) -> None:
        with pytest.raises(ValueError, match="contract_version"):
            AgentMessage(message="hi", contract_version="")

    def test_is_frozen(self) -> None:
        msg = AgentMessage(message="hi")
        with pytest.raises(Exception):
            msg.message = "bye"  # type: ignore[misc]

    def test_context_must_be_json_compatible(self) -> None:
        with pytest.raises(ValueError, match="context.fn"):
            AgentMessage(
                message="hi",
                context={"fn": lambda: None},  # type: ignore[dict-item]
            )


# ===========================================================================
# AgentResponse
# ===========================================================================


class TestAgentResponse:
    def test_reply_only(self) -> None:
        resp = AgentResponse(reply="Hello, I'm S5.")
        assert resp.reply == "Hello, I'm S5."
        assert resp.actions == []
        assert resp.contract_version == S5_CONTRACT_VERSION

    def test_actions_only(self) -> None:
        intent = ActionIntent(
            type=ACTION_CALL_TOOL_INTENT,
            payload={"tool": "read_file"},
        )
        resp = AgentResponse(actions=[intent])
        assert resp.reply is None
        assert len(resp.actions) == 1

    def test_reply_and_actions(self) -> None:
        intent = ActionIntent(type=ACTION_AGENT_STEP_INTENT)
        resp = AgentResponse(
            reply="Let me analyze that for you.",
            actions=[intent],
            metadata={"correlation_id": "abc", "confidence": 0.95, "agent": "assistant"},
        )
        assert resp.reply == "Let me analyze that for you."
        assert len(resp.actions) == 1
        assert resp.metadata["confidence"] == 0.95

    def test_neither_reply_nor_actions_raises(self) -> None:
        with pytest.raises(
            ValueError, match="at least one of reply or actions"
        ):
            AgentResponse()

    def test_non_string_reply_raises(self) -> None:
        with pytest.raises(ValueError, match="reply must be a string"):
            AgentResponse(reply=42)  # type: ignore[arg-type]

    def test_non_list_actions_raises(self) -> None:
        with pytest.raises(ValueError, match="actions must be a list"):
            AgentResponse(
                reply="hi",
                actions="not-a-list",  # type: ignore[arg-type]
            )

    def test_non_dict_metadata_raises(self) -> None:
        with pytest.raises(ValueError, match="metadata must be a dict"):
            AgentResponse(
                reply="hi",
                metadata="not-a-dict",  # type: ignore[arg-type]
            )

    def test_empty_contract_version_raises(self) -> None:
        with pytest.raises(ValueError, match="contract_version"):
            AgentResponse(reply="hi", contract_version="")

    def test_is_frozen(self) -> None:
        resp = AgentResponse(reply="hi")
        with pytest.raises(Exception):
            resp.reply = "bye"  # type: ignore[misc]

    def test_metadata_must_be_json_compatible(self) -> None:
        with pytest.raises(ValueError, match="metadata.fn"):
            AgentResponse(
                reply="hi",
                metadata={"fn": lambda: None},  # type: ignore[dict-item]
            )


# ===========================================================================
# Contract boundary enforcement
# ===========================================================================


class TestS5BoundaryEnforcement:
    """S5 must never emit S1/S4/planner structures."""

    def test_action_intent_is_not_executable(self) -> None:
        """Action intents must not look like executable instructions."""
        intent = ActionIntent(
            type=ACTION_CALL_TOOL_INTENT,
            payload={"tool": "read_file", "args": {"path": "/tmp/x"}},
        )
        # An intent has no `dispatch`, `execute`, or `submit` semantics.
        # It is declarative — the *absence* of execution fields is the test.
        assert "dispatch" not in intent.payload
        assert "submit" not in intent.payload
        assert "execute" not in intent.payload

    def test_agent_response_has_no_s1_fields(self) -> None:
        """AgentResponse must not contain S1 drift/repair fields."""
        resp = AgentResponse(reply="hello")
        assert not hasattr(resp, "drift")
        assert not hasattr(resp, "repair")
        assert not hasattr(resp, "outcome")
        assert not hasattr(resp, "plan")

    def test_agent_response_has_no_s4_fields(self) -> None:
        """AgentResponse must not contain S4 job envelope fields."""
        resp = AgentResponse(reply="hello")
        assert not hasattr(resp, "job")
        assert not hasattr(resp, "envelope")
        assert not hasattr(resp, "queue")
        assert not hasattr(resp, "worker")

    def test_agent_response_has_no_planner_fields(self) -> None:
        """AgentResponse must not contain planner structure fields."""
        resp = AgentResponse(reply="hello")
        assert not hasattr(resp, "steps")
        assert not hasattr(resp, "subgoals")
        assert not hasattr(resp, "nodes")
        assert not hasattr(resp, "segments")

    def test_s5_does_not_produce_s1_json(self) -> None:
        """AgentResponse serialized to dict must not look like S1 output."""
        resp = AgentResponse(
            reply="I processed your request.",
            metadata={"correlation_id": "abc"},
        )
        data = {
            "reply": resp.reply,
            "actions": [],
            "metadata": resp.metadata,
        }
        # No S1 fields
        assert "drift" not in data
        assert "repair" not in data
        assert "outcome" not in data
        assert "classification" not in data
        # No S4 fields
        assert "job" not in data
        assert "envelope" not in data
        assert "queue" not in data
        # No planner fields
        assert "plan" not in data
        assert "subgoals" not in data
        assert "segments" not in data
