"""Tests for stdlib.text.join primitive (Phase 3.18.7)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.text_join import TextJoinPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def text_join() -> TextJoinPrimitive:
    return TextJoinPrimitive()


class TestTextJoinPrimitive:
    """Tests for TextJoinPrimitive.validate_args and execute."""

    def test_join_with_space(self, text_join: TextJoinPrimitive) -> None:
        result = text_join.execute({"parts": ["hello", "world"], "delimiter": " "}, {})
        assert result.status == "success"
        assert result.data["text"] == "hello world"
        assert result.data["length"] == 11

    def test_join_with_empty_delimiter(self, text_join: TextJoinPrimitive) -> None:
        result = text_join.execute({"parts": ["a", "b", "c"]}, {})
        assert result.data["text"] == "abc"

    def test_join_with_newline(self, text_join: TextJoinPrimitive) -> None:
        result = text_join.execute({"parts": ["line1", "line2"], "delimiter": "\n"}, {})
        assert result.data["text"] == "line1\nline2"

    def test_join_single_element(self, text_join: TextJoinPrimitive) -> None:
        result = text_join.execute({"parts": ["only"]}, {})
        assert result.data["text"] == "only"

    def test_join_empty_list(self, text_join: TextJoinPrimitive) -> None:
        result = text_join.execute({"parts": []}, {})
        assert result.data["text"] == ""

    def test_missing_parts_raises_value_error(self, text_join: TextJoinPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'parts'"):
            text_join.validate_args({})

    def test_parts_not_list_raises_value_error(self, text_join: TextJoinPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a list"):
            text_join.validate_args({"parts": "not a list"})

    def test_parts_contains_non_string_raises_value_error(self, text_join: TextJoinPrimitive) -> None:
        with pytest.raises(ValueError, match="list of strings"):
            text_join.validate_args({"parts": [1, 2, 3]})

    def test_delimiter_not_string_raises_value_error(self, text_join: TextJoinPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            text_join.validate_args({"parts": ["a"], "delimiter": 99})
