"""
validation_errors.py — re-exports the existing ValidationError for use by
subgoal validation rules and the ValidationEngine.

The spec calls for (rule, message, field). These are carried via the existing
ValidationError constructor: ValidationError(message, details={"rule": ..., "field": ...}).
"""
from src.strategy.types.errors.ValidationError import ValidationError

__all__ = ["ValidationError"]
