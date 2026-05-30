from __future__ import annotations

from src.core.planning.models.plan import Plan
from src.core.types.errors import ValidationError
from src.core.planning.safety.purity_enforcer import enforce_cognitive_purity

from src.core.types.errors.plan_errors import (
    PlanStructureError,
    UnknownCapabilityError,
    ForbiddenCapabilityError,
    CapabilitySchemaError,
    PlanPurityError,
    PlanSafetyError,
)


class PlanValidator:
    """
    Validates a Plan object against:
    - Plan schema (structural)
    - Capability existence
    - Capability allowlist (optional)
    - Capability input schema
    - Purity rules (JSON-pure)
    - Safety rules (side-effect restrictions)
    """

    def __init__(self, capabilities: dict, allowed_capabilities: set[str] | None = None):
        self.capabilities = capabilities
        self.allowed_capabilities = allowed_capabilities

    # ----------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------
    def validate(self, plan: Plan) -> None:
        """
        Raises a typed PlanValidationError subclass on failure.
        Returns None on success.
        """
        cap = self.capabilities.get(plan.targetskillid)
        input_schema = cap["input_schema"] if cap and "input_schema" in cap else {}
        self._validate_structure(input_schema, plan)
        self._validate_capability_exists(plan)
        self._validate_capability_allowed(plan)
        self._validate_safety(plan)

    # ----------------------------------------------------------------------
    # Structural validation
    # ----------------------------------------------------------------------
    def _validate_structure(self, schema: dict, plan: Plan) -> None:
        if not isinstance(plan.intent, str) or not plan.intent:
            raise PlanStructureError("Plan intent must be a non-empty string")

        if not isinstance(plan.targetskillid, str) or not plan.targetskillid:
            raise PlanStructureError("Plan targetskillid must be a non-empty string")

        if not isinstance(plan.arguments, dict):
            raise PlanStructureError("Plan arguments must be an object")

        if not isinstance(plan.reasoning_summary, str):
            raise PlanStructureError("Plan reasoning_summary must be a string")
        
        validate_structural(schema, plan.arguments)

    # ----------------------------------------------------------------------
    # Capability existence
    # ----------------------------------------------------------------------
    def _validate_capability_exists(self, plan: Plan) -> None:
        if plan.targetskillid not in self.capabilities:
            raise UnknownCapabilityError(
                f"Unknown capability: {plan.targetskillid}"
            )

    # ----------------------------------------------------------------------
    # Capability allowlist
    # ----------------------------------------------------------------------
    def _validate_capability_allowed(self, plan: Plan) -> None:
        if self.allowed_capabilities is None:
            return

        if plan.targetskillid not in self.allowed_capabilities:
            raise ForbiddenCapabilityError(
                f"Capability '{plan.targetskillid}' is not allowed in planning mode"
            )

    # ----------------------------------------------------------------------
    # Capability input schema
    # ----------------------------------------------------------------------
    def _validate_arguments_schema(self, plan: Plan, skillinput_schema: dict) -> None:
        if not isinstance(skillinput_schema, dict):
            raise CapabilitySchemaError("Skill input schema must be an object")

        try:
            validate_structural(skillinput_schema, plan.arguments)
        except ValidationError as exc:
            raise CapabilitySchemaError(
                f"Plan arguments do not match skill input schema: {exc}"
            ) from exc

    # ----------------------------------------------------------------------
    # Purity enforcement
    # ----------------------------------------------------------------------
    def _validate_purity(self, plan: Plan) -> None:
        try:
            enforce_cognitive_purity(plan.to_dict())
        except Exception as exc:
            raise PlanPurityError(f"Plan contains non-pure values: {exc}") from exc

    # ----------------------------------------------------------------------
    # Safety rules
    # ----------------------------------------------------------------------
    def _validate_safety(self, plan: Plan) -> None:
        capability = self.capabilities.get(plan.targetskillid, {})

        # Example rule: planning cannot call side-effectful capabilities
        if capability.get("side_effects") not in (None, "none"):
            raise PlanSafetyError(
                f"Capability '{plan.targetskillid}' has side effects and cannot be used in planning"
            )