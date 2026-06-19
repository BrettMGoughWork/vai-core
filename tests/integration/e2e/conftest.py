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
from src.runtime.interfaces.contract import PromptResponse


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
# Waiting-for-input workflow (tests WAITING state + resume path)
# ======================================================================

waiting_workflow = WorkflowDefinition(
    workflow_id="waiting-agent",
    name="Waiting Agent",
    description="A workflow that pauses for user input before completing",
    version="1.0.0",
    trigger_on=["workflow.start", "workflow_request"],
    steps={
        "ask": WorkflowStep(
            step_id="ask",
            step_type="user_input",
            label="Ask the user a question",
            config={"prompt": "What would you like to do?", "timeout_seconds": 60},
            transitions={"on_success": "confirm", "on_timeout": "__end__"},
        ),
        "confirm": WorkflowStep(
            step_id="confirm",
            step_type="llm_call",
            label="Confirm the user's choice",
            config={"prompt": "The user said: {{input}}. Confirm this choice."},
            transitions={"on_success": "__end__"},
        ),
    },
    start_step="ask",
)


# ======================================================================
# Validated input workflow (tests input_schema enforcement)
# ======================================================================

validated_workflow = WorkflowDefinition(
    workflow_id="validated-agent",
    name="Validated Agent",
    description="A workflow that enforces an input_schema on user_input",
    version="1.0.0",
    trigger_on=["workflow.start", "workflow_request"],
    steps={
        "ask": WorkflowStep(
            step_id="ask",
            step_type="user_input",
            label="Ask the user a question",
            config={
                "prompt": "Enter a value:",
                "timeout_seconds": 60,
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                    },
                    "required": ["text"],
                },
            },
            transitions={"on_success": "confirm"},
        ),
        "confirm": WorkflowStep(
            step_id="confirm",
            step_type="llm_call",
            label="Confirm the user's choice",
            config={"prompt": "The user said: {{input}}. Confirm this choice."},
            transitions={"on_success": "__end__"},
        ),
    },
    start_step="ask",
)


# ======================================================================
# Invalid-input workflow (tests schema failure + retry)
# ======================================================================

invalid_workflow = WorkflowDefinition(
    workflow_id="invalid-agent",
    name="Invalid Agent",
    description="A workflow that rejects input until the exact expected message is sent",
    version="1.0.0",
    trigger_on=["workflow.start", "workflow_request"],
    steps={
        "ask": WorkflowStep(
            step_id="ask",
            step_type="user_input",
            label="Ask the user a question",
            config={
                "prompt": "Say the magic words:",
                "timeout_seconds": 60,
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "enum": ["/workflow invalid-agent VALID"],
                        },
                    },
                    "required": ["text"],
                },
            },
            transitions={"on_success": "confirm"},
        ),
        "confirm": WorkflowStep(
            step_id="confirm",
            step_type="llm_call",
            label="Confirm the user's choice",
            config={"prompt": "The user said: {{input}}. Confirm this choice."},
            transitions={"on_success": "__end__"},
        ),
    },
    start_step="ask",
)


# ======================================================================
# Timeout workflow (tests expired HITL request handling)
# ======================================================================

