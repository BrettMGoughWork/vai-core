from __future__ import annotations
from typing import Any, Dict, List, Union

from src.strategy.types.validation import validate_pure_structure
from src.strategy.types.errors.ValidationError import ValidationError

JSON = Union[Dict[str, Any], List[Any], str, int, float, bool, None]


def _normalise_dict(d: Dict[str, JSON]) -> Dict[str, JSON]:
    # Sort keys lexicographically for stable ordering
    normalised = {}
    for key in sorted(d.keys()):
        normalised[key] = normalise_cognitive_structure(d[key])
    return normalised


def _normalise_list(lst: List[JSON]) -> List[JSON]:
    # Lists preserve order; normalise each element
    return [normalise_cognitive_structure(v) for v in lst]


def normalise_cognitive_structure(value: JSON) -> JSON:
    """
    Canonical normalisation of any cognitive structure entering Stratum‑2.

    Guarantees:
    - stable ordering of dict keys
    - recursively normalised nested structures
    - JSON‑pure validation
    - deterministic representation for hashing
    """
    try:
        validate_pure_structure(value)
    except Exception as e:
        raise ValidationError(f"Cognitive structure is not JSON‑pure: {e}")

    if isinstance(value, dict):
        return _normalise_dict(value)

    if isinstance(value, list):
        return _normalise_list(value)

    # Scalars are already canonical
    return value