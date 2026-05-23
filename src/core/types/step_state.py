from __future__ import annotations
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any, Dict, List, Optional
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

    Determinism Invariants (Stratum 2):
    D1 - Input-Output Determinism
        Identical cognitive_input + identical configuration => identical StepState/StepResult sequences.

    D2 - Purity
        All structures must be JSON-pure (dict/list/scalar), validated via validate_pure_structure
    
    D3 - No hidden entropy
        No wall-clock time, randomness, environment state, or non-canonical ordering.
        created_at is logical time, not wall-clock.
        canonical_hash depends solely on cognitive_input
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
    trace: List[Any] = field(default_factory=list) # optional, pure JSON-serialisable trace of the step's execution

    # --- Canonical hash ---
    canonical_hash: str = ""

    def __post_init__(self):
        # Determinism invariants
        assert isinstance(self.created_at, int), "created_at must be logical time (int)"
        assert self.created_at >= 0, "created_at cannot be negative"
        assert self.status in StepStatus, "invalid status enum"

        # Purity
        try:
            validate_pure_structure(self.cognitive_input)
            validate_pure_structure(self.last_result)
            validate_pure_structure(self.trace)
        except Exception as e:
            raise ValidationError(f"StepState is not pure: {e}")

        # Canonical hash depends ONLY on cognitive_input
        object.__setattr__(
            self,
            "canonical_hash",
            stable_hash(self.cognitive_input),
        )

    def replace(self, **changes) -> StepState:
        # Helper for creating modified copies of StepState (since it's frozen)
        data = {field.name: getattr(self, field.name) for field in fields(self)}
        data.update(changes)
        return StepState(**data)