from __future__ import annotations
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any, Dict, Optional
from src.core.types.validation import validate_pure_structure
from src.core.types.errors import ValidationError
from src.core.types.hashing import stable_hash


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass(frozen=True)
class StepState:
    """
    Pure cognitive state for a single reasoning step.
    Stratum‑2 invariant: immutable, deterministic, serialisable.
    """

    # --- Identity ---
    step_id: str
    parent_id: Optional[str] = None # previous step or segment

    # --- Inputs ---
    cognitive_input: Dict[str, Any] = field(default_factory=dict)
    last_result: Optional[Dict[str, Any]] = None # previous StepResult (pure)

    # --- Lifecycle ---
    status: StepStatus = StepStatus.PENDING

    # --- Metadata ---
    created_at: int = 0 # logical timestamp, not wall‑clock
    attempt: int = 0 # retry counter (pure, no side effects)
    trace: Dict[str, Any] = field(default_factory=dict)

    # --- Canonical hash ---
    canonical_hash: str = ""

    def __post_init__(self):
        # Validate purity
        try:
            validate_pure_structure(self.cognitive_input)
            validate_pure_structure(self.last_result)
            validate_pure_structure(self.trace)
        except Exception as e:
            raise ValidationError(f"StepState is not pure: {e}")

        # Compute canonical hash
        object.__setattr__(self, "canonical_hash", stable_hash({
            "step_id": self.step_id,
            "parent_id": self.parent_id,
            "cognitive_input": self.cognitive_input,
            "last_result": self.last_result,
            "status": self.status.value,
            "attempt": self.attempt,
            "created_at": self.created_at,
        }))

    def replace(self, **changes) -> StepState:
        # Helper for creating modified copies of StepState (since it's frozen)
        data = {field.name: getattr(self, field.name) for field in fields(self)}
        data.update(changes)
        return StepState(**data)