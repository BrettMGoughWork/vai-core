"""
Phase R.9.4 — WorkflowOps & WorkflowInstanceStore Unit Tests
=============================================================

Tests for the operational management API (WorkflowOps) and its backing
store (WorkflowInstanceStore).
"""

from __future__ import annotations

import pytest

from src.agent.workflow.engine import (
    WorkflowEngine,
    WorkflowExecutionState,
    WorkflowStatus,
)
from src.agent.workflow.instance_store import WorkflowInstanceStore
from src.agent.workflow.ops import WorkflowOps
from src.agent.workflow.registry import WorkflowRegistry
from src.agent.workflow.workflow_definition import (
    END_TARGET,
    WorkflowDefinition,
    WorkflowStep,
)


# ===================================================================
# Helpers
# ===================================================================


def _make_state(
    execution_id: str = "exec-1",
    workflow_id: str = "wf-1",
    status: WorkflowStatus = WorkflowStatus.RUNNING,
    current_step_id: str = "step_1",
    context: dict | None = None,
    error: str | None = None,
) -> WorkflowExecutionState:
    return WorkflowExecutionState(
        execution_id=execution_id,
        workflow_id=workflow_id,
        status=status,
        current_step_id=current_step_id,
        context=context or {},
        step_results={},
        error=error,
    )


def _make_step(
    step_id: str,
    step_type: str = "llm_call",
    *,
    transitions: dict | None = None,
) -> WorkflowStep:
    return WorkflowStep(
        step_id=step_id,
        step_type=step_type,
        label=f"Step {step_id}",
        config={},
        transitions=transitions or {"on_success": END_TARGET},
    )


def _make_workflow(
    workflow_id: str = "wf-1",
    start_step: str = "step_1",
) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id=workflow_id,
        name=workflow_id,
        description="Test",
        steps={"step_1": _make_step("step_1")},
        start_step=start_step,
    )


def _make_engine() -> WorkflowEngine:
    reg = WorkflowRegistry()
    reg.register(_make_workflow())
    return WorkflowEngine(registry=reg)


def _make_ops() -> tuple[WorkflowInstanceStore, WorkflowEngine, WorkflowOps]:
    store = WorkflowInstanceStore()
    engine = _make_engine()
    ops = WorkflowOps(store=store, engine=engine)
    return store, engine, ops


# ===================================================================
# 1. WorkflowInstanceStore
# ===================================================================


class TestWorkflowInstanceStore:
    """In-memory store for workflow execution states."""

    def test_save_and_get(self):
        store = WorkflowInstanceStore()
        state = _make_state()
        store.save(state)

        retrieved = store.get("exec-1")
        assert retrieved is not None
        assert retrieved.execution_id == "exec-1"
        assert retrieved.workflow_id == "wf-1"
        assert retrieved.status == WorkflowStatus.RUNNING

    def test_get_missing_returns_none(self):
        store = WorkflowInstanceStore()
        assert store.get("nonexistent") is None

    def test_save_updates_existing(self):
        store = WorkflowInstanceStore()
        state = _make_state(status=WorkflowStatus.RUNNING)
        store.save(state)

        updated = _make_state(status=WorkflowStatus.COMPLETED)
        store.save(updated)

        retrieved = store.get("exec-1")
        assert retrieved is not None
        assert retrieved.status == WorkflowStatus.COMPLETED

    def test_list_instances_returns_all(self):
        store = WorkflowInstanceStore()
        store.save(_make_state("exec-1", status=WorkflowStatus.COMPLETED))
        store.save(_make_state("exec-2", status=WorkflowStatus.RUNNING))

        results = store.list_instances()
        assert len(results) == 2
        ids = {s.execution_id for s in results}
        assert ids == {"exec-1", "exec-2"}

    def test_list_instances_filtered_by_status(self):
        store = WorkflowInstanceStore()
        store.save(_make_state("exec-1", status=WorkflowStatus.RUNNING))
        store.save(_make_state("exec-2", status=WorkflowStatus.FAILED))

        running = store.list_instances(status=WorkflowStatus.RUNNING)
        assert len(running) == 1
        assert running[0].execution_id == "exec-1"

        failed = store.list_instances(status=WorkflowStatus.FAILED)
        assert len(failed) == 1
        assert failed[0].execution_id == "exec-2"

    def test_list_instances_filtered_by_workflow_id(self):
        store = WorkflowInstanceStore()
        store.save(_make_state("exec-1", workflow_id="wf-a"))
        store.save(_make_state("exec-2", workflow_id="wf-b"))

        results = store.list_instances(workflow_id="wf-a")
        assert len(results) == 1
        assert results[0].execution_id == "exec-1"

    def test_delete_existing(self):
        store = WorkflowInstanceStore()
        store.save(_make_state())
        assert store.delete("exec-1") is True
        assert store.get("exec-1") is None

    def test_delete_missing(self):
        store = WorkflowInstanceStore()
        assert store.delete("nonexistent") is False

    def test_get_record(self):
        store = WorkflowInstanceStore()
        store.save(_make_state())
        record = store._get_record("exec-1")  # noqa: SLF001
        assert record is not None
        assert record.state.execution_id == "exec-1"
        assert record.created_at != ""
        assert record.updated_at != ""


