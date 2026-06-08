"""Tests for stdlib.pdf.extracttext primitive (Phase 3.18.2)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.pdf_extracttext import PdfExtracttextPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> PdfExtracttextPrimitive:
    return PdfExtracttextPrimitive()


class TestPdfExtracttextValidate:
    def test_valid_path(self, prim: PdfExtracttextPrimitive) -> None:
        prim.validate_args({"path": "test.pdf"})

    def test_missing_path_raises(self, prim: PdfExtracttextPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'path' key"):
            prim.validate_args({})

    def test_non_string_path_raises(self, prim: PdfExtracttextPrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must be a string"):
            prim.validate_args({"path": 42})

    def test_empty_path_raises(self, prim: PdfExtracttextPrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must not be empty"):
            prim.validate_args({"path": ""})

    def test_null_bytes_raises(self, prim: PdfExtracttextPrimitive) -> None:
        with pytest.raises(ValueError, match="must not contain null bytes"):
            prim.validate_args({"path": "valid\x00invalid"})

    def test_args_not_a_dict_raises(self, prim: PdfExtracttextPrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestPdfExtracttextExecute:
    def test_nonexistent_file_returns_error(self, prim: PdfExtracttextPrimitive) -> None:
        result = prim.execute({"path": "nonexistent.pdf"}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "error"
        assert result.error is not None
        assert "FileNotFoundError" in result.error or "fitz" in result.error.lower() or "not found" in result.error.lower()

    def test_no_side_effects(self, prim: PdfExtracttextPrimitive) -> None:
        result = prim.execute({"path": "nonexistent.pdf"}, {})
        assert result.side_effects == []
