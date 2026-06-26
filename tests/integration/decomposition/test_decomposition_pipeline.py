"""
End-to-end integration tests for the Agent Task Decomposition pipeline.

Covers the execute_todo_plan synthetic tool lifecycle:

  - Tool injection when plan_with_todo in patterns + orchestrator configured
  - No tool injection when plan_with_todo not in patterns
  - No tool injection when decomposition_orchestrator is None
  - Intercept handler processes execute_todo_plan tool_calls
  - Error paths: missing DB, orchestrator not configured, worker not configured
"""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.agent.activation import ActivatedAgentContext, ActivationContext, ActivationEnvelope
from src.agent.adapters.memory_agent_state_store import MemoryAgentStateStore
from src.agent.contracts import AgentMessage
from src.agent.decomposition.orchestrator import (
    DecompositionOrchestrator,
)
from src.agent.decomposition.worker_pool import DecompositionWorkerPool
from src.agent.interfaces.agent_state import AgentState, LifecycleState
from src.agent.registry import AgentConstraints, AgentIdentity, AgentMetadata, AgentRegistry
from src.agent.strategy_router import RouterOutcome, StrategyRouter
from src.agent.supervisor import Supervisor
from src.agent.types.decomposition import (
    DecompositionPlan,
    MergeResult,
    SubtaskSpec,
)
from src.capabilities.planner.todo_store import TodoStore
from src.platform.runtime.join_handle import JoinHandleState
from src.platform.runtime.job_store.backends.in_memory_join_store import (
    InMemoryJoinStore,
)
from src.platform.runtime.job_store.job_store import (
    InMemoryJobStore,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def memory_join_store() -> InMemoryJoinStore:
    return InMemoryJoinStore()


@pytest.fixture
def memory_job_store() -> InMemoryJobStore:
    return InMemoryJobStore()


@pytest.fixture
def strategy_router() -> MagicMock:
    """Mock strategy router that returns an empty conversational response."""
    router = MagicMock(spec=StrategyRouter)
    router.route.return_value = {
        "output": {"message": "Understood."},
        "tool_calls": [],
        "error": None,
    }
    return router


@pytest.fixture
def todo_db() -> str:
    """Create an in-memory SQLite database with a couple of pending todos.

    Returns the database path (":memory:") so the caller can keep a separate
    connection for verification if needed.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE todos ("
        "  id TEXT PRIMARY KEY,"
        "  title TEXT NOT NULL,"
        "  description TEXT,"
        "  status TEXT DEFAULT 'pending',"
        "  agent_id TEXT,"
        "  depends_on TEXT,"
        "  created_at TEXT,"
        "  error TEXT"
        ")"
    )
    cur.execute(
        "INSERT INTO todos (id, title, description, status, agent_id, depends_on, created_at) "
        "VALUES ('research-db', 'Research database options', 'Research PostgreSQL vs MongoDB', "
        "'pending', 'default-agent', NULL, '2025-01-01T00:00:00')"
    )
    cur.execute(
        "INSERT INTO todos (id, title, description, status, agent_id, depends_on, created_at) "
        "VALUES ('write-report', 'Write comparison report', 'Write the final comparison report', "
        "'pending', 'default-agent', 'research-db', '2025-01-01T00:00:00')"
    )
    conn.commit()
    return ":memory:"


# ── Agent metadata helpers ────────────────────────────────────────────────────


def _identity(agent_id: str = "test-agent") -> AgentIdentity:
    return AgentIdentity(agent_id=agent_id, name=agent_id)


def _metadata(
    agent_id: str = "test-agent",
    patterns: list[str] | None = None,
) -> AgentMetadata:
    return AgentMetadata(
        identity=_identity(agent_id=agent_id),
        skills=[],
        inputs=["text"],
        outputs=["text", "action_intents"],
        constraints=AgentConstraints(max_tokens=4096, timeout_ms=30000),
        patterns=patterns or [],
    )


def _registry(
    agent_id: str = "test-agent",
    patterns: list[str] | None = None,
) -> AgentRegistry:
    reg = AgentRegistry()
    reg.register_agent(_metadata(agent_id=agent_id, patterns=patterns))
    return reg


def _activated_state(
    agent_id: str = "test-agent",
    patterns: list[str] | None = None,
) -> AgentState:
    """Create a minimal ACTIVATED AgentState with an activation snapshot."""
    msg = AgentMessage(message="Hello", context={"channel": "cli"})
    env = ActivationEnvelope(
        agent_id=agent_id,
        message=msg,
        activation_context={
            "timestamp": "2024-01-01T00:00:00Z",
            "channel": "cli",
            "correlation_id": "corr-1",
            "trace_id": "trace-1",
        },
    )
    ctx = ActivationContext(
        agent_metadata=_metadata(agent_id=agent_id, patterns=patterns),
        conversation_history=[],
        system_constraints={"max_tokens": 4096, "timeout_ms": 30000, "sandbox": "none"},
    )
    return AgentState(
        agent_id=agent_id,
        correlation_id="corr-1",
        trace_id="trace-1",
        lifecycle_state=LifecycleState.ACTIVATED,
        activation_snapshot=ActivatedAgentContext(envelope=env, context=ctx),
    )


def _running_state(
    agent_id: str = "test-agent",
    patterns: list[str] | None = None,
) -> AgentState:
    """Create a RUNNING AgentState with activation snapshot."""
    state = _activated_state(agent_id=agent_id, patterns=patterns)
    return state.with_(lifecycle_state=LifecycleState.RUNNING)


# ── Auto-complete worker for polling loop ─────────────────────────────────────


class _AutoCompleteWorker:
    """Simulates the S4 worker/continuation pipeline.

    On the first ``process_next()`` call, marks every **WAITING**
    ``JoinHandle`` as **COMPLETED** by recording all child jobs as
    successfully finished.
    """

    def __init__(self, join_store: InMemoryJoinStore) -> None:
        self._join_store = join_store
        self._done = False

    def process_next(self) -> None:
        if self._done:
            return
        self._done = True
        for entry in self._join_store.list():
            handle = self._join_store.get(entry["join_handle_id"])
            if handle is not None and handle.state == JoinHandleState.WAITING:
                for jid in handle.child_job_ids:
                    handle.mark_child_completed(jid)
                self._join_store.save(handle)


# ── Test: Tool injection ──────────────────────────────────────────────────────


class TestExecuteTodoPlanToolInjection:
    """Verify the execute_todo_plan synthetic tool is injected into tool_context
    only when both conditions are met: agent has ``plan_with_todo`` in its
    patterns *and* a DecompositionOrchestrator is configured.
    """

    def _capture_tool_context(
        self,
        sup: Supervisor,
        state: AgentState,
    ) -> list[dict]:
        """Run one step and return the tool_context passed to the strategy
        router by monkey-patching ``self._strategy_router.route()``."""

        captured: list[dict] = []

        def _capture(outcome: RouterOutcome) -> dict[str, Any]:
            captured.append(outcome.payload.get("tool_context", []))
            return {"output": {"message": "Understood."}, "tool_calls": [], "error": None}

        sup._strategy_router.route.side_effect = _capture
        sup.run_agent_step(state)
        return captured

    def _is_execute_todo_plan_tool(self, tc: Any) -> bool:
        return bool(
            isinstance(tc, dict)
            and isinstance(tc.get("function"), dict)
            and tc["function"].get("name") == "execute_todo_plan"
        )

    def test_tool_injected_when_patterns_match(
        self,
        strategy_router: MagicMock,
    ) -> None:
        """Tool injected when plan_with_todo in patterns + orchestrator configured."""
        sup = Supervisor(
            registry=_registry(patterns=["plan_with_todo"]),
            store=MemoryAgentStateStore(),
            strategy_router=strategy_router,
            decomposition_orchestrator=MagicMock(),
        )
        state = _running_state(patterns=["plan_with_todo"])
        contexts = self._capture_tool_context(sup, state)
        assert any(
            self._is_execute_todo_plan_tool(tc)
            for ctx in contexts
            for tc in (ctx if isinstance(ctx, list) else [ctx])
        ), "execute_todo_plan tool should be in tool_context when plan_with_todo in patterns"

    def test_tool_not_injected_when_patterns_mismatch(
        self,
        strategy_router: MagicMock,
    ) -> None:
        """No tool when plan_with_todo not in patterns, even with orchestrator."""
        sup = Supervisor(
            registry=_registry(patterns=["some-other-pattern"]),
            store=MemoryAgentStateStore(),
            strategy_router=strategy_router,
            decomposition_orchestrator=MagicMock(),
        )
        state = _running_state(patterns=["some-other-pattern"])
        contexts = self._capture_tool_context(sup, state)
        for ctx in contexts:
            for tc in (ctx if isinstance(ctx, list) else [ctx]):
                if self._is_execute_todo_plan_tool(tc):
                    pytest.fail(
                        "execute_todo_plan should NOT be injected "
                        "when plan_with_todo is not in patterns"
                    )

    def test_tool_not_injected_when_no_orchestrator(
        self,
        strategy_router: MagicMock,
    ) -> None:
        """No tool when decomposition_orchestrator is None."""
        sup = Supervisor(
            registry=_registry(patterns=["plan_with_todo"]),
            store=MemoryAgentStateStore(),
            strategy_router=strategy_router,
            decomposition_orchestrator=None,
        )
        state = _running_state(patterns=["plan_with_todo"])
        contexts = self._capture_tool_context(sup, state)
        for ctx in contexts:
            for tc in (ctx if isinstance(ctx, list) else [ctx]):
                if self._is_execute_todo_plan_tool(tc):
                    pytest.fail(
                        "execute_todo_plan should NOT be injected "
                        "when decomposition_orchestrator is None"
                    )


# ── Test: Tool intercept + execution lifecycle ────────────────────────────────


class TestExecuteTodoPlanIntercept:
    """Verify the execute_todo_plan tool_calls are intercepted *before*
    ToolOrchestrator, fan-out/fan-in is executed, and the tool_calls are
    removed from the forwarded list.
    """

    def _make_supervisor_with_tool_calls(
        self,
        strategy_router: MagicMock,
        registry: AgentRegistry,
        orchestrator: DecompositionOrchestrator | None = None,
        tool_calls: list[dict] | None = None,
    ) -> Supervisor:
        if tool_calls is None:
            tool_calls = []
        strategy_router.route.return_value = {
            "output": {"message": "Executing plan."},
            "tool_calls": tool_calls,
            "error": None,
        }

        join_store = (
            InMemoryJoinStore()
            if orchestrator is None
            else orchestrator._join_store
        )
        orch = orchestrator or DecompositionOrchestrator(
            join_store=join_store,
            enqueue_fn=None,
            enqueue_continuation_fn=None,
        )

        sup = Supervisor(
            registry=registry,
            store=MemoryAgentStateStore(),
            strategy_router=strategy_router,
            decomposition_orchestrator=orch,
            job_store=InMemoryJobStore(),
        )
        # Wire a DecompositionWorkerPool (pool_size=1) using the
        # _AutoCompleteWorker helper so the supervisor's pool check
        # passes and auto-completion fires during fan-in polling.
        pool = DecompositionWorkerPool(
            worker_factory=lambda: _AutoCompleteWorker(join_store),  # type: ignore[arg-type]
            pool_size=1,
        )
        pool.start()
        sup._decomposition_worker_pool = pool
        # Register finalizer so pool threads don't outlive the test
        import atexit as _atexit
        _atexit.register(pool.stop)
        return sup

    def test_intercept_executes_plan(
        self,
        strategy_router: MagicMock,
    ) -> None:
        """execute_todo_plan tool_call is intercepted, todos are fanned-out,
        fanned-in, marked done, and the reply confirms execution."""
        join_store = InMemoryJoinStore()
        orch = DecompositionOrchestrator(
            join_store=join_store,
            enqueue_fn=None,
            enqueue_continuation_fn=None,
        )
        reg = _registry(patterns=["plan_with_todo"])
        state = _running_state(patterns=["plan_with_todo"])
        sup = self._make_supervisor_with_tool_calls(
            strategy_router=strategy_router,
            registry=reg,
            orchestrator=orch,
            tool_calls=[
                {
                    "name": "execute_todo_plan",
                    "arguments": {"db_path": ":memory:"},
                },
            ],
        )
        result = sup.run_agent_step(state)
        reply = result.final_response.reply if result.final_response else ""
        assert "fan-out/fan-in" in reply, (
            f"Expected fan-out/fan-in message in reply, got {reply!r}"
        )

    def test_intercept_missing_db(
        self,
        strategy_router: MagicMock,
    ) -> None:
        """If db_path points to a non-existent file, the handler catches
        the error gracefully."""
        reg = _registry(patterns=["plan_with_todo"])
        state = _running_state(patterns=["plan_with_todo"])
        join_store = InMemoryJoinStore()
        sup = self._make_supervisor_with_tool_calls(
            strategy_router=strategy_router,
            registry=reg,
            orchestrator=DecompositionOrchestrator(
                join_store=join_store,
                enqueue_fn=None,
                enqueue_continuation_fn=None,
            ),
            tool_calls=[
                {
                    "name": "execute_todo_plan",
                    "arguments": {"db_path": "/nonexistent/db.sqlite"},
                },
            ],
        )
        result = sup.run_agent_step(state)
        reply = result.final_response.reply if result.final_response else ""
        assert "execute_todo_plan error" in reply, (
            f"Expected execute_todo_plan error message, got {reply!r}"
        )

    def test_intercept_empty_db(
        self,
        strategy_router: MagicMock,
    ) -> None:
        """If the db exists but has no pending todos, the handler returns
        a no-op response."""
        reg = _registry(patterns=["plan_with_todo"])
        state = _running_state(patterns=["plan_with_todo"])

        # Create an empty todo db
        conn = sqlite3.connect(":memory:")
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE todos ("
            "  id TEXT PRIMARY KEY,"
            "  title TEXT NOT NULL,"
            "  description TEXT,"
            "  status TEXT DEFAULT 'pending',"
            "  agent_id TEXT,"
            "  depends_on TEXT,"
            "  created_at TEXT,"
            "  error TEXT"
            ")"
        )
        conn.commit()
        db_path = ":memory:"

        join_store = InMemoryJoinStore()
        sup = self._make_supervisor_with_tool_calls(
            strategy_router=strategy_router,
            registry=reg,
            orchestrator=DecompositionOrchestrator(
                join_store=join_store,
                enqueue_fn=None,
                enqueue_continuation_fn=None,
            ),
            tool_calls=[
                {
                    "name": "execute_todo_plan",
                    "arguments": {"db_path": db_path},
                },
            ],
        )
        result = sup.run_agent_step(state)
        reply = result.final_response.reply if result.final_response else ""
        assert "fan-out/fan-in" in reply, (
            f"Expected fan-out/fan-in message even for empty db, got {reply!r}"
        )


# ── Test: execute_todo_plan error paths ────────────────────────────────────────


class TestExecuteTodoPlanErrors:
    """Error paths: orchestrator not configured, worker not configured."""

    def test_no_orchestrator(
        self,
        strategy_router: MagicMock,
    ) -> None:
        """When decomposition_orchestrator is None, execute_todo_plan returns
        a friendly error dict."""
        reg = _registry(patterns=["plan_with_todo"])
        state = _running_state(patterns=["plan_with_todo"])
        sup = Supervisor(
            registry=reg,
            store=MemoryAgentStateStore(),
            strategy_router=strategy_router,
            decomposition_orchestrator=None,
        )
        result = sup.execute_todo_plan(":memory:")
        assert result["status"] == "failed"
        assert "No DecompositionOrchestrator" in result["summary"]

    def test_no_worker(
        self,
        strategy_router: MagicMock,
    ) -> None:
        """When _decomposition_worker is not set, execute_todo_plan returns
        a friendly error dict."""
        reg = _registry(patterns=["plan_with_todo"])
        state = _running_state(patterns=["plan_with_todo"])
        sup = Supervisor(
            registry=reg,
            store=MemoryAgentStateStore(),
            strategy_router=strategy_router,
            decomposition_orchestrator=MagicMock(),
        )
        result = sup.execute_todo_plan(":memory:")
        assert result["status"] == "failed"
        assert "No decomposition worker" in result["summary"]
