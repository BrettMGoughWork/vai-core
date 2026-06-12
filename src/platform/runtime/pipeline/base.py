"""Pipeline abstraction — StageContext, PipelineStage protocol, and shared types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from src.platform.runtime.control_plane import ControlPlane
from src.platform.runtime.job import Job
from src.platform.runtime.safety.degraded_mode import SignalState


@dataclass
class PipelineContext:
    """Mutable context accumulated through the pipeline.

    Attributes:
        job:           The job being processed (mutated in-place by stages).
        control_plane: The ControlPlane that owns job state transitions.
        stored_job:    The job as loaded from the JobStore (if available), used
                       for idempotency validation against the live job state.
        signal_state:  Optional aggregated S1/S2/S3 stability signals for
                       degraded mode evaluation and recovery checks.
    """

    job: Job
    control_plane: ControlPlane
    stored_job: Job | None = None
    signal_state: SignalState | None = None


class PipelineStage(Protocol):
    """Protocol for a composable worker pipeline stage.

    Each stage receives the mutable :class:`PipelineContext` and may:

    * Mutate ``ctx.job`` in-place (state, result, lifecycle events, …).
    * Return the ``Job`` to short-circuit the pipeline (abort or completion).
    * Return ``None`` to let the pipeline continue to the next stage.

    The final stage in the pipeline **must** return the completed ``Job``.
    """

    name: str

    def evaluate(self, ctx: PipelineContext) -> Job | None:
        """Evaluate this stage against the current pipeline context.

        Returns:
            * The :class:`Job` to return immediately (abort or completed).
            * ``None`` to continue to the next stage.
        """
        ...
