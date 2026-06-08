"""Tests for stdlib.file.exists primitive (Phase 3.18.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.capabilities.primitives.stdlib.file_exists import FileExistsPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> FileExistsPrimitive:
    return FileExistsPrimitive()


class TestFileExistsValidate:
    """Tests for FileExistsPrimitive.validate_args."""

    def test_valid_args(self, prim: FileExistsPrimitive, tmp_path: Path) -> None:
        prim.validate_args({"path": str(tmp_path / "f.txt")})

    def test_missing_path(self, prim: FileExistsPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'path' key"):
            prim.validate_args({})

    def test_wrong_type(self, prim: FileExistsPrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must be a string"):
            prim.validate_args({"path": 42})

    def test_empty_path(self, prim: FileExistsPrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must not be empty"):
            prim.validate_args({"path": ""})

    def test_null_bytes(self, prim: FileExistsPrimitive) -> None:
        with pytest.raises(ValueError, match="must not contain null bytes"):
            prim.validate_args({"path": "valid\x00file"})

    def test_not_a_dict(self, prim: FileExistsPrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestFileExistsExecute:
    """Tests for FileExistsPrimitive.execute."""

    def test_file_exists(self, prim: FileExistsPrimitive, tmp_path: Path) -> None:
        path = tmp_path / "test.txt"
        path.write_text("hello", encoding="utf-8")
        result = prim.execute({"path": str(path)}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data == {"exists": True}
        assert result.error is None

    def test_file_deleted_returns_false(self, prim: FileExistsPrimitive, tmp_path: Path) -> None:
        path = tmp_path / "temp.txt"
        path.write_text("hello", encoding="utf-8")
        path.unlink()
        result = prim.execute({"path": str(path)}, {})
        assert result.status == "success"
        assert result.data == {"exists": False}

    def test_directory_path(self, prim: FileExistsPrimitive, tmp_path: Path) -> None:
        result = prim.execute({"path": str(tmp_path)}, {})
        assert result.status == "success"
        assert result.data == {"exists": True}