# ===================================================================
# 2. WorkflowOps — Query API
# ===================================================================


class TestWorkflowOpsList:
    """WorkflowOps.list_instances()"""

    def test_list_all(self):
        _, _, ops = _make_ops()
        ops._store.save(_make_state("exec-1"))  # noqa: SLF001
        ops._store.save(_make_state("exec-2"))  # noqa: SLF001

        results = ops.list_instances()
        assert len(results) == 2

    def test_list_filtered_by_state(self):
        _, _, ops = _make_ops()
        ops._store.save(_make_state("exec-1", status=WorkflowStatus.RUNNING))  # noqa: SLF001
        ops._store.save(_make_state("exec-2", status=WorkflowStatus.COMPLETED))  # noqa: SLF001

        results = ops.list_instances(state="completed")
        assert len(results) == 1
        assert results[0].execution_id == "exec-2"

    def test_list_invalid_state_returns_empty(self):
        _, _, ops = _make_ops()
        ops._store.save(_make_state("exec-1"))  # noqa: SLF001

        results = ops.list_instances(state="bogus_state")
        assert results == []

    def test_get_instance(self):
        _, _, ops = _make_ops()
        ops._store.save(_make_state("exec-1"))  # noqa: SLF001

        state = ops.get_instance("exec-1")
        assert state is not None
        assert state.execution_id == "exec-1"

    def test_get_instance_missing(self):
        _, _, ops = _make_ops()
        assert ops.get_instance("nonexistent") is None


# ===================================================================
# 3. WorkflowOps — Lifecycle operations
# ===================================================================


class TestWorkflowOpsCancel:
    """WorkflowOps.cancel_instance()"""

    def test_cancel_active_instance(self):
        store, engine, ops = _make_ops()
        state = _make_state(status=WorkflowStatus.RUNNING)
        store.save(state)

        result = ops.cancel_instance("exec-1")
        assert result is True

        retrieved = store.get("exec-1")
        assert retrieved is not None
        assert retrieved.status == WorkflowStatus.CANCELLED

    def test_cancel_waiting_instance(self):
        store, engine, ops = _make_ops()
        state = _make_state(status=WorkflowStatus.WAITING_FOR_INPUT)
        store.save(state)

        result = ops.cancel_instance("exec-1")
        assert result is True

        retrieved = store.get("exec-1")
        assert retrieved is not None
        assert retrieved.status == WorkflowStatus.CANCELLED

    def test_cancel_already_completed_is_noop(self):
        store, engine, ops = _make_ops()
        state = _make_state(status=WorkflowStatus.COMPLETED)
        store.save(state)

        result = ops.cancel_instance("exec-1")
        assert result is False
        assert store.get("exec-1").status == WorkflowStatus.COMPLETED  # noqa: SLF001

    def test_cancel_already_failed_is_noop(self):
        store, engine, ops = _make_ops()
        state = _make_state(status=WorkflowStatus.FAILED)
        store.save(state)

        result = ops.cancel_instance("exec-1")
        assert result is False

    def test_cancel_already_cancelled_is_noop(self):
        store, engine, ops = _make_ops()
        state = _make_state(status=WorkflowStatus.CANCELLED)
        store.save(state)

        result = ops.cancel_instance("exec-1")
        assert result is False

    def test_cancel_missing_returns_false(self):
        _, _, ops = _make_ops()
        assert ops.cancel_instance("nonexistent") is False


