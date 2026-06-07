"""
Tests for runtime structural validator (validate_structural).

Covers: required field checking, unknown field detection, type validation
for all supported JSON schema types — both happy-path and error cases.
"""

from __future__ import annotations

import pytest

from src.capabilities.runtime.validator import validate_structural, _validate_type
from src.core.types.errors import ValidationError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def basic_schema() -> dict:
    """A simple schema with string, integer, and required fields."""
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
            "active": {"type": "boolean"},
        },
        "required": ["name"],
    }


@pytest.fixture
def full_type_schema() -> dict:
    """A schema exercising every supported JSON type."""
    return {
        "type": "object",
        "properties": {
            "s": {"type": "string"},
            "i": {"type": "integer"},
            "n": {"type": "number"},
            "b": {"type": "boolean"},
            "a": {"type": "array"},
            "o": {"type": "object"},
        },
        "required": [],
    }


@pytest.fixture
def empty_schema() -> dict:
    """Schema with no properties and no required fields."""
    return {
        "type": "object",
        "properties": {},
        "required": [],
    }


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

class TestValidateStructuralHappyPath:
    """Tests that valid args pass without exception."""

    def test_all_required_and_known_fields_pass(self, basic_schema):
        """Args with all required fields and only known fields pass."""
        validate_structural(basic_schema, {"name": "Alice", "age": 30})

    def test_extra_known_field_passes_when_not_required(self, basic_schema):
        """Providing an optional known field (active) passes."""
        validate_structural(basic_schema, {"name": "Alice", "active": True})

    def test_empty_args_with_no_required_fields(self, empty_schema):
        """Empty args against a schema with no required fields passes."""
        validate_structural(empty_schema, {})

    def test_empty_args_with_no_required_fields_full(self, full_type_schema):
        """Empty args against the full-type schema with no required fields passes."""
        validate_structural(full_type_schema, {})

    def test_all_types_correct(self, full_type_schema):
        """Every supported type with a correct value passes."""
        validate_structural(full_type_schema, {
            "s": "hello",
            "i": 42,
            "n": 3.14,
            "b": True,
            "a": [1, 2, 3],
            "o": {"key": "val"},
        })

    def test_number_accepts_int(self, full_type_schema):
        """Number type accepts integer values."""
        validate_structural(full_type_schema, {"n": 42})

    def test_number_accepts_float(self, full_type_schema):
        """Number type accepts float values."""
        validate_structural(full_type_schema, {"n": 3.14})


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------

class TestValidateStructuralMissingRequired:
    """Tests that missing required fields raise ValidationError."""

    def test_missing_single_required_raises(self, basic_schema):
        """Omitting a required field raises with the field name in the message."""
        with pytest.raises(ValidationError, match="Missing required field"):
            validate_structural(basic_schema, {"age": 25})

    def test_missing_required_field_message_contains_name(self, basic_schema):
        """The error message includes the specific missing field name."""
        with pytest.raises(ValidationError, match="name"):
            validate_structural(basic_schema, {"age": 25})

    def test_multiple_required_all_missing_raises_on_first(self):
        """When multiple required fields are missing, raises on the first one."""
        schema = {
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "string"},
            },
            "required": ["a", "b"],
        }
        with pytest.raises(ValidationError, match="Missing required field: a"):
            validate_structural(schema, {})

    def test_empty_args_with_required_field_raises(self):
        """Empty args when a field is required raises."""
        schema = {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        }
        with pytest.raises(ValidationError, match="Missing required field"):
            validate_structural(schema, {})


# ---------------------------------------------------------------------------
# Unknown fields
# ---------------------------------------------------------------------------

