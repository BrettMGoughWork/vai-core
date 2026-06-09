"""Tests for stdlib.doc.extractmetadata primitive (Phase 3.18.7)."""

from __future__ import annotations

import os
import tempfile

import pytest

from src.capabilities.primitives.stdlib.doc_extractmetadata import DocExtractMetadataPrimitive


@pytest.fixture
def doc_extractmetadata() -> DocExtractMetadataPrimitive:
    return DocExtractMetadataPrimitive()


class TestDocExtractMetadataPrimitive:
    """Tests for DocExtractMetadataPrimitive.validate_args and execute."""

    def test_extract_file_metadata(self, doc_extractmetadata: DocExtractMetadataPrimitive) -> None:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"hello world")
            path = f.name
        try:
            result = doc_extractmetadata.execute({"path": path}, {})
            assert result.status == "success"
            assert result.data["filename"] == os.path.basename(path)
            assert result.data["size_bytes"] == 11
            assert result.data["is_file"] is True
            assert result.data["is_directory"] is False
            assert result.data["extension"] == ".txt"
        finally:
            os.unlink(path)

    def test_extract_directory_metadata(self, doc_extractmetadata: DocExtractMetadataPrimitive) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = doc_extractmetadata.execute({"path": tmpdir}, {})
            assert result.status == "success"
            assert result.data["is_directory"] is True
            assert result.data["is_file"] is False

    def test_file_not_found_returns_error(self, doc_extractmetadata: DocExtractMetadataPrimitive) -> None:
        result = doc_extractmetadata.execute({"path": "/nonexistent/path/xyz.abc"}, {})
        assert result.status == "error"

    def test_missing_path_raises_value_error(self, doc_extractmetadata: DocExtractMetadataPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'path'"):
            doc_extractmetadata.validate_args({})

    def test_path_not_string_raises_value_error(self, doc_extractmetadata: DocExtractMetadataPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            doc_extractmetadata.validate_args({"path": 123})
