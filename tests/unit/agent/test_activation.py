"""
Tests for Phase 5.2 — Agent Activation Contract.

Covers:
  - ActivationEnvelope construction and validation
  - ActivationContext construction and validation
  - ActivatedAgentContext validation
  - Capability resolution (channel filtering)
  - activate_agent() end-to-end
  - S5 activation boundary (S4 cannot activate)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from src.agent.contracts import AgentMessage
from src.agent.registry import (
    CAP_CONVERSATIONAL,
    CAP_PLANNING,
    CAP_TOOL_USE,
    AgentConstraints,
    AgentIdentity,
    AgentMetadata,
    AgentRegistry,
)
from src.agent.activation import (
    ACTIVATION_AUTHORIZED_CHANNELS,
    CHANNEL_CLI,
    CHANNEL_HTTP,
    CHANNEL_SYSTEM,
    CHANNEL_TUI,
    CHANNEL_WEB,
    VALID_CHANNELS,
    ActivatedAgentContext,
    ActivationContext,
    ActivationEnvelope,
    ActivationError,
    UnauthorizedChannelError,
    activate_agent,
    resolve_capabilities,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_identity() -> AgentIdentity:
    return AgentIdentity(
        agent_id="test-agent-1",
        name="Test Agent",
        description="An agent for testing",
        version="1.0.0",
    )


@pytest.fixture
def sample_metadata(sample_identity) -> AgentMetadata:
    return AgentMetadata(
        identity=sample_identity,
        capabilities=[CAP_CONVERSATIONAL, CAP_PLANNING, CAP_TOOL_USE],
    )


@pytest.fixture
def sample_message() -> AgentMessage:
    return AgentMessage(
        message="Hello, agent!",
        context={"channel": "cli"},
    )


@pytest.fixture
def registry(sample_metadata) -> AgentRegistry:
    reg = AgentRegistry()
    reg.register_agent(sample_metadata)
    return reg


# ---------------------------------------------------------------------------
# TestActivationEnvelope
# ---------------------------------------------------------------------------


class TestActivationEnvelope:
    def test_minimal_construction(self, sample_message) -> None:
        env = ActivationEnvelope(
            agent_id="agent-1",
            message=sample_message,
        )
        assert env.agent_id == "agent-1"
        assert env.message is sample_message
        assert env.activation_context == {}

    def test_full_construction(self, sample_message) -> None:
        ctx = {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "channel": "cli",
            "correlation_id": "corr-1",
            "trace_id": "trace-1",
        }
        env = ActivationEnvelope(
            agent_id="agent-1",
            message=sample_message,
            activation_context=ctx,
        )
        assert env.activation_context["channel"] == "cli"
        assert env.activation_context["correlation_id"] == "corr-1"

    def test_empty_agent_id_raises(self, sample_message) -> None:
        with pytest.raises(ValueError, match="agent_id must be non-empty"):
            ActivationEnvelope(agent_id="", message=sample_message)

    def test_invalid_message_type_raises(self) -> None:
        with pytest.raises(ValueError, match="must be an AgentMessage"):
            ActivationEnvelope(agent_id="a1", message="not a message")  # type: ignore[arg-type]

    def test_invalid_channel_raises(self, sample_message) -> None:
        with pytest.raises(ValueError, match="channel"):
            ActivationEnvelope(
                agent_id="a1",
                message=sample_message,
                activation_context={"channel": "s4_direct"},
            )

    def test_is_frozen(self, sample_message) -> None:
        env = ActivationEnvelope(agent_id="a1", message=sample_message)
        with pytest.raises(AttributeError):
            env.agent_id = "different"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestActivationContext
# ---------------------------------------------------------------------------


class TestActivationContext:
    def test_minimal_construction(self, sample_metadata) -> None:
        ctx = ActivationContext(agent_metadata=sample_metadata)
        assert ctx.resolved_capabilities == []
        assert ctx.conversation_history == []
        assert ctx.routing_hints == {}
        assert ctx.channel_metadata == {}
        assert ctx.system_constraints == {}

    def test_with_history(self, sample_metadata) -> None:
        history = [
            {"role": "user", "message": "hi"},
            {"role": "assistant", "message": "hello"},
        ]
        ctx = ActivationContext(
            agent_metadata=sample_metadata,
            conversation_history=history,
        )
        assert len(ctx.conversation_history) == 2

    def test_with_system_constraints(self, sample_metadata) -> None:
        ctx = ActivationContext(
            agent_metadata=sample_metadata,
            system_constraints={"max_tokens": 4096, "timeout_ms": 30000},
        )
        assert ctx.system_constraints["max_tokens"] == 4096

    def test_invalid_metadata_type_raises(self) -> None:
        with pytest.raises(ValueError, match="must be an AgentMetadata"):
            ActivationContext(agent_metadata="not metadata")  # type: ignore[arg-type]

    def test_non_list_capabilities_raises(self, sample_metadata) -> None:
        with pytest.raises(ValueError, match="resolved_capabilities must be a list"):
            ActivationContext(
                agent_metadata=sample_metadata,
                resolved_capabilities="not-a-list",  # type: ignore[arg-type]
            )

    def test_non_list_history_raises(self, sample_metadata) -> None:
        with pytest.raises(ValueError, match="conversation_history must be a list"):
            ActivationContext(
                agent_metadata=sample_metadata,
                conversation_history="not-a-list",  # type: ignore[arg-type]
            )

    def test_non_dict_hints_raises(self, sample_metadata) -> None:
        with pytest.raises(ValueError, match="routing_hints must be a dict"):
            ActivationContext(
                agent_metadata=sample_metadata,
                routing_hints="not-a-dict",  # type: ignore[arg-type]
            )

    def test_is_frozen(self, sample_metadata) -> None:
        ctx = ActivationContext(agent_metadata=sample_metadata)
        with pytest.raises(AttributeError):
            ctx.resolved_capabilities = ["new"]  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestActivatedAgentContext
# ---------------------------------------------------------------------------


class TestActivatedAgentContext:
    def test_construction(self, sample_metadata, sample_message) -> None:
        env = ActivationEnvelope(agent_id="a1", message=sample_message)
        actx = ActivationContext(agent_metadata=sample_metadata)
        result = ActivatedAgentContext(envelope=env, context=actx)
        assert result.envelope is env
        assert result.context is actx

    def test_invalid_envelope_raises(self, sample_metadata) -> None:
        actx = ActivationContext(agent_metadata=sample_metadata)
        with pytest.raises(ValueError, match="must be an ActivationEnvelope"):
            ActivatedAgentContext(envelope="bad", context=actx)  # type: ignore[arg-type]

    def test_invalid_context_raises(self, sample_message) -> None:
        env = ActivationEnvelope(agent_id="a1", message=sample_message)
        with pytest.raises(ValueError, match="must be an ActivationContext"):
            ActivatedAgentContext(envelope=env, context="bad")  # type: ignore[arg-type]

    def test_is_frozen(self, sample_metadata, sample_message) -> None:
        env = ActivationEnvelope(agent_id="a1", message=sample_message)
        actx = ActivationContext(agent_metadata=sample_metadata)
        result = ActivatedAgentContext(envelope=env, context=actx)
        with pytest.raises(AttributeError):
            result.envelope = env  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestCapabilityResolution
# ---------------------------------------------------------------------------


class TestCapabilityResolution:
    def test_all_capabilities_on_cli(self, sample_metadata) -> None:
        resolved = resolve_capabilities(sample_metadata, CHANNEL_CLI)
        assert resolved == [CAP_CONVERSATIONAL, CAP_PLANNING, CAP_TOOL_USE]

    def test_all_capabilities_on_web(self, sample_metadata) -> None:
        resolved = resolve_capabilities(sample_metadata, CHANNEL_WEB)
        assert resolved == [CAP_CONVERSATIONAL, CAP_PLANNING, CAP_TOOL_USE]

    def test_unknown_channel_returns_all(self, sample_metadata) -> None:
        # Unknown channel => no blocklist => all capabilities pass through.
        resolved = resolve_capabilities(sample_metadata, "unknown_channel")
        assert resolved == [CAP_CONVERSATIONAL, CAP_PLANNING, CAP_TOOL_USE]

    def test_empty_capabilities(self, sample_identity) -> None:
        metadata = AgentMetadata(
            identity=sample_identity,
            capabilities=[],
        )
        resolved = resolve_capabilities(metadata, CHANNEL_CLI)
        assert resolved == []

    def test_does_not_mutate_metadata(self, sample_metadata) -> None:
        original = list(sample_metadata.capabilities)
        resolve_capabilities(sample_metadata, CHANNEL_CLI)
        assert list(sample_metadata.capabilities) == original

    def test_deterministic(self, sample_metadata) -> None:
        r1 = resolve_capabilities(sample_metadata, CHANNEL_CLI)
        r2 = resolve_capabilities(sample_metadata, CHANNEL_CLI)
        assert r1 == r2


# ---------------------------------------------------------------------------
# TestActivateAgent
# ---------------------------------------------------------------------------


class TestActivateAgent:
    def test_successful_activation(
        self, sample_metadata, sample_message, registry
    ) -> None:
        result = activate_agent(
            agent_id="test-agent-1",
            message=sample_message,
            registry=registry,
            channel=CHANNEL_CLI,
        )
        assert isinstance(result, ActivatedAgentContext)
        assert result.envelope.agent_id == "test-agent-1"
        assert result.envelope.message is sample_message
        assert result.envelope.activation_context["channel"] == CHANNEL_CLI
        assert "timestamp" in result.envelope.activation_context
        assert "correlation_id" in result.envelope.activation_context
        assert "trace_id" in result.envelope.activation_context

        # Context is populated
        assert result.context.agent_metadata is sample_metadata
        assert result.context.resolved_capabilities == [
            CAP_CONVERSATIONAL,
            CAP_PLANNING,
            CAP_TOOL_USE,
        ]
        assert result.context.system_constraints["sandbox"] == "none"

    def test_agent_not_found_raises(self, sample_message, registry) -> None:
        with pytest.raises(ActivationError, match="cannot activate unknown"):
            activate_agent(
                agent_id="nonexistent",
                message=sample_message,
                registry=registry,
            )

    def test_injects_correlation_and_trace_ids(
        self, sample_message, registry
    ) -> None:
        result = activate_agent(
            agent_id="test-agent-1",
            message=sample_message,
            registry=registry,
            channel=CHANNEL_CLI,
            correlation_id="my-corr",
            trace_id="my-trace",
        )
        assert result.envelope.activation_context["correlation_id"] == "my-corr"
        assert result.envelope.activation_context["trace_id"] == "my-trace"

    def test_auto_generates_ids(self, sample_message, registry) -> None:
        result = activate_agent(
            agent_id="test-agent-1",
            message=sample_message,
            registry=registry,
        )
        cid = result.envelope.activation_context["correlation_id"]
        tid = result.envelope.activation_context["trace_id"]
        # Should be valid UUIDs
        uuid.UUID(cid)
        uuid.UUID(tid)

    def test_injects_conversation_history(self, sample_message, registry) -> None:
        history = [
            {"role": "user", "message": "previous message"},
        ]
        result = activate_agent(
            agent_id="test-agent-1",
            message=sample_message,
            registry=registry,
            conversation_history=history,
        )
        assert result.context.conversation_history == history

    def test_injects_routing_hints(self, sample_message, registry) -> None:
        hints = {"destination": "cli_output"}
        result = activate_agent(
            agent_id="test-agent-1",
            message=sample_message,
            registry=registry,
            routing_hints=hints,
        )
        assert result.context.routing_hints == hints

    def test_injects_channel_metadata(self, sample_message, registry) -> None:
        meta = {"client_ip": "127.0.0.1"}
        result = activate_agent(
            agent_id="test-agent-1",
            message=sample_message,
            registry=registry,
            channel_metadata=meta,
        )
        assert result.context.channel_metadata == meta

    def test_system_constraints_from_metadata(
        self, sample_message, registry, sample_identity
    ) -> None:
        constrained = AgentMetadata(
            identity=sample_identity,
            capabilities=[CAP_CONVERSATIONAL],
            constraints=AgentConstraints(
                max_tokens=2048,
                timeout_ms=15000,
                sandbox="process",
            ),
        )
        reg = AgentRegistry()
        reg.register_agent(constrained)

        result = activate_agent(
            agent_id="test-agent-1",
            message=sample_message,
            registry=reg,
        )
        assert result.context.system_constraints["max_tokens"] == 2048
        assert result.context.system_constraints["timeout_ms"] == 15000
        assert result.context.system_constraints["sandbox"] == "process"

    def test_is_deterministic(self, sample_message, registry) -> None:
        r1 = activate_agent(
            agent_id="test-agent-1",
            message=sample_message,
            registry=registry,
            channel=CHANNEL_CLI,
            correlation_id="fixed",
            trace_id="fixed",
        )
        r2 = activate_agent(
            agent_id="test-agent-1",
            message=sample_message,
            registry=registry,
            channel=CHANNEL_CLI,
            correlation_id="fixed",
            trace_id="fixed",
        )
        # Compare deterministic fields. The timestamp in activation_context
        # is inherently non-deterministic (clock precision varies across
        # runners), so we exclude it from the equality check.
        assert r1.envelope.agent_id == r2.envelope.agent_id
        assert r1.envelope.message == r2.envelope.message
        assert (
            {k: v for k, v in r1.envelope.activation_context.items() if k != "timestamp"}
            == {k: v for k, v in r2.envelope.activation_context.items() if k != "timestamp"}
        )
        assert r1.context == r2.context

    def test_is_read_only(self, sample_message, registry) -> None:
        count_before = registry.agent_count
        activate_agent(
            agent_id="test-agent-1",
            message=sample_message,
            registry=registry,
        )
        assert registry.agent_count == count_before

    def test_default_channel_is_cli(self, sample_message, registry) -> None:
        result = activate_agent(
            agent_id="test-agent-1",
            message=sample_message,
            registry=registry,
        )
        assert (
            result.envelope.activation_context["channel"] == CHANNEL_CLI
        )


# ---------------------------------------------------------------------------
# TestActivationBoundary — S4 cannot activate S5
# ---------------------------------------------------------------------------


class TestActivationBoundary:
    """Verify the S4→S5 activation prohibition."""

    def test_unknown_channel_is_rejected(
        self, sample_message, registry
    ) -> None:
        """An unrecognised channel is rejected by the activation layer."""
        from src.agent.activation import UnauthorizedChannelError

        with pytest.raises(UnauthorizedChannelError):
            activate_agent(
                agent_id="test-agent-1",
                message=sample_message,
                registry=registry,
                channel="s4_direct",
            )

    def test_all_authorized_channels(self, sample_message, registry) -> None:
        """All channels in ACTIVATION_AUTHORIZED_CHANNELS are accepted."""
        for channel in ACTIVATION_AUTHORIZED_CHANNELS:
            result = activate_agent(
                agent_id="test-agent-1",
                message=sample_message,
                registry=registry,
                channel=channel,
                correlation_id="test",
                trace_id="test",
            )
            assert (
                result.envelope.activation_context["channel"] == channel
            )

    def test_valid_channels_listed(self) -> None:
        """Every valid channel should appear in VALID_CHANNELS."""
        assert CHANNEL_CLI in VALID_CHANNELS
        assert CHANNEL_HTTP in VALID_CHANNELS
        assert CHANNEL_TUI in VALID_CHANNELS
        assert CHANNEL_WEB in VALID_CHANNELS
        assert CHANNEL_SYSTEM in VALID_CHANNELS

    def test_activation_has_no_s4_fields(self, sample_message, registry) -> None:
        """ActivatedAgentContext must not contain S4 concepts."""
        result = activate_agent(
            agent_id="test-agent-1",
            message=sample_message,
            registry=registry,
        )
        # No S4 job fields
        assert not hasattr(result, "job_envelope")
        assert not hasattr(result, "queue")
        assert not hasattr(result, "worker")
        assert not hasattr(result, "instruction")
        # No S4 state
        assert not hasattr(result.context, "s4_state")
        # No planning structures
        assert not hasattr(result.context, "plan")
        assert not hasattr(result.context, "steps")

    def test_activation_does_not_run_agent(self, sample_message, registry) -> None:
        """Activation must be purely preparatory — no execution."""
        result = activate_agent(
            agent_id="test-agent-1",
            message=sample_message,
            registry=registry,
        )
        # Should not produce any actions or replies
        assert not hasattr(result, "reply")
        assert not hasattr(result, "actions")
        # Should not contain execution state
        assert "execution" not in result.envelope.activation_context


# ---------------------------------------------------------------------------
# Test integration with contracts/registry
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_activation_pipeline(self, registry) -> None:
        """End-to-end: build message → activate → verify complete context."""
        msg = AgentMessage(
            message="Run analysis on the data",
            context={"project": "test", "user": "dev"},
            capabilities=[CAP_CONVERSATIONAL, CAP_PLANNING],
        )
        result = activate_agent(
            agent_id="test-agent-1",
            message=msg,
            registry=registry,
            channel=CHANNEL_HTTP,
            correlation_id="corr-int-1",
            trace_id="trace-int-1",
            conversation_history=[
                {"role": "user", "message": "previous turn"},
            ],
            channel_metadata={"method": "POST", "path": "/api/chat"},
        )

        # Verify envelope
        assert result.envelope.agent_id == "test-agent-1"
        assert result.envelope.message is msg
        assert result.envelope.activation_context["channel"] == CHANNEL_HTTP
        assert result.envelope.activation_context["correlation_id"] == "corr-int-1"

        # Verify context
        assert result.context.agent_metadata.identity.name == "Test Agent"
        assert CAP_CONVERSATIONAL in result.context.resolved_capabilities
        assert CAP_PLANNING in result.context.resolved_capabilities
        assert len(result.context.conversation_history) == 1
        assert result.context.channel_metadata["method"] == "POST"
        assert result.context.system_constraints["sandbox"] == "none"