class TestValidateStructuralUnknownFields:
    """Tests that unknown/extra fields raise ValidationError."""

    def test_unknown_field_raises(self, basic_schema):
        """A field not in schema properties raises."""
        with pytest.raises(ValidationError, match="Unknown field"):
            validate_structural(basic_schema, {"name": "Alice", "extra": "bad"})

    def test_unknown_field_message_contains_name(self, basic_schema):
        """The error message includes the unknown field name."""
        with pytest.raises(ValidationError, match="extra"):
            validate_structural(basic_schema, {"name": "Alice", "extra": "bad"})

    def test_unknown_field_checked_before_type(self, basic_schema):
        """Unknown fields are flagged even if their value appears type-correct."""
        with pytest.raises(ValidationError, match="Unknown field: unknown"):
            validate_structural(basic_schema, {"name": "Alice", "unknown": "str"})


# ---------------------------------------------------------------------------
# Type mismatches
# ---------------------------------------------------------------------------

class TestValidateStructuralTypeMismatches:
    """Tests that type mismatches raise ValidationError."""

    # -- integer --
    def test_integer_field_with_string_raises(self):
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": []}
        with pytest.raises(ValidationError, match="must be integer"):
            validate_structural(schema, {"x": "hello"})

    def test_integer_field_with_float_raises(self):
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": []}
        with pytest.raises(ValidationError, match="must be integer"):
            validate_structural(schema, {"x": 3.14})

    def test_integer_field_with_bool_passes(self):
        """bool is a subclass of int in Python, so this is a documented quirk."""
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": []}
        # bool IS an instance of int in Python — so this actually passes
        validate_structural(schema, {"x": True})  # passes due to isinstance(bool, int)

    def test_integer_field_with_none_raises(self):
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": []}
        with pytest.raises(ValidationError, match="must be integer"):
            validate_structural(schema, {"x": None})

    # -- number --
    def test_number_field_with_string_raises(self):
        schema = {"type": "object", "properties": {"x": {"type": "number"}}, "required": []}
        with pytest.raises(ValidationError, match="must be number"):
            validate_structural(schema, {"x": "3.14"})

    def test_number_field_with_bool_passes(self):
        """bool is a subclass of int, which passes isinstance check for number."""
        schema = {"type": "object", "properties": {"x": {"type": "number"}}, "required": []}
        validate_structural(schema, {"x": False})  # passes

    # -- boolean --
    def test_boolean_field_with_string_raises(self):
        schema = {"type": "object", "properties": {"x": {"type": "boolean"}}, "required": []}
        with pytest.raises(ValidationError, match="must be boolean"):
            validate_structural(schema, {"x": "true"})

    def test_boolean_field_with_int_raises(self):
        schema = {"type": "object", "properties": {"x": {"type": "boolean"}}, "required": []}
        with pytest.raises(ValidationError, match="must be boolean"):
            validate_structural(schema, {"x": 1})

    def test_boolean_field_with_none_raises(self):
        schema = {"type": "object", "properties": {"x": {"type": "boolean"}}, "required": []}
        with pytest.raises(ValidationError, match="must be boolean"):
            validate_structural(schema, {"x": None})

    # -- string --
    def test_string_field_with_int_raises(self):
        schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": []}
        with pytest.raises(ValidationError, match="must be string"):
            validate_structural(schema, {"x": 42})

    def test_string_field_with_none_raises(self):
        schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": []}
        with pytest.raises(ValidationError, match="must be string"):
            validate_structural(schema, {"x": None})

    # -- array --
    def test_array_field_with_string_raises(self):
        schema = {"type": "object", "properties": {"x": {"type": "array"}}, "required": []}
        with pytest.raises(ValidationError, match="must be array"):
            validate_structural(schema, {"x": "not-a-list"})

    def test_array_field_with_dict_raises(self):
        schema = {"type": "object", "properties": {"x": {"type": "array"}}, "required": []}
        with pytest.raises(ValidationError, match="must be array"):
            validate_structural(schema, {"x": {"key": "val"}})

    def test_array_field_with_none_raises(self):
        schema = {"type": "object", "properties": {"x": {"type": "array"}}, "required": []}
        with pytest.raises(ValidationError, match="must be array"):
            validate_structural(schema, {"x": None})

    # -- object --
    def test_object_field_with_string_raises(self):
        schema = {"type": "object", "properties": {"x": {"type": "object"}}, "required": []}
        with pytest.raises(ValidationError, match="must be object"):
            validate_structural(schema, {"x": "hello"})

    def test_object_field_with_list_raises(self):
        schema = {"type": "object", "properties": {"x": {"type": "object"}}, "required": []}
        with pytest.raises(ValidationError, match="must be object"):
            validate_structural(schema, {"x": [1, 2]})

    def test_object_field_with_none_raises(self):
        schema = {"type": "object", "properties": {"x": {"type": "object"}}, "required": []}
        with pytest.raises(ValidationError, match="must be object"):
            validate_structural(schema, {"x": None})


