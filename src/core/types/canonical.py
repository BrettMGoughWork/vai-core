from __future__ import annotations
from typing import Any, Dict, List


ALLOWED_SCALARS = (str, int, float, bool, type(None))


def to_canonical(value: Any) -> Any:
    if isinstance(value, ALLOWED_SCALARS):
        return value

    if isinstance(value, list):
        return [to_canonical(v) for v in value]

    if isinstance(value, dict):
        # keys must be strings; sort for determinism
        items = []
        for k in sorted(value.keys()):
            if not isinstance(k, str):
                raise TypeError(f"Non‑string key in canonical structure: {k!r}")
            items.append((k, to_canonical(value[k])))
        return dict(items)

    raise TypeError(f"Non‑canonical type: {type(value).__name__}")