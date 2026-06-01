from __future__ import annotations
from typing import Any, Dict

def compute_behavioural_delta(prev: Any, new: Any) -> Dict[str, Any]:
    if prev is None:
        return {"initial_output": True}

    if type(prev) != type(new):
        return {"type_changed": {"from": str(type(prev)), "to": str(type(new))}}

    if isinstance(prev, dict) and isinstance(new, dict):
        changed = {
            k: {"from": prev.get(k), "to": new.get(k)}
            for k in set(prev.keys()) | set(new.keys())
            if prev.get(k) != new.get(k)
        }
        return {"changed_fields": changed} if changed else {"no_change": True}

    if prev != new:
        return {"value_changed": {"from": prev, "to": new}}

    return {"no_change": True}