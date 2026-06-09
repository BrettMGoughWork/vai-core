"""Tests for stdlib.text.normalize primitive (Phase 3.18.7)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.text_normalize import TextNormalizePrimitive


@pytest.fixture
def text_normalize() -> TextNormalizePrimitive:
    return TextNormalizePrimitive()


class TestTextNormalizePrimitive:
    """Tests for TextNormalizePrimitive.validate_args and execute."""

    def test_collapse_whitespace(self, text_normalize: TextNormalizePrimitive) -> None:
        result = text_normalize.execute({"text": "hello   world\t\tfoo"}, {})
        assert result.status == "success"
        assert result.data["text"] == "hello world foo"

    def test_trim_whitespace(self, text_normalize: TextNormalizePrimitive) -> None:
        result = text_normalize.execute({"text": "  hello world  "}, {})
        assert result.data["text"] == "hello world"

    def test_lowercase(self, text_normalize: TextNormalizePrimitive) -> None:
        result = text_normalize.execute({"text": "Hello WORLD", "lowercase": True}, {})
        assert result.data["text"] == "hello world"

    def test_strip_punctuation(self, text_normalize: TextNormalizePrimitive) -> None:
        result = text_normalize.execute(
            {"text": "hello, world! how's it going?", "strip_punctuation": True}, {}
        )
        assert result.data["text"] == "hello world hows it going"

    def test_lowercase_and_strip_punctuation(self, text_normalize: TextNormalizePrimitive) -> None:
        result = text_normalize.execute(
            {"text": "Hello, WORLD!", "lowercase": True, "strip_punctuation": True}, {}
        )
        assert result.data["text"] == "hello world"

    def test_empty_string(self, text_normalize: TextNormalizePrimitive) -> None:
        result = text_normalize.execute({"text": ""}, {})
        assert result.data["text"] == ""

    def test_missing_text_raises_value_error(self, text_normalize: TextNormalizePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'text'"):
            text_normalize.validate_args({})

    def test_text_not_string_raises_value_error(self, text_normalize: TextNormalizePrimitive) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            text_normalize.validate_args({"text": None})

    def test_lowercase_not_bool_raises_value_error(self, text_normalize: TextNormalizePrimitive) -> None:
        with pytest.raises(ValueError, match="must be a bool"):
            text_normalize.validate_args({"text": "hi", "lowercase": "yes"})
