from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Any

from src.strategy.types.hashing import stable_hash
from src.strategy.types.json_pure import ensure_json_pure


@dataclass(frozen=True)
class PlanSegment:
    subgoal_id: str
    steps: List[str]

    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    skills: List[str] = field(default_factory=list)

    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
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
            "skills": self.skills,
        }
        return stable_hash(payload)

    def _compute_canonical_hash(self) -> str:
        payload = {
            "subgoal_id": self.subgoal_id,
            "steps": self.steps,
            "skills": self.skills,
            "context": self.context,
            "metadata": self.metadata,
        }
        return stable_hash(payload)

    @property
    def id(self) -> str:
        return self.segment_id