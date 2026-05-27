from __future__ import annotations
from typing import Any, Dict

from src.core.types.step_result import StepOutcome, StepResult
from src.core.planning.safety.purity_validation import validate_pure_structure
from src.core.types.errors import ValidationError
from src.core.types.errors.AgentError import ConfidenceError


# Deterministic priority order for ambiguous or missing labels
OUTCOME_PRIORITY = [
    StepOutcome.FAILURE,
    StepOutcome.TOOL_NEEDED,
    StepOutcome.SUCCESS,
    StepOutcome.CONTINUE,
]


class OutcomeClassifier:
    """
    Deterministic Stratum‑2 classifier.
    Converts Stratum‑1 classifier output into a StepResult.
    """

    def classify(self, state, raw: Dict[str, Any]) -> StepResult:
        # D2: purity
        try:
            validate_pure_structure(raw)
        except Exception as e:
            err = ValidationError(f"Classifier output not pure: {e}")
            return StepResult(
                outcome=StepOutcome.FAILURE,
                reason=str(err),
                payload={"error": err.__dict__},
                trace={},
            )

        # Extract fields
        label_raw = raw.get("label")
        reason = raw.get("reason") or "No reason provided by classifier"
        metadata = raw.get("metadata") or {}

        # Canonicalise label
        label = None
        if isinstance(label_raw, str):
            label = label_raw.strip().lower()

        # Deterministic mapping
        mapping = {
            "success": StepOutcome.SUCCESS,
            "failure": StepOutcome.FAILURE,
            "tool_needed": StepOutcome.TOOL_NEEDED,
            "continue": StepOutcome.CONTINUE,
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
                outcome=OUTCOME_PRIORITY[0], # FAILURE
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