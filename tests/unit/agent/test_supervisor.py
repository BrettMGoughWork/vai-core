"""
Phase 5.5 — Supervisor Unit Tests
==================================

Tests for the Agent Runtime Supervisor lifecycle management.

Covers:
- create_agent  (happy + error)
- activate_agent (happy + guards)
- run_agent_step (full lifecycle via simulation backend)
- suspend_agent (happy + guards)
- resume_agent (happy + guards)
- cancel_agent (happy + guards)
- complete_agent (happy + guards)
- get_response / get_lifecycle_history
- Terminal state guards across all methods
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import pytest

from src.agent.activation import ActivatedAgentContext, ActivationContext, ActivationEnvelope
from src.agent.contracts import AgentMessage, AgentResponse
from src.agent.adapters.memory_agent_state_store import MemoryAgentStateStore
from src.agent.interfaces.agent_state import AgentState, LifecycleState
from src.agent.interfaces.agent_state_store import AgentStateStore
from src.agent.registry import (
    AgentConstraints,
    AgentIdentity,
    AgentMetadata,
    AgentRegistry,
)
from src.agent.supervisor import (
    AgentInTerminalStateError,
    AgentNotActiveError,
    AgentNotSuspendedError,
    Supervisor,
    SupervisorError,
)


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
    skills: Optional[List[str]] = None,
    agent_id: str = "test-agent",
    name: str = "Test Agent",
) -> AgentMetadata:
    return AgentMetadata(
        identity=_make_identity(agent_id=agent_id, name=name),
        skills=skills or [],
        inputs=["text"],
        outputs=["text", "action_intents"],
        constraints=AgentConstraints(max_tokens=4096, timeout_ms=30000),
    )


def _make_registry(agent_id: str = "test-agent") -> AgentRegistry:
    registry = AgentRegistry()
    registry.register_agent(_make_metadata(agent_id=agent_id))
    return registry


def _make_agent_message(text: str = "Hello") -> AgentMessage:
    return AgentMessage(
        message=text,
        context={"channel": "cli"},
    )


def _make_supervisor(
    registry: Optional[AgentRegistry] = None,
    store: Optional[AgentStateStore] = None,
    **kwargs: Any,
) -> Supervisor:
    return Supervisor(
        registry=registry or _make_registry(),
        store=store or MemoryAgentStateStore(),
        **kwargs,
    )


def _make_terminal_state(agent_id: str = "test-agent") -> AgentState:
    """Create an AgentState that is already in a terminal state (COMPLETED)."""
    return AgentState(
        agent_id=agent_id,
        lifecycle_state=LifecycleState.COMPLETED,
        timestamps={"created_at": "2024-01-01T00:00:00+00:00"},
        correlation_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
    )


def _make_created_state(agent_id: str = "test-agent") -> AgentState:
    """Create a minimal CREATED AgentState."""
    return AgentState(
        agent_id=agent_id,
        lifecycle_state=LifecycleState.CREATED,
        timestamps={"created_at": "2024-01-01T00:00:00+00:00"},
        correlation_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
    )


def _make_activated_state(agent_id: str = "test-agent") -> AgentState:
    """Create an ACTIVATED AgentState with a proper activation snapshot."""
    msg = _make_agent_message()
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
        agent_metadata=_make_metadata(agent_id=agent_id),
        conversation_history=[],
        system_constraints={"max_tokens": 4096, "timeout_ms": 30000, "sandbox": "none"},
    )
    return AgentState(
        agent_id=agent_id,
        lifecycle_state=LifecycleState.ACTIVATED,
        activation_snapshot=ActivatedAgentContext(envelope=env, context=ctx),
        timestamps={
            "created_at": "2024-01-01T00:00:00+00:00",
            "activated_at": "2024-01-01T00:00:01+00:00",
        },
        correlation_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
        supervisor_metadata={
            "backend": "simulation",
            "max_iterations": 5,
            "timeout_ms": 30000,
            "total_iterations": 0,
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# create_agent
# ══════════════════════════════════════════════════════════════════════════════


class TestCreateAgent:
    def test_happy_path(self) -> None:
        sup = _make_supervisor()
        state = sup.create_agent("test-agent")
        assert state.agent_id == "test-agent"
        assert state.lifecycle_state == LifecycleState.CREATED
        assert state.version == 1
        assert state.correlation_id
        assert state.trace_id
        assert "created_at" in state.timestamps
        assert len(state.lifecycle_history) == 1
        assert state.lifecycle_history[0].to_state == LifecycleState.CREATED

    def test_empty_agent_id_raises(self) -> None:
        sup = _make_supervisor()
        with pytest.raises(SupervisorError, match="agent_id must be non-empty"):
            sup.create_agent("")

    def test_unknown_agent_raises(self) -> None:
        sup = _make_supervisor()
        with pytest.raises(SupervisorError, match="unknown agent"):
            sup.create_agent("nonexistent")

    def test_auto_persist(self) -> None:
        store = MemoryAgentStateStore()
        sup = _make_supervisor(store=store)
        sup.create_agent("test-agent")
        loaded = store.load("test-agent")
        assert loaded is not None
        assert loaded.lifecycle_state == LifecycleState.CREATED

    def test_no_auto_persist(self) -> None:
        store = MemoryAgentStateStore()
        sup = _make_supervisor(store=store, auto_persist=False)
        sup.create_agent("test-agent")
        assert store.load("test-agent") is None


# ══════════════════════════════════════════════════════════════════════════════
# activate_agent
# ══════════════════════════════════════════════════════════════════════════════


class TestActivateAgent:
    def test_happy_path(self) -> None:
        sup = _make_supervisor()
        state = sup.create_agent("test-agent")
        msg = _make_agent_message()
        activated = sup.activate_agent(state, msg)
        assert activated.lifecycle_state == LifecycleState.ACTIVATED
        assert activated.activation_snapshot is not None
        assert "activated_at" in activated.timestamps
        # version should have been incremented (create → activate is one transition)
        assert activated.version == state.version + 1

    def test_terminal_state_raises(self) -> None:
        sup = _make_supervisor()
        terminal = _make_terminal_state()
        msg = _make_agent_message()
        with pytest.raises(AgentInTerminalStateError):
            sup.activate_agent(terminal, msg)

    def test_provides_correlation_and_trace_ids(self) -> None:
        sup = _make_supervisor()
        state = sup.create_agent("test-agent")
        msg = _make_agent_message()
        activated = sup.activate_agent(
            state,
            msg,
            correlation_id="my-corr",
            trace_id="my-trace",
        )
        assert activated.correlation_id == "my-corr"
        assert activated.trace_id == "my-trace"

    def test_unknown_agent_in_registry_raises(self) -> None:
        """Activating an agent_id not in the registry should fail."""
        sup = _make_supervisor()
        state = AgentState(
            agent_id="unknown",
            lifecycle_state=LifecycleState.CREATED,
            timestamps={"created_at": "2024-01-01T00:00:00+00:00"},
            correlation_id="x",
            trace_id="y",
        )
        msg = _make_agent_message()
        with pytest.raises(SupervisorError, match="activation failed"):
            sup.activate_agent(state, msg)


# ══════════════════════════════════════════════════════════════════════════════
# run_agent_step
# ══════════════════════════════════════════════════════════════════════════════


class TestRunAgentStep:
    def test_activated_to_completed(self) -> None:
        """Full happy path: activated agent is routed to Runtime and
        produces a conversational response."""
        sup = _make_supervisor()
        state = _make_activated_state()
        result = sup.run_agent_step(state)
        # With default routing and CAP_CONVERSATIONAL, the message is
        # routed to Runtime → should transition to COMPLETED
        assert result.lifecycle_state in (LifecycleState.COMPLETED, LifecycleState.WAITING)
        assert result.route_result is not None
        assert result.version > state.version

    def test_activated_to_waiting_with_jobs(
        self,
    ) -> None:
        """An agent with job_submission capability may dispatch jobs."""
        registry = _make_registry("job-agent")
        sup = _make_supervisor(registry=registry)
        state = _make_activated_state("job-agent")
        result = sup.run_agent_step(state)
        assert result.lifecycle_state in (
            LifecycleState.COMPLETED,
            LifecycleState.WAITING,
        )
        assert result.route_result is not None

    def test_terminal_state_raises(self) -> None:
        sup = _make_supervisor()
        terminal = _make_terminal_state()
        with pytest.raises(AgentInTerminalStateError):
            sup.run_agent_step(terminal)

    def test_non_active_state_raises(self) -> None:
        """SUSPENDED or CREATED should not be directly runnable."""
        sup = _make_supervisor()

        created = _make_created_state()
        with pytest.raises(AgentNotActiveError):
            sup.run_agent_step(created)

    def test_missing_activation_fails_gracefully(self) -> None:
        """If an agent somehow reaches run_agent_step without an activation
        snapshot, it should transition to FAILED, not crash."""
        sup = _make_supervisor()
        # ACTIVATED state but no activation_snapshot — triggers the guard
        bad_state = _make_created_state().with_(  # type: ignore[call-overload]
            lifecycle_state=LifecycleState.ACTIVATED,
        )
        result = sup.run_agent_step(bad_state)
        assert result.lifecycle_state == LifecycleState.FAILED
        assert result.errors
        assert any(
            e.get("type") == "missing_activation" for e in result.errors
        )

    def test_persists_after_step(self) -> None:
        """Verify auto_persist saves after run_agent_step."""
        store = MemoryAgentStateStore()
        sup = _make_supervisor(store=store)
        state = _make_activated_state()
        sup.run_agent_step(state)
        loaded = store.load(state.agent_id)
        assert loaded is not None
        assert loaded.lifecycle_state in (
            LifecycleState.COMPLETED,
            LifecycleState.WAITING,
        )

    def test_continuation_from_waiting(self) -> None:
        """Simulate: agent dispatched jobs → WAITING → run next step."""
        sup = _make_supervisor()
        state = _make_activated_state()
        # First step
        step1 = sup.run_agent_step(state)
        assert step1.route_result is not None

        # If WAITING, simulate a continuation
        if step1.lifecycle_state == LifecycleState.WAITING:
            step2 = sup.run_agent_step(step1)
            # Should be able to continue
            assert step2.lifecycle_state in (
                LifecycleState.WAITING,
                LifecycleState.COMPLETED,
            )
            assert step2.version > step1.version


# ══════════════════════════════════════════════════════════════════════════════
# suspend_agent
# ══════════════════════════════════════════════════════════════════════════════


class TestSuspendAgent:
    def test_suspend_from_running(self) -> None:
        sup = _make_supervisor()
        state = _make_activated_state()
        # Run a step to get to RUNNING (or WAITING/COMPLETED)
        ran = sup.run_agent_step(state)

        # If it completed, we need to test with a manually RUNNING state
        if ran.lifecycle_state == LifecycleState.COMPLETED:
            # Create a state that's in RUNNING
            running = state.with_(lifecycle_state=LifecycleState.RUNNING)
            suspended = sup.suspend_agent(running, "test suspension")
            assert suspended.lifecycle_state == LifecycleState.SUSPENDED
            assert "suspended_at" in suspended.timestamps
            return

        # Otherwise suspend from the result (RUNNING or WAITING)
        suspended = sup.suspend_agent(ran, "pausing for external input")
        assert suspended.lifecycle_state == LifecycleState.SUSPENDED
        assert "suspended_at" in suspended.timestamps

    def test_terminal_state_raises(self) -> None:
        sup = _make_supervisor()
        terminal = _make_terminal_state()
        with pytest.raises(AgentInTerminalStateError):
            sup.suspend_agent(terminal, "reason")

    def test_suspend_from_invalid_state_raises(self) -> None:
        sup = _make_supervisor()
        # CREATED is not RUNNING or WAITING
        created = _make_created_state()
        with pytest.raises(AgentNotActiveError):
            sup.suspend_agent(created, "reason")

    def test_suspend_with_details(self) -> None:
        sup = _make_supervisor()
        running = _make_activated_state().with_(
            lifecycle_state=LifecycleState.RUNNING,
        )
        suspended = sup.suspend_agent(
            running,
            "timeout",
            details={"timeout_ms": 30000},
        )
        assert suspended.lifecycle_state == LifecycleState.SUSPENDED
        # The details are stored in the lifecycle event
        assert any(
            ev.reason == "timeout" for ev in suspended.lifecycle_history
        )


# ══════════════════════════════════════════════════════════════════════════════
# resume_agent
# ══════════════════════════════════════════════════════════════════════════════


class TestResumeAgent:
    def test_resume_from_suspended(self) -> None:
        sup = _make_supervisor()
        running = _make_activated_state().with_(
            lifecycle_state=LifecycleState.RUNNING,
        )
        suspended = sup.suspend_agent(running, "pause")
        resumed = sup.resume_agent(suspended)
        assert resumed.lifecycle_state == LifecycleState.RUNNING
        assert resumed.version > suspended.version

    def test_terminal_state_raises(self) -> None:
        sup = _make_supervisor()
        terminal = _make_terminal_state()
        with pytest.raises(AgentInTerminalStateError):
            sup.resume_agent(terminal)

    def test_not_suspended_raises(self) -> None:
        sup = _make_supervisor()
        created = _make_created_state()
        with pytest.raises(AgentNotSuspendedError):
            sup.resume_agent(created)


# ══════════════════════════════════════════════════════════════════════════════
# cancel_agent
# ══════════════════════════════════════════════════════════════════════════════


class TestCancelAgent:
    def test_cancel_from_created(self) -> None:
        sup = _make_supervisor()
        state = _make_created_state()
        cancelled = sup.cancel_agent(state, "manual cancellation")
        assert cancelled.lifecycle_state == LifecycleState.FAILED
        assert cancelled.errors
        assert any(e.get("type") == "cancellation" for e in cancelled.errors)

    def test_cancel_from_running(self) -> None:
        sup = _make_supervisor()
        running = _make_activated_state().with_(
            lifecycle_state=LifecycleState.RUNNING,
        )
        cancelled = sup.cancel_agent(running, "user cancelled")
        assert cancelled.lifecycle_state == LifecycleState.FAILED

    def test_terminal_state_raises(self) -> None:
        sup = _make_supervisor()
        terminal = _make_terminal_state()
        with pytest.raises(AgentInTerminalStateError):
            sup.cancel_agent(terminal, "reason")


# ══════════════════════════════════════════════════════════════════════════════
# complete_agent
# ══════════════════════════════════════════════════════════════════════════════


class TestCompleteAgent:
    def test_complete_from_any_non_terminal(self) -> None:
        sup = _make_supervisor()
        state = _make_created_state()
        response = AgentResponse(reply="Done!", metadata={})
        completed = sup.complete_agent(state, response)
        assert completed.lifecycle_state == LifecycleState.COMPLETED
        assert completed.final_response is not None
        assert completed.final_response.reply == "Done!"

    def test_terminal_state_raises(self) -> None:
        sup = _make_supervisor()
        terminal = _make_terminal_state()
        response = AgentResponse(reply="Done!", metadata={})
        with pytest.raises(AgentInTerminalStateError):
            sup.complete_agent(terminal, response)


# ══════════════════════════════════════════════════════════════════════════════
# get_response & get_lifecycle_history
# ══════════════════════════════════════════════════════════════════════════════


class TestQueryMethods:
    def test_get_response_none_before_completion(self) -> None:
        sup = _make_supervisor()
        state = _make_created_state()
        assert sup.get_response(state) is None

    def test_get_response_after_complete(self) -> None:
        sup = _make_supervisor()
        state = _make_created_state()
        response = AgentResponse(reply="Hello!", metadata={})
        completed = sup.complete_agent(state, response)
        assert sup.get_response(completed) is not None
        assert sup.get_response(completed).reply == "Hello!"

    def test_lifecycle_history(self) -> None:
        sup = _make_supervisor()
        state = sup.create_agent("test-agent")
        history = sup.get_lifecycle_history(state)
        assert len(history) >= 1
        assert history[0].to_state == LifecycleState.CREATED

    def test_lifecycle_history_tracks_transitions(self) -> None:
        sup = _make_supervisor()
        state = sup.create_agent("test-agent")
        msg = _make_agent_message()
        activated = sup.activate_agent(state, msg)
        history = sup.get_lifecycle_history(activated)
        # Should have CREATED and ACTIVATED events
        states = [ev.to_state for ev in history]
        assert LifecycleState.CREATED in states
        assert LifecycleState.ACTIVATED in states


# ══════════════════════════════════════════════════════════════════════════════
# Integration: Full lifecycle
# ══════════════════════════════════════════════════════════════════════════════


class TestFullLifecycle:
    def test_create_activate_run_complete(self) -> None:
        """Full CREATED → ACTIVATED → RUNNING → COMPLETED cycle."""
        sup = _make_supervisor()
        msg = _make_agent_message("Write a brief greeting.")

        # 1. Create
        state = sup.create_agent("test-agent")
        assert state.lifecycle_state == LifecycleState.CREATED

        # 2. Activate
        state = sup.activate_agent(state, msg)
        assert state.lifecycle_state == LifecycleState.ACTIVATED

        # 3. Run step
        state = sup.run_agent_step(state)
        # Should end up COMPLETED or WAITING with simulation backend
        assert state.lifecycle_state in (
            LifecycleState.COMPLETED,
            LifecycleState.WAITING,
        )
        assert state.route_result is not None

    def test_create_cancel(self) -> None:
        """CREATED → CANCELLED (FAILED) cycle."""
        sup = _make_supervisor()
        state = sup.create_agent("test-agent")
        assert state.lifecycle_state == LifecycleState.CREATED

        state = sup.cancel_agent(state, "changed my mind")
        assert state.lifecycle_state == LifecycleState.FAILED
        assert sup.get_response(state) is None

    def test_suspend_resume_cycle(self) -> None:
        """RUNNING → SUSPENDED → RESUMED → RUNNING."""
        sup = _make_supervisor()
        activated = _make_activated_state()

        # Run step to get to an active state
        result = sup.run_agent_step(activated)

        # If it completed, test the cycle with a manually created RUNNING state
        if result.lifecycle_state == LifecycleState.COMPLETED:
            running = activated.with_(lifecycle_state=LifecycleState.RUNNING)
            suspended = sup.suspend_agent(running, "pause for review")
            resumed = sup.resume_agent(suspended)
            assert resumed.lifecycle_state == LifecycleState.RUNNING
            return

        # Normal path: suspend from result (RUNNING or WAITING)
        suspended = sup.suspend_agent(result, "pause for review")
        assert suspended.lifecycle_state == LifecycleState.SUSPENDED

        resumed = sup.resume_agent(suspended)
        assert resumed.lifecycle_state == LifecycleState.RUNNING
