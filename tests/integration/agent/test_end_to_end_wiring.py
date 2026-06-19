"""
Sprint 5 — End-to-End Wiring Integration Tests
================================================

Tests the **full Gateway → S5 → Workflow Engine → LLM / S4B** pipeline
so a single user message exercises all layers:

    submit_channel_input
      → CLIChannel.receive / normalize
      → SessionedAdapter.ingest
      → AgentGatewayAdapter.ingest
      → Supervisor.activate_agent
      → Supervisor.run_agent_step
      → Router.route_message (DEST_WORKFLOW)
      → WorkflowEngine.start_workflow
      → WorkflowEngine.step → llm_call / tool_execute outcome
      → _run_workflow_loop dispatch
      → StrategyRouter._route_to_llm  (s5.3)
      → dispatch_route                 (s5.4)
      → _CapturingCallRuntime / InMemoryJobQueue assertions

Tests (5.3–5.5):
- 5.3: Workflow → LLM call  (single llm_call step)
- 5.4: tool_execute → S4 jobs  (single tool_execute step)
- 5.5: Multi-step workflow  (two sequential llm_call steps)
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
from src.agent.workflow import (
    InMemoryJobQueue,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowRegistry,
    WorkflowStep,
)
from src.gateway.channels.registry import ChannelRegistry
from src.gateway.channels.cli import register_cli_channel
from src.gateway.entrypoint import submit_channel_input
from src.runtime.interfaces import PromptRequest, PromptResponse


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def agent_registry() -> AgentRegistry:
    """Register a default-agent for the Gateway to resolve."""
    reg = AgentRegistry()
    reg.register_agent(AgentMetadata(
        identity=AgentIdentity(
            agent_id="default-agent",
            name="Default Agent",
            description="Default conversational agent",
        ),
    ))
    return reg


@pytest.fixture
def channel_registry() -> ChannelRegistry:
    """Fresh ChannelRegistry with a CLI channel."""
    reg = ChannelRegistry()
    register_cli_channel(reg)
    return reg


@pytest.fixture
def capturing_runtime() -> _CapturingCallRuntime:
    """Mock call_runtime that captures the last PromptRequest."""
    return _CapturingCallRuntime()


@pytest.fixture
def job_queue() -> InMemoryJobQueue:
    """Fresh in-memory job queue."""
    return InMemoryJobQueue()


# ══════════════════════════════════════════════════════════════════════════════
# 5.3 — Workflow → LLM call (single llm_call step)
# ══════════════════════════════════════════════════════════════════════════════


class TestWorkflowToLlmCall:
    """Verify a workflow with a single llm_call step dispatches to the Runtime."""

    _WORKFLOW_ID = "test-s53"

    @staticmethod
    def _build_workflow_registry() -> WorkflowRegistry:
        reg = WorkflowRegistry()
        reg.register(WorkflowDefinition(
            workflow_id="test-s53",
            name="S5.3 Test",
            description="Single LLM call step",
            steps={
                "step-1": WorkflowStep(
                    step_id="step-1",
                    step_type="llm_call",
                    label="Greet",
                    config={"message": "Hello from workflow"},
                    transitions={"on_success": "__end__"},
                ),
            },
            start_step="step-1",
        ))
        return reg

    @staticmethod
    def _build_adapter(
        agent_registry: AgentRegistry,
        capturing_runtime: _CapturingCallRuntime,
        workflow_registry: WorkflowRegistry,
    ) -> SessionedAdapter:
        strategy_router = StrategyRouter(call_runtime=capturing_runtime)
        store = MemoryAgentStateStore()
        supervisor = Supervisor(
            registry=agent_registry,
            store=store,
            strategy_router=strategy_router,
            workflow_registry=workflow_registry,
            auto_persist=True,
        )
        inner = AgentGatewayAdapter(supervisor)
        return SessionedAdapter(inner)

    @staticmethod
    def _send(
        channel_registry: ChannelRegistry,
        adapter: SessionedAdapter,
        text: str,
    ) -> dict[str, Any]:
        result = submit_channel_input(
            channel_registry,
            "cli",
            {"text": text, "sender": "brett"},
            adapter,
        )
        assert "reply" in result, f"Expected reply, got: {result}"
        return result

    def test_llm_call_step_invokes_runtime(
        self,
        agent_registry: AgentRegistry,
        channel_registry: ChannelRegistry,
        capturing_runtime: _CapturingCallRuntime,
    ) -> None:
        """A workflow with one llm_call step ends up calling the Runtime."""
        wf_reg = self._build_workflow_registry()
        adapter = self._build_adapter(agent_registry, capturing_runtime, wf_reg)

        result = self._send(channel_registry, adapter, f"/workflow {self._WORKFLOW_ID}")

        assert result["reply"] is not None
        req = capturing_runtime.last_request
        assert req is not None, "Runtime should have been called"
        # The rendered config is the step's config with templates resolved
        prompt_msg = req.prompt.get("message", "")
        # The template renders the config dict as a string; the key message
        # should survive into the rendered config
        assert "Hello from workflow" in str(prompt_msg) or "Hello from workflow" in str(req.prompt), (
            f"Expected workflow step config to reach Runtime prompt, "
            f"got: {req.prompt}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 5.4 — tool_execute → S4 jobs (single tool_execute step)
# ══════════════════════════════════════════════════════════════════════════════


class TestToolExecuteToS4Jobs:
    """Verify a workflow with a tool_execute step enqueues an S4 job."""

    _WORKFLOW_ID = "test-s54"

    @staticmethod
    def _build_workflow_registry() -> WorkflowRegistry:
        reg = WorkflowRegistry()
        reg.register(WorkflowDefinition(
            workflow_id="test-s54",
            name="S5.4 Test",
            description="Single tool_execute step",
            steps={
                "step-1": WorkflowStep(
                    step_id="step-1",
                    step_type="tool_execute",
                    label="Run tool",
                    config={"skill": "echo", "args": {"text": "hello"}},
                    transitions={"on_success": "__end__"},
                ),
            },
            start_step="step-1",
        ))
        return reg

    @staticmethod
    def _build_adapter(
        agent_registry: AgentRegistry,
        job_queue: InMemoryJobQueue,
        workflow_registry: WorkflowRegistry,
    ) -> SessionedAdapter:
        strategy_router = StrategyRouter(submit_s4_job=job_queue.submit)
        store = MemoryAgentStateStore()
        supervisor = Supervisor(
            registry=agent_registry,
            store=store,
            strategy_router=strategy_router,
            workflow_registry=workflow_registry,
            submit_job_callable=job_queue.submit,
            auto_persist=True,
        )
        inner = AgentGatewayAdapter(supervisor)
        return SessionedAdapter(inner)

    @staticmethod
    def _send(
        channel_registry: ChannelRegistry,
        adapter: SessionedAdapter,
        text: str,
    ) -> dict[str, Any]:
        result = submit_channel_input(
            channel_registry,
            "cli",
            {"text": text, "sender": "brett"},
            adapter,
        )
        return result

    def test_tool_execute_enqueues_job(
        self,
        agent_registry: AgentRegistry,
        channel_registry: ChannelRegistry,
        job_queue: InMemoryJobQueue,
    ) -> None:
        """A workflow with one tool_execute step submits a job to the queue.

        The tool_execute step dispatches via dispatch_route → submit_job_callable
        and the supervisor pauses in waiting state until the S4 job completes.
        """
        wf_reg = self._build_workflow_registry()
        adapter = self._build_adapter(agent_registry, job_queue, wf_reg)

        result = self._send(channel_registry, adapter, f"/workflow {self._WORKFLOW_ID}")

        # tool_execute dispatches the job and pauses — expect waiting state
        assert result.get("state") == "waiting", (
            f"Expected waiting state after tool_execute workflow, got: {result}"
        )

        # Verify a job was enqueued
        jobs = job_queue.list()
        assert len(jobs) == 1, (
            f"Expected 1 job in queue, got {len(jobs)}"
        )
        record = jobs[0]
        assert record.status in ("queued", "running"), (
            f"Expected job to be queued or running, got {record.status}"
        )
        # The payload should contain the step's config
        payload = record.payload
        assert payload is not None, "Job payload should not be None"
        skill = payload.get("payload", payload).get("skill", payload)
        assert "echo" in str(skill), (
            f"Expected 'echo' in job payload, got: {payload}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 5.5 — Multi-step workflow (two sequential llm_call steps)
# ══════════════════════════════════════════════════════════════════════════════


class TestMultiStepWorkflow:
    """Verify a workflow with two sequential llm_call steps executes both."""

    _WORKFLOW_ID = "test-s55"

    @staticmethod
    def _build_workflow_registry() -> WorkflowRegistry:
        reg = WorkflowRegistry()
        reg.register(WorkflowDefinition(
            workflow_id="test-s55",
            name="S5.5 Test",
            description="Two sequential llm_call steps",
            steps={
                "step-1": WorkflowStep(
                    step_id="step-1",
                    step_type="llm_call",
                    label="Analyze",
                    config={"message": "Analyze the input", "role": "analyzer"},
                    transitions={"on_success": "step-2"},
                ),
                "step-2": WorkflowStep(
                    step_id="step-2",
                    step_type="llm_call",
                    label="Summarize",
                    config={"message": "Summarize the analysis", "role": "summarizer"},
                    transitions={"on_success": "__end__"},
                ),
            },
            start_step="step-1",
        ))
        return reg

    @staticmethod
    def _build_adapter(
        agent_registry: AgentRegistry,
        capturing_runtime: _CapturingCallRuntime,
        workflow_registry: WorkflowRegistry,
    ) -> SessionedAdapter:
        strategy_router = StrategyRouter(call_runtime=capturing_runtime)
        store = MemoryAgentStateStore()
        supervisor = Supervisor(
            registry=agent_registry,
            store=store,
            strategy_router=strategy_router,
            workflow_registry=workflow_registry,
            auto_persist=True,
        )
        inner = AgentGatewayAdapter(supervisor)
        return SessionedAdapter(inner)

    @staticmethod
    def _send(
        channel_registry: ChannelRegistry,
        adapter: SessionedAdapter,
        text: str,
    ) -> dict[str, Any]:
        result = submit_channel_input(
            channel_registry,
            "cli",
            {"text": text, "sender": "brett"},
            adapter,
        )
        assert "reply" in result, f"Expected reply, got: {result}"
        return result

    def test_two_llm_call_steps_execute_in_order(
        self,
        agent_registry: AgentRegistry,
        channel_registry: ChannelRegistry,
    ) -> None:
        """Both steps execute sequentially through the Runtime."""
        wf_reg = self._build_workflow_registry()
        # Use an accumulator runtime that tracks all requests
        runtime = _AccumulatingCallRuntime()
        adapter = self._build_adapter(agent_registry, runtime, wf_reg)

        result = self._send(channel_registry, adapter, f"/workflow {self._WORKFLOW_ID}")

        assert result["reply"] is not None
        assert len(runtime.requests) >= 2, (
            f"Expected at least 2 Runtime calls for 2-step workflow, "
            f"got {len(runtime.requests)}"
        )
        # The last request should be from step-2 (summarizer)
        last_req = runtime.requests[-1]
        assert "Summarize" in str(last_req.prompt), (
            f"Expected last step to be 'Summarize', got: {last_req.prompt}"
        )


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


class _AccumulatingCallRuntime:
    """Mock call_runtime that accumulates all PromptRequests."""

    def __init__(self) -> None:
        self.requests: list[PromptRequest] = []

    def __call__(
        self,
        request: PromptRequest,
        *,
        backend: str = "conversational",
    ) -> PromptResponse:
        self.requests.append(request)
        return PromptResponse(
            output={
                "message": f"Mock: {request.prompt.get('message', '')}",
                "is_complete": True,
            },
            tool_calls=[],
        )
