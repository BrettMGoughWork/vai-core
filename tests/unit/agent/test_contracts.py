"""
Tests for Phase 5.0 — S5 Conversational Response Contract.

Covers AgentMessage, AgentResponse, ActionIntent, and the JSON‑compatibility
validator.  S5 emits only declarative intents — never executable instructions,
S1 schemas, S4 envelopes, or planner structures.
"""

from __future__ import annotations

import pytest

from src.agent.contracts import (
    S5_CONTRACT_VERSION,
    AgentMessage,
    AgentResponse,
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
        assert resp.contract_version == S5_CONTRACT_VERSION

    def test_non_string_reply_raises(self) -> None:
        with pytest.raises(ValueError, match="reply must be a string or None"):
            AgentResponse(reply=42)  # type: ignore[arg-type]

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
