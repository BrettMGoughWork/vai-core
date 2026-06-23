from __future__ import annotations
from typing import Any, Dict

from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Defined as part of error taxonomy, used via type field")
class SemanticValidationError(Exception):
    pass


def validate_semantic(schema: Dict[str, Any], args: Dict[str, Any]) -> None:
    """
    Placeholder semantic validator.
    Step 7 only requires the hook, not full rules.
    Later steps will add:
    - URL validation
    - path safety
    - enum constraints
    - positive numbers
    - domain-specific checks
    """
    return None