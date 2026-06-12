"""Job store factory — Stratum-4 runtime.

Provides ``JobStoreConfig`` for configuring the persistence backend
and ``create_job_store()`` to materialise the appropriate implementation.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.platform.runtime.job_store.job_store import InMemoryJobStore, JobStore


@dataclass
class JobStoreConfig:
    """Configuration for the Stratum-4 persistence backend.

    Attributes:
        backend:        Persistence implementation — ``"memory"`` or ``"sqlite"``.
        sqlite_path:    Path to the SQLite database file (only used when
                        ``backend="sqlite"``).
    """

    backend: str = "memory"
    sqlite_path: str = "vai_jobs.db"


def create_job_store(config: JobStoreConfig | None = None) -> JobStore:
    """Build and return a ``JobStore`` implementation based on *config*.

    Args:
        config:  Persistence configuration.  Falls back to
                 ``JobStoreConfig(backend="memory")`` when ``None``.

    Returns:
        An ``InMemoryJobStore`` or ``SqliteJobStore`` instance.

    Raises:
        ValueError:  If ``config.backend`` is not a recognised value.
    """
    if config is None:
        config = JobStoreConfig()

    if config.backend == "memory":
        return InMemoryJobStore()
    if config.backend == "sqlite":
        from src.platform.runtime.job_store.backends.sqlite_job_store import (
            SqliteJobStore,
        )

        return SqliteJobStore(db_path=config.sqlite_path)

    msg = f"Unknown job store backend: {config.backend!r} (expected 'memory' or 'sqlite')"
    raise ValueError(msg)
