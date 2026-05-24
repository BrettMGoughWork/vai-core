from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time

from src.core.types.hashing import stable_hash
from src.core.types.json_pure import ensure_json_pure


@dataclass(frozen=True)
class PlanSegment:
    segment_id: str
    subgoal_id: str
    steps: List[str] # list of step_ids
    context: Dict[str, Any]
    metadata: Dict[str, Any]
    parent_segment_id: Optional[str] = None
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    canonical_hash: str = field(init=False)

    def __post_init__(self):
        ensure_json_pure(self.context)
        ensure_json_pure(self.metadata)

        object.__setattr__(
            self,
            "canonical_hash",
            stable_hash(
                {
                    "segment_id": self.segment_id,
                    "subgoal_id": self.subgoal_id,
                    "steps": self.steps,
                    "context": self.context,
                    "metadata": self.metadata,
                    "parent_segment_id": self.parent_segment_id,
                    "created_at": self.created_at,
                }
            ),
        )