"""Tests for stdlib.zip.create primitive (Phase 3.18.10)."""

from __future__ import annotations

import os
import tempfile
import zipfile

import pytest

from src.capabilities.primitives.stdlib.zip_create import ZipCreatePrimitive


@pytest.fixture
def zip_create() -> ZipCreatePrimitive:
    return ZipCreatePrimitive()


class TestZipCreatePrimitive:
    """Tests for ZipCreatePrimitive.validate_args and execute."""

    def test_create_zip_from_files(self, zip_create: ZipCreatePrimitive) -> None:
        fd1, f1 = tempfile.mkstemp(suffix=".txt")
        os.write(fd1, b"hello")
        os.close(fd1)
        fd2, f2 = tempfile.mkstemp(suffix=".json")
        os.write(fd2, b'{"a":1}')
        os.close(fd2)
        fd3, zip_path = tempfile.mkstemp(suffix=".zip")
        os.close(fd3)
        try:
            result = zip_create.execute(
                {"archive": zip_path, "sources": [f1, f2]}, {}
            )
            assert result.status == "success"
            assert result.data["files_added"] == 2
            assert os.path.getsize(zip_path) > 0
            # verify contents
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
                assert os.path.basename(f1) in names
                assert os.path.basename(f2) in names
        finally:
            for p in [f1, f2, zip_path]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_create_zip_missing_source(self, zip_create: ZipCreatePrimitive) -> None:
        fd, zip_path = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        try:
            result = zip_create.execute(
                {"archive": zip_path, "sources": ["/nonexistent/file.txt"]}, {}
            )
            assert result.status == "error"
            assert "not found" in result.error.lower()
        finally:
            if os.path.exists(zip_path):
                os.unlink(zip_path)

    def test_missing_archive_raises_value_error(self, zip_create: ZipCreatePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'archive'"):
            zip_create.validate_args({"sources": ["f.txt"]})

    def test_missing_sources_raises_value_error(self, zip_create: ZipCreatePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'sources'"):
            zip_create.validate_args({"archive": "out.zip"})

    def test_sources_not_list_raises_value_error(self, zip_create: ZipCreatePrimitive) -> None:
        with pytest.raises(ValueError, match="must be a list"):
            zip_create.validate_args({"archive": "out.zip", "sources": "file.txt"})
