from __future__ import annotations

from src.core.planning.models.plan_segment import PlanSegment
from src.core.planning.validators.plan_segment_validator import PlanSegmentValidator as _CorePlanSegmentValidator


class SegmentValidator:
    """
    Thin wrapper around the core PlanSegmentValidator.

    Responsibilities:
    - Provide a stable boolean-returning interface for PlanSegmentManager
    - Prevent exceptions from leaking upward
    - Keep Stratum-2 deterministic and JSON-pure
    """

    def __init__(self):
        self._validator = _CorePlanSegmentValidator()

    def validate(self, segment: PlanSegment) -> bool:
        try:
            self._validator.validate(segment)
            return True # SUCCESS: no exception
        except Exception:
            return False # FAILURE