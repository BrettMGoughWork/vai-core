from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from src.core.types.validation import validate_pure_structure
from src.core.types.hashing import stable_hash
from src.core.types.errors import ValidationError


@dataclass(frozen=True)
class SegmentState:
    """
    Minimal structural representation of a reasoning segment.
    Pure, deterministic, JSON-serialisable.
    """

    segment_id: str
    parent_id: Optional[str] = None
    steps: List[Dict[str, Any]] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    canonical_hash: str = ""

    def __post_init__(self):
        try:
            validate_pure_structure(self.steps)
            validate_pure_structure(self.context)
            validate_pure_structure(self.metadata)
        except Exception as e:
            raise ValidationError(f"SegmentState is not pure: {e}")

        object.__setattr__(
            self,
            "canonical_hash",
            stable_hash({
                "segment_id": self.segment_id,
                "parent_id": self.parent_id,
                "steps": self.steps,
                "context": self.context,
                "metadata": self.metadata,
            }),
        )