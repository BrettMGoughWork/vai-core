"""Job store package for Stratum-4 runtime.

Provides an abstract ``JobStore`` interface, an ``InMemoryJobStore`` for
dev/testing, a ``SqliteJobStore`` for development, and a factory to
materialise the configured backend.
"""

from src.platform.runtime.job_store.backends.sqlite_job_store import SqliteJobStore
from src.platform.runtime.job_store.factory import JobStoreConfig, create_job_store
from src.platform.runtime.job_store.job_store import InMemoryJobStore, JobStore
from src.platform.runtime.job_store.job_store import _default_store as job_store

__all__ = [
    "InMemoryJobStore",
    "JobStore",
    "JobStoreConfig",
    "SqliteJobStore",
    "create_job_store",
    "job_store",
]
