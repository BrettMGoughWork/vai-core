import pytest

from src.primitives.runtime.validator import validate_structural
from src.core.types.errors import ValidationError


def test_validate_structural_accepts_valid_args():
    schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "count": {"type": "integer"},
        },
        "required": ["text", "count"],
    }

    validate_structural(schema, {"text": "ok", "count": 2})


def test_validate_structural_rejects_missing_required_field():
    schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    with pytest.raises(ValidationError, match="Missing required field: text"):
        validate_structural(schema, {})


def test_validate_structural_rejects_unknown_field():
    schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    with pytest.raises(ValidationError, match="Unknown field: extra"):
        validate_structural(schema, {"text": "ok", "extra": 1})


def test_validate_structural_rejects_wrong_type():
    schema = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
    }

    with pytest.raises(ValidationError, match="must be integer"):
        validate_structural(schema, {"count": "2"})
