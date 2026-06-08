"""Tests for stdlib.csv.read primitive (Phase 3.18.2)."""

from __future__ import annotations

import csv
import tempfile

import pytest

from src.capabilities.primitives.stdlib.csv_read import CsvReadPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> CsvReadPrimitive:
    return CsvReadPrimitive()


class TestCsvReadValidate:
    def test_valid_path(self, prim: CsvReadPrimitive) -> None:
        prim.validate_args({"path": "data.csv"})

    def test_missing_path_raises(self, prim: CsvReadPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'path' key"):
            prim.validate_args({})

    def test_non_string_path_raises(self, prim: CsvReadPrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must be a string"):
            prim.validate_args({"path": 42})

    def test_empty_path_raises(self, prim: CsvReadPrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must not be empty"):
            prim.validate_args({"path": ""})

    def test_null_bytes_raises(self, prim: CsvReadPrimitive) -> None:
        with pytest.raises(ValueError, match="must not contain null bytes"):
            prim.validate_args({"path": "valid\x00invalid"})

    def test_args_not_a_dict_raises(self, prim: CsvReadPrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestCsvReadExecute:
    def test_read_csv_file(self, prim: CsvReadPrimitive) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("a,b,c\n1,2,3\n4,5,6\n")
            path = f.name
        try:
            result = prim.execute({"path": path}, {})
            assert isinstance(result, PrimitiveResult)
            assert result.status == "success"
            assert result.data == {"rows": [["a", "b", "c"], ["1", "2", "3"], ["4", "5", "6"]]}
            assert result.error is None
        finally:
            import os
            os.unlink(path)

    def test_nonexistent_file_returns_error(self, prim: CsvReadPrimitive) -> None:
        result = prim.execute({"path": "nonexistent.csv"}, {})
        assert result.status == "error"
        assert result.error is not None
        assert "FileNotFoundError" in result.error

    def test_empty_csv_returns_empty_rows(self, prim: CsvReadPrimitive) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            path = f.name
        try:
            result = prim.execute({"path": path}, {})
            assert result.status == "success"
            assert result.data == {"rows": []}
        finally:
            import os
            os.unlink(path)
