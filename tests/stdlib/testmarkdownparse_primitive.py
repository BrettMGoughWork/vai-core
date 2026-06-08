"""Tests for stdlib.markdown.parse primitive (Phase 3.18.2)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.markdown_parse import MarkdownParsePrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> MarkdownParsePrimitive:
    return MarkdownParsePrimitive()


class TestMarkdownParseValidate:
    def test_valid_args(self, prim: MarkdownParsePrimitive) -> None:
        prim.validate_args({"text": "# Hello"})

    def test_missing_text_raises(self, prim: MarkdownParsePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'text' key"):
            prim.validate_args({})

    def test_non_string_text_raises(self, prim: MarkdownParsePrimitive) -> None:
        with pytest.raises(ValueError, match="'text' must be a string"):
            prim.validate_args({"text": 42})

    def test_empty_text_raises(self, prim: MarkdownParsePrimitive) -> None:
        with pytest.raises(ValueError, match="'text' must not be empty"):
            prim.validate_args({"text": ""})

    def test_args_not_a_dict_raises(self, prim: MarkdownParsePrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestMarkdownParseExecute:
    def test_parse_heading(self, prim: MarkdownParsePrimitive) -> None:
        result = prim.execute({"text": "# Hello"}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data is not None
        assert "<h1>" in result.data["html"]
        assert "Hello" in result.data["html"]
        assert result.error is None

    def test_parse_paragraph(self, prim: MarkdownParsePrimitive) -> None:
        result = prim.execute({"text": "Hello world"}, {})
        assert result.status == "success"
        assert "<p>" in result.data["html"]

    def test_parse_empty_string(self, prim: MarkdownParsePrimitive) -> None:
        """Empty string raises validation error before execution."""
        with pytest.raises(ValueError, match="'text' must not be empty"):
            prim.execute({"text": ""}, {})
