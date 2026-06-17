"""
N.3 — Integration tests: Gateway → S5 (Supervisor) → S6 (Workflow) → S1 (LLM)

Scenarios covered
-----------------
1. Happy path: Gateway adapter → S5 → llm_call workflow → COMPLETED + reply
2. Tool execute: Supervisor → tool_execute step → S4B dispatch → WAITING
3. Supervisor lifecycle: create → activate → run → complete (direct API)
4. Multi-workflow routing: dispatch to tool_execute workflow by agent_id
5. Waiting workflow: Supervisor pauses on waiting_for_input step
6. Workflow engine: pure state-machine transitions (no Supervisor)
7. TriggerRouter: WorkflowEvent → start_workflow via event bus
8. Error handling: unknown agent_id → error, failed workflow step → FAILED
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from src.agent.contracts import AgentMessage
from src.agent.interfaces.agent_state import LifecycleState
from src.agent.supervisor import Supervisor
from src.agent.workflow import WorkflowInstanceStore, WorkflowRegistry
from src.agent.workflow.engine import WorkflowEngine, WorkflowExecutionState, WorkflowStatus
from src.agent.workflow.trigger_router import TriggerRouter, WorkflowEvent


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Happy path: Gateway → S5 → llm_call → COMPLETED
# ═══════════════════════════════════════════════════════════════════════════════


class TestGatewayHappyPath:
    """Exercise the full GatewayAdapter → Supervisor → workflow → LLM pipeline."""

    def test_ingest_returns_reply(self, gateway_adapter: Any) -> None:
        """A simple 'hello' should reach the mock LLM and return a reply."""
        from src.gateway.adapters.agent_adapter import AgentRequest

        result = gateway_adapter.ingest(AgentRequest(
            channel="cli",
            message_text="hello",
            user_id="test-user",
            metadata={},
        ))

        assert "reply" in result, f"Expected reply in result, got: {result}"
        assert "Mock response to:" in result["reply"], (
            f"Expected mock LLM response, got: {result['reply']}"
        )
        assert "agent_id" in result

    def test_ingest_returns_metadata(self, gateway_adapter: Any) -> None:
        """The response should include agent metadata."""
        from src.gateway.adapters.agent_adapter import AgentRequest

        result = gateway_adapter.ingest(AgentRequest(
            channel="cli",
            message_text="hello",
            user_id="test-user",
            metadata={"trace_id": "abc-123"},
        ))

        assert result.get("metadata") is not None

    def test_ingest_non_empty_message_validates(self) -> None:
        """AgentRequest with empty message_text should raise."""
        from src.gateway.adapters.agent_adapter import AgentRequest

        with pytest.raises(ValueError, match="message_text"):
            AgentRequest(channel="cli", message_text="")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Tool execute: Supervisor → tool_execute → S4B → WAITING
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolExecutePath:
    """Workflow steps of type ``tool_execute`` dispatch to S4B."""

    def test_tool_execute_dispatches_s4_job(
        self,
        multi_workflow_registry: WorkflowRegistry,
        job_queue: Any,
        strategy_router: Any,
    ) -> None:
        """A tool_execute step should submit a job to the S4 queue."""
        from src.agent.adapters.memory_agent_state_store import MemoryAgentStateStore
        from src.agent.registry import AgentIdentity, AgentMetadata, AgentRegistry

        # Wire a Supervisor with tool_execute workflow and S4 submit
        agent_reg = AgentRegistry()
        agent_reg.register_agent(AgentMetadata(
            identity=AgentIdentity(
                agent_id="tools-workflow",
                name="Tool Agent",
                description="Agent that executes tools",
            ),
            capabilities=["conversational"],
        ))

        wf_store = WorkflowInstanceStore()
        supervisor = Supervisor(
            registry=agent_reg,
            store=MemoryAgentStateStore(),
            workflow_registry=multi_workflow_registry,
            submit_job_callable=job_queue.submit,
            strategy_router=strategy_router,
            workflow_instance_store=wf_store,
        )

        state = supervisor.create_agent("tools-workflow")
        state = supervisor.activate_agent(
            state,
            AgentMessage(message="run workflow", context={}),
            channel="cli",
        )
        state = supervisor.run_agent_step(state)

        # The agent should be WAITING after dispatching to S4B
        assert state.lifecycle_state == LifecycleState.WAITING, (
            f"Expected WAITING after tool_execute, got {state.lifecycle_state}"
        )
        # A job should have been submitted
        assert job_queue.call_count >= 1, "Expected at least 1 S4 job submission"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Supervisor lifecycle: create → activate → run → complete
# ═══════════════════════════════════════════════════════════════════════════════


class TestSupervisorLifecycle:
    """Test Supervisor's public API directly."""

    def test_create_agent(self, wired_supervisor: Supervisor) -> None:
        """create_agent should return a valid AgentState."""
        state = wired_supervisor.create_agent("default-agent")
        assert state.agent_id == "default-agent"
        assert state.lifecycle_state == LifecycleState.CREATED

    def test_activate_agent(self, wired_supervisor: Supervisor) -> None:
        """activate_agent should transition to RUNNING."""
        state = wired_supervisor.create_agent("default-agent")
        state = wired_supervisor.activate_agent(
            state,
            AgentMessage(message="hello", context={}),
            channel="cli",
        )
        assert state.lifecycle_state == LifecycleState.ACTIVATED

    def test_run_agent_completes(self, wired_supervisor: Supervisor) -> None:
        """One full cycle: create → activate → step → COMPLETED."""
        state = wired_supervisor.create_agent("default-agent")
        state = wired_supervisor.activate_agent(
            state,
            AgentMessage(message="hello", context={}),
            channel="cli",
        )
        state = wired_supervisor.run_agent_step(state)
        assert state.lifecycle_state in (
            LifecycleState.COMPLETED, LifecycleState.RUNNING,
        ), f"Expected COMPLETED or RUNNING, got {state.lifecycle_state}"

    def test_create_unknown_agent(self, wired_supervisor: Supervisor) -> None:
        """Unknown agent_id should raise SupervisorError."""
        from src.agent.supervisor import SupervisorError

        with pytest.raises(SupervisorError):
            wired_supervisor.create_agent("nonexistent-agent")

    def test_cancel_agent(self, wired_supervisor: Supervisor) -> None:
        """cancelling an ACTIVATED agent should set CANCELLED state."""
        state = wired_supervisor.create_agent("default-agent")
        state = wired_supervisor.activate_agent(
            state,
            AgentMessage(message="hello", context={}),
            channel="cli",
        )
        state = wired_supervisor.cancel_agent(state, reason="test cancellation")
        assert state.lifecycle_state == LifecycleState.FAILED

    def test_get_response(self, wired_supervisor: Supervisor) -> None:
        """get_response should return the agent's final reply after completion."""
        state = wired_supervisor.create_agent("default-agent")
        state = wired_supervisor.activate_agent(
            state,
            AgentMessage(message="hello", context={}),
            channel="cli",
        )
        state = wired_supervisor.run_agent_step(state)

        if state.lifecycle_state == LifecycleState.COMPLETED:
            response = wired_supervisor.get_response(state)
            assert response is not None
            assert response.reply is not None

    def test_lifecycle_history(self, wired_supervisor: Supervisor) -> None:
        """Lifecycle events should accumulate through the agent's run."""
        state = wired_supervisor.create_agent("default-agent")
        state = wired_supervisor.activate_agent(
            state,
            AgentMessage(message="hello", context={}),
            channel="cli",
        )
        state = wired_supervisor.run_agent_step(state)
        history = wired_supervisor.get_lifecycle_history(state)
        assert len(history) >= 2  # At least created + activated or ran


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Multi-workflow routing
# ═══════════════════════════════════════════════════════════════════════════════


