class PlanValidationError(Exception):
    """Base class for all plan validation errors."""
    pass


class PlanStructureError(PlanValidationError):
    """Plan does not match the required plan schema."""
    pass


class UnknownCapabilityError(PlanValidationError):
    """Plan references a capability that does not exist."""
    pass


class ForbiddenCapabilityError(PlanValidationError):
    """Plan references a capability that is not allowed in planning mode."""
    pass


class CapabilitySchemaError(PlanValidationError):
    """Plan arguments do not match the capability's input schema."""
    pass


class PlanPurityError(PlanValidationError):
    """Plan contains non‑pure or unserialisable values."""
    pass


class PlanSafetyError(PlanValidationError):
    """Plan violates safety or allowed‑actions rules."""
    pass