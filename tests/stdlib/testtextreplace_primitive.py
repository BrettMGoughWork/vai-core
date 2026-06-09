"""Tests for stdlib.text.replace primitive (Phase 3.18.7)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.text_replace import TextReplacePrimitive


@pytest.fixture
def text_replace() -> TextReplacePrimitive:
    return TextReplacePrimitive()


class TestTextReplacePrimitive:
    """Tests for TextReplacePrimitive.validate_args and execute."""

    def test_replace_single(self, text_replace: TextReplacePrimitive) -> None:
        result = text_replace.execute({"text": "hello world", "old": "world", "new": "there"}, {})
        assert result.status == "success"
        assert result.data["text"] == "hello there"

    def test_replace_multiple(self, text_replace: TextReplacePrimitive) -> None:
        result = text_replace.execute({"text": "foo foo foo", "old": "foo", "new": "bar"}, {})
        assert result.data["text"] == "bar bar bar"

    def test_replace_with_count(self, text_replace: TextReplacePrimitive) -> None:
        result = text_replace.execute(
            {"text": "foo foo foo", "old": "foo", "new": "bar", "count": 2}, {}
        )
        assert result.data["text"] == "bar bar foo"

    def test_replace_no_match(self, text_replace: TextReplacePrimitive) -> None:
        result = text_replace.execute({"text": "hello", "old": "xyz", "new": "abc"}, {})
        assert result.data["text"] == "hello"

    def test_missing_text_raises_value_error(self, text_replace: TextReplacePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'text'"):
            text_replace.validate_args({})

    def test_missing_old_raises_value_error(self, text_replace: TextReplacePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'old'"):
            text_replace.validate_args({"text": "hi", "new": "bye"})

    def test_missing_new_raises_value_error(self, text_replace: TextReplacePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'new'"):
            text_replace.validate_args({"text": "hi", "old": "hi"})

    def test_count_not_int_raises_value_error(self, text_replace: TextReplacePrimitive) -> None:
        with pytest.raises(ValueError, match="must be an integer"):
            text_replace.validate_args({"text": "hi", "old": "h", "new": "x", "count": "all"})
