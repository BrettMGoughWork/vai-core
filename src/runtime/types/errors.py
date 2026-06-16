"""
ValidationError for cross-stratum structural validation.

Canonical home for the ValidationError class used by
both S2 (strategy) and S3 (capabilities) to avoid
circular dependencies.
"""


class ValidationError(Exception):
    """
    Raised when structural validation of data or arguments fails.

    Used by ``validate_structural`` to signal type mismatches,
    missing required fields, or unknown fields.
    """

    pass
