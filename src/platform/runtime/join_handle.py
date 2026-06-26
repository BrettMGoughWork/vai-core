"""
JoinHandle — Stratum-4 Fan-in Coordination
============================================

A ``JoinHandle`` tracks the lifecycle of a fan-in operation: a parent job
spawns N child subtask jobs, and the join handle monitors their progress
until all are finished (or a terminal condition is reached).

Ownership
---------
- Created by ``DecompositionOrchestrator.fan_out()``
- Stored in ``JoinStore``
- Updated by the scheduler as child jobs complete / fail
- Read by ``DecompositionOrchestrator.fan_in()`` to determine merge readiness

Lifecycle
---------
WAITING → (all succeeded) → COMPLETED
WAITING → (any failed)     → FAILED
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class JoinHandleState(str, Enum):
    """State of a fan-in join handle."""

    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


class JoinHandle(BaseModel):
    """Tracks fan-in progress for a decomposed parent job.

    Fields:
        join_handle_id:    UUID v4 — stable identifier for store lookups.
        parent_job_id:     The job that spawned the fan-out.
        plan_id:           Links back to the ``DecompositionPlan``.
        child_job_ids:     All subtask job IDs in this fan-out group.
        completed_ids:     Subset of child_job_ids that have finished.
        failed_ids:        Subset of child_job_ids that have failed.
        state:             Current join lifecycle state.
        merge_strategy:    How to combine results (pass-through from plan).
        merge_agent_id:    Optional agent to run LLM merge.
        created_at:        Timestamp of creation.
        completed_at:      Timestamp when state reached COMPLETED or FAILED.
    """

    join_handle_id: str = Field(default_factory=lambda: str(uuid4()))
    parent_job_id: str
    plan_id: str
    child_job_ids: list[str]
    completed_ids: list[str] = Field(default_factory=list)
    failed_ids: list[str] = Field(default_factory=list)
    state: JoinHandleState = JoinHandleState.WAITING
    merge_strategy: str = "concat"
    merge_agent_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    def is_ready(self) -> bool:
        """Return ``True`` when all child jobs have completed or failed."""
        return len(self.completed_ids) + len(self.failed_ids) >= len(self.child_job_ids)

    def all_succeeded(self) -> bool:
        """Return ``True`` when all child jobs have succeeded (none failed)."""
        return len(self.completed_ids) == len(self.child_job_ids) and len(self.failed_ids) == 0

    def mark_child_completed(self, child_job_id: str) -> None:
        """Record a child job as completed successfully."""
        if child_job_id not in self.child_job_ids:
            # Not tracked by this handle — ignore (e.g. continuation job
            # sharing the same plan_id as the subtask group).
            return
        if child_job_id not in self.completed_ids:
            self.completed_ids.append(child_job_id)
        self._advance()

    def mark_child_failed(self, child_job_id: str) -> None:
        """Record a child job as failed."""
        if child_job_id not in self.child_job_ids:
            # Not tracked by this handle — ignore (e.g. continuation job
            # sharing the same plan_id as the subtask group).
            return
        if child_job_id not in self.failed_ids:
            self.failed_ids.append(child_job_id)
        self._advance()

    def _advance(self) -> None:
        """Transition state when all children are accounted for."""
        if not self.is_ready():
            return
        self.completed_at = datetime.now(timezone.utc)
        if self.all_succeeded():
            self.state = JoinHandleState.COMPLETED
        else:
            self.state = JoinHandleState.FAILED
