"""Tests for stdlib.base64.encode primitive (Phase 3.18.10)."""

from __future__ import annotations

import base64
import os
import tempfile

import pytest

from src.capabilities.primitives.stdlib.base64_encode import Base64EncodePrimitive


@pytest.fixture
def base64_encode() -> Base64EncodePrimitive:
    return Base64EncodePrimitive()


class TestBase64EncodePrimitive:
    """Tests for Base64EncodePrimitive.validate_args and execute."""

    def test_encode_string(self, base64_encode: Base64EncodePrimitive) -> None:
        result = base64_encode.execute({"data": "hello world"}, {})
        assert result.status == "success"
        assert result.data["encoded"] == base64.b64encode(b"hello world").decode()
        assert result.data["original_size"] == 11

    def test_encode_empty_string(self, base64_encode: Base64EncodePrimitive) -> None:
        result = base64_encode.execute({"data": ""}, {})
        assert result.status == "success"
        assert result.data["encoded"] == ""

    def test_encode_file(self, base64_encode: Base64EncodePrimitive) -> None:
        fd, path = tempfile.mkstemp()
        os.write(fd, b"binary content \x00\x01\x02")
        os.close(fd)
        try:
            result = base64_encode.execute({"file": path}, {})
            assert result.status == "success"
            expected = base64.b64encode(b"binary content \x00\x01\x02").decode()
            assert result.data["encoded"] == expected
        finally:
            os.unlink(path)

    def test_encode_nonexistent_file(self, base64_encode: Base64EncodePrimitive) -> None:
        result = base64_encode.execute({"file": "/nonexistent/file.bin"}, {})
        assert result.status == "error"

    def test_decode_roundtrip(self, base64_encode: Base64EncodePrimitive) -> None:
        original = "test data 123"
        result = base64_encode.execute({"data": original}, {})
        decoded = base64.b64decode(result.data["encoded"]).decode()
        assert decoded == original

    def test_missing_both_data_and_file_raises_value_error(self, base64_encode: Base64EncodePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'data' or 'file'"):
            base64_encode.validate_args({})

    def test_data_not_string_raises_value_error(self, base64_encode: Base64EncodePrimitive) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            base64_encode.validate_args({"data": 99})
