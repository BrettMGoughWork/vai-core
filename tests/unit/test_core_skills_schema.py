from typing import Optional

from src.primitives.runtime.schema import generate_schema_from_handler


def test_generate_schema_from_handler_maps_common_python_types():
    def handler(name: str, retries: int, ratio: float, enabled: bool, tag: Optional[str] = None):
        return {"ok": True}

    schema = generate_schema_from_handler(handler)

    assert schema["type"] == "object"
    assert schema["properties"]["name"]["type"] == "string"
    assert schema["properties"]["retries"]["type"] == "integer"
    assert schema["properties"]["ratio"]["type"] == "number"
    assert schema["properties"]["enabled"]["type"] == "boolean"
    assert schema["properties"]["tag"]["type"] == "string"
    assert schema["required"] == ["name", "retries", "ratio", "enabled"]
