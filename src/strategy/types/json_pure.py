import json
from typing import Any


def ensure_json_pure(value: Any) -> None:
    try:
        json.dumps(value)
    except TypeError as e:
        raise TypeError(f"Value is not JSON-serializable: {e}")