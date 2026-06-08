"""Tests for stdlib.html.select primitive (Phase 3.18.2)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.html_select import HtmlSelectPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> HtmlSelectPrimitive:
    return HtmlSelectPrimitive()


class TestHtmlSelectValidate:
    def test_valid_args(self, prim: HtmlSelectPrimitive) -> None:
        prim.validate_args({"html": "<p>a</p>", "selector": "p"})

    def test_missing_html_raises(self, prim: HtmlSelectPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'html' key"):
            prim.validate_args({"selector": "p"})

    def test_missing_selector_raises(self, prim: HtmlSelectPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'selector' key"):
            prim.validate_args({"html": "<p>a</p>"})

    def test_html_not_string_raises(self, prim: HtmlSelectPrimitive) -> None:
        with pytest.raises(ValueError, match="'html' must be a string"):
            prim.validate_args({"html": 42, "selector": "p"})

    def test_selector_not_string_raises(self, prim: HtmlSelectPrimitive) -> None:
        with pytest.raises(ValueError, match="'selector' must be a string"):
            prim.validate_args({"html": "<p>a</p>", "selector": 42})

    def test_empty_selector_raises(self, prim: HtmlSelectPrimitive) -> None:
        with pytest.raises(ValueError, match="'selector' must not be empty"):
            prim.validate_args({"html": "<p>a</p>", "selector": ""})

    def test_args_not_a_dict_raises(self, prim: HtmlSelectPrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestHtmlSelectExecute:
    def test_select_matching_elements(self, prim: HtmlSelectPrimitive) -> None:
        result = prim.execute({"html": "<p>a</p><p>b</p>", "selector": "p"}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data is not None
        assert len(result.data["matches"]) == 2
        assert result.error is None

    def test_select_no_matches(self, prim: HtmlSelectPrimitive) -> None:
        result = prim.execute({"html": "<p>a</p><p>b</p>", "selector": "span"}, {})
        assert result.status == "success"
        assert result.data["matches"] == []

    def test_invalid_selector_returns_error(self, prim: HtmlSelectPrimitive) -> None:
        result = prim.execute({"html": "<p>a</p>", "selector": "###invalid"}, {})
        assert result.status == "error"
        assert result.error is not None
