from __future__ import annotations
from typing import Any, Dict

from src.core.types.step_result import StepResult
from src.core.planning.safety.purity_validation import validate_pure_structure
from src.core.types.errors import ValidationError
from src.core.types.errors.AgentError import ConfidenceError
from src.core.state.outcome import StepOutcome

# Canonical Stratum‑2 priority order
# Highest → lowest
OUTCOME_PRIORITY = [
    StepOutcome.FATAL, # unrecoverable
    StepOutcome.RECOVERABLE, # tool_needed / retryable
    StepOutcome.SUCCESS, # terminal success
    StepOutcome.NOOP, # continue reasoning
]


class OutcomeClassifier:
    """
    Deterministic Stratum‑2 classifier.
    Converts Stratum‑1 classifier output into a StepResult.
    """

    def classify(self, state, raw: Dict[str, Any]) -> StepResult:
        # D2: purity validation
        try:
            validate_pure_structure(raw)
        except Exception as e:
            err = ValidationError(f"Classifier output not pure: {e}")
            return StepResult(
                outcome=StepOutcome.FATAL,
                reason=str(err),
                payload={"error": err.__dict__},
                trace={},
            )

        # Extract fields
        label_raw = raw.get("label")
        reason = raw.get("reason") or "No reason provided by classifier"
        metadata = raw.get("metadata") or {}

        # Normalise label
        label = None
        if isinstance(label_raw, str):
            label = label_raw.strip().lower()

        # Stratum‑1 → Stratum‑2 mapping
        mapping = {
            "success": StepOutcome.SUCCESS,
            "failure": StepOutcome.FATAL,
            "tool_needed": StepOutcome.RECOVERABLE,
            "continue": StepOutcome.NOOP,
        }

        outcome = mapping.get(label)

        # Deterministic fallback for unknown/missing labels
        if outcome is None:
            err = ConfidenceError(
                "Unknown classifier label",
                details={
                    "step_id": getattr(state, "step_id", None),
                    "label": label_raw,
                    "raw_classifier": raw,
                },
            )
            return StepResult(
                outcome=OUTCOME_PRIORITY[0], # FATAL
                reason=err.message,
                payload={"error": err.to_dict()},
                trace={},
            )

        # Normal case
        return StepResult(
            outcome=outcome,
            reason=reason,
            payload=metadata,
            trace={},
        )