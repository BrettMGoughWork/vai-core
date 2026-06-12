"""Control Plane Supervisor — global job lifecycle correctness for Stratum-4.

The Control Plane Supervisor continuously evaluates the global correctness of
job lifecycle state across S2 (Job Store), S3 (Scheduler), and S4 (Worker Pool
+ Supervisor Loop + Queue Supervisor).

It detects inconsistent job states, performs deterministic auto-repair when
safe, and escalates to the S4 Control Plane when repair is impossible.

The Control Plane Supervisor is stateless, idempotent, and backend-agnostic.

Output format ready for inclusion in /src/supervisor/control_plane_supervisor.py
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# S2 state values
S2_STATE_QUEUED = "queued"
S2_STATE_PROCESSING = "processing"
S2_STATE_SUCCEEDED = "succeeded"
S2_STATE_FAILED = "failed"

# Event type constants
EVENT_JOB_INCONSISTENT = "job_inconsistent"
EVENT_JOB_AUTO_REPAIRED = "job_auto_repaired"
EVENT_CONTROL_PLANE_ESCALATION = "control_plane_escalation"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso_timestamp(now: float) -> str:
    """Format ``now`` (seconds since epoch) as a naive ISO-8601 string."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now))


# ---------------------------------------------------------------------------
# Data model — JobStateSnapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JobStateSnapshot:
    """A single job's state as seen from S2, S3, and S4.

    Attributes:
        job_id:         The job identifier.
        s2_state:       State reported by S2 (Job Store).
        s3_has_job:     Whether S3 (Scheduler) still holds the job.
        s3_worker_id:   Worker assigned by S3, if any (``None`` otherwise).
        s4_worker_ids:  Workers currently claiming this job (empty = none).
    """

    job_id: str = ""
    s2_state: str = S2_STATE_QUEUED
    s3_has_job: bool = False
    s3_worker_id: str | None = None
    s4_worker_ids: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Data model — InconsistencyEvent (§2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InconsistencyEvent:
    """Emitted when a job is detected in an inconsistent state.

    Schema spec::

        {
            "event": "job_inconsistent",
            "job_id": "<string>",
            "s2_state": "<string>",
            "s3_state": "<string>",
            "s4_state": "<string>",
            "timestamp": "<iso8601>",
            "reason": "<machine-readable>"
        }

    Attributes:
        event:      Always ``"job_inconsistent"``.
        job_id:     The inconsistent job.
        s2_state:   State from S2.
        s3_state:   Human-readable description of S3 state.
        s4_state:   Human-readable description of S4 state.
        timestamp:  ISO-8601 timestamp of detection.
        reason:     Machine-readable reason string.
    """

    event: str = EVENT_JOB_INCONSISTENT
    job_id: str = ""
    s2_state: str = ""
    s3_state: str = ""
    s4_state: str = ""
    timestamp: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        """Return a plain dict matching the spec schema."""
        return {
            "event": self.event,
            "job_id": self.job_id,
            "s2_state": self.s2_state,
            "s3_state": self.s3_state,
            "s4_state": self.s4_state,
            "timestamp": self.timestamp,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Data model — AutoRepairEvent (§3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AutoRepairEvent:
    """Emitted when a deterministic auto-repair is performed.

    Schema spec::

        {
            "event": "job_auto_repaired",
            "job_id": "<string>",
            "old_state": "<string>",
            "new_state": "<string>",
            "timestamp": "<iso8601>",
            "reason": "<machine-readable>"
        }

    Attributes:
        event:      Always ``"job_auto_repaired"``.
        job_id:     The repaired job.
        old_state:  State before repair.
        new_state:  State after repair.
        timestamp:  ISO-8601 timestamp of repair.
        reason:     Machine-readable reason string.
    """

    event: str = EVENT_JOB_AUTO_REPAIRED
    job_id: str = ""
    old_state: str = ""
    new_state: str = ""
    timestamp: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        """Return a plain dict matching the spec schema."""
        return {
            "event": self.event,
            "job_id": self.job_id,
            "old_state": self.old_state,
            "new_state": self.new_state,
            "timestamp": self.timestamp,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Data model — ControlPlaneEscalation (§4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ControlPlaneEscalation:
    """Emitted when a situation cannot be auto-repaired.

    Schema spec::

        {
            "event": "control_plane_escalation",
            "severity": "critical",
            "job_id": "<string|null>",
            "reason": "<string>",
            "timestamp": "<iso8601>"
        }

    Attributes:
        event:      Always ``"control_plane_escalation"``.
        severity:   Always ``"critical"``.
        job_id:     The job involved, or ``""`` for global issues.
        reason:     Machine-readable reason string.
        timestamp:  ISO-8601 timestamp of escalation.
    """

    event: str = EVENT_CONTROL_PLANE_ESCALATION
    severity: str = "critical"
    job_id: str = ""
    reason: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict:
        """Return a plain dict matching the spec schema."""
        return {
            "event": self.event,
            "severity": self.severity,
            "job_id": self.job_id,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Configuration — ControlPlaneSupervisorConfig
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ControlPlaneSupervisorConfig:
    """Configuration for :class:`ControlPlaneSupervisor`.

    Attributes:
        max_inconsistencies_per_window:
            Escalate if more than this many inconsistencies in the window.
        escalation_window_seconds:
            Time window (seconds) for counting inconsistencies.
        repair_enabled:
            Whether auto-repair is enabled (default ``True``).
    """

    max_inconsistencies_per_window: int = 10
    escalation_window_seconds: float = 60.0
    repair_enabled: bool = True


# ---------------------------------------------------------------------------
# Decision — ControlPlaneSupervisorDecision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ControlPlaneSupervisorDecision:
    """The result of a single Control Plane Supervisor evaluation cycle.

    Attributes:
        inconsistencies:  Inconsistency events detected this cycle.
        auto_repairs:     Auto-repair events performed this cycle.
        escalations:      Escalation events to emit.
        repaired_job_ids: Set of jobs that were auto-repaired.
    """

    inconsistencies: list[InconsistencyEvent] = field(default_factory=list)
    auto_repairs: list[AutoRepairEvent] = field(default_factory=list)
    escalations: list[ControlPlaneEscalation] = field(default_factory=list)
    repaired_job_ids: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# ControlPlaneSupervisor
# ---------------------------------------------------------------------------


class ControlPlaneSupervisor:
    """Global correctness authority for job lifecycle.

    The Control Plane Supervisor is stateless and idempotent — each
    ``evaluate()`` call compares S2/S3/S4 snapshots and produces a decision
    without persisting any internal state beyond the current cycle.

    Args:
        config: Supervisor configuration.
        clock:  A no-arg callable returning the current time in seconds
            (defaults to :func:`time.time`).  Inject a deterministic
            clock in tests.
    """

    def __init__(
        self,
        config: ControlPlaneSupervisorConfig | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.config = config or ControlPlaneSupervisorConfig()
        self._clock = clock if clock is not None else time.time

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        snapshots: list[JobStateSnapshot],
        active_worker_ids: set[str] | None = None,
        now: float | None = None,
    ) -> ControlPlaneSupervisorDecision:
        """Run one full control plane supervisor evaluation cycle.

        Steps (spec §5):
            1. Compare S2/S3/S4 states for each job.
            2. Identify inconsistencies.
            3. Attempt deterministic auto-repair.
            4. Escalate if repair is unsafe or impossible.
            5. Return decision with all events.

        Args:
            snapshots:  List of :class:`JobStateSnapshot` for all known jobs.
            active_worker_ids:
                Set of currently active worker IDs (used for consistency
                checks like "S3 assigned to nonexistent worker").
            now:        Current timestamp.  Defaults to ``self._clock()``.

        Returns:
            A :class:`ControlPlaneSupervisorDecision` with all detections.
        """
        ts = now if now is not None else self._clock()
        active_wids = active_worker_ids or set()
        decision = ControlPlaneSupervisorDecision()

        for snap in snapshots:
            # Step 2: Identify inconsistencies
            inc = self._detect_inconsistencies(snap, active_wids, ts)
            if inc is not None:
                decision.inconsistencies.append(inc)

                # Step 3: Attempt deterministic auto-repair
                repair = self._attempt_auto_repair(snap, ts)
                if repair is not None:
                    decision.auto_repairs.append(repair)
                    decision.repaired_job_ids.add(snap.job_id)
                else:
                    # Step 4: Escalate if repair is unsafe or impossible
                    esc = self._build_escalation(
                        snap.job_id,
                        f"Unsafe/cannot repair: {inc.reason}",
                        ts,
                    )
                    decision.escalations.append(esc)

        # Global inconsistency escalation
        if len(decision.inconsistencies) > self.config.max_inconsistencies_per_window:
            esc = self._build_escalation(
                "",
                f"Inconsistencies exceeded threshold: "
                f"{len(decision.inconsistencies)} > "
                f"{self.config.max_inconsistencies_per_window}",
                ts,
            )
            decision.escalations.append(esc)

        return decision

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect_inconsistencies(
        self,
        snap: JobStateSnapshot,
        active_worker_ids: set[str],
        ts: float,
    ) -> InconsistencyEvent | None:
        """Return an ``InconsistencyEvent`` if *snap* is inconsistent.

        Checks (spec §2):
        1. S2=queued but S3 has assigned it (has job + has worker).
        2. S2=processing but no S4 worker claims it.
        3. S2=processing but multiple S4 workers claim it.
        4. S2=succeeded/failed but S3 still has it.
        5. S3 assigned to nonexistent worker.
        6. S4 claims a job S2 considers queued.
        """
        s4_str = self._s4_state_str(snap)
        s3_str = self._s3_state_str(snap)

        # Check 5: S3 assigned to nonexistent worker (most specific — check first)
        if (snap.s3_worker_id is not None
                and snap.s3_worker_id not in active_worker_ids):
            return InconsistencyEvent(
                event=EVENT_JOB_INCONSISTENT,
                job_id=snap.job_id,
                s2_state=snap.s2_state,
                s3_state=s3_str,
                s4_state=s4_str,
                timestamp=_iso_timestamp(ts),
                reason=f"S3 assigned to nonexistent worker {snap.s3_worker_id}",
            )

        # Check 1: S2 queued ∧ S3 assigned
        if (snap.s2_state == S2_STATE_QUEUED
                and snap.s3_has_job
                and snap.s3_worker_id is not None):
            return InconsistencyEvent(
                event=EVENT_JOB_INCONSISTENT,
                job_id=snap.job_id,
                s2_state=snap.s2_state,
                s3_state=s3_str,
                s4_state=s4_str,
                timestamp=_iso_timestamp(ts),
                reason=f"S2 queued but S3 assigned to {snap.s3_worker_id}",
            )

        # Check 2: S2 processing ∧ no S4 worker
        if (snap.s2_state == S2_STATE_PROCESSING
                and len(snap.s4_worker_ids) == 0):
            return InconsistencyEvent(
                event=EVENT_JOB_INCONSISTENT,
                job_id=snap.job_id,
                s2_state=snap.s2_state,
                s3_state=s3_str,
                s4_state=s4_str,
                timestamp=_iso_timestamp(ts),
                reason="S2 processing but no worker claims job",
            )

        # Check 3: S2 processing ∧ multiple S4 workers
        if (snap.s2_state == S2_STATE_PROCESSING
                and len(snap.s4_worker_ids) > 1):
            return InconsistencyEvent(
                event=EVENT_JOB_INCONSISTENT,
                job_id=snap.job_id,
                s2_state=snap.s2_state,
                s3_state=s3_str,
                s4_state=s4_str,
                timestamp=_iso_timestamp(ts),
                reason=f"S2 processing but {len(snap.s4_worker_ids)} workers claim it",
            )

        # Check 4: S2 succeeded/failed ∧ S3 still holds
        if (snap.s2_state in (S2_STATE_SUCCEEDED, S2_STATE_FAILED)
                and snap.s3_has_job):
            return InconsistencyEvent(
                event=EVENT_JOB_INCONSISTENT,
                job_id=snap.job_id,
                s2_state=snap.s2_state,
                s3_state=s3_str,
                s4_state=s4_str,
                timestamp=_iso_timestamp(ts),
                reason=f"S2 {snap.s2_state} but S3 still holds job",
            )

        # Check 6: S4 claims job but S2 says queued
        if (len(snap.s4_worker_ids) > 0
                and snap.s2_state == S2_STATE_QUEUED):
            return InconsistencyEvent(
                event=EVENT_JOB_INCONSISTENT,
                job_id=snap.job_id,
                s2_state=snap.s2_state,
                s3_state=s3_str,
                s4_state=s4_str,
                timestamp=_iso_timestamp(ts),
                reason=f"S4 claims job but S2 reports queued",
            )

        return None

    def _attempt_auto_repair(
        self,
        snap: JobStateSnapshot,
        ts: float,
    ) -> AutoRepairEvent | None:
        """Attempt deterministic auto-repair for *snap*.

        Allowed repairs (spec §3):
        1. S3/S4 claim job but S2 says queued → reset to queued
        2. S2 processing but no worker claims → reset to queued
        3. S2 processing and worker crashed → reset to queued
        4. S2 succeeded/failed but S3 still holds → remove from scheduler
        """
        if not self.config.repair_enabled:
            return None

        # Repair 1: S3/S4 claim but S2 says queued → no-op (already safe)
        if (snap.s2_state == S2_STATE_QUEUED
                and (snap.s3_has_job or len(snap.s4_worker_ids) > 0)):
            return AutoRepairEvent(
                event=EVENT_JOB_AUTO_REPAIRED,
                job_id=snap.job_id,
                old_state=S2_STATE_QUEUED,
                new_state=S2_STATE_QUEUED,
                timestamp=_iso_timestamp(ts),
                reason="S3/S4 diverged from S2; resetting S3/S4 to match S2 queued",
            )

        # Repair 2+3: S2 processing but no S4 worker → reset to queued
        if (snap.s2_state == S2_STATE_PROCESSING
                and len(snap.s4_worker_ids) == 0):
            return AutoRepairEvent(
                event=EVENT_JOB_AUTO_REPAIRED,
                job_id=snap.job_id,
                old_state=S2_STATE_PROCESSING,
                new_state=S2_STATE_QUEUED,
                timestamp=_iso_timestamp(ts),
                reason="Job stuck in processing with no active worker; resetting to queued",
            )

        # Repair 4: S2 succeeded/failed but S3 still holds → remove
        if (snap.s2_state in (S2_STATE_SUCCEEDED, S2_STATE_FAILED)
                and snap.s3_has_job):
            return AutoRepairEvent(
                event=EVENT_JOB_AUTO_REPAIRED,
                job_id=snap.job_id,
                old_state=snap.s2_state,
                new_state=snap.s2_state,
                timestamp=_iso_timestamp(ts),
                reason=f"Job {snap.s2_state} but S3 still holds; removing from scheduler",
            )

        return None

    def _build_escalation(
        self,
        job_id: str,
        reason: str,
        ts: float,
    ) -> ControlPlaneEscalation:
        return ControlPlaneEscalation(
            event=EVENT_CONTROL_PLANE_ESCALATION,
            severity="critical",
            job_id=job_id,
            reason=reason,
            timestamp=_iso_timestamp(ts),
        )

    @staticmethod
    def _s3_state_str(snap: JobStateSnapshot) -> str:
        """Human-readable S3 state description."""
        if not snap.s3_has_job:
            return "not_scheduled"
        if snap.s3_worker_id:
            return f"assigned_to_{snap.s3_worker_id}"
        return "queued"

    @staticmethod
    def _s4_state_str(snap: JobStateSnapshot) -> str:
        """Human-readable S4 state description."""
        if not snap.s4_worker_ids:
            return "not_claimed"
        return f"claimed_by_{','.join(snap.s4_worker_ids)}"
