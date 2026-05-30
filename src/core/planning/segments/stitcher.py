from __future__ import annotations

from typing import List

from src.core.planning.models.plan_segment import PlanSegment
from src.core.planning.segments.errors import SegmentStitchingError


class SegmentStitcher:
    """
    Pure deterministic stitching engine for PlanSegments.

    Responsibilities:
    - Sort segments deterministically
    - Ensure all segments belong to the same subgoal
    - Ensure continuous, gap-free, overlap-free numeric step sequences
    - Return a stitched, ordered chain
    """

    # ------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------
    def stitch(self, segments: List[PlanSegment]) -> List[PlanSegment]:
        if not segments:
            return []

        # 1. Ensure all segments share the same subgoal_id
        subgoal_ids = {s.subgoal_id for s in segments}
        if len(subgoal_ids) != 1:
            raise SegmentStitchingError(
                f"Segments belong to multiple subgoals: {subgoal_ids}"
            )

        # 2. Deterministic ordering: created_at, then canonical_hash
        ordered = sorted(
            segments,
            key=lambda s: (s.created_at, s.canonical_hash),
        )

        # 3. Validate continuous numeric step chain
        self._validate_step_chain(ordered)

        return ordered

    # ------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------
    def _to_int(self, step_id: str) -> int:
        """
        Convert a step_id string to an integer.
        Raises SegmentStitchingError if conversion fails.
        """
        try:
            return int(step_id)
        except Exception:
            raise SegmentStitchingError(f"Step ID is not numeric: {step_id}")

    def _validate_step_chain(self, segments: List[PlanSegment]) -> None:
        """
        Ensures segments form a continuous, gap-free, overlap-free numeric chain.
        """

        # Convert each segment's step range into numeric tuples
        ranges = []
        for seg in segments:
            start = self._to_int(seg.steps[0])
            end = self._to_int(seg.steps[-1])
            ranges.append((start, end, seg.segment_id))

        # Check for overlaps or gaps
        for i in range(len(ranges) - 1):
            start_a, end_a, id_a = ranges[i]
            start_b, end_b, id_b = ranges[i + 1]

            # Overlap
            if start_b <= end_a:
                raise SegmentStitchingError(
                    f"Overlapping segments: {id_a} ({start_a}-{end_a}) "
                    f"and {id_b} ({start_b}-{end_b})"
                )

            # Gap
            if start_b != end_a + 1:
                raise SegmentStitchingError(
                    f"Gap between segments: {id_a} ends at {end_a}, "
                    f"but {id_b} starts at {start_b}"
                )