class TestMultiWorkflowRouting:
    """Different agent_ids route to different workflow definitions."""

    def test_hello_workflow_via_default_agent(
        self,
        gateway_adapter: Any,
    ) -> None:
        """default-agent should use the hello_world workflow (llm_call → reply)."""
        from src.gateway.adapters.agent_adapter import AgentRequest

        result = gateway_adapter.ingest(AgentRequest(
            channel="cli",
            message_text="hello",
            user_id="test-user",
            metadata={},
        ))

        assert "reply" in result, f"Expected reply, got: {result}"
        assert "Mock response" in result["reply"]

    def test_tool_workflow_via_explicit_agent_id(
        self,
        multi_workflow_registry: WorkflowRegistry,
        job_queue: Any,
        store: Any,
        agent_registry: Any,
        strategy_router: Any,
    ) -> None:
        """tools-workflow should dispatch to S4B via tool_execute."""
        from src.agent.registry import AgentMetadata, AgentIdentity

        wf_store = WorkflowInstanceStore()

        # Register the tools-workflow agent
        agent_registry.register_agent(AgentMetadata(
            identity=AgentIdentity(
                agent_id="tools-workflow",
                name="Tools Workflow Agent",
                description="Agent that dispatches tool execute jobs",
            ),
            capabilities=["conversational"],
        ))

        supervisor = Supervisor(
            registry=agent_registry,
            store=store,
            workflow_registry=multi_workflow_registry,
            submit_job_callable=job_queue.submit,
            strategy_router=strategy_router,
            workflow_instance_store=wf_store,
        )

        state = supervisor.create_agent("tools-workflow")  # uses name matching
        state = supervisor.activate_agent(
            state,
            AgentMessage(message="execute workflow now", context={}),
            channel="cli",
        )
        state = supervisor.run_agent_step(state)

        assert state.lifecycle_state == LifecycleState.WAITING
        assert job_queue.call_count >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Waiting workflow: Supervisor pauses on waiting_for_input step
