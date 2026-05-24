"""
Plan Validation - Validates plans before execution.

Exports the PlanValidationResult dataclass and validate_plan() function
for validating plan structure, safety, and completeness.
"""

from ...planning.validators.plan_validation import (
    CapabilityRegistry,
    PlanValidationResult,
    validate_plan,
)

from ...planning.safety.purity_validation import validate_pure_structure

__all__ = [
    "CapabilityRegistry",
    "PlanValidationResult",
    "validate_plan",
    "validate_pure_structure",
]
