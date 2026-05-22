from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from .step_state import StepState
from .step_result import StepResult, StepOutcome
from .step_result_factory import (
    success,
    failure,
    tool_needed,
    continue_reasoning,
)
from src.core.types.validation import validate_pure_structure
from src.core.types.errors.error_types import (
    semantic_error,
    confidence_error,
)


class OutcomeClassifier:
    """
    Interface for pure outcome classifiers (Stratum 2).

    Invariants:
    - No LLM calls
    - No tool calls
    - No side effects
    - Deterministic: same StepState -> same StepResult
    """

    def classify(self, state: StepState) -> StepResult: # pragma: no cover - interface
        raise NotImplementedError


@dataclass(frozen=True)
class DefaultOutcomeClassifier(OutcomeClassifier):
    """
    Default Step Outcome Classifier (PHASE 2.1.5).

    Expects Stratum 1 to provide a structured classifier output in:

        state.cognitive_input["classifier"] = {
            "label": "success" | "failure" | "tool_needed" | "continue",
            "reason": "<short explanation>",
            "metadata": { ... } # optional, pure JSON object
        }

    This wrapper:
    - Validates purity of the classifier payload
    - Maps label -> StepOutcome
    - Falls back to FAILURE with an embedded AgentError on invalid input
    """

    def classify(self, state: StepState) -> StepResult:
        cognitive_input = state.cognitive_input or {}

        if "classifier" not in cognitive_input:
            err = semantic_error(
                "Missing classifier output in StepState.cognitive_input",
                details={
                    "step_id": getattr(state, "step_id", None),
                    "cognitive_input_keys": list(cognitive_input.keys()),
                },
            )
            return failure(
                reason=err.message,
                payload={"error": err.to_dict() if hasattr(err, "to_dict") else err.__dict__},
            )

        raw = cognitive_input["classifier"]

        # Ensure classifier payload is pure and JSON‑serialisable
        try:
            validate_pure_structure(raw)
        except Exception as e:
            err = semantic_error(
                "Non‑pure classifier output",
                details={
                    "step_id": getattr(state, "step_id", None),
                    "exception": str(e),
                },
            )
            return failure(
                reason=err.message,
                payload={"error": err.to_dict() if hasattr(err, "to_dict") else err.__dict__},
            )

        if not isinstance(raw, dict):
            err = semantic_error(
                "Classifier output must be a dict",
                details={
                    "step_id": getattr(state, "step_id", None),
                    "actual_type": type(raw).__name__,
                },
            )
            return failure(
                reason=err.message,
                payload={"error": err.to_dict() if hasattr(err, "to_dict") else err.__dict__},
            )

        label = raw.get("label")
        reason = raw.get("reason") or "No reason provided by classifier"
        metadata = raw.get("metadata") or {}

        # Map label -> StepOutcome
        if label == "success" or label == getattr(StepOutcome, "SUCCESS", "success"):
            return success(reason=reason, payload=metadata)

        if label == "failure" or label == getattr(StepOutcome, "FAILURE", "failure"):
            return failure(reason=reason, payload=metadata)

        if label == "tool_needed" or label == getattr(StepOutcome, "TOOL_NEEDED", "tool_needed"):
            return tool_needed(reason=reason, payload=metadata)

        if label == "continue" or label == getattr(StepOutcome, "CONTINUE", "continue"):
            return continue_reasoning(reason=reason, payload=metadata)

        # Unknown label -> confidence error -> FAILURE
        err = confidence_error(
            "Unknown classifier label",
            details={
                "step_id": getattr(state, "step_id", None),
                "label": label,
                "raw_classifier": raw,
            },
        )
        return failure(
            reason=err.message,
            payload={"error": err.to_dict() if hasattr(err, "to_dict") else err.__dict__},
        )
