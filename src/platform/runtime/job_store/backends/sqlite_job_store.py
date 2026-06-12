"""SQLite job store backend — Stratum-4 runtime.

Persists ``Job`` instances as JSON blobs in a local SQLite database.
Zero external dependencies (SQLite is part of the Python standard library).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing

from src.platform.runtime.job import Job
from src.platform.runtime.job_store.job_store import JobStore


class SqliteJobStore(JobStore):
    """SQLite-backed job store.

    Schema::

        CREATE TABLE IF NOT EXISTS jobs (
            job_id     TEXT PRIMARY KEY,
            data       TEXT NOT NULL,
            created_at TEXT
        )

    The ``data`` column stores ``Job.model_dump_json()`` and is deserialised
    via ``Job.model_validate_json()`` on read.

    Args:
        db_path: Path to the SQLite database file.  Use ``":memory:"`` for
            an in-memory database (useful for testing).
    """

    def __init__(self, db_path: str = "vai_jobs.db") -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        """Lazy-initialised connection (keeps the store lightweight)."""
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
            self._migrate()
        return self._conn

    def close(self) -> None:
        """Close the underlying database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _migrate(self) -> None:
        """Ensure the schema exists."""
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id     TEXT PRIMARY KEY,
                data       TEXT NOT NULL,
                created_at TEXT
            )
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # JobStore interface
    # ------------------------------------------------------------------

    def save(self, job: Job) -> None:
        """Persist *job*, overwriting any existing entry with the same id."""
        self.conn.execute(
            "INSERT OR REPLACE INTO jobs (job_id, data, created_at) VALUES (?, ?, ?)",
            (job.job_id, job.model_dump_json(), job.created_at.isoformat()),
        )
        self.conn.commit()

    def get(self, job_id: str) -> Job | None:
        """Retrieve a job by ``job_id``, or ``None`` if not found."""
        row = self.conn.execute(
            "SELECT data FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            return None
        return Job.model_validate_json(row["data"])

    def list(self) -> list[dict]:
        """Return metadata for all known jobs."""
        rows = self.conn.execute(
            "SELECT job_id, created_at FROM jobs ORDER BY created_at"
        ).fetchall()
        return [{"job_id": row["job_id"], "created_at": row["created_at"]} for row in rows]

    def delete(self, job_id: str) -> None:
        """Remove a job by ``job_id`` (no-op if missing)."""
        self.conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
        self.conn.commit()

    def __len__(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS cnt FROM jobs").fetchone()
        return row["cnt"]
