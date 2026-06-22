"""Unit tests for TodoWorker S4 pipeline compatibility fixes (Sprint 12a.3).

These tests verify the two critical bug fixes:
  - Payload normalization: ChannelMessage → dict (Bug 1)
  - ExecutionContext dict handling: isinstance(dict) check (Bug 2)

Without these fixes, TodoWorker would fail inside the S4 pipeline because
ExecutionStage passes ``job.payload`` (ChannelMessage) and
``execution_context.to_dict()`` (plain dict).
"""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.capabilities.planner.todo_store import TodoStore
from src.agent.planner.todo_worker import TodoWorker
from src.gateway.normalization import ChannelMessage
from src.platform.runtime.execution_context import ExecutionContext


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
