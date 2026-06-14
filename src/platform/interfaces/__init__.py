"""
Platform Stratum — Integration Interfaces
==========================================

Canonical re-exports of the Platform stratum's contracts.

The Platform stratum owns:
- Channel message types (ingress transport)
- Job, queue, and worker types
- Execution safety types (degraded-mode, circuit-breaker)
"""

from __future__ import annotations

# ── Transport / Channel Messages ──────────────────────────────────────────

from src.platform.transport.normalization import (
    ChannelMessage as ChannelMessage,
)

# ── Job / Queue Types ─────────────────────────────────────────────────────

from src.platform.runtime.job import (
    Job as Job,
)

from src.platform.runtime.job_state import (
    JobState as JobState,
)

from src.platform.queue.queue import (
    Queue as Queue,
)

from src.platform.runtime.worker import (
    Worker as Worker,
)

# ── Job Submission (S5 → S4 boundary) ─────────────────────────────────...

from src.platform.runtime.job_submission import (
    submit_job as submit_job,
)

# ── Execution Safety ──────────────────────────────────────────────────────

from src.platform.runtime.safety.degraded_mode import (
    DegradedMode as DegradedMode,
    default_degraded_mode as default_degraded_mode,
)

__all__ = [
    "ChannelMessage",
    "Job",
    "JobState",
    "Queue",
    "Worker",
    "submit_job",
    "DegradedMode",
    "default_degraded_mode",
]
