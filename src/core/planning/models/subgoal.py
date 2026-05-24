from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import time

from src.core.types.hashing import stable_hash
from src.core.types.json_pure import ensure_json_pure


@dataclass(frozen=True)
class Subgoal:
    subgoal_id: str
    goal: str
    context: Dict[str, Any]
    metadata: Dict[str, Any]
    parent_id: Optional[str] = None
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    canonical_hash: str = field(init=False)

    def __post_init__(self):
        # JSON purity enforcement
        ensure_json_pure(self.context)
        ensure_json_pure(self.metadata)

        # Compute canonical hash
        object.__setattr__(
            self,
            "canonical_hash",
            stable_hash(
                {
                    "subgoal_id": self.subgoal_id,
                    "goal": self.goal,
                    "context": self.context,
                    "metadata": self.metadata,
                    "parent_id": self.parent_id,
                    "created_at": self.created_at,
                }
            ),
        )