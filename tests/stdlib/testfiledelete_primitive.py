"""Tests for stdlib.file.delete primitive (Phase 3.18.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.capabilities.primitives.stdlib.file_delete import FileDeletePrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> FileDeletePrimitive:
    return FileDeletePrimitive()


class TestFileDeleteValidate:
    """Tests for FileDeletePrimitive.validate_args."""

    def test_valid_args(self, prim: FileDeletePrimitive, tmp_path: Path) -> None:
        prim.validate_args({"path": str(tmp_path / "f.txt")})

    def test_missing_path(self, prim: FileDeletePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'path' key"):
            prim.validate_args({})

    def test_wrong_type(self, prim: FileDeletePrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must be a string"):
            prim.validate_args({"path": 42})

    def test_empty_path(self, prim: FileDeletePrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must not be empty"):
            prim.validate_args({"path": ""})

    def test_null_bytes(self, prim: FileDeletePrimitive) -> None:
        with pytest.raises(ValueError, match="must not contain null bytes"):
            prim.validate_args({"path": "valid\x00file"})

    def test_not_a_dict(self, prim: FileDeletePrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestFileDeleteExecute:
    """Tests for FileDeletePrimitive.execute."""

    def test_delete_file_success(self, prim: FileDeletePrimitive, tmp_path: Path) -> None:
        path = tmp_path / "test.txt"
        path.write_text("hello", encoding="utf-8")
        assert path.exists()
        result = prim.execute({"path": str(path)}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data == {"ok": True}
        assert result.error is None
        assert not path.exists()

    def test_delete_already_deleted_returns_error(
        self, prim: FileDeletePrimitive, tmp_path: Path
    ) -> None:
        path = tmp_path / "missing.txt"
        result = prim.execute({"path": str(path)}, {})
        assert result.status == "error"
        assert result.error is not None
        assert "FileNotFoundError" in result.error
