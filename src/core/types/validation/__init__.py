"""
Plan Validation - Validates plans before execution.

Exports the PlanValidationResult dataclass and validate_plan() function
for validating plan structure, safety, and completeness.
"""

from .plan_validation import (
    CapabilityRegistry,
    PlanValidationResult,
    validate_plan,
)

__all__ = [
    "CapabilityRegistry",
    "PlanValidationResult",
    "validate_plan",
]
