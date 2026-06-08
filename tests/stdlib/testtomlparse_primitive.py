"""Tests for stdlib.toml.parse primitive (Phase 3.18.2)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.toml_parse import TomlParsePrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> TomlParsePrimitive:
    return TomlParsePrimitive()


class TestTomlParseValidate:
    def test_valid_args(self, prim: TomlParsePrimitive) -> None:
        prim.validate_args({"text": 'key = "val"'})

    def test_missing_text_raises(self, prim: TomlParsePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'text' key"):
            prim.validate_args({})

    def test_non_string_text_raises(self, prim: TomlParsePrimitive) -> None:
        with pytest.raises(ValueError, match="'text' must be a string"):
            prim.validate_args({"text": 42})

    def test_empty_text_raises(self, prim: TomlParsePrimitive) -> None:
        with pytest.raises(ValueError, match="'text' must not be empty"):
            prim.validate_args({"text": ""})

    def test_args_not_a_dict_raises(self, prim: TomlParsePrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestTomlParseExecute:
    def test_parse_valid_toml(self, prim: TomlParsePrimitive) -> None:
        result = prim.execute({"text": 'key = "val"'}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data == {"value": {"key": "val"}}
        assert result.error is None

    def test_invalid_toml_returns_error(self, prim: TomlParsePrimitive) -> None:
        result = prim.execute({"text": "key = = broken"}, {})
        assert result.status == "error"
        assert result.error is not None
        assert "TOMLDecodeError" in result.error
