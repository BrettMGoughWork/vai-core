"""
Sprint 4a — Multi-Turn Conversation Memory Integration Tests
=============================================================

Tests for conversation history accumulation (4a.7), session boundary
isolation (4a.8), and governance context for conversational turns (4a.9).

These tests validate the **full Gateway → S5 pipeline**::

    submit_channel_input
      → CLIChannel.receive / normalize
      → SessionedAdapter.ingest        (auto session management)
      → AgentGatewayAdapter.ingest     (Supervisor wiring)
      → Supervisor.activate_agent      (stores conversation_history)
      → Supervisor.run_agent_step      (builds RouterOutcome)
      → StrategyRouter._route_to_llm   (injects governance context)
      → _CapturingCallRuntime          (captures PromptRequest for assertions)

All tests use a mock call_runtime so no real LLM is required.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from src.agent import (
    AgentIdentity,
    AgentMetadata,
    AgentRegistry,
    MemoryAgentStateStore,
    Supervisor,
)
from src.agent.adapters.gateway_adapter import AgentGatewayAdapter
from src.agent.adapters.sessioned_adapter import SessionedAdapter
from src.agent.strategy_router import StrategyRouter
from src.gateway.channels.registry import ChannelRegistry
from src.gateway.channels.cli import register_cli_channel
from src.gateway.entrypoint import submit_channel_input
from src.runtime.interfaces import PromptRequest, PromptResponse
from src.strategy.memory.drift_memory import DriftMemory
from src.strategy.memory.governance.memory_governance import MemoryGovernance
from src.strategy.memory.plan_memory import PlanMemory
from src.strategy.memory.segment_memory import SegmentMemory
from src.strategy.memory.subgoal_memory import SubgoalMemory


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def agent_registry() -> AgentRegistry:
    """Register a ``default-agent`` so the Gateway can resolve it."""
    reg = AgentRegistry()
    reg.register_agent(AgentMetadata(
        identity=AgentIdentity(
            agent_id="default-agent",
            name="Default Agent",
            description="Default conversational agent",
        ),
        capabilities=["conversational"],
    ))
    return reg


@pytest.fixture
def channel_registry() -> ChannelRegistry:
    """Fresh ChannelRegistry with a registered CLI channel."""
    reg = ChannelRegistry()
    register_cli_channel(reg)
    return reg


@pytest.fixture
def capturing_runtime() -> _CapturingCallRuntime:
    """A mock call_runtime that captures the last PromptRequest."""
    return _CapturingCallRuntime()


@pytest.fixture
def governance() -> MemoryGovernance:
    """MemoryGovernance with empty in-memory stores — no violations."""
    return MemoryGovernance(
        subgoal_memory=SubgoalMemory(),
        segment_memory=SegmentMemory(),
        plan_memory=PlanMemory(),
        drift_memory=DriftMemory(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# 4a.7 — Multi-turn conversation references prior content
# ══════════════════════════════════════════════════════════════════════════════


class TestMultiTurnConversationHistory:
    """Verify conversation history is accumulated through the Gateway pipeline."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_adapter(
        agent_registry: AgentRegistry,
        capturing_runtime: _CapturingCallRuntime,
        governance: Optional[MemoryGovernance] = None,
    ) -> SessionedAdapter:
        """Build SessionedAdapter → AgentGatewayAdapter → Supervisor → StrategyRouter → mock."""
        strategy_router = StrategyRouter(
            call_runtime=capturing_runtime,
            governance=governance,
        )
        store = MemoryAgentStateStore()
        supervisor = Supervisor(
            registry=agent_registry,
            store=store,
            strategy_router=strategy_router,
            auto_persist=True,
        )
        inner = AgentGatewayAdapter(supervisor)
        return SessionedAdapter(inner)

    @staticmethod
    def _send(
        channel_registry: ChannelRegistry,
        adapter: SessionedAdapter,
        text: str,
        sender: str = "brett",
    ) -> dict[str, Any]:
        """Submit one CLI message through the full Gateway pipeline."""
        result = submit_channel_input(
            channel_registry,
            "cli",
            {"text": text, "sender": sender},
            adapter,
        )
        assert "reply" in result, f"Expected reply, got: {result}"
        return result

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_first_turn_has_empty_history(
        self,
        agent_registry: AgentRegistry,
        channel_registry: ChannelRegistry,
        capturing_runtime: _CapturingCallRuntime,
    ) -> None:
        """The first turn in a session has no conversation_history."""
        adapter = self._build_adapter(agent_registry, capturing_runtime)

        self._send(channel_registry, adapter, "hello")

        req = capturing_runtime.last_request
        assert req is not None
        history = req.memory.get("conversation_history", [])
        assert len(history) == 0, (
            f"Expected empty history on first turn, got {len(history)} entries"
        )

    def test_second_turn_carries_prior_history(
        self,
        agent_registry: AgentRegistry,
        channel_registry: ChannelRegistry,
        capturing_runtime: _CapturingCallRuntime,
    ) -> None:
        """Second turn receives history containing the first user/assistant pair."""
        adapter = self._build_adapter(agent_registry, capturing_runtime)

        self._send(channel_registry, adapter, "turn A")
        self._send(channel_registry, adapter, "turn B")

        req = capturing_runtime.last_request
        assert req is not None
        history = req.memory.get("conversation_history", [])
        # Turn A user + Turn A assistant = 2 entries visible to turn B
        assert len(history) == 2, (
            f"Expected 2 entries (user+assistant from turn A), got {len(history)}"
        )
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "turn A"
        assert history[1]["role"] == "assistant"

    def test_third_turn_sees_full_context(
        self,
        agent_registry: AgentRegistry,
        channel_registry: ChannelRegistry,
        capturing_runtime: _CapturingCallRuntime,
    ) -> None:
        """Third turn sees all prior turns in conversation_history."""
        adapter = self._build_adapter(agent_registry, capturing_runtime)

        self._send(channel_registry, adapter, "turn A")
        self._send(channel_registry, adapter, "my name is Brett")
        self._send(channel_registry, adapter, "what's my name?")

        req = capturing_runtime.last_request
        assert req is not None
        history = req.memory.get("conversation_history", [])
        # 2 turns × 2 entries (user + assistant) = 4 entries
        assert len(history) == 4, (
            f"Expected 4 entries after 2 prior turns, got {len(history)}"
        )

        contents = [e["content"] for e in history]
        assert "turn A" in contents
        assert "my name is Brett" in contents
        assert "what's my name?" not in contents, (
            "Current turn should not appear in history yet"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 4a.8 — Fresh session boundary isolates history
# ══════════════════════════════════════════════════════════════════════════════


class TestSessionBoundaryIsolation:
    """Verify that different user sessions have isolated history."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_adapter(
        agent_registry: AgentRegistry,
        capturing_runtime: _CapturingCallRuntime,
    ) -> SessionedAdapter:
        """Same wiring as 4a.7 — no governance needed."""
        strategy_router = StrategyRouter(call_runtime=capturing_runtime)
        store = MemoryAgentStateStore()
        supervisor = Supervisor(
            registry=agent_registry,
            store=store,
            strategy_router=strategy_router,
            auto_persist=True,
        )
        inner = AgentGatewayAdapter(supervisor)
        return SessionedAdapter(inner)

    @staticmethod
    def _send(
        channel_registry: ChannelRegistry,
        adapter: SessionedAdapter,
        text: str,
        sender: str = "brett",
    ) -> dict[str, Any]:
        """Submit one CLI message through the full Gateway pipeline."""
        result = submit_channel_input(
            channel_registry,
            "cli",
            {"text": text, "sender": sender},
            adapter,
        )
        assert "reply" in result, f"Expected reply, got: {result}"
        return result

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_fresh_session_starts_empty(
        self,
        agent_registry: AgentRegistry,
        channel_registry: ChannelRegistry,
        capturing_runtime: _CapturingCallRuntime,
    ) -> None:
        """A fresh session (different sender) begins with empty history."""
        adapter = self._build_adapter(agent_registry, capturing_runtime)

        # Session A completes one turn
        self._send(channel_registry, adapter, "session A", sender="alice")
        req_a = capturing_runtime.last_request
        assert req_a is not None
        hist_a = req_a.memory.get("conversation_history", [])
        assert len(hist_a) == 0  # first turn has empty history

        # Session B — different sender, should also be empty
        self._send(channel_registry, adapter, "session B", sender="bob")
        req_b = capturing_runtime.last_request
        assert req_b is not None
        hist_b = req_b.memory.get("conversation_history", [])
        assert len(hist_b) == 0, (
            f"Expected fresh session to have empty history, got {len(hist_b)} entries"
        )

    def test_sessions_do_not_leak(
        self,
        agent_registry: AgentRegistry,
        channel_registry: ChannelRegistry,
        capturing_runtime: _CapturingCallRuntime,
    ) -> None:
        """History from one session must not appear in another."""
        adapter = self._build_adapter(agent_registry, capturing_runtime)

        # Session A: two turns
        self._send(channel_registry, adapter, "A-first", sender="alice")
        self._send(channel_registry, adapter, "A-second", sender="alice")

        # Verify session A accumulated history
        req_a = capturing_runtime.last_request
        assert req_a is not None
        hist_a = req_a.memory.get("conversation_history", [])
        assert len(hist_a) == 2  # A-first user + assistant

        # Session B: one turn with a different sender
        self._send(channel_registry, adapter, "B-first", sender="bob")
        req_b = capturing_runtime.last_request
        assert req_b is not None
        hist_b = req_b.memory.get("conversation_history", [])

        assert len(hist_b) == 0, (
            f"Expected 0 entries for fresh session B, got {len(hist_b)}"
        )

        # Double-check: B's history must not contain A's content
        b_contents = [e.get("content", "") for e in hist_b]
        assert "A-second" not in b_contents, (
            "Session B should not see session A's history"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 4a.9 — Governance context for conversational turns
# ══════════════════════════════════════════════════════════════════════════════


class TestGovernanceForConversationalTurns:
    """Verify governance context is injected through the Gateway pipeline."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_adapter(
        agent_registry: AgentRegistry,
        capturing_runtime: _CapturingCallRuntime,
        governance: Optional[MemoryGovernance] = None,
    ) -> SessionedAdapter:
        """Build the full pipeline with an optional governance instance."""
        strategy_router = StrategyRouter(
            call_runtime=capturing_runtime,
            governance=governance,
        )
        store = MemoryAgentStateStore()
        supervisor = Supervisor(
            registry=agent_registry,
            store=store,
            strategy_router=strategy_router,
            auto_persist=True,
        )
        inner = AgentGatewayAdapter(supervisor)
        return SessionedAdapter(inner)

    @staticmethod
    def _send(
        channel_registry: ChannelRegistry,
        adapter: SessionedAdapter,
        text: str = "hello",
    ) -> dict[str, Any]:
        """Submit one CLI message through the full pipeline."""
        result = submit_channel_input(
            channel_registry,
            "cli",
            {"text": text, "sender": "brett"},
            adapter,
        )
        assert "reply" in result, f"Expected reply, got: {result}"
        return result

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_governance_context_in_memory_when_configured(
        self,
        agent_registry: AgentRegistry,
        channel_registry: ChannelRegistry,
        capturing_runtime: _CapturingCallRuntime,
        governance: MemoryGovernance,
    ) -> None:
        """When MemoryGovernance is wired, PromptRequest.memory has 'governance'."""
        adapter = self._build_adapter(
            agent_registry, capturing_runtime, governance=governance,
        )

        self._send(channel_registry, adapter)

        req = capturing_runtime.last_request
        assert req is not None
        assert "governance" in req.memory, (
            "Expected 'governance' key in memory when governance is configured"
        )

    def test_governance_context_not_injected_when_not_configured(
        self,
        agent_registry: AgentRegistry,
        channel_registry: ChannelRegistry,
        capturing_runtime: _CapturingCallRuntime,
    ) -> None:
        """Without governance, memory does NOT contain 'governance' key."""
        adapter = self._build_adapter(
            agent_registry, capturing_runtime, governance=None,
        )

        self._send(channel_registry, adapter)

        req = capturing_runtime.last_request
        assert req is not None
        assert "governance" not in req.memory, (
            "Expected no 'governance' key when governance is None"
        )

    def test_governance_includes_consistency_issues(
        self,
        agent_registry: AgentRegistry,
        channel_registry: ChannelRegistry,
        capturing_runtime: _CapturingCallRuntime,
        governance: MemoryGovernance,
    ) -> None:
        """The governance dict contains the 'consistency_issues' key."""
        adapter = self._build_adapter(
            agent_registry, capturing_runtime, governance=governance,
        )

        self._send(channel_registry, adapter)

        req = capturing_runtime.last_request
        assert req is not None
        gov = req.memory.get("governance", {})
        assert "consistency_issues" in gov, (
            "Expected 'consistency_issues' in governance context"
        )
        assert isinstance(gov["consistency_issues"], list)


# ══════════════════════════════════════════════════════════════════════════════
# Shared capture helper
# ══════════════════════════════════════════════════════════════════════════════


class _CapturingCallRuntime:
    """Wraps a mock call_runtime that captures the last PromptRequest."""

    def __init__(self) -> None:
        self.last_request: Optional[PromptRequest] = None

    def __call__(
        self,
        request: PromptRequest,
        *,
        backend: str = "conversational",
    ) -> PromptResponse:
        self.last_request = request
        return PromptResponse(
            output={
                "message": f"Mock: {request.prompt.get('message', '')}",
                "is_complete": True,
            },
            tool_calls=[],
        )
