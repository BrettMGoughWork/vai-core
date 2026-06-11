from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class LoopMetrics:
    """
    Pure loop metrics container (Stratum 2).

    Uses logical time from StepState.created_at, not wall clock.
    """
    step_count: int = 0
    start_created_at: Optional[int] = None
    end_created_at: Optional[int] = None
    termination_reason: str = "not_terminated"
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> int:
        if self.start_created_at is None or self.end_created_at is None:
            return 0
        return self.end_created_at - self.start_created_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_count": self.step_count,
            "start_created_at": self.start_created_at,
            "end_created_at": self.end_created_at,
            "duration": self.duration,
            "termination_reason": self.termination_reason,
            "extra": self.extra,
        }