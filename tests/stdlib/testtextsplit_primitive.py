"""Tests for stdlib.text.split primitive (Phase 3.18.7)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.text_split import TextSplitPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def text_split() -> TextSplitPrimitive:
    return TextSplitPrimitive()


class TestTextSplitPrimitive:
    """Tests for TextSplitPrimitive.validate_args and execute."""

    def test_split_by_space(self, text_split: TextSplitPrimitive) -> None:
        result = text_split.execute({"text": "hello world foo"}, {})
        assert result.status == "success"
        assert result.data["parts"] == ["hello", "world", "foo"]
        assert result.data["count"] == 3

    def test_split_by_comma(self, text_split: TextSplitPrimitive) -> None:
        result = text_split.execute({"text": "a,b,c", "delimiter": ","}, {})
        assert result.data["parts"] == ["a", "b", "c"]

    def test_split_with_maxsplit(self, text_split: TextSplitPrimitive) -> None:
        result = text_split.execute({"text": "a b c d", "maxsplit": 2}, {})
        assert result.data["parts"] == ["a", "b", "c d"]

    def test_split_empty_string(self, text_split: TextSplitPrimitive) -> None:
        result = text_split.execute({"text": ""}, {})
        assert result.data["parts"] == [""]

    def test_split_no_delimiter_match(self, text_split: TextSplitPrimitive) -> None:
        result = text_split.execute({"text": "hello", "delimiter": ","}, {})
        assert result.data["parts"] == ["hello"]

    def test_missing_text_raises_value_error(self, text_split: TextSplitPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'text'"):
            text_split.validate_args({})

    def test_text_not_string_raises_value_error(self, text_split: TextSplitPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            text_split.validate_args({"text": 123})

    def test_delimiter_not_string_raises_value_error(self, text_split: TextSplitPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            text_split.validate_args({"text": "hi", "delimiter": 5})

    def test_maxsplit_not_int_raises_value_error(self, text_split: TextSplitPrimitive) -> None:
        with pytest.raises(ValueError, match="must be an integer"):
            text_split.validate_args({"text": "hi", "maxsplit": "two"})
