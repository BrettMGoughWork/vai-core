"""Tests for stdlib.file.stat primitive (Phase 3.18.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.capabilities.primitives.stdlib.file_stat import FileStatPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> FileStatPrimitive:
    return FileStatPrimitive()


class TestFileStatValidate:
    """Tests for FileStatPrimitive.validate_args."""

    def test_valid_args(self, prim: FileStatPrimitive, tmp_path: Path) -> None:
        prim.validate_args({"path": str(tmp_path / "f.txt")})

    def test_missing_path(self, prim: FileStatPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'path' key"):
            prim.validate_args({})

    def test_wrong_type(self, prim: FileStatPrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must be a string"):
            prim.validate_args({"path": 42})

    def test_empty_path(self, prim: FileStatPrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must not be empty"):
            prim.validate_args({"path": ""})

    def test_null_bytes(self, prim: FileStatPrimitive) -> None:
        with pytest.raises(ValueError, match="must not contain null bytes"):
            prim.validate_args({"path": "valid\x00file"})

    def test_not_a_dict(self, prim: FileStatPrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestFileStatExecute:
    """Tests for FileStatPrimitive.execute."""

    def test_stat_file_returns_metadata(self, prim: FileStatPrimitive, tmp_path: Path) -> None:
        path = tmp_path / "test.txt"
        path.write_text("hello world", encoding="utf-8")
        result = prim.execute({"path": str(path)}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert isinstance(result.data, dict)
        assert result.data.get("size", -1) >= 0
        assert isinstance(result.data.get("modified"), str)
        assert result.data["modified"]  # non-empty isoformat string
        assert isinstance(result.data.get("created"), str)
        assert result.data["created"]
        assert result.error is None

    def test_nonexistent_file(self, prim: FileStatPrimitive, tmp_path: Path) -> None:
        path = str(tmp_path / "missing.txt")
        result = prim.execute({"path": path}, {})
        assert result.status == "error"
        assert result.error is not None
        assert "FileNotFoundError" in result.error
