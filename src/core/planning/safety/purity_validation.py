from __future__ import annotations
from typing import Any


ALLOWED_SCALARS = (str, int, float, bool, type(None))


def validate_pure_structure(value: Any, path: str = "") -> None:
    """
    Ensures that a structure is JSON‑serialisable and contains only pure types.

    Allowed:
    - dict
    - list
    - str, int, float, bool, None

    Disallowed:
    - tuples, sets
    - custom objects
    - functions, callables
    - bytes, bytearray
    - anything with __dict__
    """

    # Scalars
    if isinstance(value, ALLOWED_SCALARS):
        return

    # Lists
    if isinstance(value, list):
        for i, item in enumerate(value):
            validate_pure_structure(item, f"{path}[{i}]")
        return

    # Dicts
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise TypeError(f"Non‑string key at {path}: {k!r}")
            validate_pure_structure(v, f"{path}.{k}")
        return

    # Everything else is impure
    raise TypeError(
        f"Impure value at {path or '<root>'}: {type(value).__name__}"
    )
