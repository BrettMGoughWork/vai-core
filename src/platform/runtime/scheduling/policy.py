"""Deterministic job scheduling policies (FIFO / Priority).

Stratum-4 — pure logic, no IO, no queue backend dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


# ---------------------------------------------------------------------------
# SchedulingMode
# ---------------------------------------------------------------------------


class SchedulingMode(Enum):
    """Supported job scheduling policies.

    Attributes:
        FIFO:     Earliest-created job first (oldest first).
        PRIORITY: Highest-priority job first; tie-break by age then job_id.
    """

    FIFO = "fifo"
    PRIORITY = "priority"


# ---------------------------------------------------------------------------
# JobMetadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JobMetadata:
    """Minimal, immutable representation of a job for scheduling decisions.

    Attributes:
        job_id:     Unique identifier.
        priority:   Numeric priority (higher = more important).
        created_at: Timestamp used for FIFO ordering and PRIORITY tie-breaks.
    """

    job_id: str
    priority: int
    created_at: datetime


# ---------------------------------------------------------------------------
# SchedulingContext & Decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SchedulingContext:
    """Input to the scheduler — a snapshot of pending jobs.

    Attributes:
        pending_jobs: List of :class:`JobMetadata` for all currently
            eligible jobs.
    """

    pending_jobs: list[JobMetadata]


@dataclass(frozen=True)
class SchedulingDecision:
    """Output of the scheduler — which job to claim next.

    Attributes:
        job_id: The selected job, or ``None`` if no job is available.
        reason: Human-readable explanation (``"no-jobs"``, ``"selected"``,
            or the specific policy name).
    """

    job_id: str | None
    reason: str | None


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class Scheduler:
    """Deterministic, backend-agnostic job scheduler.

    Args:
        mode: The scheduling policy to apply.
    """

    def __init__(self, mode: SchedulingMode) -> None:
        self.mode = mode

    def select(self, ctx: SchedulingContext) -> SchedulingDecision:
        """Select the next job to claim.

        Args:
            ctx: Snapshot of pending jobs.

        Returns:
            A :class:`SchedulingDecision` identifying the chosen job (or
            ``None`` if there are no pending jobs).
        """
        if not ctx.pending_jobs:
            return SchedulingDecision(job_id=None, reason="no-jobs")

        if self.mode == SchedulingMode.FIFO:
            return self._select_fifo(ctx)

        # PRIORITY (default fallback)
        return self._select_priority(ctx)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _select_fifo(ctx: SchedulingContext) -> SchedulingDecision:
        """Oldest job first, deterministic tie-break by job_id."""
        if not ctx.pending_jobs:
            return SchedulingDecision(job_id=None, reason="no-jobs")

        # Sort by created_at ascending, then job_id ascending
        best = sorted(
            ctx.pending_jobs,
            key=lambda j: (j.created_at, j.job_id),
        )[0]
        return SchedulingDecision(
            job_id=best.job_id,
            reason=f"fifo:created_at={best.created_at.isoformat()}",
        )

    @staticmethod
    def _select_priority(ctx: SchedulingContext) -> SchedulingDecision:
        """Highest priority first; tie-break by age then job_id."""
        if not ctx.pending_jobs:
            return SchedulingDecision(job_id=None, reason="no-jobs")

        # Sort by priority descending, created_at ascending, job_id ascending
        best = sorted(
            ctx.pending_jobs,
            key=lambda j: (-j.priority, j.created_at, j.job_id),
        )[0]
        return SchedulingDecision(
            job_id=best.job_id,
            reason=(
                f"priority:{best.priority}:"
                f"created_at={best.created_at.isoformat()}"
            ),
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_scheduler(mode: SchedulingMode) -> Scheduler:
    """Build a :class:`Scheduler` for the given *mode*.

    Args:
        mode: The scheduling policy to use.

    Returns:
        A configured :class:`Scheduler` instance.
    """
    return Scheduler(mode=mode)
