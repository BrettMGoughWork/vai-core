"""S4 event logging — Stratum-4 observability.

Minimal, side‑effect free (except stdout) logging functions that emit
stable, parseable lines at key job lifecycle points.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.platform.runtime.job import Job


def _log(event: str, job: Job) -> None:
    """Print a single structured log line to stdout."""
    ts = datetime.now(timezone.utc).isoformat()
    print(f"[S4] {ts} EVENT {event} job_id={job.job_id}", flush=True)


def log_job_created(job: Job) -> None:
    """Emit when a job is created and enqueued."""
    _log("job_created", job)


def log_job_started(job: Job) -> None:
    """Emit when a worker picks up a job for execution."""
    _log("job_started", job)


def log_job_finished(job: Job) -> None:
    """Emit when a worker finishes executing a job."""
    _log("job_finished", job)
