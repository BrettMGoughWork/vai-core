from __future__ import annotations

from typing import Dict, List, Optional

from src.core.planning.segments.errors import SegmentNotFoundError
from src.core.types.plan_segment import PlanSegment


class SegmentState:
    """
    Deterministic in-memory store for PlanSegments.

    Responsibilities:
    - Store segments by segment_id
    - Provide lookup/update/insert operations
    - Maintain a chronological JSON-pure event log
    - Provide helpers for stitching (e.g., list by subgoal)
    """

    def __init__(self):
        # segment_id -> PlanSegment
        self._segments: Dict[str, PlanSegment] = {}

        # chronological JSON-pure event log
        self._events: List[dict] = []

    # ------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------
    def insert(self, segment: PlanSegment) -> None:
        self._segments[segment.segment_id] = segment

    def update(self, segment: PlanSegment) -> None:
        if segment.segment_id not in self._segments:
            raise SegmentNotFoundError(segment.segment_id)
        self._segments[segment.segment_id] = segment

    def get(self, segment_id: str) -> Optional[PlanSegment]:
        return self._segments.get(segment_id)

    # ------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------
    def list_for_subgoal(self, subgoal_id: str) -> List[PlanSegment]:
        """
        Returns all segments belonging to a given subgoal_id.
        Order is undefined; stitching logic will sort deterministically.
        """
        return [
            seg for seg in self._segments.values()
            if seg.subgoal_id == subgoal_id
        ]

    def all_segments(self) -> List[PlanSegment]:
        return list(self._segments.values())

    # ------------------------------------------------------------
    # Event log
    # ------------------------------------------------------------
    def record_event(self, event: dict) -> None:
        """
        Events must be JSON-pure dicts.
        """
        self._events.append(event)

    def events(self) -> List[dict]:
        return list(self._events)