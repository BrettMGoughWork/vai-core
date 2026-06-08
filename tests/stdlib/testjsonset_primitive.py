"""Tests for stdlib.json.set primitive (Phase 3.18.2)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.json_set import JsonSetPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> JsonSetPrimitive:
    return JsonSetPrimitive()


class TestJsonSetValidate:
    def test_valid_args(self, prim: JsonSetPrimitive) -> None:
        prim.validate_args({"obj": {"a": 1}, "key": "b", "value": 2})

    def test_missing_obj_raises(self, prim: JsonSetPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'obj' key"):
            prim.validate_args({"key": "b", "value": 2})

    def test_missing_key_raises(self, prim: JsonSetPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'key' key"):
            prim.validate_args({"obj": {}, "value": 2})

    def test_obj_not_dict_raises(self, prim: JsonSetPrimitive) -> None:
        with pytest.raises(ValueError, match="'obj' must be a dict"):
            prim.validate_args({"obj": "not_a_dict", "key": "b", "value": 2})

    def test_key_not_string_raises(self, prim: JsonSetPrimitive) -> None:
        with pytest.raises(ValueError, match="'key' must be a string"):
            prim.validate_args({"obj": {}, "key": 42, "value": 2})

    def test_empty_key_raises(self, prim: JsonSetPrimitive) -> None:
        with pytest.raises(ValueError, match="'key' must not be empty"):
            prim.validate_args({"obj": {}, "key": "", "value": 2})

    def test_args_not_a_dict_raises(self, prim: JsonSetPrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestJsonSetExecute:
    def test_set_new_key(self, prim: JsonSetPrimitive) -> None:
        result = prim.execute({"obj": {"a": 1}, "key": "b", "value": 2}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data is not None
        assert result.data["obj"] == {"a": 1, "b": 2}
        assert result.error is None

    def test_set_existing_key_overwrites(self, prim: JsonSetPrimitive) -> None:
        result = prim.execute({"obj": {"a": 1, "b": 2}, "key": "b", "value": 99}, {})
        assert result.status == "success"
        assert result.data["obj"] == {"a": 1, "b": 99}

    def test_set_non_json_serializable_value_errors(self, prim: JsonSetPrimitive) -> None:
        result = prim.execute({"obj": {}, "key": "x", "value": object()}, {})
        assert result.status == "error"
        assert result.error is not None

    def test_original_obj_not_mutated(self, prim: JsonSetPrimitive) -> None:
        original = {"a": 1}
        result = prim.execute({"obj": original, "key": "b", "value": 2}, {})
        assert result.status == "success"
        assert original == {"a": 1}
        assert result.data["obj"] == {"a": 1, "b": 2}
