"""Tests for stdlib.file.append primitive (Phase 3.18.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.capabilities.primitives.stdlib.file_append import FileAppendPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> FileAppendPrimitive:
    return FileAppendPrimitive()


class TestFileAppendValidate:
    """Tests for FileAppendPrimitive.validate_args."""

    def test_valid_args(self, prim: FileAppendPrimitive, tmp_path: Path) -> None:
        prim.validate_args({"path": str(tmp_path / "f.txt"), "content": "data"})

    def test_missing_path(self, prim: FileAppendPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'path' key"):
            prim.validate_args({"content": "data"})

    def test_missing_content(self, prim: FileAppendPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'content' key"):
            prim.validate_args({"path": "/tmp/x.txt"})

    def test_wrong_type_path(self, prim: FileAppendPrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must be a string"):
            prim.validate_args({"path": 42, "content": "data"})

    def test_wrong_type_content(self, prim: FileAppendPrimitive) -> None:
        with pytest.raises(ValueError, match="'content' must be a string"):
            prim.validate_args({"path": "/tmp/x.txt", "content": 42})

    def test_empty_path(self, prim: FileAppendPrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must not be empty"):
            prim.validate_args({"path": "", "content": "data"})

    def test_null_bytes(self, prim: FileAppendPrimitive) -> None:
        with pytest.raises(ValueError, match="must not contain null bytes"):
            prim.validate_args({"path": "valid\x00file", "content": "data"})

    def test_not_a_dict(self, prim: FileAppendPrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestFileAppendExecute:
    """Tests for FileAppendPrimitive.execute."""

    def test_append_to_file_and_read_back(self, prim: FileAppendPrimitive, tmp_path: Path) -> None:
        path = tmp_path / "test.txt"
        path.write_text("hello\n", encoding="utf-8")
        result = prim.execute({"path": str(path), "content": "world"}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data == {"ok": True}
        assert result.error is None
        assert path.read_text(encoding="utf-8") == "hello\nworld"

    def test_nonexistent_parent_dir(self, prim: FileAppendPrimitive, tmp_path: Path) -> None:
        path = str(tmp_path / "nonexistent" / "file.txt")
        result = prim.execute({"path": path, "content": "data"}, {})
        assert result.status == "error"
        assert result.error is not None
        assert "FileNotFoundError" in result.error