timeout_workflow = WorkflowDefinition(
    workflow_id="timeout-agent",
    name="Timeout Agent",
    description="A workflow with an immediately-expired user_input timeout",
    version="1.0.0",
    trigger_on=["workflow.start", "workflow_request"],
    steps={
        "ask": WorkflowStep(
            step_id="ask",
            step_type="user_input",
            label="Ask the user a question",
            config={
                "prompt": "Quick question:",
                "timeout_seconds": -2,  # expired immediately
            },
            transitions={"on_success": "confirm"},
            # No on_timeout → handle_timeout will FAIL the workflow
        ),
        "confirm": WorkflowStep(
            step_id="confirm",
            step_type="llm_call",
            label="Confirm the user's choice",
            config={"prompt": "The user said: {{input}}. Confirm this choice."},
            transitions={"on_success": "__end__"},
        ),
    },
    start_step="ask",
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
    """``AgentRegistry`` with default + tools-workflow agents."""
    reg = AgentRegistry()
    reg.register_agent(AgentMetadata(
        identity=AgentIdentity(
            agent_id="default-agent",
            name="Default Agent",
            description="Default conversational agent",
        ),
        capabilities=["conversational"],
    ))
    reg.register_agent(AgentMetadata(
        identity=AgentIdentity(
            agent_id="tools-workflow",
            name="Tools Workflow Agent",
            description="Agent that dispatches tool execute jobs",
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


@pytest.fixture
def wired_tool_supervisor(
    agent_registry: AgentRegistry,
    store: MemoryAgentStateStore,
    multi_workflow_registry: WorkflowRegistry,
    job_queue: InMemoryJobQueue,
    strategy_router: StrategyRouter,
) -> Supervisor:
    """A fully-wired ``Supervisor`` with tool_execute workflow support.

    Same as ``wired_supervisor`` but uses ``multi_workflow_registry``
    so tool_execute steps can be dispatched to S4B.
    """
    wf_store = WfStore()
    return Supervisor(
        registry=agent_registry,
        store=store,
        workflow_registry=multi_workflow_registry,
        submit_job_callable=job_queue.submit,
        strategy_router=strategy_router,
        workflow_instance_store=wf_store,
    )


@pytest.fixture
def tool_gateway_adapter(
    wired_tool_supervisor: Supervisor,
) -> AgentGatewayAdapter:
    """``AgentGatewayAdapter`` wrapping the wired tool supervisor.

    The adapter's supervisor has access to the ``tool_execute`` workflow
    so tests can exercise the WAITING → resume path.
    """
    return AgentGatewayAdapter(wired_tool_supervisor)


# ======================================================================
# EventBus / WorkflowEngine / TriggerRouter fixtures
# ======================================================================


@pytest.fixture
def event_bus() -> Any:
    """Fresh in-process ``EventBus`` for each test."""
    from src.agent.workflow.event_bus import EventBus
    return EventBus()


@pytest.fixture
def workflow_engine(workflow_registry: WorkflowRegistry) -> Any:
    """``WorkflowEngine`` wired to the hello_world registry."""
    from src.agent.workflow.engine import WorkflowEngine
    return WorkflowEngine(registry=workflow_registry)


@pytest.fixture
def trigger_router(
    workflow_registry: WorkflowRegistry,
    workflow_engine: Any,
) -> Any:
    """``TriggerRouter`` wired to the registry and engine."""
    from src.agent.workflow.trigger_router import TriggerRouter
    return TriggerRouter(registry=workflow_registry, engine=workflow_engine)


@pytest.fixture
def waiting_workflow_registry(
    workflow_registry: WorkflowRegistry,
) -> WorkflowRegistry:
    """Registry with hello_world + waiting_agent workflows."""
    workflow_registry.register(waiting_workflow)
    return workflow_registry


@pytest.fixture
def validated_workflow_registry(
    workflow_registry: WorkflowRegistry,
) -> WorkflowRegistry:
    """Registry with hello_world + validated_agent workflows."""
    workflow_registry.register(validated_workflow)
    return workflow_registry


@pytest.fixture
def timeout_workflow_registry(
    workflow_registry: WorkflowRegistry,
) -> WorkflowRegistry:
    """Registry with hello_world + timeout_agent workflows."""
    workflow_registry.register(timeout_workflow)
    return workflow_registry


@pytest.fixture
def invalid_workflow_registry(
    workflow_registry: WorkflowRegistry,
) -> WorkflowRegistry:
    """Registry with hello_world + invalid_agent workflows."""
    workflow_registry.register(invalid_workflow)
    return workflow_registry


@pytest.fixture
def full_gateway_registry() -> Any:
    """``ChannelRegistry`` with all standard channels registered.

    Provides a realistic registry for testing the Gateway entrypoint
    (``submit_channel_input`` / ``process_channel_input``).
    """
    from src.gateway.channels.registry import ChannelRegistry
    from src.gateway.channels.cli import register_cli_channel
    from src.gateway.channels.web import register_web_channel
    from src.gateway.channels.ws import register_websocket_channel
    from src.gateway.channels.slack import register_slack_channel
    from src.gateway.channels.mail import register_mail_channel
    from src.gateway.channels.webhook import register_webhook_channel

    reg = ChannelRegistry()
    register_cli_channel(reg)
    register_web_channel(reg)
    register_websocket_channel(reg)
    register_slack_channel(reg)
    register_mail_channel(reg)
    register_webhook_channel(reg)
    return reg
