"""Tests for stdlib.file.read primitive (Phase 3.7.2)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.file_read import FileReadPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def reader() -> FileReadPrimitive:
    """Real FileReadPrimitive instance."""
    return FileReadPrimitive()


@pytest.fixture
def test_file(tmp_path) -> str:
    """Create a temporary UTF-8 file and return its path."""
    path = tmp_path / "test.txt"
    path.write_text("hello world\nline 2", encoding="utf-8")
    return str(path)


class TestFileReadPrimitiveValidate:
    """Tests for FileReadPrimitive.validate_args."""

    def test_valid_path_passes(self, reader: FileReadPrimitive, test_file: str) -> None:
        """A valid path passes validation."""
        reader.validate_args({"path": test_file})

    def test_missing_path_raises(self, reader: FileReadPrimitive) -> None:
        """Missing 'path' key raises ValueError."""
        with pytest.raises(ValueError, match="must contain 'path' key"):
            reader.validate_args({})

    def test_non_string_path_raises(self, reader: FileReadPrimitive) -> None:
        """A non-string path raises ValueError."""
        with pytest.raises(ValueError, match="'path' must be a string"):
            reader.validate_args({"path": 42})

    def test_empty_path_raises(self, reader: FileReadPrimitive) -> None:
        """An empty string path raises ValueError."""
        with pytest.raises(ValueError, match="'path' must not be empty"):
            reader.validate_args({"path": ""})

    def test_null_byte_raises(self, reader: FileReadPrimitive) -> None:
        """A path containing a null byte raises ValueError."""
        with pytest.raises(ValueError, match="must not contain null bytes"):
            reader.validate_args({"path": "valid\x00invalid"})

    def test_args_not_a_dict_raises(self, reader: FileReadPrimitive) -> None:
        """Non-dict args raises ValueError."""
        with pytest.raises(ValueError, match="args must be a dict"):
            reader.validate_args("not a dict")  # type: ignore[arg-type]


class TestFileReadPrimitiveExecute:
    """Tests for FileReadPrimitive.execute."""

    def test_reads_utf8_file(self, reader: FileReadPrimitive, test_file: str) -> None:
        """Reading a UTF-8 file returns correct content."""
        result = reader.execute({"path": test_file}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data == {"content": "hello world\nline 2"}
        assert result.error is None

    def test_missing_file_returns_error(self, reader: FileReadPrimitive, tmp_path) -> None:
        """A non-existent file returns FileNotFoundError error result."""
        path = str(tmp_path / "does_not_exist.txt")
        result = reader.execute({"path": path}, {})
        assert result.status == "error"
        assert result.error is not None
        assert "FileNotFoundError" in result.error

    def test_deterministic_output(self, reader: FileReadPrimitive, test_file: str) -> None:
        """Repeated reads of the same file return identical content."""
        results = [reader.execute({"path": test_file}, {}) for _ in range(3)]
        assert all(r.data == results[0].data for r in results)
        assert all(r.status == "success" for r in results)

    def test_no_side_effects(self, reader: FileReadPrimitive, test_file: str) -> None:
        """Primitive result has an empty side_effects list."""
        result = reader.execute({"path": test_file}, {})
        assert result.side_effects == []

    def test_context_is_ignored(self, reader: FileReadPrimitive, test_file: str) -> None:
        """The context dict is not used."""
        result = reader.execute({"path": test_file}, {"trace_id": "abc"})
        assert result.status == "success"

    def test_input_is_not_mutated(self, reader: FileReadPrimitive, test_file: str) -> None:
        """The input args dict is not modified."""
        args = {"path": test_file}
        before = dict(args)
        reader.execute(args, {})
        assert args == before
