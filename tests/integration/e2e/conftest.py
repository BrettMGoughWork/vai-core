"""
E2E test fixtures — fully-wired dependencies for the Gateway → S5 → S6 pipeline.

Provides:
    - ``InMemoryJobQueue`` — records submitted S4 jobs for later inspection
    - ``hello_world_workflow`` — a ``WorkflowDefinition`` with one ``llm_call`` step
    - ``mock_call_runtime`` — returns a deterministic ``PromptResponse``
    - ``wired_supervisor`` — ``Supervisor`` with workflow_registry, submit_job_callable,
      strategy_router, and workflow_instance_store
    - ``gateway_adapter`` — ``AgentGatewayAdapter`` wrapping the wired supervisor
    - ``job_queue`` — the ``InMemoryJobQueue`` instance for assertions
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.agent.adapters.gateway_adapter import AgentGatewayAdapter
from src.agent.adapters.memory_agent_state_store import MemoryAgentStateStore
from src.agent.contracts import AgentMessage
from src.agent.registry import AgentIdentity, AgentMetadata, AgentRegistry
from src.agent.strategy_router import StrategyRouter
from src.agent.supervisor import Supervisor
from src.agent.workflow import (
    WorkflowDefinition,
    WorkflowInstanceStore,
    WorkflowRegistry,
    WorkflowStep,
)
from src.agent.workflow.instance_store import WorkflowInstanceStore as WfStore
from src.runtime.contracts import PromptResponse


# ======================================================================
# In-memory S4 job queue
# ======================================================================


class InMemoryJobQueue:
    """Records submitted S4 jobs for later inspection.

    Usage
    -----
    .. code-block:: python

        queue = InMemoryJobQueue()
        job_id = queue.submit({"type": "tool_call", ...})
        assert queue.call_count == 1
    """

    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}
        self.call_count = 0

    def submit(self, payload: dict[str, Any]) -> str:
        """Record a job submission and return a synthetic job ID."""
        self.call_count += 1
        job_id = f"job-{self.call_count}-{uuid4().hex[:8]}"
        self.jobs[job_id] = {"payload": payload, "status": "pending"}
        return job_id


# ======================================================================
# Mock LLM callable (replaces StrategyRouter's call_runtime_backend)
# ======================================================================


def mock_call_runtime(request: Any, *, backend: str = "mock") -> PromptResponse:
    """Return a deterministic ``PromptResponse`` regardless of input."""
    _ = backend  # ignore — all backends return the same mock
    return PromptResponse(
        output={"message": f"Mock response to: {request.prompt}"},
        tool_calls=[],
    )


# ======================================================================
# Hello World workflow definition
# ======================================================================

hello_world_workflow = WorkflowDefinition(
    workflow_id="default-agent",
    name="Hello World",
    description="A simple hello world workflow with one LLM call step",
    version="1.0.0",
    trigger_on=["workflow.start", "workflow_request"],
    steps={
        "greet": WorkflowStep(
            step_id="greet",
            step_type="llm_call",
            label="Greet the user",
            config={"prompt": "Say hello to the user: {{input}}"},
            transitions={"on_success": "__end__"},
        ),
    },
    start_step="greet",
)

# A workflow that dispatches to S4B (for testing tool_execute → WAITING)

tool_execute_workflow = WorkflowDefinition(
    workflow_id="tools-workflow",
    name="Tool Executor",
    description="A workflow with one tool_execute step",
    version="1.0.0",
    trigger_on=["workflow.start"],
    steps={
        "run_tool": WorkflowStep(
            step_id="run_tool",
            step_type="tool_execute",
            label="Run a tool",
            config={
                "skill_name": "test_tool",
                "arguments": {"param1": "value1"},
            },
            transitions={"on_success": "__end__"},
        ),
    },
    start_step="run_tool",
)


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def job_queue() -> InMemoryJobQueue:
    """Fresh ``InMemoryJobQueue`` for each test."""
    return InMemoryJobQueue()


@pytest.fixture
def workflow_registry() -> WorkflowRegistry:
    """``WorkflowRegistry`` pre-loaded with the hello_world workflow."""
    reg = WorkflowRegistry()
    reg.register(hello_world_workflow)
    return reg


@pytest.fixture
def agent_registry() -> AgentRegistry:
    """``AgentRegistry`` with a default conversational agent."""
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
def store() -> MemoryAgentStateStore:
    """Fresh ``MemoryAgentStateStore``."""
    return MemoryAgentStateStore()


@pytest.fixture
def strategy_router() -> StrategyRouter:
    """``StrategyRouter`` with mock LLM callable + no planner/capabilities.

    The mock ``call_runtime`` returns a predictable ``PromptResponse`` so
    llm_call steps always succeed without a real LLM backend.
    """
    return StrategyRouter(call_runtime=mock_call_runtime)


@pytest.fixture
def wired_supervisor(
    agent_registry: AgentRegistry,
    store: MemoryAgentStateStore,
    workflow_registry: WorkflowRegistry,
    job_queue: InMemoryJobQueue,
    strategy_router: StrategyRouter,
) -> Supervisor:
    """A fully-wired ``Supervisor`` with all dependencies.

    Wires:
    - ``workflow_registry`` — enables DEST_WORKFLOW route
    - ``submit_job_callable`` — enables tool_execute → S4B dispatch
    - ``strategy_router`` — routes llm_call outcomes to mock LLM
    - ``workflow_instance_store`` — persists workflow state transitions

    Without this fixture, the DEST_WORKFLOW and S4B paths produce errors.
    """
    wf_store = WfStore()
    return Supervisor(
        registry=agent_registry,
        store=store,
        workflow_registry=workflow_registry,
        submit_job_callable=job_queue.submit,
        strategy_router=strategy_router,
        workflow_instance_store=wf_store,
    )


@pytest.fixture
def gateway_adapter(wired_supervisor: Supervisor) -> AgentGatewayAdapter:
    """``AgentGatewayAdapter`` wrapping the wired supervisor.

    Usage in tests::

        result = gateway_adapter.ingest(AgentRequest(
            message_text="run my workflow",
            channel="test",
            user_id="test-user",
            metadata={},
        ))
    """
    return AgentGatewayAdapter(wired_supervisor)


@pytest.fixture
def multi_workflow_registry(
    workflow_registry: WorkflowRegistry,
) -> WorkflowRegistry:
    """Registry with both hello_world and tool_execute workflows."""
    workflow_registry.register(tool_execute_workflow)
    return workflow_registry
