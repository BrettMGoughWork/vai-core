"""Tests for stdlib.file.list primitive (Phase 3.18.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.capabilities.primitives.stdlib.file_listdir import FileListdirPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> FileListdirPrimitive:
    return FileListdirPrimitive()


class TestFileListdirValidate:
    """Tests for FileListdirPrimitive.validate_args."""

    def test_valid_args(self, prim: FileListdirPrimitive, tmp_path: Path) -> None:
        prim.validate_args({"path": str(tmp_path)})

    def test_missing_path(self, prim: FileListdirPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'path' key"):
            prim.validate_args({})

    def test_wrong_type(self, prim: FileListdirPrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must be a string"):
            prim.validate_args({"path": 42})

    def test_empty_path(self, prim: FileListdirPrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must not be empty"):
            prim.validate_args({"path": ""})

    def test_null_bytes(self, prim: FileListdirPrimitive) -> None:
        with pytest.raises(ValueError, match="must not contain null bytes"):
            prim.validate_args({"path": "valid\x00dir"})

    def test_not_a_dict(self, prim: FileListdirPrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestFileListdirExecute:
    """Tests for FileListdirPrimitive.execute."""

    def test_list_temp_directory(self, prim: FileListdirPrimitive, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a", encoding="utf-8")
        (tmp_path / "b.txt").write_text("b", encoding="utf-8")
        result = prim.execute({"path": str(tmp_path)}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert isinstance(result.data, dict)
        entries = result.data.get("entries", [])
        assert "a.txt" in entries
        assert "b.txt" in entries
        assert result.error is None

    def test_nonexistent_directory(self, prim: FileListdirPrimitive, tmp_path: Path) -> None:
        path = str(tmp_path / "does_not_exist")
        result = prim.execute({"path": path}, {})
        assert result.status == "error"
        assert result.error is not None
        assert "FileNotFoundError" in result.error
