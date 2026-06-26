"""In-memory join store — Stratum-4 runtime.

In-memory implementation of ``JoinStore`` backed by a plain dict.
Intended as a development / test stand-in for a persistent store.

Following the exact same pattern as ``InMemoryJobStore``.
"""

from __future__ import annotations

import threading

from src.platform.runtime.join_handle import JoinHandle
from src.platform.runtime.job_store.join_store import JoinStore


class InMemoryJoinStore(JoinStore):
    """In-memory join store backed by a plain dict."""

    def __init__(self) -> None:
        self._store: dict[str, JoinHandle] = {}
        self._lock = threading.Lock()

    def save(self, handle: JoinHandle) -> None:
        """Store or overwrite a join handle by its ``join_handle_id``."""
        with self._lock:
            self._store[handle.join_handle_id] = handle

    def get(self, handle_id: str) -> JoinHandle | None:
        """Retrieve a join handle by its ``join_handle_id``, or ``None`` if not found.

        Returns a **deep copy** so callers receive an independent instance.
        """
        with self._lock:
            stored = self._store.get(handle_id)
            if stored is None:
                return None
            return stored.model_copy(deep=True)

    def list(self) -> list[dict]:
        """Return metadata for all known join handles."""
        with self._lock:
            return [
                {"join_handle_id": h.join_handle_id, "created_at": h.created_at.isoformat()}
                for h in self._store.values()
            ]

    def delete(self, handle_id: str) -> None:
        """Remove a join handle by ``join_handle_id`` (no-op if missing)."""
        with self._lock:
            self._store.pop(handle_id, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    # ── Atomic child-record operations ────────────────────────────────

    def record_child_completed(self, handle_id: str, child_job_id: str) -> None:
        """Atomically mark *child_job_id* completed on the join handle."""
        with self._lock:
            handle = self._store.get(handle_id)
            if handle is None:
                return
            handle.mark_child_completed(child_job_id)
            # Save back under the lock — no race window.

    def record_child_failed(self, handle_id: str, child_job_id: str) -> None:
        """Atomically mark *child_job_id* failed on the join handle."""
        with self._lock:
            handle = self._store.get(handle_id)
            if handle is None:
                return
            handle.mark_child_failed(child_job_id)


# module-level singleton so gateway, worker, etc. share one store
_default_join_store = InMemoryJoinStore()
