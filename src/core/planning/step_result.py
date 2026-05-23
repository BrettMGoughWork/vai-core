from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict

from src.core.types.validation import validate_pure_structure
from src.core.types.errors import ValidationError
from src.core.types.hashing import stable_hash


class StepOutcome(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TOOL_NEEDED = "tool_needed"
    CONTINUE = "continue"


@dataclass(frozen=True)
class StepResult:
    """
    Pure cognitive output of a single reasoning step.
    Stratum‑2 invariant: immutable, deterministic, serialisable.
    """

    outcome: StepOutcome
    reason: str
    payload: Dict[str, Any] = field(default_factory=dict)
    trace: Dict[str, Any] = field(default_factory=dict)

    # Deterministic identity hash
    canonical_hash: str = field(init=False)

    def __post_init__(self):
        # Determinism invariants
        assert isinstance(self.reason, str), "reason must be deterministic text"
        assert self.outcome in StepOutcome, "invalid outcome enum"

        # Purity
        try:
            validate_pure_structure(self.payload)
            validate_pure_structure(self.trace)
        except Exception as e:
            raise ValidationError(f"StepResult is not pure: {e}")

        # Canonical identity depends ONLY on outcome/reason/payload
        identity = {
            "outcome": self.outcome.value,
            "reason": self.reason,
            "payload": self.payload,
        }

        object.__setattr__(
            self,
            "canonical_hash",
            stable_hash(identity),
        )