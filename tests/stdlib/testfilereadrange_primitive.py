"""Tests for stdlib.file.readrange primitive (Phase 3.18.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.capabilities.primitives.stdlib.file_readrange import FileReadrangePrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def prim() -> FileReadrangePrimitive:
    return FileReadrangePrimitive()


class TestFileReadrangeValidate:
    """Tests for FileReadrangePrimitive.validate_args."""

    def test_valid_args(self, prim: FileReadrangePrimitive, tmp_path: Path) -> None:
        prim.validate_args({"path": str(tmp_path / "f.txt"), "start": 0, "end": 5})

    def test_missing_path(self, prim: FileReadrangePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'path' key"):
            prim.validate_args({"start": 0, "end": 5})

    def test_missing_start(self, prim: FileReadrangePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'start' key"):
            prim.validate_args({"path": "/tmp/x.txt", "end": 5})

    def test_missing_end(self, prim: FileReadrangePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'end' key"):
            prim.validate_args({"path": "/tmp/x.txt", "start": 0})

    def test_wrong_type_path(self, prim: FileReadrangePrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must be a string"):
            prim.validate_args({"path": 42, "start": 0, "end": 5})

    def test_wrong_type_start(self, prim: FileReadrangePrimitive) -> None:
        with pytest.raises(ValueError, match="'start' must be an integer"):
            prim.validate_args({"path": "/tmp/x.txt", "start": "0", "end": 5})

    def test_start_negative(self, prim: FileReadrangePrimitive) -> None:
        with pytest.raises(ValueError, match="'start' must be >= 0"):
            prim.validate_args({"path": "/tmp/x.txt", "start": -1, "end": 5})

    def test_end_not_greater_than_start(self, prim: FileReadrangePrimitive) -> None:
        with pytest.raises(ValueError, match="must be greater than 'start'"):
            prim.validate_args({"path": "/tmp/x.txt", "start": 5, "end": 5})

    def test_empty_path(self, prim: FileReadrangePrimitive) -> None:
        with pytest.raises(ValueError, match="'path' must not be empty"):
            prim.validate_args({"path": "", "start": 0, "end": 5})

    def test_null_bytes(self, prim: FileReadrangePrimitive) -> None:
        with pytest.raises(ValueError, match="must not contain null bytes"):
            prim.validate_args({"path": "valid\x00file", "start": 0, "end": 5})

    def test_not_a_dict(self, prim: FileReadrangePrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            prim.validate_args("bad")  # type: ignore[arg-type]


class TestFileReadrangeExecute:
    """Tests for FileReadrangePrimitive.execute."""

    def test_readrange_zero_to_five(self, prim: FileReadrangePrimitive, tmp_path: Path) -> None:
        path = tmp_path / "test.txt"
        path.write_text("hello world\nline 2\n", encoding="utf-8")
        result = prim.execute({"path": str(path), "start": 0, "end": 5}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data == {"content": "hello"}
        assert result.error is None

    def test_nonexistent_file(self, prim: FileReadrangePrimitive, tmp_path: Path) -> None:
        path = str(tmp_path / "missing.txt")
        result = prim.execute({"path": path, "start": 0, "end": 5}, {})
        assert result.status == "error"
        assert result.error is not None
        assert "FileNotFoundError" in result.error
