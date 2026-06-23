"""Integration tests for the sub-goal planner two-level pipeline (Sprint 12b.16-17).

Validates:
  - Two-level pipeline: goals → inner ReAct loop → tasks created/executed →
    goal marked done → next goal → ...
  - Crash recovery: orchestrator crash mid-goal → resume → complete remaining
  - Progress compaction across inner-loop iterations
  - Goals-before-tasks priority ordering
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
from src.agent.planner.todo_orchestrator import TodoOrchestrator
from src.capabilities.planner.todo_store import TodoStore
from src.platform.queue.queue import InMemoryQueue
from src.platform.runtime.control_plane import ControlPlane
from src.platform.runtime.job_store import InMemoryJobStore


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def workflow_registry() -> WorkflowRegistry:
    """Load real todo-execute-item and subgoal-execute-loop workflows."""
    registry = WorkflowRegistry()
    config_dir = Path(__file__).resolve().parents[3] / "config" / "workflows"
    definitions = load_workflows_from_yaml(str(config_dir))
    for defn in definitions:
        registry.register(defn)
    return registry


@pytest.fixture
def workflow_engine(workflow_registry: WorkflowRegistry) -> WorkflowEngine:
    """Real WorkflowEngine with workflows registered."""
    return WorkflowEngine(registry=workflow_registry)


@pytest.fixture
def in_memory_queue() -> InMemoryQueue:
    return InMemoryQueue()


@pytest.fixture
def control_plane() -> ControlPlane:
    return ControlPlane(job_store=InMemoryJobStore())


@pytest.fixture
def todo_db(tmp_path: Any) -> str:
    """Create an empty SQLite DB with todo_list tables, including sub-goal columns."""
    db_path = str(tmp_path / "todos.db")
    TodoStore._ensure_table(db_path)
    return db_path


def _make_router_with_side_effect(responses: list[dict]):
    """Create a mock StrategyRouter that returns preset responses in order.

    Each call to router.route() consumes one response from the list.
    """
    router = MagicMock(spec=StrategyRouter)
    router.route.side_effect = responses
    return router


def _orchestrator_for_responses(
    responses: list[dict],
    engine: WorkflowEngine,
    queue: InMemoryQueue,
    control_plane: ControlPlane,
) -> TodoOrchestrator:
    """Create an orchestrator with a side-effect-driven mock router."""
    router = _make_router_with_side_effect(responses)
    mock_executor = MagicMock(return_value={"status": "success"})
    return TodoOrchestrator(
        workflow_engine=engine,
        strategy_router=router,
        inline_tool_executor=mock_executor,
        queue=queue,
        control_plane=control_plane,
        timeout_seconds=30,
        max_iterations_per_goal=5,
    )


# =========================================================================
# Tests: Two-level pipeline (12b.16)
# =========================================================================


class TestSubGoalTwoLevelPipeline:
    """End-to-end: goals populate → orchestrator processes via inner loop."""

    def test_single_goal_completes_after_inner_loop(
        self,
        workflow_engine: WorkflowEngine,
        in_memory_queue: InMemoryQueue,
        control_plane: ControlPlane,
        todo_db: str,
    ) -> None:
        """A single goal goes through inner loop iterations and completes."""
        orchestrator = _orchestrator_for_responses(
            [
                # Iteration 1: 4 LLM calls (anchor → create → execute → assess)
                {"output": "Progress: partial. COMPLETE: NO, more tasks needed.",
                 "error": None},
                {"output": "Task t1 created.", "error": None},
                {"output": "Task executed.", "error": None},
                {"output": "Task went well.", "error": None},
                # Iteration 2: 4 LLM calls — anchor says COMPLETE: YES
                {"output": "Excellent! All criteria met. COMPLETE: YES",
                 "error": None},
                {"output": "Final task created.", "error": None},
                {"output": "Final task executed.", "error": None},
                {"output": "Final assessment done.", "error": None},
            ],
            workflow_engine,
            in_memory_queue,
            control_plane,
        )

        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.add_goal("auth-goal", "Auth Module", "Implement auth",
                       completion_criterion="All auth tests pass")
        conn.close()

        result = orchestrator.run(todo_db)

        assert result["done"] is True

        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        goal = store.get("auth-goal")
        assert goal is not None
        assert goal.status == "done"
        conn.close()

    def test_multiple_goals_process_in_order(
        self,
        workflow_engine: WorkflowEngine,
        in_memory_queue: InMemoryQueue,
        control_plane: ControlPlane,
        todo_db: str,
    ) -> None:
        """Goals are processed sequentially, each completing before the next."""
        orchestrator = _orchestrator_for_responses(
            [
                # Goal 1: 4 LLM calls (anchor → create → execute → assess)
                {"output": "Done. COMPLETE: YES", "error": None},
                {"output": "Task g1-t1 created.", "error": None},
                {"output": "Task g1-t1 done.", "error": None},
                {"output": "Goal 1 assessed.", "error": None},
                # Goal 2: 4 LLM calls
                {"output": "Done. COMPLETE: YES", "error": None},
                {"output": "Task g2-t1 created.", "error": None},
                {"output": "Task g2-t1 done.", "error": None},
                {"output": "Goal 2 assessed.", "error": None},
            ],
            workflow_engine,
            in_memory_queue,
            control_plane,
        )

        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.add_goal("goal-1", "Goal 1", "First sub-goal",
                       completion_criterion="C1")
        store.add_goal("goal-2", "Goal 2", "Second sub-goal",
                       completion_criterion="C2")
        conn.close()

        result = orchestrator.run(todo_db)

        assert result["done"] is True

        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        assert store.is_complete() is True
        assert store.get("goal-1").status == "done"
        assert store.get("goal-2").status == "done"
        conn.close()

    def test_mixed_goals_and_independent_tasks(
        self,
        workflow_engine: WorkflowEngine,
        in_memory_queue: InMemoryQueue,
        control_plane: ControlPlane,
        todo_db: str,
    ) -> None:
        """Independent tasks are processed after all goals complete."""
        orchestrator = _orchestrator_for_responses(
            [
                # Goal iteration: 4 LLM calls (anchor → create → execute → assess)
                {"output": "Done. COMPLETE: YES", "error": None},
                {"output": "Task created.", "error": None},
                {"output": "Task done.", "error": None},
                {"output": "Goal assessed.", "error": None},
                # Independent task: 1 LLM call (todo-execute-item)
                {"output": "Task done.", "error": None},
            ],
            workflow_engine,
            in_memory_queue,
            control_plane,
        )

        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.add_goal("g1", "Goal", "Sub-goal")
        store.add_todo("indep-task", "Independent", "Standalone task",
                       type="task")
        conn.close()

        result = orchestrator.run(todo_db)

        assert result["done"] is True

        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        assert store.is_complete() is True
        # Goal completed first
        assert store.get("g1").status == "done"
        # Then independent task
        assert store.get("indep-task").status == "done"
        conn.close()


class TestSubGoalProgressCompaction:
    """Progress is compacted into the goal description over iterations."""

    def test_progress_accumulates_across_iterations(
        self,
        workflow_engine: WorkflowEngine,
        in_memory_queue: InMemoryQueue,
        control_plane: ControlPlane,
        todo_db: str,
    ) -> None:
        """Multiple inner-loop iterations append progress to the goal."""
        orchestrator = _orchestrator_for_responses(
            [
                # Iteration 1: 4 LLM calls
                {"output": "Working... COMPLETE: NO", "error": None},
                {"output": "Task t1 created.", "error": None},
                {"output": "Task t1 done.", "error": None},
                {"output": "Good progress.", "error": None},
                # Iteration 2: 4 LLM calls
                {"output": "Working... COMPLETE: NO", "error": None},
                {"output": "Task t2 created.", "error": None},
                {"output": "Task t2 done.", "error": None},
                {"output": "More progress.", "error": None},
                # Iteration 3: 4 LLM calls
                {"output": "All good. COMPLETE: YES", "error": None},
                {"output": "Final task created.", "error": None},
                {"output": "Final task done.", "error": None},
                {"output": "Final assessment.", "error": None},
            ],
            workflow_engine,
            in_memory_queue,
            control_plane,
        )

        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.add_goal("g1", "Goal", "Initial description")
        conn.close()

        result = orchestrator.run(todo_db)

        assert result["done"] is True

        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        goal = store.get("g1")
        assert goal is not None
        # Progress should appear for each completed iteration
        progress_count = goal.description.count("[progress]")
        assert progress_count >= 2  # At least 2 iterations before COMPLETE: YES
        conn.close()


# =========================================================================
# Tests: Crash recovery with inner loop (12b.17)
# =========================================================================


class TestSubGoalCrashRecovery:
    """Crash recovery: crash mid-goal, resume, and complete."""

    def test_resume_after_crash_mid_goal(
        self,
        workflow_engine: WorkflowEngine,
        in_memory_queue: InMemoryQueue,
        control_plane: ControlPlane,
        todo_db: str,
    ) -> None:
        """Crash during a goal's inner loop → resume → complete the goal.

        Simulates a process/power failure that leaves the goal and its tasks
        in an in_progress state.  The second run picks up the in_progress
        goal and finishes it.
        """
        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        # Simulate a goal that was mid-processing when the crash occurred
        store.add_goal("g1", "Goal", "[progress] Completed step A\nOriginal desc")
        store.mark_in_progress("g1")
        # A task was already created and done in a prior iteration
        store.add_todo("g1-t1", "Task 1", "Already done", type="task",
                       parent_goal_id="g1")
        store.mark_done("g1-t1")
        # Another task was in_progress when the crash happened
        store.add_todo("g1-t2", "Task 2", "Was in progress", type="task",
                       parent_goal_id="g1")
        store.mark_in_progress("g1-t2")
        conn.close()

        # Resume run: finish the remaining work
        orchestrator = _orchestrator_for_responses(
            [
                # Goal 1 iteration: 4 LLM calls
                {"output": "Resumed. Everything done. COMPLETE: YES",
                 "error": None},
                {"output": "Task t3 created.", "error": None},
                {"output": "Task t3 done.", "error": None},
                {"output": "Final assessment.", "error": None},
            ],
            workflow_engine,
            in_memory_queue,
            control_plane,
        )

        result = orchestrator.run(todo_db)

        assert result["done"] is True

        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        goal = store.get("g1")
        assert goal is not None
        assert goal.status == "done"
        assert "[progress]" in goal.description
        conn.close()

    def test_resume_picks_up_in_progress_goal(
        self,
        workflow_engine: WorkflowEngine,
        in_memory_queue: InMemoryQueue,
        control_plane: ControlPlane,
        todo_db: str,
    ) -> None:
        """If a goal was in_progress from a prior crashed run, the orchestrator
        resumes it first (rather than starting a new goal)."""
        router = _make_router_with_side_effect([
            # Goal 1 (resume in_progress): 4 LLM calls
            {"output": "All good. COMPLETE: YES", "error": None},
            {"output": "Task t1 created.", "error": None},
            {"output": "Task t1 done.", "error": None},
            {"output": "Goal 1 assessed.", "error": None},
            # Goal 2: 4 LLM calls
            {"output": "All good. COMPLETE: YES", "error": None},
            {"output": "Task t2 created.", "error": None},
            {"output": "Task t2 done.", "error": None},
            {"output": "Goal 2 assessed.", "error": None},
        ])
        orchestrator = TodoOrchestrator(
            workflow_engine=workflow_engine,
            strategy_router=router,
            inline_tool_executor=MagicMock(return_value={"status": "success"}),
            queue=in_memory_queue,
            control_plane=control_plane,
            timeout_seconds=30,
            max_iterations_per_goal=5,
        )

        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        # Simulate a half-done goal with progress already compacted
        store.add_goal("g1", "Goal 1", "[progress] Step 1\nOriginal desc")
        store.mark_in_progress("g1")
        # Add a task that was already created and done
        store.add_todo("g1-t1", "Created task", "Some task",
                       type="task", parent_goal_id="g1")
        store.mark_done("g1-t1")
        # Add a second pending goal
        store.add_goal("g2", "Goal 2", "Second goal")
        conn.close()

        result = orchestrator.run(todo_db)

        assert result["done"] is True

        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        assert store.get("g1").status == "done"
        assert store.get("g2").status == "done"
        conn.close()


class TestSubGoalBounding:
    """Inner loop bounding prevents infinite loops."""

    def test_max_iterations_exhausted_marks_goal_failed(
        self,
        workflow_engine: WorkflowEngine,
        in_memory_queue: InMemoryQueue,
        control_plane: ControlPlane,
        todo_db: str,
    ) -> None:
        """When max_iterations_per_goal is reached without COMPLETE, the
        goal is marked failed and the system moves on."""
        # Always return COMPLETE: NO — never finishes
        # With max_iterations_per_goal=3 and 3 calls per iteration,
        # we need at most 12 responses (3 iterations × 4 steps)
        # But the orchestrator will stop after 3 iterations
        endless_responses = [
            {"output": "Still going... COMPLETE: NO", "error": None}
            for _ in range(20)
        ]
        orchestrator = _orchestrator_for_responses(
            endless_responses,
            workflow_engine,
            in_memory_queue,
            control_plane,
        )
        # Override with a tighter limit
        orchestrator.max_iterations_per_goal = 3

        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.add_goal("endless", "Endless", "Never finishes")
        conn.close()

        result = orchestrator.run(todo_db)

        # System still completes (orchestrator reports done when nothing left)
        conn = sqlite3.connect(todo_db)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        goal = store.get("endless")
        assert goal is not None
        # Goal should be failed (or blocked) — not in_progress, not done
        assert goal.status in ("failed", "blocked")
        conn.close()
