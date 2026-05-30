from __future__ import annotations

from typing import Dict, Any

from src.core.types.plan_segment import PlanSegment


class SegmentCreatedEvent:
    """
    Pure JSON event emitted when a segment is created.
    """

    @staticmethod
    def from_segment(segment: PlanSegment) -> Dict[str, Any]:
        return {
            "type": "segment_created",
            "segment_id": segment.segment_id,
            "subgoal_id": segment.subgoal_id,
            "steps": segment.steps,
            "context": segment.context,
            "metadata": segment.metadata,
            "created_at": segment.created_at,
            "canonical_hash": segment.canonical_hash,
        }


class SegmentStitchedEvent:
    """
    Pure JSON event emitted when segments are stitched into a chain.
    """

    @staticmethod
    def from_chain(segments: list[PlanSegment]) -> Dict[str, Any]:
        return {
            "type": "segments_stitched",
            "segment_ids": [s.segment_id for s in segments],
            "subgoal_id": segments[0].subgoal_id if segments else None,
            "count": len(segments),
        }
