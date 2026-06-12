"""Queue Supervisor — deterministic queue health monitoring for Stratum-4.

The Queue Supervisor runs on a fixed interval and is responsible for:

- monitoring the job queue at a fixed interval
- detecting jobs that have exceeded their allowed processing window
- detecting queue backpressure conditions
- emitting structured events for observability
- avoiding modifying job state directly
- avoiding executing job logic
- avoiding interfering with the worker pool

The Queue Supervisor is diagnostic, not agentic.

Output format ready for inclusion in /src/supervisor/queue_supervisor.py
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STUCK_STATE_QUEUED = "queued"
STUCK_STATE_PROCESSING = "processing"

EVENT_JOB_STUCK = "job_stuck"
EVENT_QUEUE_BACKPRESSURE = "queue_backpressure"
EVENT_QUEUE_SUPERVISOR_ESCALATION = "queue_supervisor_escalation"

# ---------------------------------------------------------------------------
# Data model — QueueMetrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QueueMetrics:
    """Snapshot of queue state at a point in time.

    Attributes:
        queue_length:   Number of jobs currently in the queue (not yet popped).
        in_flight_count: Number of jobs currently leased (popped but not acked).
        enqueue_rate:   Inflow rate (jobs per second) over the last interval.
        dequeue_rate:   Outflow rate (jobs per second) over the last interval.
        queued_jobs:    List of ``(job_id, age_seconds)`` for jobs still queued.
        in_flight_jobs: List of ``(job_id, age_seconds)`` for jobs in-flight.
    """

    queue_length: int = 0
    in_flight_count: int = 0
    enqueue_rate: float = 0.0
    dequeue_rate: float = 0.0
    queued_jobs: list[tuple[str, float]] = field(default_factory=list)
    in_flight_jobs: list[tuple[str, float]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Data model — StuckJobEvent (schema from spec §2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StuckJobEvent:
    """Emitted when a job is detected as stuck.

    Schema spec::

        {
            "event": "job_stuck",
            "job_id": "<string>",
            "state": "<queued|processing>",
            "age_ms": "<number>",
            "timeout_ms": "<number>",
            "timestamp": "<iso8601>"
        }

    Attributes:
        job_id:     The stuck job.
        state:      ``"queued"`` or ``"processing"``.
        age_ms:     How long the job has been in this state.
        timeout_ms: The threshold that was exceeded.
        timestamp:  ISO-8601 timestamp of detection.
    """

    event: str = EVENT_JOB_STUCK
    job_id: str = ""
    state: str = STUCK_STATE_QUEUED
    age_ms: float = 0.0
    timeout_ms: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> dict:
        """Return a plain dict matching the spec schema."""
        return {
            "event": self.event,
            "job_id": self.job_id,
            "state": self.state,
            "age_ms": self.age_ms,
            "timeout_ms": self.timeout_ms,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Data model — QueueBackpressureEvent (schema from spec §3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QueueBackpressureEvent:
    """Emitted when backpressure conditions are detected.

    Schema spec::

        {
            "event": "queue_backpressure",
            "queue_length": "<number>",
            "avg_job_age_ms": "<number>",
            "enqueue_rate": "<number>",
            "dequeue_rate": "<number>",
            "timestamp": "<iso8601>"
        }

    Attributes:
        queue_length:  Number of jobs in the queue.
        avg_job_age_ms: Average age of queued jobs in milliseconds.
        enqueue_rate:  Inflow rate (jobs/sec).
        dequeue_rate:  Outflow rate (jobs/sec).
        timestamp:     ISO-8601 timestamp of detection.
    """

    event: str = EVENT_QUEUE_BACKPRESSURE
    queue_length: int = 0
    avg_job_age_ms: float = 0.0
    enqueue_rate: float = 0.0
    dequeue_rate: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> dict:
        """Return a plain dict matching the spec schema."""
        return {
            "event": self.event,
            "queue_length": self.queue_length,
            "avg_job_age_ms": self.avg_job_age_ms,
            "enqueue_rate": self.enqueue_rate,
            "dequeue_rate": self.dequeue_rate,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Data model — QueueSupervisorEscalation (schema from spec §5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QueueSupervisorEscalation:
    """Emitted when escalation thresholds are exceeded.

    Schema spec::

        {
            "event": "queue_supervisor_escalation",
            "severity": "critical",
            "reason": "<string>",
            "timestamp": "<iso8601>"
        }

    Attributes:
        reason:    Machine-readable escalation reason.
        timestamp: ISO-8601 timestamp of escalation.
    """

    event: str = EVENT_QUEUE_SUPERVISOR_ESCALATION
    severity: str = "critical"
    reason: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict:
        """Return a plain dict matching the spec schema."""
        return {
            "event": self.event,
            "severity": self.severity,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Configuration — QueueSupervisorConfig
# ---------------------------------------------------------------------------


@dataclass
class QueueSupervisorConfig:
    """Configuration for :class:`QueueSupervisor`.

    Attributes:
        max_processing_time_ms:
            Jobs in-flight longer than this are declared stuck.
        max_queue_age_ms:
            Jobs queued longer than this are declared stuck.
        ack_timeout_ms:
            Jobs not acknowledged within this window are declared stuck.
        backpressure_queue_length_threshold:
            Queue length above this triggers backpressure.
        backpressure_avg_age_ms:
            Average queued job age above this triggers backpressure.
        backpressure_enqueue_dequeue_ratio:
            Enqueue/dequeue rate ratio above this triggers backpressure.
        backpressure_consecutive_intervals:
            Number of consecutive backpressure detections before escalation.
        critical_stuck_job_threshold:
            Number of stuck jobs in one cycle triggers escalation.
        critical_queue_length:
            Queue length above this triggers immediate escalation.
        critical_job_age_ms:
            Any queued job older than this triggers immediate escalation.
    """

    max_processing_time_ms: float = 30000.0  # 30s
    max_queue_age_ms: float = 60000.0  # 60s
    ack_timeout_ms: float = 10000.0  # 10s

    backpressure_queue_length_threshold: int = 100
    backpressure_avg_age_ms: float = 30000.0  # 30s
    backpressure_enqueue_dequeue_ratio: float = 1.5
    backpressure_consecutive_intervals: int = 3

    critical_stuck_job_threshold: int = 5
    critical_queue_length: int = 200
    critical_job_age_ms: float = 120000.0  # 120s


# ---------------------------------------------------------------------------
# Decision — QueueSupervisorDecision
# ---------------------------------------------------------------------------


@dataclass
class QueueSupervisorDecision:
    """The result of a single Queue Supervisor evaluation cycle.

    Attributes:
        stuck_jobs:     Stuck job events detected this cycle.
        backpressure_events: Backpressure events detected this cycle.
        escalations:    Escalation events to emit.
        has_backpressure: ``True`` if backpressure was detected this cycle.
        consecutive_backpressure_intervals:
            Running count of consecutive cycles with backpressure.
        queue_length:   Current queue length.
        avg_job_age_ms: Average age of queued jobs.
    """

    stuck_jobs: list[StuckJobEvent] = field(default_factory=list)
    backpressure_events: list[QueueBackpressureEvent] = field(default_factory=list)
    escalations: list[QueueSupervisorEscalation] = field(default_factory=list)
    has_backpressure: bool = False
    consecutive_backpressure_intervals: int = 0
    queue_length: int = 0
    avg_job_age_ms: float = 0.0


# ---------------------------------------------------------------------------
# QueueSupervisor
# ---------------------------------------------------------------------------


class QueueSupervisor:
    """Deterministic queue health supervisor.

    The supervisor is pure logic — it receives queue metrics, evaluates stuck
    job and backpressure conditions, checks escalation thresholds, and returns
    a :class:`QueueSupervisorDecision`.  No IO, no side effects.

    Args:
        config: Queue Supervisor configuration.
        clock:  A no-arg callable returning the current time in seconds
            (defaults to :func:`time.time`).  Inject a deterministic
            clock in tests.
    """

    def __init__(
        self,
        config: QueueSupervisorConfig | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.config = config or QueueSupervisorConfig()
        self._clock = clock if clock is not None else time.time

        # State tracking
        self._backpressure_count: int = 0
        self._stuck_job_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        metrics: QueueMetrics,
        now: float | None = None,
    ) -> QueueSupervisorDecision:
        """Run one full queue supervisor evaluation cycle.

        Steps (spec §4):
            1. Read queue metrics.
            2. Identify stuck jobs.
            3. Emit ``job_stuck`` events.
            4. Evaluate backpressure conditions.
            5. Emit ``queue_backpressure`` events.
            6. Check escalation thresholds.

        Args:
            metrics: Snapshot of current queue state.
            now:     Current timestamp.  Defaults to ``self._clock()``.

        Returns:
            A :class:`QueueSupervisorDecision` describing all detections.
        """
        ts = now if now is not None else self._clock()
        cfg = self.config
        decision = QueueSupervisorDecision()

        # Step 2: Identify stuck jobs
        stuck_events = self._detect_stuck_jobs(metrics, cfg, ts)
        decision.stuck_jobs = stuck_events

        # Track stuck job count across cycles (reset each cycle)
        self._stuck_job_count = len(stuck_events)

        # Step 4: Evaluate backpressure conditions
        backpressure_events, bp_detected = self._detect_backpressure(
            metrics, cfg, ts
        )
        decision.backpressure_events = backpressure_events
        decision.has_backpressure = bp_detected

        # Track consecutive backpressure intervals
        if bp_detected:
            self._backpressure_count += 1
        else:
            self._backpressure_count = 0
        decision.consecutive_backpressure_intervals = self._backpressure_count

        # Step 6: Check escalation thresholds
        decision.escalations = self._check_escalation(metrics, cfg, ts)

        decision.queue_length = metrics.queue_length
        decision.avg_job_age_ms = _avg_age_ms(metrics.queued_jobs)

        return decision

    def reset(self) -> None:
        """Reset internal state (backpressure counter, stuck counter)."""
        self._backpressure_count = 0
        self._stuck_job_count = 0

    @property
    def backpressure_count(self) -> int:
        """Return the number of consecutive backpressure intervals."""
        return self._backpressure_count

    @property
    def stuck_job_count(self) -> int:
        """Return the number of stuck jobs in the last cycle."""
        return self._stuck_job_count

    # ------------------------------------------------------------------
    # Internal — Stuck job detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_stuck_jobs(
        metrics: QueueMetrics,
        cfg: QueueSupervisorConfig,
        ts: float,
    ) -> list[StuckJobEvent]:
        """Identify stuck jobs from queue metrics.

        A job is stuck if (spec §2):
            - in-flight longer than *max_processing_time_ms*
            - OR queued longer than *max_queue_age_ms*
            - OR in-flight but no ack within *ack_timeout_ms*

        Args:
            metrics: Current queue snapshot.
            cfg:     Supervisor configuration.
            ts:      Current timestamp for event emission.

        Returns:
            A list of :class:`StuckJobEvent`.
        """
        events: list[StuckJobEvent] = []
        iso_ts = _iso_timestamp(ts)

        # Check queued jobs
        for job_id, age_s in metrics.queued_jobs:
            age_ms = age_s * 1000.0
            if age_ms > cfg.max_queue_age_ms:
                events.append(StuckJobEvent(
                    job_id=job_id,
                    state=STUCK_STATE_QUEUED,
                    age_ms=age_ms,
                    timeout_ms=cfg.max_queue_age_ms,
                    timestamp=iso_ts,
                ))

        # Check in-flight jobs
        for job_id, age_s in metrics.in_flight_jobs:
            age_ms = age_s * 1000.0
            if age_ms > cfg.max_processing_time_ms:
                events.append(StuckJobEvent(
                    job_id=job_id,
                    state=STUCK_STATE_PROCESSING,
                    age_ms=age_ms,
                    timeout_ms=cfg.max_processing_time_ms,
                    timestamp=iso_ts,
                ))
            elif age_ms > cfg.ack_timeout_ms:
                # In-flight but no ack within expected window
                events.append(StuckJobEvent(
                    job_id=job_id,
                    state=STUCK_STATE_PROCESSING,
                    age_ms=age_ms,
                    timeout_ms=cfg.ack_timeout_ms,
                    timestamp=iso_ts,
                ))

        return events

    # ------------------------------------------------------------------
    # Internal — Backpressure detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_backpressure(
        metrics: QueueMetrics,
        cfg: QueueSupervisorConfig,
        ts: float,
    ) -> tuple[list[QueueBackpressureEvent], bool]:
        """Evaluate backpressure conditions.

        Backpressure occurs when (spec §3):
            - queue length exceeds threshold
            - average job age exceeds threshold
            - enqueue rate exceeds dequeue rate by ratio threshold

        Args:
            metrics: Current queue snapshot.
            cfg:     Supervisor configuration.
            ts:      Current timestamp for event emission.

        Returns:
            A tuple of ``(events, detected)`` where *detected* is ``True``
            if any backpressure condition was triggered.
        """
        events: list[QueueBackpressureEvent] = []
        avg_age = _avg_age_ms(metrics.queued_jobs)
        iso_ts = _iso_timestamp(ts)

        detected = False

        # Condition 1: Queue length exceeds threshold
        if metrics.queue_length > cfg.backpressure_queue_length_threshold:
            detected = True

        # Condition 2: Average job age exceeds threshold
        if avg_age > cfg.backpressure_avg_age_ms:
            detected = True

        # Condition 3: Enqueue rate exceeds dequeue rate
        if (
            metrics.enqueue_rate > 0.0
            and metrics.dequeue_rate > 0.0
            and metrics.enqueue_rate / metrics.dequeue_rate
            > cfg.backpressure_enqueue_dequeue_ratio
        ):
            detected = True

        if detected:
            events.append(QueueBackpressureEvent(
                queue_length=metrics.queue_length,
                avg_job_age_ms=avg_age,
                enqueue_rate=metrics.enqueue_rate,
                dequeue_rate=metrics.dequeue_rate,
                timestamp=iso_ts,
            ))

        return events, detected

    # ------------------------------------------------------------------
    # Internal — Escalation checks
    # ------------------------------------------------------------------

    def _check_escalation(
        self,
        metrics: QueueMetrics,
        cfg: QueueSupervisorConfig,
        ts: float,
    ) -> list[QueueSupervisorEscalation]:
        """Check escalation thresholds and return any escalation events.

        Escalate to the S4 Control Plane if (spec §5):
            - stuck jobs exceed threshold
            - backpressure persists for N consecutive intervals
            - queue length exceeds critical threshold
            - job age exceeds critical threshold

        Args:
            metrics: Current queue snapshot.
            cfg:     Supervisor configuration.
            ts:      Current timestamp.

        Returns:
            A list of :class:`QueueSupervisorEscalation` events.
        """
        escalations: list[QueueSupervisorEscalation] = []
        iso_ts = _iso_timestamp(ts)
        avg_age = _avg_age_ms(metrics.queued_jobs)

        # Threshold 1: Stuck jobs exceed threshold
        if self._stuck_job_count > cfg.critical_stuck_job_threshold:
            escalations.append(QueueSupervisorEscalation(
                reason=(
                    f"Stuck job threshold exceeded: "
                    f"{self._stuck_job_count} stuck jobs "
                    f"(max {cfg.critical_stuck_job_threshold})"
                ),
                timestamp=iso_ts,
            ))

        # Threshold 2: Backpressure persists for N consecutive intervals
        if (
            self._backpressure_count > 0
            and self._backpressure_count >= cfg.backpressure_consecutive_intervals
        ):
            escalations.append(QueueSupervisorEscalation(
                reason=(
                    f"Backpressure persisted for "
                    f"{self._backpressure_count} consecutive intervals "
                    f"(threshold {cfg.backpressure_consecutive_intervals})"
                ),
                timestamp=iso_ts,
            ))

        # Threshold 3: Queue length exceeds critical threshold
        if metrics.queue_length > cfg.critical_queue_length:
            escalations.append(QueueSupervisorEscalation(
                reason=(
                    f"Critical queue length: "
                    f"{metrics.queue_length} jobs "
                    f"(max {cfg.critical_queue_length})"
                ),
                timestamp=iso_ts,
            ))

        # Threshold 4: Job age exceeds critical threshold
        for job_id, age_s in metrics.queued_jobs:
            age_ms = age_s * 1000.0
            if age_ms > cfg.critical_job_age_ms:
                escalations.append(QueueSupervisorEscalation(
                    reason=(
                        f"Critical job age: job {job_id} "
                        f"age {age_ms:.0f}ms "
                        f"(max {cfg.critical_job_age_ms:.0f}ms)"
                    ),
                    timestamp=iso_ts,
                ))
                break  # One escalation per cycle for this condition

        return escalations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso_timestamp(ts: float) -> str:
    """Convert a Unix timestamp to an ISO-8601 string.

    Args:
        ts: Unix timestamp in seconds.

    Returns:
        ISO-8601 formatted string (UTC).
    """
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _avg_age_ms(jobs: list[tuple[str, float]]) -> float:
    """Compute the average age of a list of (job_id, age_seconds) tuples.

    Args:
        jobs: List of ``(job_id, age_seconds)`` entries.

    Returns:
        Average age in milliseconds, or ``0.0`` if the list is empty.
    """
    if not jobs:
        return 0.0
    total = sum(age_s for _, age_s in jobs)
    return (total / len(jobs)) * 1000.0
