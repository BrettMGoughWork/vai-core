"""Tests for stdlib.file.write primitive (Phase 3.7.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.capabilities.primitives.stdlib.file_write import FileWritePrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def writer() -> FileWritePrimitive:
    """Real FileWritePrimitive instance."""
    return FileWritePrimitive()


class TestFileWritePrimitiveValidate:
    """Tests for FileWritePrimitive.validate_args."""

    def test_valid_args_passes(self, writer: FileWritePrimitive, tmp_path: Path) -> None:
        """Valid path and content pass validation."""
        writer.validate_args({"path": str(tmp_path / "out.txt"), "content": "data"})

    def test_missing_path_raises(self, writer: FileWritePrimitive) -> None:
        """Missing 'path' key raises ValueError."""
        with pytest.raises(ValueError, match="must contain 'path' key"):
            writer.validate_args({"content": "data"})

    def test_missing_content_raises(self, writer: FileWritePrimitive) -> None:
        """Missing 'content' key raises ValueError."""
        with pytest.raises(ValueError, match="must contain 'content' key"):
            writer.validate_args({"path": "/tmp/x.txt"})

    def test_non_string_path_raises(self, writer: FileWritePrimitive) -> None:
        """Non-string path raises ValueError."""
        with pytest.raises(ValueError, match="'path' must be a string"):
            writer.validate_args({"path": 42, "content": "data"})

    def test_non_string_content_raises(self, writer: FileWritePrimitive) -> None:
        """Non-string content raises ValueError."""
        with pytest.raises(ValueError, match="'content' must be a string"):
            writer.validate_args({"path": "/tmp/x.txt", "content": 42})

    def test_null_byte_raises(self, writer: FileWritePrimitive) -> None:
        """Null byte in path raises ValueError."""
        with pytest.raises(ValueError, match="must not contain null bytes"):
            writer.validate_args({"path": "valid\x00invalid", "content": "data"})

    def test_empty_path_raises(self, writer: FileWritePrimitive) -> None:
        """Empty path raises ValueError."""
        with pytest.raises(ValueError, match="'path' must not be empty"):
            writer.validate_args({"path": "", "content": "data"})

    def test_args_not_a_dict_raises(self, writer: FileWritePrimitive) -> None:
        """Non-dict args raises ValueError."""
        with pytest.raises(ValueError, match="args must be a dict"):
            writer.validate_args("bad")  # type: ignore[arg-type]


class TestFileWritePrimitiveExecute:
    """Tests for FileWritePrimitive.execute."""

    def test_writes_content_to_file(self, writer: FileWritePrimitive, tmp_path: Path) -> None:
        """Writing creates a file with the correct content."""
        path = str(tmp_path / "out.txt")
        result = writer.execute({"path": path, "content": "hello world"}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data == {"ok": True}
        assert tmp_path.joinpath("out.txt").read_text(encoding="utf-8") == "hello world"

    def test_overwrites_existing_file(self, writer: FileWritePrimitive, tmp_path: Path) -> None:
        """Writing overwrites an existing file."""
        path = str(tmp_path / "overwrite.txt")
        tmp_path.joinpath("overwrite.txt").write_text("original", encoding="utf-8")
        writer.execute({"path": path, "content": "replacement"}, {})
        assert tmp_path.joinpath("overwrite.txt").read_text(encoding="utf-8") == "replacement"

    def test_missing_directory_returns_error(self, writer: FileWritePrimitive, tmp_path: Path) -> None:
        """Writing to a non-existent directory returns FileNotFoundError."""
        path = str(tmp_path / "nonexistent" / "file.txt")
        result = writer.execute({"path": path, "content": "data"}, {})
        assert result.status == "error"
        assert result.error is not None
        assert "FileNotFoundError" in result.error

    def test_deterministic_output(self, writer: FileWritePrimitive, tmp_path: Path) -> None:
        """Repeated writes produce identical results."""
        path = str(tmp_path / "det.txt")
        args = {"path": path, "content": "data"}
        results = [writer.execute(args, {}) for _ in range(3)]
        assert all(r.status == "success" for r in results)
        assert all(r.data == {"ok": True} for r in results)

    def test_no_side_effects_list(self, writer: FileWritePrimitive, tmp_path: Path) -> None:
        """Primitive result has an empty side_effects list (side effects are real)."""
        path = str(tmp_path / "se.txt")
        result = writer.execute({"path": path, "content": "data"}, {})
        assert result.side_effects == []

    def test_input_is_not_mutated(self, writer: FileWritePrimitive, tmp_path: Path) -> None:
        """The input args dict is not modified."""
        args = {"path": str(tmp_path / "no_mut.txt"), "content": "data"}
        before = dict(args)
        writer.execute(args, {})
        assert args == before
