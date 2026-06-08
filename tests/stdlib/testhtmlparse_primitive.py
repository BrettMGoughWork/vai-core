"""Tests for stdlib.html.parse primitive (Phase 3.18.2)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.html_parse import HtmlParsePrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> HtmlParsePrimitive:
    return HtmlParsePrimitive()


class TestHtmlParseValidate:
    def test_valid_args(self, prim: HtmlParsePrimitive) -> None:
        prim.validate_args({"text": "<p>hi</p>"})

    def test_missing_text_raises(self, prim: HtmlParsePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'text' key"):
            prim.validate_args({})

    def test_non_string_text_raises(self, prim: HtmlParsePrimitive) -> None:
        with pytest.raises(ValueError, match="'text' must be a string"):
            prim.validate_args({"text": 42})

    def test_empty_text_raises(self, prim: HtmlParsePrimitive) -> None:
        with pytest.raises(ValueError, match="'text' must not be empty"):
            prim.validate_args({"text": ""})

    def test_args_not_a_dict_raises(self, prim: HtmlParsePrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestHtmlParseExecute:
    def test_parse_simple_html(self, prim: HtmlParsePrimitive) -> None:
        result = prim.execute({"text": "<p>hi</p>"}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data is not None
        assert "html" in result.data
        assert "text" in result.data
        assert "hi" in result.data["text"]
        assert result.error is None

    def test_parse_empty_string_raises(self, prim: HtmlParsePrimitive) -> None:
        """Empty string is rejected by validation before execution."""
        with pytest.raises(ValueError, match="'text' must not be empty"):
            prim.execute({"text": ""}, {})

    def test_no_side_effects(self, prim: HtmlParsePrimitive) -> None:
        result = prim.execute({"text": "<p>hello</p>"}, {})
        assert result.side_effects == []
