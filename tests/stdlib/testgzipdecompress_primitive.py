"""Tests for stdlib.gzip.decompress primitive (Phase 3.18.10)."""

from __future__ import annotations

import base64
import gzip
import os
import tempfile

import pytest

from src.capabilities.primitives.stdlib.gzip_decompress import GzipDecompressPrimitive


@pytest.fixture
def gzip_decompress() -> GzipDecompressPrimitive:
    return GzipDecompressPrimitive()


class TestGzipDecompressPrimitive:
    """Tests for GzipDecompressPrimitive.validate_args and execute."""

    def test_decompress_base64_data(self, gzip_decompress: GzipDecompressPrimitive) -> None:
        original = b"hello world test"
        compressed = base64.b64encode(gzip.compress(original)).decode()
        result = gzip_decompress.execute({"data": compressed}, {})
        assert result.status == "success"
        assert result.data["text"] == "hello world test"

    def test_decompress_file(self, gzip_decompress: GzipDecompressPrimitive) -> None:
        fd, gz_path = tempfile.mkstemp(suffix=".gz")
        os.close(fd)
        try:
            with gzip.open(gz_path, "wb") as f:
                f.write(b"file content here")
            result = gzip_decompress.execute({"file": gz_path}, {})
            assert result.status == "success"
            assert result.data["text"] == "file content here"
        finally:
            os.unlink(gz_path)

    def test_decompress_file_to_output(self, gzip_decompress: GzipDecompressPrimitive) -> None:
        fd, gz_path = tempfile.mkstemp(suffix=".gz")
        os.close(fd)
        fd2, output_path = tempfile.mkstemp(suffix=".txt")
        os.close(fd2)
        try:
            with gzip.open(gz_path, "wb") as f:
                f.write(b"output test")
            result = gzip_decompress.execute(
                {"file": gz_path, "output": output_path}, {}
            )
            assert result.status == "success"
            with open(output_path) as f:
                assert f.read() == "output test"
        finally:
            for p in [gz_path, output_path]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_decompress_nonexistent_file(self, gzip_decompress: GzipDecompressPrimitive) -> None:
        result = gzip_decompress.execute({"file": "/nonexistent/data.gz"}, {})
        assert result.status == "error"

    def test_decompress_invalid_data(self, gzip_decompress: GzipDecompressPrimitive) -> None:
        result = gzip_decompress.execute({"data": "not valid gzip data"}, {})
        assert result.status == "error"

    def test_missing_file_and_data_raises_value_error(self, gzip_decompress: GzipDecompressPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'file' or 'data'"):
            gzip_decompress.validate_args({})
