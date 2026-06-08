"""Tests for stdlib.json.parse primitive (Phase 3.18.2)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.json_parse import JsonParsePrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> JsonParsePrimitive:
    return JsonParsePrimitive()


class TestJsonParseValidate:
    def test_valid_args(self, prim: JsonParsePrimitive) -> None:
        prim.validate_args({"text": '{"a": 1}'})

    def test_missing_text_raises(self, prim: JsonParsePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'text' key"):
            prim.validate_args({})

    def test_non_string_text_raises(self, prim: JsonParsePrimitive) -> None:
        with pytest.raises(ValueError, match="'text' must be a string"):
            prim.validate_args({"text": 42})

    def test_empty_text_raises(self, prim: JsonParsePrimitive) -> None:
        with pytest.raises(ValueError, match="'text' must not be empty"):
            prim.validate_args({"text": ""})

    def test_args_not_a_dict_raises(self, prim: JsonParsePrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestJsonParseExecute:
    def test_parse_object(self, prim: JsonParsePrimitive) -> None:
        result = prim.execute({"text": '{"a": 1}'}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data == {"value": {"a": 1}}
        assert result.error is None

    def test_parse_array(self, prim: JsonParsePrimitive) -> None:
        result = prim.execute({"text": "[1, 2, 3]"}, {})
        assert result.status == "success"
        assert result.data == {"value": [1, 2, 3]}

    def test_parse_number(self, prim: JsonParsePrimitive) -> None:
        result = prim.execute({"text": "42"}, {})
        assert result.status == "success"
        assert result.data == {"value": 42}

    def test_invalid_json_returns_error(self, prim: JsonParsePrimitive) -> None:
        result = prim.execute({"text": "invalid json"}, {})
        assert result.status == "error"
        assert result.error is not None
        assert "JSONDecodeError" in result.error

    def test_empty_string_raises_validation_error(self, prim: JsonParsePrimitive) -> None:
        """Empty string is rejected by validate_args before execution."""
        with pytest.raises(ValueError, match="'text' must not be empty"):
            prim.execute({"text": ""}, {})
