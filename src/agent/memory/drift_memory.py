from __future__ import annotations

from collections import deque
from typing import List, Optional

from src.agent.memory.drift_memory_types import DriftEvent, DriftMemorySnapshot


class DriftMemory:
    """
    Pure, deterministic bounded ring buffer for DriftEvent objects.

    Ephemeral — intended to live only for the duration of a single plan.
    When capacity is exceeded the oldest event is dropped automatically.
    No I/O, no side effects, no external state.
    """

    DEFAULT_CAPACITY = 20

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        if capacity <= 0:
            raise ValueError(f"capacity must be > 0, got {capacity}")
        self._capacity = capacity
        self._buffer: deque[DriftEvent] = deque(maxlen=capacity)

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def record(self, event: DriftEvent) -> None:
        """Append event to the buffer. Drops the oldest event when capacity is exceeded."""
        self._buffer.append(event)

    def recent(self, n: int) -> List[DriftEvent]:
        """
        Return the n most recent events, oldest-first within the window.
        Returns an empty list if n <= 0.
        """
        if n <= 0:
            return []
        events = list(self._buffer)
        return events[-n:]

    def last(self) -> Optional[DriftEvent]:
        """Return the most recently recorded event, or None if the buffer is empty."""
        return self._buffer[-1] if self._buffer else None

    def clear(self) -> None:
        """Remove all events from the buffer."""
        self._buffer.clear()

    # ------------------------------------------------------------------
    # Filtering helpers
    # ------------------------------------------------------------------

    def filter_by_subgoal(self, subgoal_id: str) -> List[DriftEvent]:
        """Return all buffered events whose subgoal_id matches, oldest-first."""
        return [e for e in self._buffer if e.subgoal_id == subgoal_id]

    def filter_by_signal(self, signal_type: str) -> List[DriftEvent]:
        """Return all buffered events whose signal_type matches, oldest-first."""
        return [e for e in self._buffer if e.signal_type == signal_type]

    def count_recent(self, signal_type: str, window: int) -> int:
        """
        Count events matching signal_type within the most recent `window` events.
        Returns 0 if window <= 0.
        """
        if window <= 0:
            return 0
        events = list(self._buffer)
        recent_events = events[-window:]
        return sum(1 for e in recent_events if e.signal_type == signal_type)

    # ------------------------------------------------------------------
    # Snapshotting
    # ------------------------------------------------------------------

    def snapshot(self) -> DriftMemorySnapshot:
        """Return an immutable snapshot of the current buffer, oldest-first."""
        return DriftMemorySnapshot(events=tuple(self._buffer))

    def load_snapshot(self, snapshot: DriftMemorySnapshot) -> None:
        """
        Replace the current buffer with the contents of a snapshot.

        If the snapshot contains more events than the current capacity,
        only the most recent `capacity` events are loaded (bounded-buffer semantics).
        """
        self._buffer.clear()
        for event in snapshot.events[-self._capacity:]:
            self._buffer.append(event)

    # ------------------------------------------------------------------
    # Bulk removal (used by eviction orchestrator)
    # ------------------------------------------------------------------

    def remove_events(self, events: List[DriftEvent]) -> None:
        """
        Remove specific DriftEvents by matching field values.

        Matching is done on the (timestamp, subgoal_id, segment_id, signal_type)
        tuple, which is the deterministic sort key used by EvictionRules.
        """
        if not events:
            return
        keys_to_remove = {(e.timestamp, e.subgoal_id, e.segment_id, e.signal_type) for e in events}
        self._buffer = deque(
            (e for e in self._buffer if (e.timestamp, e.subgoal_id, e.segment_id, e.signal_type) not in keys_to_remove),
            maxlen=self._capacity,
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def capacity(self) -> int:
        return self._capacity

    def __len__(self) -> int:
        return len(self._buffer)