# ---------------------------------------------------------------------------
# Edge cases for validate_structural
# ---------------------------------------------------------------------------

class TestValidateStructuralEdgeCases:
    """Edge cases for validate_structural."""

    def test_schema_with_no_type_key_defaults(self):
        """When a property has no 'type' key, any value is accepted (fall-through)."""
        schema = {
            "type": "object",
            "properties": {"x": {}},  # no type specified
            "required": [],
        }
        validate_structural(schema, {"x": "anything"})
        validate_structural(schema, {"x": 42})
        validate_structural(schema, {"x": None})

    def test_schema_with_empty_properties(self):
        """Schema with empty properties dict; any args outside of it are unknown."""
        schema = {"type": "object", "properties": {}, "required": []}
        with pytest.raises(ValidationError, match="Unknown field"):
            validate_structural(schema, {"anything": 1})

    def test_args_with_extra_keys_and_missing_required(self):
        """Missing required is caught before unknown field checks would run."""
        schema = {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a"],
        }
        with pytest.raises(ValidationError, match="Missing required field: a"):
            validate_structural(schema, {"b": "extra"})

    def test_field_name_in_error_messages(self):
        """Errors include the field name for easy debugging."""
        schema = {"type": "object", "properties": {"count": {"type": "integer"}}, "required": []}
        with pytest.raises(ValidationError, match="'count'"):
            validate_structural(schema, {"count": "not-int"})


# ---------------------------------------------------------------------------
# _validate_type direct tests
# ---------------------------------------------------------------------------

class TestValidateTypeDirect:
    """Direct tests for the internal _validate_type function."""

    def test_no_type_key_accepts_anything(self):
        """An empty schema dict accepts any value (falls through all ifs)."""
        _validate_type("f", "anything", {})
        _validate_type("f", 42, {})
        _validate_type("f", None, {})
        _validate_type("f", [1, 2], {})

    def test_unknown_type_key_accepts_anything(self):
        """An unrecognized type key accepts any value."""
        _validate_type("f", "hello", {"type": "unknown_type"})

    def test_integer_accepts_int(self):
        _validate_type("f", 0, {"type": "integer"})
        _validate_type("f", -1, {"type": "integer"})

    def test_boolean_accepts_bool(self):
        _validate_type("f", True, {"type": "boolean"})
        _validate_type("f", False, {"type": "boolean"})

    def test_string_accepts_str(self):
        _validate_type("f", "", {"type": "string"})
        _validate_type("f", "hello", {"type": "string"})

    def test_array_accepts_list(self):
        _validate_type("f", [], {"type": "array"})
        _validate_type("f", [1, 2, 3], {"type": "array"})

    def test_object_accepts_dict(self):
        _validate_type("f", {}, {"type": "object"})
        _validate_type("f", {"k": "v"}, {"type": "object"})

    def test_number_accepts_int(self):
        _validate_type("f", 42, {"type": "number"})

    def test_number_accepts_float(self):
        _validate_type("f", 3.14, {"type": "number"})
