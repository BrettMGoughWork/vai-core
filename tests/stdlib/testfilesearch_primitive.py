"""Tests for stdlib.file.search primitive (Phase 3.18.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.capabilities.primitives.stdlib.file_search import FileSearchPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> FileSearchPrimitive:
    return FileSearchPrimitive()


class TestFileSearchValidate:
    """Tests for FileSearchPrimitive.validate_args."""

    def test_valid_args(self, prim: FileSearchPrimitive, tmp_path: Path) -> None:
        prim.validate_args({"path": str(tmp_path / "f.txt"), "pattern": "hello"})

    def test_missing_path(self, prim: FileSearchPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'path' key"):
            prim.validate_args({"pattern": "hello"})

    def test_missing_pattern(self, prim: FileSearchPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'pattern' key"):
            prim.validate_args({"path": "/tmp/x.txt"})

    def test_wrong_type_path(self, prim: FileSearchPrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must be a string"):
            prim.validate_args({"path": 42, "pattern": "hello"})

    def test_wrong_type_pattern(self, prim: FileSearchPrimitive) -> None:
        with pytest.raises(ValueError, match="'pattern' must be a string"):
            prim.validate_args({"path": "/tmp/x.txt", "pattern": 42})

    def test_empty_pattern(self, prim: FileSearchPrimitive) -> None:
        with pytest.raises(ValueError, match="'pattern' must not be empty"):
            prim.validate_args({"path": "/tmp/x.txt", "pattern": ""})

    def test_empty_path(self, prim: FileSearchPrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must not be empty"):
            prim.validate_args({"path": "", "pattern": "hello"})

    def test_null_bytes(self, prim: FileSearchPrimitive) -> None:
        with pytest.raises(ValueError, match="must not contain null bytes"):
            prim.validate_args({"path": "valid\x00file", "pattern": "hello"})

    def test_not_a_dict(self, prim: FileSearchPrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestFileSearchExecute:
    """Tests for FileSearchPrimitive.execute."""

    def test_matching_pattern_finds_lines(self, prim: FileSearchPrimitive, tmp_path: Path) -> None:
        path = tmp_path / "test.txt"
        path.write_text("apple\nbanana\ncherry\ndate\n", encoding="utf-8")
        result = prim.execute({"path": str(path), "pattern": "a"}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data == {"matches": ["apple", "banana", "date"]}
        assert result.error is None

    def test_no_match_returns_empty(self, prim: FileSearchPrimitive, tmp_path: Path) -> None:
        path = tmp_path / "test.txt"
        path.write_text("one\ntwo\nthree\n", encoding="utf-8")
        result = prim.execute({"path": str(path), "pattern": "zzz"}, {})
        assert result.status == "success"
        assert result.data == {"matches": []}

    def test_nonexistent_file(self, prim: FileSearchPrimitive, tmp_path: Path) -> None:
        path = str(tmp_path / "missing.txt")
        result = prim.execute({"path": path, "pattern": "hello"}, {})
        assert result.status == "error"
        assert result.error is not None
        assert "FileNotFoundError" in result.error

    def test_invalid_regex(self, prim: FileSearchPrimitive, tmp_path: Path) -> None:
        path = tmp_path / "test.txt"
        path.write_text("content", encoding="utf-8")
        result = prim.execute({"path": str(path), "pattern": r"["}, {})
        assert result.status == "error"
        assert result.error is not None
        assert "re.error" in result.error
