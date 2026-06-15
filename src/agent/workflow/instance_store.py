"""
Phase R.9.1 — WorkflowInstanceStore
=====================================

Persistent store for ``WorkflowExecutionState`` instances, indexed by
``execution_id``, ``workflow_id``, and ``status``.

Provides the cross-agent query layer that ``WorkflowOps`` depends on:
- ``save()`` — upsert by execution_id (auto-timestamps)
- ``get()`` — single instance lookup
- ``list_instances()`` — filtered by optional workflow_id / status
- ``delete()`` — remove an instance

Default implementation uses an in-memory dict (single-process deployments).
A SQLite-backed version is a future extension for multi-process scenarios.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from src.agent.workflow.engine import WorkflowExecutionState, WorkflowStatus


# ---------------------------------------------------------------------------
# Record wrapper — pairs state with store-managed timestamps
# ---------------------------------------------------------------------------


@dataclass
class WorkflowInstanceRecord:
    """Internal record that wraps state with timestamps managed by the store."""

    state: WorkflowExecutionState
    created_at: str = ""
    updated_at: str = ""


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class WorkflowInstanceStore:
    """Persistent store for workflow execution instances.

    Thread‑safe for single‑process use.  All mutation methods accept
    a ``WorkflowExecutionState`` and manage timestamps internally.
    """

    def __init__(self) -> None:
        self._records: Dict[str, WorkflowInstanceRecord] = {}

    # ── Public API ─────────────────────────────────────────────────────

    def save(self, instance: WorkflowExecutionState) -> None:
        """Upsert a workflow execution state.

        The first ``save()`` call for an execution_id sets ``created_at``;
        subsequent calls update ``updated_at``.
        """
        now = datetime.now(timezone.utc).isoformat()
        existing = self._records.get(instance.execution_id)
        if existing is None:
            self._records[instance.execution_id] = WorkflowInstanceRecord(
                state=instance,
                created_at=now,
                updated_at=now,
            )
        else:
            existing.state = instance
            existing.updated_at = now

    def get(self, execution_id: str) -> Optional[WorkflowExecutionState]:
        """Retrieve a workflow execution state by its execution_id.

        Returns ``None`` if no instance with that ID exists.
        """
        record = self._records.get(execution_id)
        return record.state if record is not None else None

    def list_instances(
        self,
        *,
        workflow_id: Optional[str] = None,
        status: Optional[WorkflowStatus] = None,
    ) -> List[WorkflowExecutionState]:
        """List instances, optionally filtered by workflow_id and/or status.

        Results are sorted by ``created_at`` descending (newest first).
        """
        results: List[WorkflowExecutionState] = []
        for record in self._records.values():
            if workflow_id is not None and record.state.workflow_id != workflow_id:
                continue
            if status is not None and record.state.status != status:
                continue
            results.append(record.state)

        # Stable sort — newest first
        results.sort(
            key=lambda s: (
                self._records[s.execution_id].created_at
                if s.execution_id in self._records
                else ""
            ),
            reverse=True,
        )
        return results

    def delete(self, execution_id: str) -> bool:
        """Delete a workflow execution instance.

        Returns ``True`` if the instance existed and was removed,
        ``False`` if it did not exist.
        """
        if execution_id in self._records:
            del self._records[execution_id]
            return True
        return False

    # ── Internal helpers ───────────────────────────────────────────────

    def _get_record(
        self, execution_id: str
    ) -> Optional[WorkflowInstanceRecord]:
        """Retrieve the full record (state + timestamps)."""
        return self._records.get(execution_id)

    @property
    def _instance_count(self) -> int:
        """Number of instances currently in the store (useful for tests)."""
        return len(self._records)
