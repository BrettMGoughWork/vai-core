"""Tests for stdlib.yaml.parse primitive (Phase 3.18.2)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.yaml_parse import YamlParsePrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> YamlParsePrimitive:
    return YamlParsePrimitive()


class TestYamlParseValidate:
    def test_valid_args(self, prim: YamlParsePrimitive) -> None:
        prim.validate_args({"text": "key: val"})

    def test_missing_text_raises(self, prim: YamlParsePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'text' key"):
            prim.validate_args({})

    def test_non_string_text_raises(self, prim: YamlParsePrimitive) -> None:
        with pytest.raises(ValueError, match="'text' must be a string"):
            prim.validate_args({"text": 42})

    def test_empty_text_raises(self, prim: YamlParsePrimitive) -> None:
        with pytest.raises(ValueError, match="'text' must not be empty"):
            prim.validate_args({"text": ""})

    def test_args_not_a_dict_raises(self, prim: YamlParsePrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestYamlParseExecute:
    def test_parse_dict(self, prim: YamlParsePrimitive) -> None:
        result = prim.execute({"text": "key: val"}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data == {"value": {"key": "val"}}
        assert result.error is None

    def test_parse_number(self, prim: YamlParsePrimitive) -> None:
        result = prim.execute({"text": "42"}, {})
        assert result.status == "success"
        assert result.data == {"value": 42}

    def test_invalid_yaml_returns_error(self, prim: YamlParsePrimitive) -> None:
        result = prim.execute({"text": "invalid: [bad"}, {})
        assert result.status == "error"
        assert result.error is not None
        assert "YAMLError" in result.error
