"""
Tests for runtime canonicalisation functions.

Covers: canonicalise_args, canonicalize_args alias, and _canonicalise_value
— string trimming/whitespace normalisation, integer/number/boolean coercion,
array and object passthrough, and fallback behaviour.
"""

from __future__ import annotations

import pytest

from src.capabilities.runtime.canonical import (
    canonicalise_args,
    canonicalize_args,
    _canonicalise_value,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mixed_schema() -> dict:
    """Schema with every supported type."""
    return {
        "type": "object",
        "properties": {
            "s": {"type": "string"},
            "i": {"type": "integer"},
            "n": {"type": "number"},
            "b": {"type": "boolean"},
            "a": {"type": "array"},
            "o": {"type": "object"},
            "unknown_type_field": {},  # no type
        },
    }


# ---------------------------------------------------------------------------
# canonicalise_args — string canonicalisation
# ---------------------------------------------------------------------------

class TestCanonicaliseArgsStrings:
    """Tests for string trimming and whitespace normalisation."""

    def test_trims_leading_whitespace(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"s": "  hello"})
        assert result["s"] == "hello"

    def test_trims_trailing_whitespace(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"s": "hello  "})
        assert result["s"] == "hello"

    def test_trims_both_sides(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"s": "  hello  "})
        assert result["s"] == "hello"

    def test_collapses_internal_whitespace(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"s": "hello    world"})
        assert result["s"] == "hello world"

    def test_collapses_newlines_and_tabs(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"s": "hello\t\n  \tworld"})
        assert result["s"] == "hello world"

    def test_empty_string_stays_empty(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"s": ""})
        assert result["s"] == ""

    def test_whitespace_only_becomes_empty(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"s": "   "})
        assert result["s"] == ""

    def test_non_string_value_left_alone(self, mixed_schema):
        """String canonicalisation only applies to actual strings."""
        result = canonicalise_args(mixed_schema, {"s": 42})
        assert result["s"] == 42


# ---------------------------------------------------------------------------
# canonicalise_args — integer coercion
# ---------------------------------------------------------------------------

class TestCanonicaliseArgsInteger:
    """Tests for integer coercion."""

    def test_int_passes_through(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"i": 42})
        assert result["i"] == 42
        assert isinstance(result["i"], int)

    def test_digit_string_coerces_to_int(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"i": "42"})
        assert result["i"] == 42
        assert isinstance(result["i"], int)

    def test_digit_string_with_whitespace_coerces(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"i": "  99  "})
        assert result["i"] == 99

    def test_negative_digit_string_not_coerced(self, mixed_schema):
        """isdigit() returns False for negative numbers, so no coercion."""
        result = canonicalise_args(mixed_schema, {"i": "-5"})
        assert result["i"] == "-5"  # stays string

    def test_non_digit_string_left_as_is(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"i": "hello"})
        assert result["i"] == "hello"

    def test_float_value_left_as_is_for_integer(self, mixed_schema):
        """Float is not int, so stays unchanged for integer field."""
        result = canonicalise_args(mixed_schema, {"i": 3.14})
        assert result["i"] == 3.14

    def test_bool_left_as_is_for_integer(self, mixed_schema):
        """bool is instance of int but not coerced further."""
        result = canonicalise_args(mixed_schema, {"i": True})
        assert result["i"] is True

    def test_none_left_as_is(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"i": None})
        assert result["i"] is None


# ---------------------------------------------------------------------------
# canonicalise_args — number coercion
# ---------------------------------------------------------------------------

class TestCanonicaliseArgsNumber:
    """Tests for number (float) coercion."""

    def test_float_passes_through(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"n": 3.14})
        assert result["n"] == 3.14
        assert isinstance(result["n"], float)

    def test_int_passes_through_for_number(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"n": 42})
        assert result["n"] == 42
        assert isinstance(result["n"], int)

    def test_numeric_string_coerces_to_float(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"n": "3.14"})
        assert result["n"] == 3.14
        assert isinstance(result["n"], float)

    def test_integer_string_coerces_to_float(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"n": "42"})
        assert result["n"] == 42.0
        assert isinstance(result["n"], float)

    def test_string_with_whitespace_coerces(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"n": "  2.5  "})
        assert result["n"] == 2.5

    def test_non_numeric_string_left_as_is(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"n": "hello"})
        assert result["n"] == "hello"

    def test_bool_passes_through_for_number(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"n": False})
        assert result["n"] is False


# ---------------------------------------------------------------------------
# canonicalise_args — boolean coercion
# ---------------------------------------------------------------------------

class TestCanonicaliseArgsBoolean:
    """Tests for boolean string coercion."""

    def test_bool_true_passes_through(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"b": True})
        assert result["b"] is True

    def test_bool_false_passes_through(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"b": False})
        assert result["b"] is False

    # True values
    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "TRUE "])
    def test_true_strings_coerce(self, mixed_schema, value):
        result = canonicalise_args(mixed_schema, {"b": value})
        assert result["b"] is True

    @pytest.mark.parametrize("value", ["yes", "Yes", "YES"])
    def test_yes_strings_coerce_to_true(self, mixed_schema, value):
        result = canonicalise_args(mixed_schema, {"b": value})
        assert result["b"] is True

    @pytest.mark.parametrize("value", ["1", " 1 "])
    def test_one_strings_coerce_to_true(self, mixed_schema, value):
        result = canonicalise_args(mixed_schema, {"b": value})
        assert result["b"] is True

    # False values
    @pytest.mark.parametrize("value", ["false", "False", "FALSE", " false "])
    def test_false_strings_coerce(self, mixed_schema, value):
        result = canonicalise_args(mixed_schema, {"b": value})
        assert result["b"] is False

    @pytest.mark.parametrize("value", ["no", "No", "NO"])
    def test_no_strings_coerce_to_false(self, mixed_schema, value):
        result = canonicalise_args(mixed_schema, {"b": value})
        assert result["b"] is False

    @pytest.mark.parametrize("value", ["0", " 0 "])
    def test_zero_strings_coerce_to_false(self, mixed_schema, value):
        result = canonicalise_args(mixed_schema, {"b": value})
        assert result["b"] is False

    def test_unrecognised_string_left_as_is(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"b": "maybe"})
        assert result["b"] == "maybe"

    def test_non_string_left_as_is_for_boolean(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"b": 1})
        assert result["b"] == 1

    def test_none_left_as_is_for_boolean(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"b": None})
        assert result["b"] is None


