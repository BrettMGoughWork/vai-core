"""
Phase R.9.2 — WorkflowOps
==========================

Operational management API for workflow instances.

Provides the cross-agent view that ops teams need:
- ``list_instances()`` — view all runs, optionally filtered by state
- ``get_instance()`` — full detail for a single run
- ``cancel_instance()`` — stop a running/paused workflow
- ``retry_instance()`` — reset a failed workflow for re-execution
- ``dead_letter_queue()`` — instances that need manual intervention
- ``metrics()`` — aggregate counts, durations, failure rates

WorkflowOps wraps ``WorkflowInstanceStore`` (persistence) and
``WorkflowEngine`` (state machine operations).  It does **not** own
the execution loop — the Agent Runtime Supervisor handles that.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from src.agent.workflow.engine import (
    WorkflowEngine,
    WorkflowExecutionState,
    WorkflowStatus,
)
from src.agent.workflow.instance_store import WorkflowInstanceStore


class WorkflowOps:
    """Operational management API for workflow instances.

    Instantiated with a store and an engine.  The store is shared with
    the Agent Supervisor so state transitions are visible immediately.
    """

    def __init__(
        self,
        store: WorkflowInstanceStore,
        engine: WorkflowEngine,
    ) -> None:
        self._store = store
        self._engine = engine

    # ── Query API ─────────────────────────────────────────────────────

    def list_instances(
        self,
        state: Optional[str] = None,
    ) -> List[WorkflowExecutionState]:
        """List all workflow instances, optionally filtered by status.

        Args:
            state: Optional status string (e.g. ``"running"``, ``"failed"``).
                   Case-insensitive match against ``WorkflowStatus`` values.

        Returns:
            Instances sorted by creation time descending.
        """
        status: Optional[WorkflowStatus] = None
        if state is not None:
            try:
                status = WorkflowStatus(state.lower())
            except ValueError:
                return []
        return self._store.list_instances(status=status)

    def get_instance(
        self,
        execution_id: str,
    ) -> Optional[WorkflowExecutionState]:
        """Get the full state for a single workflow execution.

        Returns ``None`` if the execution_id is not found.
        """
        return self._store.get(execution_id)

    # ── Lifecycle operations ──────────────────────────────────────────

    def cancel_instance(self, execution_id: str) -> bool:
        """Cancel a running or paused workflow execution.

        Uses ``WorkflowEngine.cancel()`` to produce the cancelled state,
        then persists it.

        Args:
            execution_id: The execution to cancel.

        Returns:
            ``True`` if the instance existed and was cancelled.
            ``False`` if the instance was not found or already terminal.
        """
        state = self._store.get(execution_id)
        if state is None:
            return False

        if state.status in (
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        ):
            return False

        new_state = self._engine.cancel(state)
        self._store.save(new_state)
        return True

    def retry_instance(self, execution_id: str) -> bool:
        """Reset a failed workflow for re-execution.

        Clears the error, sets status back to RUNNING, and preserves
        the existing context and step_results.  The caller must
        re-invoke the supervisor execution loop to actually re-run
        the failed step.

        Args:
            execution_id: The failed execution to retry.

        Returns:
            ``True`` if the instance was reset.  ``False`` if the
            instance was not found or was not in FAILED state.
        """
        state = self._store.get(execution_id)
        if state is None:
            return False

        if state.status != WorkflowStatus.FAILED:
            return False

        # Preserve context and step_results; clear error; set RUNNING
        new_state = WorkflowExecutionState(
            execution_id=state.execution_id,
            workflow_id=state.workflow_id,
            status=WorkflowStatus.RUNNING,
            current_step_id=state.current_step_id,
            context=dict(state.context),
            step_results=dict(state.step_results),
            error=None,
        )
        self._store.save(new_state)
        return True

    # ── Dead-letter queue ─────────────────────────────────────────────

    def dead_letter_queue(self) -> List[WorkflowExecutionState]:
        """Return failed workflow instances that need manual intervention.

        Currently returns all instances with ``status=FAILED``.
        Future versions may add retry-count thresholds.
        """
        return self._store.list_instances(status=WorkflowStatus.FAILED)

    # ── Metrics ───────────────────────────────────────────────────────

    def metrics(self) -> Dict[str, object]:
        """Aggregate metrics across all workflow instances.

        Returns:
            A dict with counts by state, average duration (in milliseconds),
            and failure rate:

            .. code-block:: python

                {
                    "active": 5,
                    "completed": 100,
                    "failed": 3,
                    "cancelled": 1,
                    "waiting": 2,
                    "total": 111,
                    "avg_duration_ms": 450.0,
                    "failure_rate": 0.027,
                }
        """
        now = datetime.now(timezone.utc)
        instances = self._store.list_instances()

        counts: Dict[str, int] = {
            "active": 0,
            "running": 0,
            "waiting": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "pending": 0,
            "total": len(instances),
        }

        total_duration_ms = 0.0
        instances_with_duration = 0

        for inst in instances:
            # Map status enum to counts dict key
            if inst.status == WorkflowStatus.RUNNING:
                counts["running"] += 1
                counts["active"] += 1
            elif inst.status == WorkflowStatus.WAITING_FOR_INPUT:
                counts["waiting"] += 1
                counts["active"] += 1
            elif inst.status == WorkflowStatus.PENDING:
                counts["pending"] += 1
                counts["active"] += 1
            elif inst.status == WorkflowStatus.COMPLETED:
                counts["completed"] += 1
            elif inst.status == WorkflowStatus.FAILED:
                counts["failed"] += 1
            elif inst.status == WorkflowStatus.CANCELLED:
                counts["cancelled"] += 1

            # Duration — only for terminal instances
            if inst.status in (
                WorkflowStatus.COMPLETED,
                WorkflowStatus.FAILED,
                WorkflowStatus.CANCELLED,
            ):
                record = self._store._get_record(inst.execution_id)  # type: ignore[attr-defined]  # noqa: SLF001
                if record is not None and record.created_at:
                    try:
                        created = datetime.fromisoformat(record.created_at)
                        duration_s = (now - created).total_seconds()
                        total_duration_ms += duration_s * 1000
                        instances_with_duration += 1
                    except (ValueError, TypeError):
                        pass

        total_terminal = counts["completed"] + counts["failed"]
        failure_rate = (
            round(counts["failed"] / total_terminal, 3)
            if total_terminal > 0
            else 0.0
        )

        avg_duration_ms = (
            round(total_duration_ms / instances_with_duration, 1)
            if instances_with_duration > 0
            else 0.0
        )

        return {
            "active": counts["active"],
            "running": counts["running"],
            "waiting": counts["waiting"],
            "completed": counts["completed"],
            "failed": counts["failed"],
            "cancelled": counts["cancelled"],
            "total": counts["total"],
            "avg_duration_ms": avg_duration_ms,
            "failure_rate": failure_rate,
        }