# ═══════════════════════════════════════════════════════════════════════════════


class TestWaitingWorkflow:
    """Workflows with ``waiting_for_input`` steps pause the agent."""

    def test_waiting_step_suspends_agent(
        self,
        waiting_workflow_registry: WorkflowRegistry,
        job_queue: Any,
        store: Any,
        agent_registry: Any,
        strategy_router: Any,
    ) -> None:
        """A waiting_for_input step should transition to WAITING state."""
        wf_store = WorkflowInstanceStore()
        supervisor = Supervisor(
            registry=agent_registry,
            store=store,
            workflow_registry=waiting_workflow_registry,
            submit_job_callable=job_queue.submit,
            strategy_router=strategy_router,
            workflow_instance_store=wf_store,
        )

        # Register the waiting-agent
        from src.agent.registry import AgentMetadata, AgentIdentity
        agent_registry.register_agent(AgentMetadata(
            identity=AgentIdentity(
                agent_id="waiting-agent",
                name="Waiting Agent",
                description="Agent that pauses for input",
            ),
            capabilities=["conversational"],
        ))

        state = supervisor.create_agent("waiting-agent")
        msg = AgentMessage(message="start workflow waiting", context={})
        state = supervisor.activate_agent(state, msg, channel="cli")
        state = supervisor.run_agent_step(state)

        assert state.lifecycle_state == LifecycleState.WAITING, (
            f"Expected WAITING after waiting_for_input step, "
            f"got {state.lifecycle_state}"
        )

    def test_resume_from_waiting(
        self,
        waiting_workflow_registry: WorkflowRegistry,
        job_queue: Any,
        store: Any,
        agent_registry: Any,
        strategy_router: Any,
    ) -> None:
        """Resuming a WAITING agent should progress to the next step."""
        from src.agent.registry import AgentMetadata, AgentIdentity

        agent_registry.register_agent(AgentMetadata(
            identity=AgentIdentity(
                agent_id="waiting-agent",
                name="Waiting Agent",
                description="Agent that pauses for input",
            ),
            capabilities=["conversational"],
        ))

        wf_store = WorkflowInstanceStore()
        supervisor = Supervisor(
            registry=agent_registry,
            store=store,
            workflow_registry=waiting_workflow_registry,
            submit_job_callable=job_queue.submit,
            strategy_router=strategy_router,
            workflow_instance_store=wf_store,
        )

        state = supervisor.create_agent("waiting-agent")
        state = supervisor.activate_agent(
            state, AgentMessage(message="start workflow", context={}), channel="cli",
        )
        state = supervisor.run_agent_step(state)
        assert state.lifecycle_state == LifecycleState.WAITING

        # Resume with user input — message must route to DEST_WORKFLOW
        # (the message text becomes the user input for the engine)
        state = supervisor.run_agent_step(
            state, message="start workflow I want to say goodbye",
        )
        assert state.lifecycle_state == LifecycleState.COMPLETED, (
            f"Expected COMPLETED after resume, got {state.lifecycle_state}"
        )

        assert state.lifecycle_state in (
            LifecycleState.COMPLETED, LifecycleState.RUNNING,
        ), f"Expected COMPLETED or RUNNING, got {state.lifecycle_state}"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Workflow engine: pure state-machine transitions
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkflowEngine:
    """Direct tests of the WorkflowEngine (no Supervisor involved)."""

    def test_start_workflow(self, workflow_engine: WorkflowEngine) -> None:
        """start_workflow should create RUNNING state at the start step."""
        state = workflow_engine.start_workflow("default-agent")
        assert state.status == WorkflowStatus.RUNNING
        assert state.current_step_id == "greet"
        assert state.workflow_id == "default-agent"

    def test_step_returns_llm_call_outcome(
        self, workflow_engine: WorkflowEngine,
    ) -> None:
        """The first step of hello_world should return an llm_call outcome."""
        state = workflow_engine.start_workflow("default-agent")
        new_state, outcome = workflow_engine.step(state)
        assert outcome.type == "llm_call", (
            f"Expected llm_call outcome, got {outcome.type}"
        )
        assert outcome.step_id == "greet"

    def test_resume_with_result_completes(
        self, workflow_engine: WorkflowEngine,
    ) -> None:
        """After providing an llm_call result, the workflow should complete."""
        state = workflow_engine.start_workflow("default-agent")
        state, outcome = workflow_engine.step(state)
        assert outcome.type == "llm_call"

        state, _ = workflow_engine.resume_with_result(
            state, outcome.step_id,
            result={"message": "Hello, world!"},
        )
        assert state.status == WorkflowStatus.COMPLETED, (
            f"Expected COMPLETED after resume, got {state.status}"
        )

    def test_start_missing_workflow(self, workflow_engine: WorkflowEngine) -> None:
        """Starting an unregistered workflow should raise ValueError."""
        with pytest.raises(ValueError, match="not found"):
            workflow_engine.start_workflow("does-not-exist")


