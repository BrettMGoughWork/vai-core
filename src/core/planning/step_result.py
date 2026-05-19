from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional
from core.types.validation import validate_pure_structure
from core.types.errors import ValidationError


class StepOutcome(Enum):
    SUCCESS = "success" # cognitive step completed
    FAILURE = "failure" # cognitive step failed
    TOOL_NEEDED = "tool_needed" # requires Stratum 1 execution
    CONTINUE = "continue" # continue reasoning (no tool)


@dataclass(frozen=True)
class StepResult:
    """
    Pure cognitive output of a single reasoning step.
    Stratum‑2 invariant: immutable, deterministic, serialisable.
    """

    outcome: StepOutcome
    reason: str # human-readable explanation (pure)
    payload: Dict[str, Any] = field(default_factory=dict) # structured output
    trace: Dict[str, Any] = field(default_factory=dict) # cognitive trace additions

    def __post_init__(self):
        try:
            validate_pure_structure(self.payload)
            validate_pure_structure(self.trace)
        except Exception as e:
            raise ValidationError(f"StepResult is not pure: {e}")