"""Tests for stdlib.csv.write primitive (Phase 3.18.2)."""

from __future__ import annotations

import csv
import os
import tempfile

import pytest

from src.capabilities.primitives.stdlib.csv_write import CsvWritePrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> CsvWritePrimitive:
    return CsvWritePrimitive()


class TestCsvWriteValidate:
    def test_valid_args(self, prim: CsvWritePrimitive) -> None:
        prim.validate_args({"path": "out.csv", "rows": [["a", "b"], ["1", "2"]]})

    def test_missing_path_raises(self, prim: CsvWritePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'path' key"):
            prim.validate_args({"rows": []})

    def test_non_string_path_raises(self, prim: CsvWritePrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must be a string"):
            prim.validate_args({"path": 42, "rows": []})

    def test_empty_path_raises(self, prim: CsvWritePrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must not be empty"):
            prim.validate_args({"path": "", "rows": []})

    def test_null_bytes_raises(self, prim: CsvWritePrimitive) -> None:
        with pytest.raises(ValueError, match="must not contain null bytes"):
            prim.validate_args({"path": "valid\x00invalid", "rows": []})

    def test_missing_rows_raises(self, prim: CsvWritePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'rows' key"):
            prim.validate_args({"path": "out.csv"})

    def test_rows_not_list_raises(self, prim: CsvWritePrimitive) -> None:
        with pytest.raises(ValueError, match="'rows' must be a list"):
            prim.validate_args({"path": "out.csv", "rows": "not_a_list"})

    def test_args_not_a_dict_raises(self, prim: CsvWritePrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestCsvWriteExecute:
    def test_write_and_read_back(self, prim: CsvWritePrimitive) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            path = f.name
        try:
            rows = [["a", "b"], ["1", "2"], ["3", "4"]]
            result = prim.execute({"path": path, "rows": rows}, {})
            assert isinstance(result, PrimitiveResult)
            assert result.status == "success"
            assert result.data == {"ok": True}

            with open(path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                written = list(reader)
            assert written == rows
        finally:
            os.unlink(path)

    def test_empty_rows_writes_header_only(self, prim: CsvWritePrimitive) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            path = f.name
        try:
            result = prim.execute({"path": path, "rows": []}, {})
            assert result.status == "success"

            with open(path, "r", encoding="utf-8", newline="") as f:
                content = f.read()
            # Empty rows writes nothing (no data rows)
            assert content == ""
        finally:
            os.unlink(path)

    def test_bad_parent_dir_returns_error(self, prim: CsvWritePrimitive) -> None:
        result = prim.execute(
            {"path": "C:\\nonexistent_dir_xyz\\output.csv", "rows": [["a"]]}, {}
        )
        assert result.status == "error"
        assert result.error is not None

    def test_no_side_effects(self, prim: CsvWritePrimitive) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            path = f.name
        try:
            result = prim.execute({"path": path, "rows": [["x"]]}, {})
            assert result.side_effects == []
        finally:
            os.unlink(path)