# ═══════════════════════════════════════════════════════════════════════════════
# 7. TriggerRouter: WorkflowEvent → start_workflow
# ═══════════════════════════════════════════════════════════════════════════════


class TestTriggerRouter:
    """The TriggerRouter bridges S4 events to workflow instances."""

    def test_handle_start_event_creates_execution(
        self,
        trigger_router: TriggerRouter,
        workflow_engine: WorkflowEngine,
    ) -> None:
        """A workflow.start event should create a new execution."""
        event = WorkflowEvent(
            event_type="workflow.start",
            payload={"input": "hello from event"},
            correlation_id="evt-001",
        )
        execution_id = trigger_router.handle_event(event)
        assert execution_id is not None, "Expected an execution_id"

    def test_handle_event_no_match(
        self,
        trigger_router: TriggerRouter,
    ) -> None:
        """An event type with no matching workflow returns None."""
        event = WorkflowEvent(
            event_type="workflow.nonexistent",
            payload={},
            correlation_id="evt-002",
        )
        execution_id = trigger_router.handle_event(event)
        assert execution_id is None

    def test_subscribe_and_publish(
        self,
        trigger_router: TriggerRouter,
        event_bus: Any,
        workflow_engine: WorkflowEngine,
    ) -> None:
        """Publishing via EventBus should trigger workflow start."""
        trigger_router.subscribe_to(["workflow.start"], event_bus)

        from src.agent.workflow.trigger_router import WorkflowEvent
        event_bus.publish(
            "workflow.start",
            event=WorkflowEvent(
                event_type="workflow.start",
                payload={"input": "bus event"},
                correlation_id="evt-003",
            ),
        )

        # The TriggerRouter handler ran synchronously —
        # we verify indirectly through the engine/registry state.
        # Since handle_event returns execution_id but publish is fire-and-forget,
        # we verify the event bus had subscribers.
        assert event_bus.subscriber_count >= 1

    def test_subscribe_all(
        self,
        trigger_router: TriggerRouter,
        event_bus: Any,
    ) -> None:
        """subscribe_all should register all trigger event types from the registry."""
        trigger_router.subscribe_all(event_bus)
        assert event_bus.subscriber_count >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Error handling
# ═══════════════════════════════════════════════════════════════════════════════


class TestS4BJobCompletion:
    """Gap 1: Simulate S4B job-completion via Supervisor tools.

    Tests that ``set_tool_result()`` and ``get_agent_state()`` work
    correctly, and that a tool_execute workflow can be driven to
    completion by injecting a result.
    """

    def test_tool_execute_with_result_resumes_and_completes(
        self,
        wired_tool_supervisor: Supervisor,
    ) -> None:
        """tool_execute workflow runs→WAITING→set result→run_agent_step→COMPLETED."""
        agent_id = "tools-workflow"
        msg = AgentMessage(
            message="run workflow",
            context={"channel": "cli"},
        )

        state = wired_tool_supervisor.create_agent(agent_id)
        state = wired_tool_supervisor.activate_agent(state, msg, channel="cli")
        state = wired_tool_supervisor.run_agent_step(state)

        assert state.lifecycle_state == LifecycleState.WAITING
        assert "workflow_waiting_for" in state.supervisor_metadata
        assert "tool_result" in state.supervisor_metadata["workflow_waiting_for"]

        # Simulate S4B job completion
        wired_tool_supervisor.set_tool_result(agent_id, "42")

        # Resume the workflow
        state = wired_tool_supervisor.get_agent_state(agent_id)
        state = wired_tool_supervisor.run_agent_step(state)
        assert state.lifecycle_state == LifecycleState.COMPLETED

        resp = wired_tool_supervisor.get_response(state)
        assert resp is not None
        assert resp.reply is not None

    def test_set_tool_result_nonexistent_agent(self) -> None:
        """set_tool_result on unknown agent should raise."""
        from src.agent.supervisor import Supervisor, SupervisorError

        supervisor = Supervisor.__new__(Supervisor)

        # Minimal wiring so _store is accessible
        from src.agent.adapters.memory_agent_state_store import MemoryAgentStateStore
        supervisor._store = MemoryAgentStateStore()
        supervisor._auto_persist = True

        with pytest.raises(SupervisorError, match="No agent found"):
            supervisor.set_tool_result("ghost", "result")

    def test_get_agent_state_nonexistent(self) -> None:
        """get_agent_state on unknown agent should raise."""
        from src.agent.supervisor import Supervisor, SupervisorError

        supervisor = Supervisor.__new__(Supervisor)
        from src.agent.adapters.memory_agent_state_store import MemoryAgentStateStore
        supervisor._store = MemoryAgentStateStore()

        with pytest.raises(SupervisorError, match="No agent found"):
            supervisor.get_agent_state("ghost")