class TestWorkflowOpsRetry:
    """WorkflowOps.retry_instance()"""

    def test_retry_failed_instance(self):
        store, engine, ops = _make_ops()
        state = _make_state(
            status=WorkflowStatus.FAILED,
            current_step_id="step_1",
            context={"key": "value"},
        )
        store.save(state)

        result = ops.retry_instance("exec-1")
        assert result is True

        retrieved = store.get("exec-1")
        assert retrieved is not None
        assert retrieved.status == WorkflowStatus.RUNNING
        assert retrieved.error is None
        assert retrieved.current_step_id == "step_1"
        assert retrieved.context == {"key": "value"}

    def test_retry_running_is_noop(self):
        store, engine, ops = _make_ops()
        state = _make_state(status=WorkflowStatus.RUNNING)
        store.save(state)

        result = ops.retry_instance("exec-1")
        assert result is False
        assert store.get("exec-1").status == WorkflowStatus.RUNNING  # noqa: SLF001

    def test_retry_completed_is_noop(self):
        store, engine, ops = _make_ops()
        state = _make_state(status=WorkflowStatus.COMPLETED)
        store.save(state)

        result = ops.retry_instance("exec-1")
        assert result is False

    def test_retry_cancelled_is_noop(self):
        store, engine, ops = _make_ops()
        state = _make_state(status=WorkflowStatus.CANCELLED)
        store.save(state)

        result = ops.retry_instance("exec-1")
        assert result is False

    def test_retry_missing_returns_false(self):
        _, _, ops = _make_ops()
        assert ops.retry_instance("nonexistent") is False


# ===================================================================
# 4. WorkflowOps — Dead-letter queue
# ===================================================================


class TestWorkflowOpsDeadLetter:
    """WorkflowOps.dead_letter_queue()"""

    def test_returns_only_failed(self):
        store, _, ops = _make_ops()
        store.save(_make_state("exec-1", status=WorkflowStatus.FAILED))
        store.save(_make_state("exec-2", status=WorkflowStatus.RUNNING))
        store.save(_make_state("exec-3", status=WorkflowStatus.COMPLETED))

        dlq = ops.dead_letter_queue()
        assert len(dlq) == 1
        assert dlq[0].execution_id == "exec-1"

    def test_empty_when_no_failures(self):
        store, _, ops = _make_ops()
        store.save(_make_state("exec-1", status=WorkflowStatus.COMPLETED))

        assert ops.dead_letter_queue() == []


# ===================================================================
# 5. WorkflowOps — Metrics
# ===================================================================


class TestWorkflowOpsMetrics:
    """WorkflowOps.metrics()"""

    def test_empty_store(self):
        _, _, ops = _make_ops()
        m = ops.metrics()
        assert m["total"] == 0
        assert m["active"] == 0
        assert m["failure_rate"] == 0.0
        assert m["avg_duration_ms"] == 0.0

    def test_counts_by_status(self):
        store, _, ops = _make_ops()
        store.save(_make_state("e1", status=WorkflowStatus.RUNNING))
        store.save(_make_state("e2", status=WorkflowStatus.COMPLETED))
        store.save(_make_state("e3", status=WorkflowStatus.FAILED))
        store.save(_make_state("e4", status=WorkflowStatus.WAITING_FOR_INPUT))
        store.save(_make_state("e5", status=WorkflowStatus.CANCELLED))

        m = ops.metrics()
        assert m["total"] == 5
        assert m["active"] == 2  # RUNNING + WAITING_FOR_INPUT
        assert m["running"] == 1
        assert m["completed"] == 1
        assert m["failed"] == 1
        assert m["cancelled"] == 1
        assert m["waiting"] == 1

    def test_failure_rate(self):
        store, _, ops = _make_ops()
        store.save(_make_state("e1", status=WorkflowStatus.COMPLETED))
        store.save(_make_state("e2", status=WorkflowStatus.COMPLETED))
        store.save(_make_state("e3", status=WorkflowStatus.FAILED))

        m = ops.metrics()
        assert m["total"] == 3
        assert m["failure_rate"] == 0.333  # 1/3

    def test_no_terminal_instances_no_division_error(self):
        store, _, ops = _make_ops()
        store.save(_make_state("e1", status=WorkflowStatus.RUNNING))

        m = ops.metrics()
        assert m["total"] == 1
        assert m["failure_rate"] == 0.0
        assert m["avg_duration_ms"] == 0.0
