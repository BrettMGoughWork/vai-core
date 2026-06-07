"""
Tests for runtime schema generation (generate_schema_from_handler).

Covers: Python type → JSON schema mapping for all supported types,
Optional/Union handling, required vs optional parameters based on defaults,
and self-skipping.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Union

import pytest

from src.capabilities.runtime.schema import generate_schema_from_handler, _python_type_to_json


# ---------------------------------------------------------------------------
# Fixtures — handler functions of varying signatures
# ---------------------------------------------------------------------------

def handler_no_params() -> str:
    """Handler with zero parameters."""
    return "ok"


def handler_all_required(
    a: str,
    b: int,
    c: float,
    d: bool,
    e: list,
    f: dict,
) -> None:
    """Handler where every parameter has a type hint and no defaults."""
    pass


def handler_with_default(a: str, b: int = 42) -> None:
    """Handler with one required and one optional parameter."""
    pass


def handler_optional(a: Optional[str], b: Optional[int] = None) -> None:
    """Handler with Optional types — one required, one with default."""
    pass


def handler_union_optional(a: Union[str, None], b: Union[int, None] = None) -> None:
    """Handler with Union[X, None] — equivalent to Optional."""
    pass


def handler_no_hints(a, b=10):
    """Handler with no type hints — defaults to string."""
    pass


class HandlerClass:
    """A class with a method that takes self plus params."""

    def method(self, x: int, y: str = "default") -> bool:
        return True

    @staticmethod
    def static_method(a: float) -> int:
        return int(a)


# ---------------------------------------------------------------------------
# generate_schema_from_handler tests
# ---------------------------------------------------------------------------

class TestGenerateSchemaFromHandler:
    """Tests for generate_schema_from_handler."""

    # -- Top-level structure --

    def test_returns_dict(self):
        schema = generate_schema_from_handler(handler_all_required)
        assert isinstance(schema, dict)

    def test_has_type_object(self):
        schema = generate_schema_from_handler(handler_all_required)
        assert schema["type"] == "object"

    def test_has_properties_key(self):
        schema = generate_schema_from_handler(handler_all_required)
        assert "properties" in schema

    def test_has_required_key(self):
        schema = generate_schema_from_handler(handler_all_required)
        assert "required" in schema

    # -- No parameters --

    def test_no_params_returns_empty_schema(self):
        schema = generate_schema_from_handler(handler_no_params)
        assert schema["properties"] == {}
        assert schema["required"] == []

    # -- Required vs optional --

    def test_all_required_when_no_defaults(self):
        schema = generate_schema_from_handler(handler_all_required)
        assert set(schema["required"]) == {"a", "b", "c", "d", "e", "f"}

    def test_default_makes_field_optional(self):
        schema = generate_schema_from_handler(handler_with_default)
        assert "a" in schema["required"]
        assert "b" not in schema["required"]

    def test_optional_required_when_no_default(self):
        schema = generate_schema_from_handler(handler_optional)
        # 'a' is Optional[str] but has no default → required
        assert "a" in schema["required"]
        assert "b" not in schema["required"]

    # -- Type mapping --

    def test_str_maps_to_string(self):
        schema = generate_schema_from_handler(handler_all_required)
        assert schema["properties"]["a"]["type"] == "string"

    def test_int_maps_to_integer(self):
        schema = generate_schema_from_handler(handler_all_required)
        assert schema["properties"]["b"]["type"] == "integer"

    def test_float_maps_to_number(self):
        schema = generate_schema_from_handler(handler_all_required)
        assert schema["properties"]["c"]["type"] == "number"

    def test_bool_maps_to_boolean(self):
        schema = generate_schema_from_handler(handler_all_required)
        assert schema["properties"]["d"]["type"] == "boolean"

    def test_list_maps_to_array(self):
        schema = generate_schema_from_handler(handler_all_required)
        assert schema["properties"]["e"]["type"] == "array"
        assert "items" in schema["properties"]["e"]

    def test_dict_maps_to_object(self):
        schema = generate_schema_from_handler(handler_all_required)
        assert schema["properties"]["f"]["type"] == "object"

    # -- Optional / Union mapping --

    def test_optional_unwraps_to_inner_type(self):
        schema = generate_schema_from_handler(handler_optional)
        assert schema["properties"]["a"]["type"] == "string"
        assert schema["properties"]["b"]["type"] == "integer"

    def test_union_with_none_unwraps(self):
        schema = generate_schema_from_handler(handler_union_optional)
        assert schema["properties"]["a"]["type"] == "string"
        assert schema["properties"]["b"]["type"] == "integer"

    # -- self-skipping --

    def test_self_parameter_skipped(self):
        schema = generate_schema_from_handler(HandlerClass.method)
        assert "self" not in schema["properties"]
        assert "x" in schema["properties"]
        assert "y" in schema["properties"]

    def test_self_not_in_required(self):
        schema = generate_schema_from_handler(HandlerClass.method)
        assert "self" not in schema["required"]

    def test_static_method_has_no_self(self):
        schema = generate_schema_from_handler(HandlerClass.static_method)
        assert "self" not in schema["properties"]
        assert "a" in schema["properties"]

    # -- No type hints --

    def test_no_hints_defaults_to_string(self):
        schema = generate_schema_from_handler(handler_no_hints)
        assert schema["properties"]["a"]["type"] == "string"
        assert schema["properties"]["b"]["type"] == "string"

    def test_no_hints_respects_defaults(self):
        schema = generate_schema_from_handler(handler_no_hints)
        assert "a" in schema["required"]
        assert "b" not in schema["required"]


# ---------------------------------------------------------------------------
# _python_type_to_json direct tests
# ---------------------------------------------------------------------------

class TestPythonTypeToJson:
    """Direct tests for the internal _python_type_to_json function."""

    def test_int_returns_integer(self):
        assert _python_type_to_json(int) == {"type": "integer"}

    def test_float_returns_number(self):
        assert _python_type_to_json(float) == {"type": "number"}

    def test_bool_returns_boolean(self):
        assert _python_type_to_json(bool) == {"type": "boolean"}

    def test_str_returns_string(self):
        assert _python_type_to_json(str) == {"type": "string"}

    def test_list_returns_array(self):
        result = _python_type_to_json(list)
        assert result["type"] == "array"
        assert "items" in result

    def test_dict_returns_object(self):
        assert _python_type_to_json(dict) == {"type": "object"}

    def test_typing_list_returns_array(self):
        result = _python_type_to_json(List[str])
        assert result["type"] == "array"

    def test_typing_dict_returns_object(self):
        result = _python_type_to_json(Dict[str, int])
        assert result["type"] == "object"

    def test_optional_unwraps_to_inner(self):
        result = _python_type_to_json(Optional[int])
        assert result == {"type": "integer"}

    def test_union_with_none_unwraps(self):
        result = _python_type_to_json(Union[int, None])
        assert result == {"type": "integer"}

    def test_unknown_type_falls_back_to_string(self):
        result = _python_type_to_json(bytes)
        assert result == {"type": "string"}

    def test_none_type_falls_back_to_string(self):
        """A bare None type falls back to string."""
        result = _python_type_to_json(type(None))
        assert result == {"type": "string"}