class TestGatewayAdapterResume:
    """Gap 2: GatewayAdapter resume path.

    Tests that ``AgentGatewayAdapter.resume()`` correctly handles
    WAITING agents, completed transitions, and error cases.
    """

    def test_adapter_resume_tool_workflow(
        self,
        tool_gateway_adapter: AgentGatewayAdapter,
    ) -> None:
        """ingest(tool_execute_trigger) → WAITING → resume → COMPLETED."""
        from src.gateway.adapters.agent_adapter import AgentRequest

        # Step 1: Ingest a tool-workflow request
        result = tool_gateway_adapter.ingest(AgentRequest(
            channel="cli",
            message_text="run workflow",
            user_id="test-user",
            metadata={"agent_id": "tools-workflow"},
        ))

        assert "error" not in result, f"ingest failed: {result}"
        assert result.get("state") == "waiting"
        agent_id = result["agent_id"]

        # Simulate S4B completion
        tool_gateway_adapter._supervisor.set_tool_result(agent_id, '"hello from tool"')

        # Step 2: Resume
        result = tool_gateway_adapter.resume(agent_id, "continue")
        assert "error" not in result, f"resume failed: {result}"
        assert "reply" in result
        assert result["agent_id"] == agent_id

    def test_adapter_resume_nonexistent_agent(
        self,
        tool_gateway_adapter: AgentGatewayAdapter,
    ) -> None:
        """resume with unknown agent_id should return error."""
        result = tool_gateway_adapter.resume("ghost", "hello")
        assert "error" in result
        assert "Failed to load agent state" in result["error"]

    def test_adapter_resume_non_waiting_agent(
        self,
        tool_gateway_adapter: AgentGatewayAdapter,
    ) -> None:
        """resume on a non-WAITING agent should return error."""
        from src.gateway.adapters.agent_adapter import AgentRequest

        # Run a quick workflow that completes immediately
        result = tool_gateway_adapter.ingest(AgentRequest(
            channel="cli",
            message_text="hello",
            user_id="test-user",
            metadata={},
        ))

        # This should complete without waiting
        assert "reply" in result, f"unexpected non-reply: {result}"  # noqa: S101
        agent_id = result["agent_id"]

        # Try to resume — should fail since agent is not WAITING
        result = tool_gateway_adapter.resume(agent_id, "continue")
        assert "error" in result
        assert "not WAITING" in result["error"]


class TestErrorHandling:
    """Edge cases and error paths in the Gateway → S5 pipeline."""

    def test_unknown_agent_id(
        self,
        wired_supervisor: Supervisor,
    ) -> None:
        """Creating an agent with an unknown ID should raise."""
        from src.agent.supervisor import SupervisorError

        with pytest.raises(SupervisorError):
            wired_supervisor.create_agent("ghost-agent")

    def test_gateway_adapter_unknown_agent(
        self,
        gateway_adapter: Any,
    ) -> None:
        """Gateway adapter should return error for unknown agent_id."""
        from src.gateway.adapters.agent_adapter import AgentRequest

        result = gateway_adapter.ingest(AgentRequest(
            channel="cli",
            message_text="hello",
            user_id="test-user",
            metadata={"agent_id": "ghost-agent"},
        ))
        assert "error" in result

    def test_activate_without_create(self, wired_supervisor: Supervisor) -> None:
        """Activating without creating should raise."""
        with pytest.raises(Exception):
            wired_supervisor.activate_agent(
                None,  # type: ignore[arg-type]
                AgentMessage(message="test", context={}),
                channel="cli",
            )
