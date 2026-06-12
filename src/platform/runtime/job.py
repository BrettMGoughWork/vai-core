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
    """

    job_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    state: JobState = JobState.PENDING
    payload: ChannelMessage
    result: dict[str, Any] | None = None
    trace: list[dict] = Field(default_factory=list)
    execution_context: ExecutionContext | None = None
    resume_token: str | None = None

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
