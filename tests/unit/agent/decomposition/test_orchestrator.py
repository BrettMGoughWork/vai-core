"""
Tests for DecompositionOrchestrator.
======================================

Covers:
- fan_out: creates child jobs, validates DAG, enqueues via callback
- fan_in: reads JoinHandle, runs merge, returns MergeResult
- cancel: marks pending join handles as FAILED
- Edge cases: empty subtasks, no enqueue_fn, circular deps, missing handle
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.agent.decomposition.orchestrator import (
    DecompositionOrchestrator,
)
from src.agent.types.decomposition import (
    DecompositionPlan,
    SubtaskSpec,
)
from src.platform.runtime.join_handle import (
    JoinHandle,
    JoinHandleState,
)
from src.platform.runtime.job_store.join_store import JoinStore
from src.platform.runtime.job_store.backends.in_memory_join_store import (
    InMemoryJoinStore,
)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _spec(id: str, depends_on: list[str] | None = None) -> SubtaskSpec:
    return SubtaskSpec(
        id=id,
        description=f"Subtask {id}",
        depends_on=depends_on or [],
    )


def _plan(
    plan_id: str = "plan-1",
    subtasks: list[SubtaskSpec] | None = None,
    merge_strategy: str = "concat",
) -> DecompositionPlan:
    return DecompositionPlan(
        plan_id=plan_id,
        parent_task="test task",
        subtasks=subtasks if subtasks is not None else [_spec("a"), _spec("b")],
        merge_strategy=merge_strategy,
    )


# ══════════════════════════════════════════════════════════════════════════════
# fan_out
# ══════════════════════════════════════════════════════════════════════════════


class TestFanOut:
    def test_basic_fan_out_creates_subtasks(self) -> None:
        store = InMemoryJoinStore()
        plan = _plan()
        orchestrator = DecompositionOrchestrator(join_store=store)
        result = orchestrator.fan_out(plan=plan, parent_job_id="parent-1")

        assert len(result.child_job_ids) == 2
        assert result.join_handle_id is not None
        assert result.continuation_job_id is not None

        # JoinHandle should be in the store
        handle = store.get(result.join_handle_id)
        assert handle is not None
        assert handle.parent_job_id == "parent-1"
        assert handle.plan_id == "plan-1"
        assert len(handle.child_job_ids) == 2

    def test_fan_out_with_invalid_dag_raises(self) -> None:
        store = InMemoryJoinStore()
        plan = _plan(
            subtasks=[_spec("a", ["b"]), _spec("b", ["a"])],
        )
        orchestrator = DecompositionOrchestrator(join_store=store)
        with pytest.raises(Exception, match="Cycle"):
            orchestrator.fan_out(plan=plan, parent_job_id="parent-1")

    def test_fan_out_enqueues_via_callback(self) -> None:
        enqueue_fn = MagicMock(return_value="job-id")
        store = InMemoryJoinStore()
        plan = _plan()
        orchestrator = DecompositionOrchestrator(
            join_store=store,
            enqueue_fn=enqueue_fn,
        )
        result = orchestrator.fan_out(plan=plan, parent_job_id="parent-1")

        assert enqueue_fn.call_count == 2
        for call_args in enqueue_fn.call_args_list:
            job = call_args[0][0]
            assert job["parent_job_id"] == "parent-1"
            assert job["plan_id"] == "plan-1"
            assert job["job_type"] == "subtask"

        # Returned job IDs should match what enqueue_fn returned
        assert len(result.child_job_ids) == 2
        assert all(jid == "job-id" for jid in result.child_job_ids)

    def test_fan_out_sets_depends_on(self) -> None:
        records: list[dict] = []

        def enqueue_fn(job: dict) -> str:
            records.append(job)
            return job["job_id"]

        store = InMemoryJoinStore()
        plan = _plan(subtasks=[_spec("a"), _spec("b", ["a"])])
        orchestrator = DecompositionOrchestrator(
            join_store=store,
            enqueue_fn=enqueue_fn,
        )
        orchestrator.fan_out(plan=plan, parent_job_id="parent-1")

        a_job = next(j for j in records if j["subtask_id"] == "a")
        b_job = next(j for j in records if j["subtask_id"] == "b")
        assert a_job["depends_on"] == []
        assert b_job["depends_on"] == ["a"]

    def test_fan_out_empty_subtasks(self) -> None:
        store = InMemoryJoinStore()
        plan = _plan(subtasks=[])
        orchestrator = DecompositionOrchestrator(join_store=store)
        result = orchestrator.fan_out(plan=plan, parent_job_id="parent-1")

        assert result.child_job_ids == []
        assert result.join_handle_id is not None

    def test_fan_out_with_continuation(self) -> None:
        continuation_fn = MagicMock(return_value="cont-job-id")
        store = InMemoryJoinStore()
        plan = _plan()
        orchestrator = DecompositionOrchestrator(
            join_store=store,
            enqueue_continuation_fn=continuation_fn,
        )
        result = orchestrator.fan_out(plan=plan, parent_job_id="parent-1")

        continuation_fn.assert_called_once()
        assert result.continuation_job_id == "cont-job-id"

    def test_fan_out_no_callback_generates_synthetic_ids(self) -> None:
        store = InMemoryJoinStore()
        plan = _plan()
        orchestrator = DecompositionOrchestrator(join_store=store)
        result = orchestrator.fan_out(plan=plan, parent_job_id="parent-1")

        assert len(result.child_job_ids) == 2
        # Synthetic UUIDs are generated, so they should be non-empty strings
        assert all(isinstance(jid, str) and len(jid) > 0 for jid in result.child_job_ids)


# ══════════════════════════════════════════════════════════════════════════════
# fan_in
# ══════════════════════════════════════════════════════════════════════════════


class TestFanIn:
    def test_fan_in_with_completed_handle(self) -> None:
        store = InMemoryJoinStore()
        handle = JoinHandle(
            parent_job_id="parent-1",
            plan_id="plan-1",
            child_job_ids=["a", "b"],
            completed_ids=["a", "b"],
            state=JoinHandleState.COMPLETED,
        )
        store.save(handle)

        orchestrator = DecompositionOrchestrator(join_store=store)
        child_results = {
            "a": {"output": "result a"},
            "b": {"output": "result b"},
        }
        result = orchestrator.fan_in(
            join_handle_id=handle.join_handle_id,
            child_results=child_results,
        )

        assert result.output is not None
        assert "result a" in result.output
        assert "result b" in result.output

    def test_fan_in_raises_if_waiting(self) -> None:
        store = InMemoryJoinStore()
        handle = JoinHandle(
            parent_job_id="parent-1",
            plan_id="plan-1",
            child_job_ids=["a", "b"],
        )
        store.save(handle)

        orchestrator = DecompositionOrchestrator(join_store=store)
        with pytest.raises(ValueError, match="children not yet complete"):
            orchestrator.fan_in(
                join_handle_id=handle.join_handle_id,
                child_results={},
            )

    def test_fan_in_raises_if_not_found(self) -> None:
        store = InMemoryJoinStore()
        orchestrator = DecompositionOrchestrator(join_store=store)
        with pytest.raises(ValueError, match="JoinHandle not found"):
            orchestrator.fan_in(
                join_handle_id="nonexistent",
                child_results={},
            )

    def test_fan_in_with_parent_context(self) -> None:
        store = InMemoryJoinStore()
        handle = JoinHandle(
            parent_job_id="parent-1",
            plan_id="plan-1",
            child_job_ids=["a"],
            completed_ids=["a"],
            state=JoinHandleState.COMPLETED,
        )
        store.save(handle)

        orchestrator = DecompositionOrchestrator(join_store=store)
        result = orchestrator.fan_in(
            join_handle_id=handle.join_handle_id,
            child_results={"a": {"output": "hello"}},
            parent_context={"task": "my test task"},
        )
        assert result.output is not None

    def test_fan_in_marks_handle_completed_after_merge(self) -> None:
        store = InMemoryJoinStore()
        handle = JoinHandle(
            parent_job_id="parent-1",
            plan_id="plan-1",
            child_job_ids=["a"],
            completed_ids=["a"],
            state=JoinHandleState.COMPLETED,
        )
        handle_id = handle.join_handle_id
        store.save(handle)

        orchestrator = DecompositionOrchestrator(join_store=store)
        orchestrator.fan_in(
            join_handle_id=handle_id,
            child_results={"a": {"output": "ok"}},
        )

        # Handle should still be COMPLETED in store after merge
        updated = store.get(handle_id)
        assert updated is not None
        assert updated.state == JoinHandleState.COMPLETED


# ══════════════════════════════════════════════════════════════════════════════
# cancel
# ══════════════════════════════════════════════════════════════════════════════


class TestCancel:
    def test_cancel_marks_waiting_handles_as_failed(self) -> None:
        store = InMemoryJoinStore()
        handle = JoinHandle(
            parent_job_id="parent-1",
            plan_id="plan-1",
            child_job_ids=["a", "b"],
        )
        handle_id = handle.join_handle_id
        store.save(handle)

        orchestrator = DecompositionOrchestrator(join_store=store)
        cancelled = orchestrator.cancel("plan-1")

        updated = store.get(handle_id)
        assert updated is not None
        assert updated.state == JoinHandleState.FAILED
        assert cancelled == ["a", "b"]

    def test_cancel_skips_non_matching_plans(self) -> None:
        store = InMemoryJoinStore()
        handle = JoinHandle(
            parent_job_id="parent-1",
            plan_id="other-plan",
            child_job_ids=["a"],
        )
        store.save(handle)

        orchestrator = DecompositionOrchestrator(join_store=store)
        cancelled = orchestrator.cancel("plan-1")
        assert cancelled == []

        # Handle should still be WAITING
        updated = store.get(handle.join_handle_id)
        assert updated is not None
        assert updated.state == JoinHandleState.WAITING

    def test_cancel_empty_store(self) -> None:
        store = InMemoryJoinStore()
        orchestrator = DecompositionOrchestrator(join_store=store)
        cancelled = orchestrator.cancel("plan-1")
        assert cancelled == []

    def test_cancel_does_not_touch_completed_handles(self) -> None:
        store = InMemoryJoinStore()
        handle = JoinHandle(
            parent_job_id="parent-1",
            plan_id="plan-1",
            child_job_ids=["a"],
            completed_ids=["a"],
            state=JoinHandleState.COMPLETED,
        )
        store.save(handle)

        orchestrator = DecompositionOrchestrator(join_store=store)
        cancelled = orchestrator.cancel("plan-1")

        # Completed handle should stay COMPLETED
        updated = store.get(handle.join_handle_id)
        assert updated is not None
        assert updated.state == JoinHandleState.COMPLETED
        # But child IDs are still returned
        assert cancelled == ["a"]
