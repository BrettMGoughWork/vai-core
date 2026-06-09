"""Tests for stdlib.doc.detecttype primitive (Phase 3.18.7)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.doc_detecttype import DocDetectTypePrimitive


@pytest.fixture
def doc_detecttype() -> DocDetectTypePrimitive:
    return DocDetectTypePrimitive()


class TestDocDetectTypePrimitive:
    """Tests for DocDetectTypePrimitive.validate_args and execute."""

    def test_detect_json(self, doc_detecttype: DocDetectTypePrimitive) -> None:
        result = doc_detecttype.execute({"path": "data.json"}, {})
        assert result.status == "success"
        assert result.data["category"] == "json"
        assert result.data["extension"] == ".json"
        assert result.data["is_binary"] is False

    def test_detect_python(self, doc_detecttype: DocDetectTypePrimitive) -> None:
        result = doc_detecttype.execute({"path": "script.py"}, {})
        assert result.data["category"] == "python"
        assert result.data["extension"] == ".py"

    def test_detect_image(self, doc_detecttype: DocDetectTypePrimitive) -> None:
        result = doc_detecttype.execute({"path": "photo.png"}, {})
        assert result.data["category"] == "image"

    def test_detect_no_extension(self, doc_detecttype: DocDetectTypePrimitive) -> None:
        result = doc_detecttype.execute({"path": "README"}, {})
        assert result.data["extension"] == ""
        assert result.data["category"] == "unknown"

    def test_detect_txt(self, doc_detecttype: DocDetectTypePrimitive) -> None:
        result = doc_detecttype.execute({"path": "notes.txt"}, {})
        assert result.data["category"] == "text"

    def test_missing_path_raises_value_error(self, doc_detecttype: DocDetectTypePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'path'"):
            doc_detecttype.validate_args({})

    def test_path_not_string_raises_value_error(self, doc_detecttype: DocDetectTypePrimitive) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            doc_detecttype.validate_args({"path": 42})
