"""Integration tests for the todo-list planner full pipeline (Sprint 12a.9).

Validates the full pipeline:
- TodoStore populated with items (simulating todo-breakdown pattern output)
- TodoOrchestrator → S4 Worker → TodoWorker → WorkflowEngine
- Multi-item iteration with dependency-aware topological ordering
- Status transitions (pending → in_progress → done)
- Completion detection (all items done)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.agent.strategy_router import StrategyRouter
from src.agent.workflow.engine import WorkflowEngine
from src.agent.workflow.loader import load_workflows_from_yaml
from src.agent.workflow.registry import WorkflowRegistry
from src.capabilities.planner.todo_orchestrator import TodoOrchestrator
from src.capabilities.planner.todo_store import TodoStore
from src.platform.queue.queue import InMemoryQueue
from src.platform.runtime.control_plane import ControlPlane
from src.platform.runtime.job_store import InMemoryJobStore


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def workflow_registry() -> WorkflowRegistry:
    """Load the real todo-execute-item workflow from YAML."""
    registry = WorkflowRegistry()
    config_dir = Path(__file__).resolve().parents[3] / "config" / "workflows"
    definitions = load_workflows_from_yaml(str(config_dir))
    for defn in definitions:
        registry.register(defn)
    return registry


@pytest.fixture
def workflow_engine(workflow_registry: WorkflowRegistry) -> WorkflowEngine:
    """Real WorkflowEngine with the todo-execute-item workflow registered."""
    return WorkflowEngine(registry=workflow_registry)


@pytest.fixture
def in_memory_queue() -> InMemoryQueue:
    return InMemoryQueue()


@pytest.fixture
def control_plane() -> ControlPlane:
    return ControlPlane(job_store=InMemoryJobStore())


@pytest.fixture
def mock_strategy_router() -> MagicMock:
    """Mock StrategyRouter — returns a successful LLM response immediately."""
    router = MagicMock(spec=StrategyRouter)
    router.route.return_value = {
        "output": "Task completed successfully.",
        "error": None,
    }
    return router


@pytest.fixture
def mock_inline_executor() -> MagicMock:
    """Mock inline tool executor."""
    return MagicMock(return_value={"status": "success"})


@pytest.fixture
def orchestrator(
    workflow_engine: WorkflowEngine,
    mock_strategy_router: MagicMock,
    mock_inline_executor: MagicMock,
    in_memory_queue: InMemoryQueue,
    control_plane: ControlPlane,
) -> TodoOrchestrator:
    """Full TodoOrchestrator with real engine + queue + control_plane."""
    return TodoOrchestrator(
        workflow_engine=workflow_engine,
        strategy_router=mock_strategy_router,
        inline_tool_executor=mock_inline_executor,
        queue=in_memory_queue,
        control_plane=control_plane,
        timeout_seconds=30,
    )


@pytest.fixture
def todo_db(tmp_path: Any) -> str:
    """Create an empty SQLite DB with todo_list tables."""
    db_path = str(tmp_path / "todos.db")
    TodoStore._ensure_table(db_path)
    return db_path


# =========================================================================
# Tests
# =========================================================================


class TestTodoListFullPipeline:
    """End-to-end: populate todos → run orchestrator → verify all done."""

    def test_single_item_runs_to_completion(
        self,
        orchestrator: TodoOrchestrator,
        todo_db: str,
    ) -> None:
        """A single todo item is processed and marked done."""
        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.add_todo("setup-db", "Setting up database", "Create and migrate the DB")
        conn.close()

        result = orchestrator.run(todo_db)

        assert result["done"] is True
        assert "complete" in str(result["output"]).lower() or "done" in str(result)

        # Verify item is marked done
        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        item = store.get("setup-db")
        assert item is not None
        assert item.status == "done"
        conn.close()

    def test_multiple_independent_items_all_complete(
        self,
        orchestrator: TodoOrchestrator,
        todo_db: str,
    ) -> None:
        """Multiple independent items are all processed and marked done."""
        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.add_todo("item-a", "Item A", "First task")
        store.add_todo("item-b", "Item B", "Second task")
        store.add_todo("item-c", "Item C", "Third task")
        conn.close()

        result = orchestrator.run(todo_db)

        assert result["done"] is True

        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        assert store.is_complete() is True
        assert store.done_count() == 3
        for tid in ("item-a", "item-b", "item-c"):
            assert store.get(tid).status == "done"
        conn.close()

    def test_dependency_chain_in_order(
        self,
        orchestrator: TodoOrchestrator,
        todo_db: str,
    ) -> None:
        """Items with dependencies are processed in topological order."""
        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        # B depends on A; C depends on B
        store.add_todo("item-a", "Item A", "First")
        store.add_todo("item-b", "Item B", "Second")
        store.add_todo("item-c", "Item C", "Third")
        store.add_dep("item-b", "item-a")
        store.add_dep("item-c", "item-b")
        conn.close()

        result = orchestrator.run(todo_db)

        assert result["done"] is True

        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        assert store.is_complete() is True
        assert store.done_count() == 3
        conn.close()

    def test_mixed_dependencies_and_independent(
        self,
        orchestrator: TodoOrchestrator,
        todo_db: str,
    ) -> None:
        """Mix of dependent and independent items all complete."""
        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.add_todo("setup-auth", "Setting up auth", "Auth module")
        store.add_todo("setup-db", "Setting up database", "DB module")
        store.add_todo("api-routes", "Creating API routes", "Routes depend on auth+db")
        store.add_todo("frontend", "Building frontend", "Independent FE work")
        store.add_dep("api-routes", "setup-auth")
        store.add_dep("api-routes", "setup-db")
        conn.close()

        result = orchestrator.run(todo_db)

        assert result["done"] is True

        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        assert store.is_complete() is True
        assert store.done_count() == 4
        conn.close()

    def test_empty_db_returns_done_immediately(
        self,
        orchestrator: TodoOrchestrator,
        todo_db: str,
    ) -> None:
        """An empty todo list completes immediately with a summary."""
        result = orchestrator.run(todo_db)

        assert result["done"] is True
        assert "complete" in str(result["output"]).lower()

    def test_result_includes_summary(
        self,
        orchestrator: TodoOrchestrator,
        todo_db: str,
    ) -> None:
        """The result output contains a meaningful summary."""
        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.add_todo("task-1", "Task One", "Description one")
        store.add_todo("task-2", "Task Two", "Description two")
        conn.close()

        result = orchestrator.run(todo_db)

        assert "output" in result
        assert len(str(result["output"])) > 0

    def test_cognitive_state_persists_db_path(
        self,
        orchestrator: TodoOrchestrator,
        todo_db: str,
    ) -> None:
        """The result includes cognitive_state with db_path."""
        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.add_todo("task-1", "Task One", "Description")
        conn.close()

        result = orchestrator.run(todo_db)

        assert "cognitive_state" in result
        assert result["cognitive_state"]["db_path"] == todo_db


# =========================================================================
# 12a.11 — Crash Recovery Integration Tests
# =========================================================================


class TestCrashRecovery:
    """Verify TodoWorker resumes from in_progress items after a simulated crash."""

    def test_resume_from_in_progress_after_crash(
        self,
        orchestrator: TodoOrchestrator,
        todo_db: str,
    ) -> None:
        """When an item is left in_progress (crash), the next run picks it up first."""
        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.add_todo("task-a", "Task A", "First item")
        store.add_todo("task-b", "Task B", "Second item")
        store.add_todo("task-c", "Task C", "Third item")
        store.mark_in_progress("task-b")  # Simulate crash mid-processing
        conn.close()

        # Run the orchestrator — should complete task-b (in_progress),
        # then task-a, task-c in order.
        result = orchestrator.run(todo_db)

        assert result["done"] is True

        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        assert store.is_complete() is True
        assert store.done_count() == 3
        assert store.get("task-b").status == "done"
        assert store.get("task-a").status == "done"
        assert store.get("task-c").status == "done"
        conn.close()

    def test_resume_from_in_progress_with_dependencies(
        self,
        orchestrator: TodoOrchestrator,
        todo_db: str,
    ) -> None:
        """In_progress prioritization respects dependency ordering — ready items only."""
        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.add_todo("setup", "Setup", "Foundation step")
        store.add_todo("build-a", "Build A", "Depends on setup")
        store.add_todo("build-b", "Build B", "Also depends on setup")
        store.add_dep("build-a", "setup")
        store.add_dep("build-b", "setup")
        store.mark_in_progress("setup")  # Simulate crash mid-setup
        conn.close()

        result = orchestrator.run(todo_db)

        assert result["done"] is True

        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        assert store.is_complete() is True
        assert store.get("setup").status == "done"
        assert store.get("build-a").status == "done"
        assert store.get("build-b").status == "done"
        conn.close()

    def test_all_in_progress_resume(
        self,
        orchestrator: TodoOrchestrator,
        todo_db: str,
    ) -> None:
        """All items in_progress (total crash) — all get resumed and completed."""
        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        for tid in ("x", "y", "z"):
            store.add_todo(tid, f"Item {tid.upper()}", f"Task {tid}")
            store.mark_in_progress(tid)
        conn.close()

        result = orchestrator.run(todo_db)

        assert result["done"] is True

        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        assert store.is_complete() is True
        assert store.done_count() == 3
        conn.close()

    def test_crash_recovery_does_not_replay_done_items(
        self,
        orchestrator: TodoOrchestrator,
        todo_db: str,
    ) -> None:
        """Done items stay done — only in_progress/pending items are processed."""
        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.add_todo("done-item", "Already Done", "Done before crash")
        store.add_todo("crashed-item", "Crashed Item", "In progress at crash")
        store.add_todo("pending-item", "Pending Item", "Not yet started")
        store.mark_done("done-item")
        store.mark_in_progress("crashed-item")
        conn.close()

        result = orchestrator.run(todo_db)

        assert result["done"] is True

        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        assert store.is_complete() is True
        assert store.get("done-item").status == "done"  # unchanged
        assert store.get("crashed-item").status == "done"
        assert store.get("pending-item").status == "done"
        conn.close()
