"""Tests for stdlib.zip.extract primitive (Phase 3.18.10)."""

from __future__ import annotations

import os
import tempfile
import zipfile

import pytest

from src.capabilities.primitives.stdlib.zip_extract import ZipExtractPrimitive


@pytest.fixture
def zip_extract() -> ZipExtractPrimitive:
    return ZipExtractPrimitive()


class TestZipExtractPrimitive:
    """Tests for ZipExtractPrimitive.validate_args and execute."""

    def _create_test_zip(self, files: dict[str, str]) -> str:
        """Helper: create a temp zip with given filename→content mapping."""
        fd, path = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        with zipfile.ZipFile(path, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        return path

    def test_extract_zip(self, zip_extract: ZipExtractPrimitive) -> None:
        zip_path = self._create_test_zip({"hello.txt": "hello world", "data.json": '{"a":1}'})
        try:
            dest = tempfile.mkdtemp()
            result = zip_extract.execute({"archive": zip_path, "destination": dest}, {})
            assert result.status == "success"
            assert result.data["files_extracted"] == 2
            assert os.path.exists(os.path.join(dest, "hello.txt"))
            assert os.path.exists(os.path.join(dest, "data.json"))
        finally:
            os.unlink(zip_path)
            import shutil
            shutil.rmtree(dest, ignore_errors=True)

    def test_extract_nonexistent_archive(self, zip_extract: ZipExtractPrimitive) -> None:
        result = zip_extract.execute({"archive": "/nonexistent/archive.zip"}, {})
        assert result.status == "error"

    def test_extract_invalid_zip(self, zip_extract: ZipExtractPrimitive) -> None:
        fd, path = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        try:
            with open(path, "w") as f:
                f.write("not a zip")
            result = zip_extract.execute({"archive": path}, {})
            assert result.status == "error"
        finally:
            os.unlink(path)

    def test_missing_archive_raises_value_error(self, zip_extract: ZipExtractPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'archive'"):
            zip_extract.validate_args({})

    def test_archive_not_string_raises_value_error(self, zip_extract: ZipExtractPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            zip_extract.validate_args({"archive": 123})
