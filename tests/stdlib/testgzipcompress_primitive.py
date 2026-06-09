"""Tests for stdlib.gzip.compress primitive (Phase 3.18.10)."""

from __future__ import annotations

import gzip
import os
import tempfile

import pytest

from src.capabilities.primitives.stdlib.gzip_compress import GzipCompressPrimitive


@pytest.fixture
def gzip_compress() -> GzipCompressPrimitive:
    return GzipCompressPrimitive()


class TestGzipCompressPrimitive:
    """Tests for GzipCompressPrimitive.validate_args and execute."""

    def test_compress_string_data(self, gzip_compress: GzipCompressPrimitive) -> None:
        result = gzip_compress.execute({"data": "hello world"}, {})
        assert result.status == "success"
        assert "compressed_base64" in result.data
        assert result.data["original_size"] == 11
        assert result.data["compressed_size"] > 0

    def test_compress_string_to_file(self, gzip_compress: GzipCompressPrimitive) -> None:
        fd, output_path = tempfile.mkstemp(suffix=".gz")
        os.close(fd)
        try:
            result = gzip_compress.execute(
                {"data": "hello world", "output": output_path}, {}
            )
            assert result.status == "success"
            assert os.path.getsize(output_path) > 0
        finally:
            os.unlink(output_path)

    def test_compress_file(self, gzip_compress: GzipCompressPrimitive) -> None:
        fd, input_path = tempfile.mkstemp(suffix=".txt")
        os.write(fd, b"repeated repeated repeated text")
        os.close(fd)
        try:
            result = gzip_compress.execute({"file": input_path}, {})
            assert result.status == "success"
            assert result.data["compressed_size"] > 0
            assert os.path.exists(result.data["output"])
        finally:
            os.unlink(input_path)
            if "output" in result.data and os.path.exists(result.data["output"]):
                os.unlink(result.data["output"])

    def test_compress_nonexistent_file(self, gzip_compress: GzipCompressPrimitive) -> None:
        result = gzip_compress.execute({"file": "/nonexistent/data.txt"}, {})
        assert result.status == "error"

    def test_missing_both_file_and_data_raises_value_error(self, gzip_compress: GzipCompressPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'file' or 'data'"):
            gzip_compress.validate_args({})

    def test_data_not_string_raises_value_error(self, gzip_compress: GzipCompressPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            gzip_compress.validate_args({"data": 123})

    def test_roundtrip_compress_decompress(self, gzip_compress: GzipCompressPrimitive) -> None:
        original = "hello world test data"
        result = gzip_compress.execute({"data": original}, {})
        assert result.status == "success"
        compressed = result.data["compressed_base64"]
        # decompress to verify
        import base64
        decompressed = gzip.decompress(base64.b64decode(compressed))
        assert decompressed.decode() == original
