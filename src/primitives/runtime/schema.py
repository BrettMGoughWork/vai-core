from __future__ import annotations
import inspect
from typing import Any, Callable, Dict, get_type_hints, List, Optional, Union


def _python_type_to_json(t: Any) -> Dict[str, Any]:
    # Handle typing.Optional[X] / Union[X, None]
    origin = getattr(t, "__origin__", None)
    args = getattr(t, "__args__", ())

    if origin is Union and type(None) in args:
        # Optional[X] → treat as X, requiredness handled separately
        non_none = [a for a in args if a is not type(None)][0]
        return _python_type_to_json(non_none)

    if t is int:
        return {"type": "integer"}
    if t is float:
        return {"type": "number"}
    if t is bool:
        return {"type": "boolean"}
    if t is str:
        return {"type": "string"}
    if t is list or origin is list or origin is List:
        return {"type": "array", "items": {}}
    if t is dict or origin is dict or origin is Dict:
        return {"type": "object"}

    # Fallback
    return {"type": "string"}


def generate_schema_from_handler(handler: Callable[..., Any]) -> Dict[str, Any]:
    sig = inspect.signature(handler)
    hints = get_type_hints(handler)

    properties: Dict[str, Any] = {}
    required: List[str] = []

    for name, param in sig.parameters.items():
        if name == "self":
            continue

        annotated_type = hints.get(name, str)
        schema_entry = _python_type_to_json(annotated_type)
        properties[name] = schema_entry

        # Required if no default
        if param.default is inspect._empty:
            required.append(name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }