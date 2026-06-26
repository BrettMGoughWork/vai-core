"""Job v1 model and factory — Stratum-4 runtime.

A ``Job`` is created from a ``ChannelMessage`` and tracks the lifecycle
of a single unit of work inside S4.  Pure data — no orchestration, no
worker logic, no control plane.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from src.platform.runtime.execution_context import ExecutionContext
from src.platform.runtime.job_state import JobState
from src.platform.transport.normalization import ChannelMessage


class Job(BaseModel):
    """A unit of work inside Stratum-4.

    Fields:
        job_id:             UUID v4 string, generated at creation.
        created_at:         Timezone-aware UTC timestamp of creation.
        state:              Current lifecycle state via ``JobState`` enum.
        payload:            The ``ChannelMessage`` that triggered this job.
        result:             Optional output dict, populated after execution.
        trace:              Append-only state-transition trace.
        execution_context:  Opaque cross-cycle cognitive envelope.

    Decomposition fields (used for agent task fan-out/fan-in):
        job_type:           "default" | "subtask" | "continuation"
        parent_job_id:      Links child job back to its parent.
        priority:           Higher values = earlier dispatch.
        max_retries:        Per-job retry limit.
        timeout_seconds:    Per-job timeout.
        plan_id:            Links to the ``DecompositionPlan``.
        subtask_id:         Matches ``SubtaskSpec.id``.
        depends_on:         Subtask IDs this job waits for.
    """

    job_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    state: JobState = JobState.PENDING
    payload: ChannelMessage
    result: dict[str, Any] | None = None
    trace: list[dict] = Field(default_factory=list)
    execution_context: ExecutionContext | None = None
    resume_token: str | None = None
    failure_count: int = 0
    consecutive_failures: int = 0
    panic_count: int = 0
    crash_count: int = 0

    # ── Decomposition fields ──────────────────────────────────────────
    job_type: str = "default"
    parent_job_id: str | None = None
    priority: int = 0
    max_retries: int = 0
    timeout_seconds: int = 300
    plan_id: str | None = None
    subtask_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Checkpoint helpers
    # ------------------------------------------------------------------

    def save_checkpoint(self) -> dict:
        """Serialise the current execution context for persistence.

        Returns:
            The ``ExecutionContext`` as a plain dict, or an empty dict if
            no context has been initialised yet.
        """
        if self.execution_context is None:
            return {}
        return self.execution_context.to_dict()


def create_job(channel_message: ChannelMessage) -> Job:
    """Create a new ``Job`` from a ``ChannelMessage``.

    Generates a UUID4 ``job_id`` and UTC ``created_at`` timestamp.
    The job starts in ``JobState.PENDING`` with ``result=None``.

    Args:
        channel_message: The normalized inbound message.

    Returns:
        A new ``Job`` instance.
    """
    return Job(
        job_id=str(uuid4()),
        created_at=datetime.now(timezone.utc),
        state=JobState.PENDING,
        payload=channel_message,
        result=None,
    )
