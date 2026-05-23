from __future__ import annotations
import hashlib
import json
from typing import Any

from .canonical import to_canonical

def _canonicalise(value: Any) -> Any:
    """
    Convert Python objects into a canonical JSON-serialisable structure:
    - dicts → sorted by key
    - lists/tuples → canonicalised element-wise
    - primitives → unchanged
    """
    if isinstance(value, dict):
        return {k: _canonicalise(value[k]) for k in sorted(value.keys())}

    if isinstance(value, (list, tuple)):
        return [_canonicalise(v) for v in value]

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    raise TypeError(f"Non-canonicalisable type in stable_hash: {type(value)}")


def stable_hash(value: Any) -> str:
    """
    Deterministic, canonical, stable hash for cognitive state.
    Produces identical output for identical logical structures.
    """
    canonical = to_canonical(value)

    # JSON with sorted keys ensures deterministic serialisation
    encoded = json.dumps(canonical, separators=(",", ":"), sort_keys=True)

    # SHA-256 is stable, fast, and collision-resistant
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()