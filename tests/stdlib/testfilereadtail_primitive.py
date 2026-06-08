"""Tests for stdlib.file.readtail primitive (Phase 3.18.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.capabilities.primitives.stdlib.file_readtail import FileReadtailPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> FileReadtailPrimitive:
    return FileReadtailPrimitive()


class TestFileReadtailValidate:
    """Tests for FileReadtailPrimitive.validate_args."""

    def test_valid_args(self, prim: FileReadtailPrimitive, tmp_path: Path) -> None:
        prim.validate_args({"path": str(tmp_path / "f.txt"), "lines": 3})

    def test_missing_path(self, prim: FileReadtailPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'path' key"):
            prim.validate_args({"lines": 3})

    def test_missing_lines(self, prim: FileReadtailPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'lines' key"):
            prim.validate_args({"path": "/tmp/x.txt"})

    def test_wrong_type_path(self, prim: FileReadtailPrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must be a string"):
            prim.validate_args({"path": 42, "lines": 3})

    def test_wrong_type_lines(self, prim: FileReadtailPrimitive) -> None:
        with pytest.raises(ValueError, match="'lines' must be an integer"):
            prim.validate_args({"path": "/tmp/x.txt", "lines": "3"})

    def test_lines_zero(self, prim: FileReadtailPrimitive) -> None:
        with pytest.raises(ValueError, match="'lines' must be positive"):
            prim.validate_args({"path": "/tmp/x.txt", "lines": 0})

    def test_lines_negative(self, prim: FileReadtailPrimitive) -> None:
        with pytest.raises(ValueError, match="'lines' must be positive"):
            prim.validate_args({"path": "/tmp/x.txt", "lines": -1})

    def test_empty_path(self, prim: FileReadtailPrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must not be empty"):
            prim.validate_args({"path": "", "lines": 3})

    def test_null_bytes(self, prim: FileReadtailPrimitive) -> None:
        with pytest.raises(ValueError, match="must not contain null bytes"):
            prim.validate_args({"path": "valid\x00file", "lines": 3})

    def test_not_a_dict(self, prim: FileReadtailPrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestFileReadtailExecute:
    """Tests for FileReadtailPrimitive.execute."""

    def test_readtail_three_lines(self, prim: FileReadtailPrimitive, tmp_path: Path) -> None:
        path = tmp_path / "test.txt"
        path.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")
        result = prim.execute({"path": str(path), "lines": 3}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data == {"content": "line3\nline4\nline5\n"}
        assert result.error is None

    def test_nonexistent_file(self, prim: FileReadtailPrimitive, tmp_path: Path) -> None:
        path = str(tmp_path / "missing.txt")
        result = prim.execute({"path": path, "lines": 3}, {})
        assert result.status == "error"
        assert result.error is not None
        assert "FileNotFoundError" in result.error
