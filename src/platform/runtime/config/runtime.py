"""Runtime-level configuration dataclasses.

Configurations are grouped by subsystem.  Each dataclass maps to a
specific factory or backend, keeping the runtime DI chain explicit.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.platform.runtime.scheduling.policy import SchedulingMode
from src.platform.runtime.worker_pool.isolation import IsolationMode


@dataclass
class RuntimeConcurrencyConfig:
    """Top-level concurrency configuration for the Stratum-4 runtime.

    Attributes:
        isolation: Concurrency backend (threads or processes).
        concurrency: Number of workers to spawn.
        tick_interval: Sleep gap (seconds) between handler invocations
            when no work is available.
    """

    isolation: IsolationMode = IsolationMode.THREADS
    concurrency: int = 1
    tick_interval: float = 0.05


@dataclass
class SchedulingConfig:
    """Configuration for the job scheduling layer.

    Attributes:
        scheduling_mode: The policy to use when selecting the next job.
    """

    scheduling_mode: SchedulingMode = SchedulingMode.FIFO


@dataclass
class HeartbeatConfig:
    """Configuration for the heartbeat subsystem.

    Attributes:
        interval_seconds: How often each worker emits a heartbeat.
        timeout_seconds: Maximum age before a worker is considered unhealthy.
    """

    interval_seconds: float = 1.0
    timeout_seconds: float = 5.0


@dataclass
class PersistenceConfig:
    """Configuration for the persistence (JobStore) backend.

    Attributes:
        backend:     Persistence implementation — ``"memory"`` or ``"sqlite"``.
        sqlite_path: Path to the SQLite database file (only used when
                     ``backend="sqlite"``).
    """

    backend: str = "memory"
    sqlite_path: str = "vai_jobs.db"
