from __future__ import annotations

from typing import List, Optional

from src.strategy.types.plan_segment import PlanSegment
from src.strategy.planning.segments.state import SegmentState
from src.strategy.planning.validators.plan_segment_validator import PlanSegmentValidator as SegmentValidator
from src.strategy.planning.segments.stitcher import SegmentStitcher
from src.strategy.planning.segments.events import (
    SegmentCreatedEvent,
    SegmentStitchedEvent,
)
from src.strategy.planning.segments.errors import (
    SegmentValidationError,
    SegmentStitchingError,
)


class PlanSegmentManager:
    """
    Governance layer for PlanSegments.

    Responsibilities:
    - Create segments
    - Validate segments
    - Stitch segments into deterministic chains
    - Emit JSON-pure events
    - Update SegmentState
    """

    def __init__(
        self,
        state: SegmentState,
        validator: Optional[SegmentValidator] = None,
        stitcher: Optional[SegmentStitcher] = None,
    ):
        self._state = state
        self._validator = validator or SegmentValidator()
        self._stitcher = stitcher or SegmentStitcher()

    # ------------------------------------------------------------
    # Segment creation
    # ------------------------------------------------------------
    def create_segment(
        self,
        subgoal_id: str,
        steps: List[str],
        context: Optional[dict] = None,
        metadata: Optional[dict] = None,
        skills: Optional[List[str]] = None,
        created_at: Optional[str] = None,
    ) -> PlanSegment:
        
        if not steps:
            raise SegmentValidationError("steps must be non-empty")

        segment = PlanSegment(
            subgoal_id=subgoal_id,
            steps=steps,
            context=context or {},
            metadata=metadata or {},
            skills=skills or [],
            created_at=created_at or "",
        )

        # Structural validation
        if not self._validator.validate(segment):
            raise SegmentValidationError(f"Invalid segment: {segment.segment_id}")

        # Insert into state
        self._state.insert(segment)

        # Emit event
        self._state.record_event(SegmentCreatedEvent.from_segment(segment))

        return segment

    # ------------------------------------------------------------
    # Segment validation
    # ------------------------------------------------------------
    def validate(self, segment: PlanSegment) -> None:
        if not self._validator.validate(segment):
            raise SegmentValidationError(f"Invalid segment: {segment.segment_id}")

    # ------------------------------------------------------------
    # Segment stitching
    # ------------------------------------------------------------
    def stitch(self, segments: List[PlanSegment]) -> List[PlanSegment]:
        """
        Returns a deterministic stitched chain of segments.
        Raises SegmentStitchingError on invalid chains.
        """

        try:
            chain = self._stitcher.stitch(segments)
        except SegmentStitchingError:
            raise
        except Exception as e:
            raise SegmentStitchingError(str(e))

        # Emit event
        self._state.record_event(SegmentStitchedEvent.from_chain(chain))

        return chain