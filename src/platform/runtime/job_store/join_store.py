"""Join store — Stratum-4 runtime.

Abstract interface for ``JoinHandle`` persistence.  No orchestration, no
lifecycle, no control plane — just save, get, list, and delete.

Following the exact same pattern as ``JobStore`` in ``job_store.py``.
"""

from __future__ import annotations

from src.platform.runtime.join_handle import JoinHandle


class JoinStore:
    """Abstract interface for ``JoinHandle`` persistence.

    Implementations must satisfy the following contract:
      - ``save()`` persists or overwrites a join handle by ``join_handle_id``.
      - ``get()`` returns the join handle, or ``None`` if not found.
      - ``list()`` returns metadata for all known join handles.
      - ``delete()`` removes a join handle by ``join_handle_id``.
      - ``__len__()`` returns the number of stored join handles.
    """

    def save(self, handle: JoinHandle) -> None:
        """Persist *handle*, overwriting any existing entry with the same id."""
        raise NotImplementedError

    def get(self, handle_id: str) -> JoinHandle | None:
        """Retrieve a join handle by ``join_handle_id``, or ``None`` if not found."""
        raise NotImplementedError

    def list(self) -> list[dict]:
        """Return metadata for all known join handles.

        Each entry should contain at minimum ``join_handle_id`` and ``created_at``.
        """
        raise NotImplementedError

    def delete(self, handle_id: str) -> None:
        """Remove a join handle by ``join_handle_id``.

        Deleting a non-existent handle is a no-op.
        """
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError
