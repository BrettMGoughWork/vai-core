from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any

from src.core.types.hashing import stable_hash
from src.core.types.json_pure import ensure_json_pure


@dataclass(frozen=True)
class PlanSegment:
    subgoal_id: str
    steps: List[str]

    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    segment_id: str = field(init=False)
    canonical_hash: str = field(init=False)

    def __post_init__(self):
        # JSON purity only — no structural validation here
        ensure_json_pure(self.context)
        ensure_json_pure(self.metadata)

        object.__setattr__(self, "segment_id", self._compute_segment_id())
        object.__setattr__(self, "canonical_hash", self._compute_canonical_hash())

    def _compute_segment_id(self) -> str:
        payload = {
            "subgoal_id": self.subgoal_id,
            "steps": self.steps,
            "created_at": self.created_at,
        }
        return stable_hash(payload)

    def _compute_canonical_hash(self) -> str:
        payload = {
            "subgoal_id": self.subgoal_id,
            "steps": self.steps,
            "context": self.context,
            "metadata": self.metadata,
        }
        return stable_hash(payload)

    @property
    def id(self) -> str:
        return self.segment_id