# ---------------------------------------------------------------------------
# canonicalise_args — array and object passthrough
# ---------------------------------------------------------------------------

class TestCanonicaliseArgsArrayAndObject:
    """Tests for array and object passthrough."""

    def test_array_passes_through(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"a": [1, "two", True]})
        assert result["a"] == [1, "two", True]

    def test_empty_array_passes_through(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"a": []})
        assert result["a"] == []

    def test_object_passes_through(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"o": {"x": 1, "y": "z"}})
        assert result["o"] == {"x": 1, "y": "z"}

    def test_empty_object_passes_through(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"o": {}})
        assert result["o"] == {}


# ---------------------------------------------------------------------------
# canonicalise_args — fallback / no type
# ---------------------------------------------------------------------------

class TestCanonicaliseArgsFallback:
    """Tests for fallback behaviour when no type is specified."""

    def test_no_type_returns_value_unchanged(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {"unknown_type_field": "hello"})
        assert result["unknown_type_field"] == "hello"

    def test_field_not_in_schema_properties_returns_unchanged(self, mixed_schema):
        """Field without a properties entry uses empty schema dict."""
        result = canonicalise_args(mixed_schema, {"some_extra": "value"})
        assert result["some_extra"] == "value"


# ---------------------------------------------------------------------------
# canonicalise_args — deterministic / idempotency
# ---------------------------------------------------------------------------

class TestCanonicaliseArgsIdempotency:
    """Tests that canonicalisation is idempotent."""

    def test_canonicalising_twice_returns_same_result(self, mixed_schema):
        args = {
            "s": "  hello  world  ",
            "i": " 42 ",
            "n": " 3.14 ",
            "b": " true ",
            "a": [],
            "o": {},
        }
        first = canonicalise_args(mixed_schema, args)
        second = canonicalise_args(mixed_schema, first)
        assert first == second

    def test_empty_args_returns_empty_dict(self, mixed_schema):
        result = canonicalise_args(mixed_schema, {})
        assert result == {}


# ---------------------------------------------------------------------------
# canonicalize_args alias
# ---------------------------------------------------------------------------

class TestCanonicalizeArgsAlias:
    """Tests for the American-spelling alias."""

    def test_alias_returns_same_as_canonicalise(self, mixed_schema):
        args = {"s": "  test  ", "i": " 7 "}
        result_c = canonicalise_args(mixed_schema, args)
        result_z = canonicalize_args(mixed_schema, args)
        assert result_z == result_c

    def test_alias_with_empty_args(self, mixed_schema):
        assert canonicalize_args(mixed_schema, {}) == canonicalise_args(mixed_schema, {})


# ---------------------------------------------------------------------------
# _canonicalise_value direct tests
# ---------------------------------------------------------------------------

class TestCanonicaliseValueDirect:
    """Direct tests for the internal _canonicalise_value function."""

    # String
    def test_string_strips_and_collapses(self):
        result = _canonicalise_value("  foo   bar  ", {"type": "string"})
        assert result == "foo bar"

    # Integer
    def test_integer_coerces_digit_string(self):
        result = _canonicalise_value("42", {"type": "integer"})
        assert result == 42
        assert isinstance(result, int)

    def test_integer_passes_int_through(self):
        assert _canonicalise_value(99, {"type": "integer"}) == 99

    def test_integer_does_not_coerce_float(self):
        assert _canonicalise_value(3.14, {"type": "integer"}) == 3.14

    # Number
    def test_number_coerces_string(self):
        result = _canonicalise_value("2.5", {"type": "number"})
        assert result == 2.5

    def test_number_passes_float_through(self):
        assert _canonicalise_value(2.5, {"type": "number"}) == 2.5

    def test_number_invalid_string_left_alone(self):
        assert _canonicalise_value("abc", {"type": "number"}) == "abc"

    # Boolean
    def test_boolean_coerces_true_string(self):
        assert _canonicalise_value("true", {"type": "boolean"}) is True

    def test_boolean_coerces_false_string(self):
        assert _canonicalise_value("false", {"type": "boolean"}) is False

    def test_boolean_unknown_string_left_alone(self):
        assert _canonicalise_value("unknown", {"type": "boolean"}) == "unknown"

    # Array
    def test_array_passes_through(self):
        assert _canonicalise_value([1, "a"], {"type": "array"}) == [1, "a"]

    # Object
    def test_object_passes_through(self):
        assert _canonicalise_value({"k": "v"}, {"type": "object"}) == {"k": "v"}

    # Fallback
    def test_no_type_returns_unchanged(self):
        assert _canonicalise_value("hello", {}) == "hello"
