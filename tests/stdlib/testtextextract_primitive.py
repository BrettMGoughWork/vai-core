"""Tests for stdlib.text.extract primitive (Phase 3.18.7)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.text_extract import TextExtractPrimitive


@pytest.fixture
def text_extract() -> TextExtractPrimitive:
    return TextExtractPrimitive()


class TestTextExtractPrimitive:
    """Tests for TextExtractPrimitive.validate_args and execute."""

    def test_extract_words(self, text_extract: TextExtractPrimitive) -> None:
        result = text_extract.execute({"text": "cat dog bird", "pattern": r"\w+"}, {})
        assert result.status == "success"
        assert result.data["matches"] == ["cat", "dog", "bird"]

    def test_extract_numbers(self, text_extract: TextExtractPrimitive) -> None:
        result = text_extract.execute({"text": "abc 123 def 456", "pattern": r"\d+"}, {})
        assert result.data["matches"] == ["123", "456"]

    def test_extract_no_match(self, text_extract: TextExtractPrimitive) -> None:
        result = text_extract.execute({"text": "hello", "pattern": r"\d+"}, {})
        assert result.data["matches"] == []

    def test_extract_with_group(self, text_extract: TextExtractPrimitive) -> None:
        result = text_extract.execute(
            {"text": "name:alice,name:bob", "pattern": r"name:(\w+)", "group": 1}, {}
        )
        assert result.data["matches"] == ["alice", "bob"]

    def test_extract_case_insensitive(self, text_extract: TextExtractPrimitive) -> None:
        import re
        result = text_extract.execute(
            {"text": "Hello HELLO hello", "pattern": r"hello", "flags": re.IGNORECASE}, {}
        )
        assert result.data["matches"] == ["Hello", "HELLO", "hello"]

    def test_missing_text_raises_value_error(self, text_extract: TextExtractPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'text'"):
            text_extract.validate_args({})

    def test_missing_pattern_raises_value_error(self, text_extract: TextExtractPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'pattern'"):
            text_extract.validate_args({"text": "hi"})

    def test_invalid_pattern_raises_value_error(self, text_extract: TextExtractPrimitive) -> None:
        with pytest.raises(ValueError, match="valid regex"):
            text_extract.validate_args({"text": "hi", "pattern": "["})
