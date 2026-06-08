"""Tests for stdlib.file.glob primitive (Phase 3.18.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.capabilities.primitives.stdlib.file_glob import FileGlobPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> FileGlobPrimitive:
    return FileGlobPrimitive()


class TestFileGlobValidate:
    """Tests for FileGlobPrimitive.validate_args."""

    def test_valid_args(self, prim: FileGlobPrimitive, tmp_path: Path) -> None:
        prim.validate_args({"pattern": str(tmp_path / "*.txt")})

    def test_missing_pattern(self, prim: FileGlobPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'pattern' key"):
            prim.validate_args({})

    def test_wrong_type(self, prim: FileGlobPrimitive) -> None:
        with pytest.raises(ValueError, match="'pattern' must be a string"):
            prim.validate_args({"pattern": 42})

    def test_empty_pattern(self, prim: FileGlobPrimitive) -> None:
        with pytest.raises(ValueError, match="'pattern' must not be empty"):
            prim.validate_args({"pattern": ""})

    def test_not_a_dict(self, prim: FileGlobPrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestFileGlobExecute:
    """Tests for FileGlobPrimitive.execute."""

    def test_glob_txt_files(self, prim: FileGlobPrimitive, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a", encoding="utf-8")
        (tmp_path / "b.txt").write_text("b", encoding="utf-8")
        (tmp_path / "c.csv").write_text("c", encoding="utf-8")
        pattern = str(tmp_path / "*.txt")
        result = prim.execute({"pattern": pattern}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert isinstance(result.data, dict)
        paths = result.data.get("paths", [])
        assert len(paths) == 2
        assert str(tmp_path / "a.txt") in paths
        assert str(tmp_path / "b.txt") in paths
        assert result.error is None

    def test_no_match_returns_empty(self, prim: FileGlobPrimitive, tmp_path: Path) -> None:
        pattern = str(tmp_path / "*.xyz")
        result = prim.execute({"pattern": pattern}, {})
        assert result.status == "success"
        assert result.data == {"paths": []}
