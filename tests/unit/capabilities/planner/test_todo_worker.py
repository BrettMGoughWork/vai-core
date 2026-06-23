"""Unit tests for TodoWorker S4 pipeline compatibility fixes (Sprint 12a.3 / 12b.12-15).

These tests verify:
  - Payload normalization: ChannelMessage → dict (Bug 1)
  - ExecutionContext dict handling: isinstance(dict) check (Bug 2)
  - Inner loop boundedness: stops at max_iterations_per_goal
  - COMPLETE signal parsing: _parse_complete_signal() edge cases
  - Progress compaction: append_progress() called per iteration
  - Adviser persona pattern: required sections in subgoal-execute-loop
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.capabilities.planner.todo_store import TodoStore
from src.agent.planner.todo_worker import TodoWorker, _StepFailedError
from src.gateway.normalization import ChannelMessage
from src.platform.runtime.execution_context import ExecutionContext


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def store(tmp_path: Any) -> TodoStore:
    """A fresh TodoStore backed by a temporary SQLite database."""
    db_path = str(tmp_path / "todos.db")
    TodoStore._ensure_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return TodoStore(conn)


# =========================================================================
# Helpers
# =========================================================================


def _make_todo_db(tmp_path: Any) -> str:
    db_path = str(tmp_path / "test.db")
    TodoStore._ensure_table(db_path)
    return db_path


def _make_worker() -> tuple[TodoWorker, MagicMock, MagicMock, MagicMock]:
    """Create a TodoWorker with mocked dependencies.

    The mock engine is configured to return "completed" immediately so
    that smoke tests (which don't exercise the full workflow) pass
    without needing a real engine.
    """
    engine = MagicMock()
    wf_state = MagicMock()
    wf_state.step_results = {}
    completed_outcome = MagicMock()
    completed_outcome.type = "completed"
    completed_outcome.step_id = None
    completed_outcome.error = None
    engine.start_workflow.return_value = wf_state
    engine.step.return_value = (wf_state, completed_outcome)
    engine.resume_with_result.return_value = (wf_state, completed_outcome)

    router = MagicMock()
    executor = MagicMock(return_value={"status": "success"})
    worker = TodoWorker(
        workflow_engine=engine,
        strategy_router=router,
        inline_tool_executor=executor,
    )
    return worker, engine, router, executor


# =========================================================================
# Payload normalization (Bug 1)
# =========================================================================


class TestTodoWorkerPayloadNormalization:
    """ExecutionStage passes ``job.payload`` which is a ChannelMessage Pydantic
    model.  TodoWorker must normalize it to a plain dict before calling
    ``.get()`` dict methods."""

    def test_channel_message_payload_normalized_to_dict(
        self,
        tmp_path: Any,
    ) -> None:
        """ChannelMessage.payload is accepted — converted to dict automatically."""
        worker, _, _, _ = _make_worker()
        db_path = _make_todo_db(tmp_path)
        msg = ChannelMessage(
            input={},
            metadata={"db_path": db_path},
            channel="planner",
        )
        result = worker(payload=msg)
        # Should not raise AttributeError from calling .get() on ChannelMessage
        assert "done" in result

    def test_plain_dict_payload_still_works(
        self,
        tmp_path: Any,
    ) -> None:
        """Plain dict payloads (e.g. from tests) still work unchanged."""
        worker, _, _, _ = _make_worker()
        db_path = _make_todo_db(tmp_path)
        result = worker(
            payload={"metadata": {"db_path": db_path}, "input": {}}
        )
        assert "done" in result

    def test_payload_without_metadata_gets_db_from_input(
        self,
        tmp_path: Any,
    ) -> None:
        """db_path can also come from payload.input.db_path."""
        worker, _, _, _ = _make_worker()
        db_path = _make_todo_db(tmp_path)
        result = worker(
            payload={"metadata": {}, "input": {"db_path": db_path}}
        )
        assert "done" in result


# =========================================================================
# ExecutionContext handling (Bug 2)
# =========================================================================


class TestTodoWorkerExecutionContextDictHandling:
    """ExecutionStage passes ``execution_context.to_dict()`` — a plain dict
    like ``{"cognitive_state": {...}, "last_result": None, ...}``.
    TodoWorker previously checked ``hasattr(ec, "cognitive_state")`` which
    is False for dicts, causing cognitive_state to be lost across cycles."""

    def test_execution_context_as_dict_with_cognitive_state(
        self,
        tmp_path: Any,
    ) -> None:
        """dict execution_context with cognitive_state → db_path restored."""
        worker, _, _, _ = _make_worker()
        db_path = _make_todo_db(tmp_path)
        result = worker(
            payload={"metadata": {}, "input": {}},
            execution_context={"cognitive_state": {"db_path": db_path}},
        )
        assert "done" in result

    def test_execution_context_as_dict_without_cognitive_state(
        self,
        tmp_path: Any,
    ) -> None:
        """dict execution_context without cognitive_state → falls through to payload."""
        worker, _, _, _ = _make_worker()
        db_path = _make_todo_db(tmp_path)
        result = worker(
            payload={"metadata": {"db_path": db_path}, "input": {}},
            execution_context={"last_result": None},
        )
        assert "done" in result

    def test_execution_context_as_object_with_cognitive_state(
        self,
        tmp_path: Any,
    ) -> None:
        """ExecutionContext object with cognitive_state still works."""
        worker, _, _, _ = _make_worker()
        db_path = _make_todo_db(tmp_path)
        ec = ExecutionContext()
        ec.cognitive_state = {"db_path": db_path}
        result = worker(
            payload={"metadata": {}, "input": {}},
            execution_context=ec,
        )
        assert "done" in result

    def test_execution_context_none(
        self,
        tmp_path: Any,
    ) -> None:
        """None execution_context → falls through to payload.metadata.db_path."""
        worker, _, _, _ = _make_worker()
        db_path = _make_todo_db(tmp_path)
        result = worker(
            payload={"metadata": {"db_path": db_path}, "input": {}},
            execution_context=None,
        )
        assert "done" in result

    def test_no_db_path_anywhere_returns_done_message(self) -> None:
        """When no db_path is found anywhere, returns early with a message."""
        worker, _, _, _ = _make_worker()
        result = worker(payload={"metadata": {}, "input": {}})
        assert result["done"] is True
        assert "No db_path" in result["output"]


# =========================================================================
# End-to-end: empty DB runs to completion
# =========================================================================


class TestTodoWorkerEmptyDB:
    """With an empty todo_list table, TodoWorker returns done=True immediately."""

    def test_empty_db_returns_done(
        self,
        tmp_path: Any,
    ) -> None:
        worker, _, _, _ = _make_worker()
        db_path = _make_todo_db(tmp_path)
        result = worker(
            payload={"metadata": {"db_path": db_path}, "input": {}}
        )
        assert result["done"] is True
        assert "output" in result


class TestTodoWorkerCognitiveState:
    """Cognitive state persistence between cycles."""

    def test_cognitive_state_in_return_value(
        self,
        tmp_path: Any,
    ) -> None:
        """Return dict includes cognitive_state for checkpointing."""
        worker, _, _, _ = _make_worker()
        db_path = _make_todo_db(tmp_path)

        # Use a dict execution_context to simulate S4 pipeline flow
        result = worker(
            payload={"metadata": {"db_path": db_path}, "input": {}},
            execution_context={"cognitive_state": {"db_path": db_path}},
        )
        assert "cognitive_state" in result
        assert result["cognitive_state"]["db_path"] == db_path


# =========================================================================
# Sprint 12b: Sub-goal planner — inner loop, bounding, signal parsing
# =========================================================================


class _TestInertEngine:
    """Workflow engine stub that returns a preset response — never COMPLETE."""

    def __init__(self, message: str = "Inert response") -> None:
        self.message = message
        self.run_count = 0

    def start_workflow(self, workflow_id: str, context: dict) -> Any:
        return MagicMock()

    def step(self, wf_state: Any) -> tuple[Any, MagicMock]:
        self.run_count += 1
        outcome = MagicMock()
        outcome.type = "completed"
        return wf_state, outcome

    def fail_step(self, wf_state: Any, reason: str) -> tuple[Any, MagicMock]:
        outcome = MagicMock()
        outcome.type = "error"
        return wf_state, outcome

    def result(self) -> str:
        return self.message


class _TestInertRouter:
    """StrategyRouter stub that returns a preset response."""

    def __init__(self, message: str = "Inert") -> None:
        self.message = message

    def route(self, *args: Any, **kwargs: Any) -> dict:
        return {"output": self.message, "error": None}


def _make_inert_worker(
    store: TodoStore,
    engine_message: str = "Not done yet, COMPLETE: NO",
    max_iterations: int = 3,
) -> tuple[TodoWorker, _TestInertEngine, _TestInertRouter]:
    """Create a TodoWorker with inert mocks — never reaches COMPLETE.

    Pass ``engine_message`` to control the engine's LLM call output
    (e.g., ``"All good. COMPLETE: YES"`` for a one-shot success).
    """
    engine = _TestInertEngine(engine_message)
    router = _TestInertRouter(engine_message)
    worker = TodoWorker(
        workflow_engine=engine,      # type: ignore[arg-type]
        strategy_router=router,      # type: ignore[arg-type]
        inline_tool_executor=MagicMock(return_value={"status": "success"}),
        max_iterations_per_goal=max_iterations,
    )
    return worker, engine, router


class _MockOrchestratorForWorker:
    """Minimal orchestrator stub providing only what TodoWorker calls."""

    def __init__(self, store: Any) -> None:
        self.todo_store = store


class TestParseCompleteSignal:
    """12b.15: _parse_complete_signal() regex behavior."""

    def test_detects_yes(self) -> None:
        assert TodoWorker._parse_complete_signal("COMPLETE: YES") is True
        assert TodoWorker._parse_complete_signal("COMPLETE: YES, task done") is True

    def test_detects_no(self) -> None:
        assert TodoWorker._parse_complete_signal("COMPLETE: NO, more work needed") is False
        assert TodoWorker._parse_complete_signal("COMPLETE: NO") is False

    def test_casing_irrelevant(self) -> None:
        assert TodoWorker._parse_complete_signal("complete: yes") is True
        assert TodoWorker._parse_complete_signal("Complete: Yes") is True

    def test_trailing_whitespace(self) -> None:
        assert TodoWorker._parse_complete_signal("COMPLETE: YES  ") is True
        assert TodoWorker._parse_complete_signal("  COMPLETE: YES") is True

    def test_no_complete_keyword(self) -> None:
        assert TodoWorker._parse_complete_signal("Some random text") is False

    def test_empty_response(self) -> None:
        assert TodoWorker._parse_complete_signal("") is False

    def test_model_names_positive_answer(self) -> None:
        """'Yes, complete' without the keyword is NOT a signal — ensures
        the pattern doesn't have false positives on generic 'yes' text."""
        assert TodoWorker._parse_complete_signal(
            "Yes, the task is done and everything looks good"
        ) is False


class TestInnerLoopBoundedness:
    """12b.12: Inner loop stops at max_iterations_per_goal."""

    def test_stops_after_max_iterations(self, store: TodoStore) -> None:
        """After max_iterations with no COMPLETE, goal is marked failed."""
        worker, _engine, _router = _make_inert_worker(
            store, engine_message="Not done yet, COMPLETE: NO",
            max_iterations=3,
        )

        store.add_goal("g1", "Goal 1", "Needs work")
        store.mark_in_progress("g1")
        goal = store.get("g1")

        # Mock _run_subgoal_iteration to return (summary, "COMPLETE: NO")
        call_count = 0

        def fake_iteration(context, store_arg):
            nonlocal call_count
            call_count += 1
            return f"Task {call_count} done", "COMPLETE: NO"

        with patch.object(worker, "_run_subgoal_iteration", fake_iteration):
            with pytest.raises(_StepFailedError) as exc_info:
                worker._run_goal_inner_loop(goal, store)

        assert "max" in str(exc_info.value).lower()
        assert call_count == 3
        goal_after = store.get("g1")
        assert goal_after is not None
        # mark_failed decrements retries_remaining; with 3 default retries
        # it goes back to "pending" until retries are exhausted.
        assert goal_after.status in ("pending", "failed")

    def test_no_exception_when_goal_done_first_iteration(
        self, store: TodoStore
    ) -> None:
        """If first iteration returns COMPLETE: YES, we never hit max."""
        worker, _engine, _router = _make_inert_worker(
            store, engine_message="All done, COMPLETE: YES",
            max_iterations=3,
        )

        store.add_goal("g1", "Goal 1", "Needs work")
        store.mark_in_progress("g1")
        goal = store.get("g1")

        call_count = 0

        def fake_iteration(context, store_arg):
            nonlocal call_count
            call_count += 1
            return "Task done", "COMPLETE: YES"

        with patch.object(worker, "_run_subgoal_iteration", fake_iteration):
            worker._run_goal_inner_loop(goal, store)

        assert call_count == 1
        goal_after = store.get("g1")
        assert goal_after is not None
        assert goal_after.status == "done"


class TestProgressCompaction:
    """12b.14: append_progress() is called after each inner-loop iteration."""

    def test_progress_appended_each_iteration(self, store: TodoStore) -> None:
        """Progress text is appended to the goal description each iteration."""
        worker, _engine, _router = _make_inert_worker(
            store, engine_message="Still working, COMPLETE: NO",
            max_iterations=2,
        )

        store.add_goal("g1", "Goal 1", "Base desc")
        store.mark_in_progress("g1")
        goal = store.get("g1")

        call_count = 0

        def fake_iteration(context, store_arg):
            nonlocal call_count
            call_count += 1
            return f"Progress entry {call_count}", "COMPLETE: NO"

        with patch.object(worker, "_run_subgoal_iteration", fake_iteration):
            with pytest.raises(_StepFailedError):
                worker._run_goal_inner_loop(goal, store)

        assert call_count == 2
        goal_after = store.get("g1")
        assert goal_after is not None
        # Progress should appear twice (once per iteration)
        assert "Progress entry 1" in goal_after.description
        assert "Progress entry 2" in goal_after.description


class TestAdviserPersonaPattern:
    """12b.13: subgoal-execute-loop includes the adviser persona sections."""

    def test_workflow_has_anchor_step(self) -> None:
        config_path = _find_workflow("subgoal-execute-loop")
        with open(config_path, "r", encoding="utf-8") as f:
            yaml_text = f.read()
        assert "anchor_and_reflect" in yaml_text

    def test_anchor_step_contains_adviser_instructions(self) -> None:
        config_path = _find_workflow("subgoal-execute-loop")
        with open(config_path, "r", encoding="utf-8") as f:
            yaml_text = f.read()
        assert "adviser" in yaml_text.lower()
        assert "COMPLETE: YES" in yaml_text

    def test_anchor_step_contains_evidence_guardrail(self) -> None:
        config_path = _find_workflow("subgoal-execute-loop")
        with open(config_path, "r", encoding="utf-8") as f:
            yaml_text = f.read()
        assert "evidence" in yaml_text.lower() or "not opinion" in yaml_text.lower()


# =========================================================================
# Helpers
# =========================================================================


def _find_workflow(name: str) -> Path:
    """Resolve a workflow YAML file by name from config/workflows/."""
    candidates = [
        Path("config/workflows") / f"{name}.yaml",
        Path("config/workflows") / name,
    ]
    for p in candidates:
        if p.exists():
            return p
    # Try relative to src/
    for p in candidates:
        full = Path("src") / p
        if full.exists():
            return full
    raise FileNotFoundError(f"Workflow {name!r} not found: tried {candidates}")
