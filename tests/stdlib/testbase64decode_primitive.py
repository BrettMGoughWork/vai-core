"""Tests for stdlib.base64.decode primitive (Phase 3.18.10)."""

from __future__ import annotations

import base64

import pytest

from src.capabilities.primitives.stdlib.base64_decode import Base64DecodePrimitive


@pytest.fixture
def base64_decode() -> Base64DecodePrimitive:
    return Base64DecodePrimitive()


class TestBase64DecodePrimitive:
    """Tests for Base64DecodePrimitive.validate_args and execute."""

    def test_decode_valid(self, base64_decode: Base64DecodePrimitive) -> None:
        encoded = base64.b64encode(b"hello world").decode()
        result = base64_decode.execute({"data": encoded}, {})
        assert result.status == "success"
        assert result.data["text"] == "hello world"
        assert result.data["decoded_size"] == 11

    def test_decode_empty(self, base64_decode: Base64DecodePrimitive) -> None:
        result = base64_decode.execute({"data": ""}, {})
        assert result.status == "success"
        assert result.data["text"] == ""
        assert result.data["decoded_size"] == 0

    def test_decode_binary_content(self, base64_decode: Base64DecodePrimitive) -> None:
        original = b"\x00\x01\x02\xff\xfe\xfd"
        encoded = base64.b64encode(original).decode()
        result = base64_decode.execute({"data": encoded}, {})
        assert result.status == "success"
        assert result.data["decoded_size"] == 6

    def test_decode_invalid_raises_error(self, base64_decode: Base64DecodePrimitive) -> None:
        result = base64_decode.execute({"data": "!!!not valid base64!!!"}, {})
        assert result.status == "error"

    def test_roundtrip(self, base64_decode: Base64DecodePrimitive) -> None:
        original = "test data 123!@#"
        encoded = base64.b64encode(original.encode()).decode()
        decoded = base64_decode.execute({"data": encoded}, {})
        assert decoded.data["text"] == original

    def test_missing_data_raises_value_error(self, base64_decode: Base64DecodePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'data'"):
            base64_decode.validate_args({})

    def test_data_not_string_raises_value_error(self, base64_decode: Base64DecodePrimitive) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            base64_decode.validate_args({"data": 123})
