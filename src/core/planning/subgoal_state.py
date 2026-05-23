from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from src.core.types.validation import validate_pure_structure
from src.core.types.hashing import stable_hash
from src.core.types.errors import ValidationError


@dataclass(frozen=True)
class SubgoalState:
    """
    Minimal structural representation of a subgoal.
    Pure, deterministic, JSON-serialisable.
    """

    subgoal_id: str
    parent_id: Optional[str] = None
    goal: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    canonical_hash: str = ""

    def __post_init__(self):
        try:
            validate_pure_structure(self.context)
            validate_pure_structure(self.metadata)
        except Exception as e:
            raise ValidationError(f"SubgoalState is not pure: {e}")

        object.__setattr__(
            self,
            "canonical_hash",
            stable_hash({
                "subgoal_id": self.subgoal_id,
                "parent_id": self.parent_id,
                "goal": self.goal,
                "context": self.context,
                "metadata": self.metadata,
            }),
        )