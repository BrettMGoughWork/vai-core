"""Tests for stdlib.json.get primitive (Phase 3.18.2)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.json_get import JsonGetPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> JsonGetPrimitive:
    return JsonGetPrimitive()


class TestJsonGetValidate:
    def test_valid_args(self, prim: JsonGetPrimitive) -> None:
        prim.validate_args({"obj": {"a": 1}, "key": "a"})

    def test_missing_obj_raises(self, prim: JsonGetPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'obj' key"):
            prim.validate_args({"key": "a"})

    def test_missing_key_raises(self, prim: JsonGetPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'key' key"):
            prim.validate_args({"obj": {}})

    def test_obj_not_dict_raises(self, prim: JsonGetPrimitive) -> None:
        with pytest.raises(ValueError, match="'obj' must be a dict"):
            prim.validate_args({"obj": "not_a_dict", "key": "a"})

    def test_key_not_string_raises(self, prim: JsonGetPrimitive) -> None:
        with pytest.raises(ValueError, match="'key' must be a string"):
            prim.validate_args({"obj": {}, "key": 42})

    def test_empty_key_raises(self, prim: JsonGetPrimitive) -> None:
        with pytest.raises(ValueError, match="'key' must not be empty"):
            prim.validate_args({"obj": {}, "key": ""})

    def test_args_not_a_dict_raises(self, prim: JsonGetPrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestJsonGetExecute:
    def test_get_existing_key(self, prim: JsonGetPrimitive) -> None:
        result = prim.execute({"obj": {"a": 1, "b": 2}, "key": "a"}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data == {"value": 1}
        assert result.error is None

    def test_get_missing_key_returns_error(self, prim: JsonGetPrimitive) -> None:
        result = prim.execute({"obj": {"a": 1}, "key": "b"}, {})
        assert result.status == "error"
        assert result.error is not None
        assert "KeyError" in result.error

    def test_get_nested_value(self, prim: JsonGetPrimitive) -> None:
        result = prim.execute({"obj": {"a": {"nested": 42}}, "key": "a"}, {})
        assert result.status == "success"
        assert result.data == {"value": {"nested": 42}}

    def test_no_side_effects(self, prim: JsonGetPrimitive) -> None:
        result = prim.execute({"obj": {"x": 1}, "key": "x"}, {})
        assert result.side_effects == []
