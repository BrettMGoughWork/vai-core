from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict

from src.strategy.types.cognitive_step_outcome import CognitiveStepOutcome
from src.strategy.planning.safety.purity_validation import validate_pure_structure
from src.strategy.types.errors import ValidationError
from src.agent.memory.types.hashing import stable_hash


@dataclass(frozen=True)
class StepResult:
    @staticmethod
    def failure(reason: str, payload: dict | None = None, trace: list | None = None) -> 'StepResult':
        return StepResult(
            outcome=CognitiveStepOutcome.FAILURE,
            reason=reason,
            payload=payload if payload is not None else {},
            trace=trace if trace is not None else [],
        )

    """
    Pure cognitive output of a single reasoning step.
    Stratum‑2 invariant: immutable, deterministic, serialisable.
    """

    outcome: CognitiveStepOutcome
    reason: str
    payload: Dict[str, Any] = field(default_factory=dict)
    trace: Dict[str, Any] = field(default_factory=dict)

    # Deterministic identity hash
    canonical_hash: str = field(init=False)

    def __post_init__(self):
        # Determinism invariants
        assert isinstance(self.reason, str), "reason must be deterministic text"
        assert self.outcome in CognitiveStepOutcome, "invalid outcome enum"

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