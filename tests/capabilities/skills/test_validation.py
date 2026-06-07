"""
Tests for skill validation module (Phase 3.3.5).

Covers: validate_manifest_structure, validate_execution_args,
validate_step_result — both positive and negative cases.
"""

from __future__ import annotations

import pytest

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveType, PrimitiveResult
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.skills.manifest import SkillManifest
from src.capabilities.skills.skill import Skill
from src.capabilities.skills.validation import (
    validate_manifest_structure,
    validate_execution_args,
    validate_step_result,
)


# ---------------------------------------------------------------------------
# Fake primitive
# ---------------------------------------------------------------------------

class FakePrimitive(PrimitiveBase):
    """Minimal concrete primitive for validation testing."""

    def __init__(self, *, name: str, description: str = "") -> None:
        super().__init__(name=name, description=description, primitive_type=PrimitiveType.PYTHON)

    def validate_args(self, _args: dict) -> None:
        return

    def execute(self, _args: dict, _context: dict) -> PrimitiveResult:
        return PrimitiveResult(status="success", data=None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_registry(*names):
    """Create a PrimitiveRegistry with the given primitive names."""
    reg = PrimitiveRegistry()
    for name in names:
        reg.register(name, FakePrimitive(name=name))
    return reg


def make_manifest(**overrides):
    """Create a minimal SkillManifest."""
    data = {
        "name": "test",
        "description": "A test skill",
        "primitives": ["file.read"],
        "inputs": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "steps": [
            {"call": "file.read", "args": {"path": "/x"}},
        ],
    }
    data.update(overrides)
    return SkillManifest.from_dict(data)


def make_skill(**overrides):
    """Create a Skill from a manifest and registry."""
    manifest_data = {
        "name": "test",
        "description": "A test skill",
        "primitives": ["file.read"],
        "inputs": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "steps": [
            {"call": "file.read", "args": {}},
        ],
    }
    manifest_data.update(overrides)
    manifest = SkillManifest.from_dict(manifest_data)
    reg = make_registry("file.read")
    return Skill.from_manifest(manifest, reg)


# ---------------------------------------------------------------------------
# validate_manifest_structure tests
# ---------------------------------------------------------------------------

class TestValidateManifestStructure:
    """Tests for parse-time validate_manifest_structure."""

    def test_valid_manifest_passes(self):
        """A valid manifest with registered primitives passes."""
        manifest = make_manifest()
        registry = make_registry("file.read")
        validate_manifest_structure(manifest, registry)  # Should not raise.

    def test_unknown_primitive_raises(self):
        """A primitive name not in the registry raises ValueError."""
        manifest = SkillManifest(
            name="test", description="test",
            primitives=["does.not.exist"], inputs={},
            steps=[{"call": "does.not.exist", "args": {}}],
        )
        registry = make_registry("file.read")
        with pytest.raises(ValueError, match="unknown primitive"):
            validate_manifest_structure(manifest, registry)

    def test_non_dict_inputs_raises(self):
        """Non-dict inputs raises ValueError with 'invalid input schema'."""
        manifest = SkillManifest(
            name="test", description="test",
            primitives=["file.read"], inputs="bad",
            steps=[{"call": "file.read", "args": {}}],
        )
        registry = make_registry("file.read")
        with pytest.raises(ValueError, match="invalid input schema"):
            validate_manifest_structure(manifest, registry)

    def test_non_string_input_schema_keys_raises(self):
        """Input schema with non-string keys raises."""
        manifest = make_manifest(inputs={1: "val"})
        registry = make_registry("file.read")
        with pytest.raises(ValueError, match="invalid input schema"):
            validate_manifest_structure(manifest, registry)

    def test_invalid_step_structure_not_a_dict_raises(self):
        """A step that is not a dict raises."""
        manifest = SkillManifest(
            name="test", description="test",
            primitives=["file.read"], inputs={},
            steps=["not-a-dict"],
        )
        registry = make_registry("file.read")
        with pytest.raises(ValueError, match="invalid step structure"):
            validate_manifest_structure(manifest, registry)

    def test_step_missing_call_raises(self):
        """A step missing 'call' key raises."""
        manifest = SkillManifest(
            name="test", description="test",
            primitives=["file.read"], inputs={},
            steps=[{"args": {}}],
        )
        registry = make_registry("file.read")
        with pytest.raises(ValueError, match="invalid step structure"):
            validate_manifest_structure(manifest, registry)

    def test_step_missing_args_raises(self):
        """A step missing 'args' key raises."""
        manifest = make_manifest(steps=[{"call": "file.read"}])
        registry = make_registry("file.read")
        with pytest.raises(ValueError, match="invalid step structure"):
            validate_manifest_structure(manifest, registry)

    def test_step_call_not_in_primitives_raises(self):
        """A step whose 'call' is not in manifest.primitives raises."""
        manifest = SkillManifest(
            name="test", description="test",
            primitives=["file.read"], inputs={},
            steps=[{"call": "http.get", "args": {}}],
        )
        registry = make_registry("file.read", "http.get")
        with pytest.raises(ValueError, match="invalid step structure"):
            validate_manifest_structure(manifest, registry)

    def test_step_args_not_dict_raises(self):
        """A step with non-dict args raises."""
        manifest = SkillManifest(
            name="test", description="test",
            primitives=["file.read"], inputs={},
            steps=[{"call": "file.read", "args": "bad"}],
        )
        registry = make_registry("file.read")
        with pytest.raises(ValueError, match="invalid step structure"):
            validate_manifest_structure(manifest, registry)

    def test_step_on_error_not_string_raises(self):
        """A step with non-string, non-None on_error raises."""
        manifest = SkillManifest(
            name="test", description="test",
            primitives=["file.read"], inputs={},
            steps=[{"call": "file.read", "args": {}, "on_error": 99}],
        )
        registry = make_registry("file.read")
        with pytest.raises(ValueError, match="invalid step structure"):
            validate_manifest_structure(manifest, registry)


# ---------------------------------------------------------------------------
# validate_execution_args tests
# ---------------------------------------------------------------------------

class TestValidateExecutionArgs:
    """Tests for execution-time validate_execution_args."""

    def test_valid_args_pass(self):
        """Valid args matching the input schema pass."""
        skill = make_skill()
        validate_execution_args(skill, {"text": "hello"})

    def test_non_dict_args_raises(self):
        """Non-dict args raises ValueError."""
        skill = make_skill()
        with pytest.raises(ValueError, match="invalid execution args"):
            validate_execution_args(skill, "not-a-dict")

    def test_missing_required_key_raises(self):
        """Missing a required key raises."""
        skill = make_skill()
        with pytest.raises(ValueError, match="invalid execution args"):
            validate_execution_args(skill, {})

    def test_type_mismatch_raises(self):
        """Wrong type for a schema key raises."""
        skill = make_skill()
        with pytest.raises(ValueError, match="invalid execution args"):
            validate_execution_args(skill, {"text": 42})

    def test_extra_keys_allowed(self):
        """Extra keys not in the schema are allowed."""
        skill = make_skill()
        validate_execution_args(skill, {"text": "hello", "extra": True})

    def test_no_required_keys_allows_empty(self):
        """If schema has no required keys, empty args passes."""
        skill = make_skill(inputs={})
        validate_execution_args(skill, {})


# ---------------------------------------------------------------------------
# validate_step_result tests
# ---------------------------------------------------------------------------

class TestValidateStepResult:
    """Tests for execution-time validate_step_result."""

    def test_error_status_returns_immediately(self):
        """When step_result.status is 'error', no validation occurs."""
        skill = make_skill()
        pr = PrimitiveResult(status="error", error="something broke")
        # Should not raise even though output_schema might be strict.
        validate_step_result(skill, pr, 0)

    def test_non_final_step_skips_validation(self):
        """Non-final steps skip output validation even with data."""
        skill = make_skill(steps=[
            {"call": "file.read", "args": {}},
            {"call": "file.read", "args": {}},
        ])
        pr = PrimitiveResult(status="success", data={"extra": "stuff"})
        validate_step_result(skill, pr, 0)  # step 0 of 2, not final.

    def test_final_step_with_valid_data_passes(self):
        """Final step with data matching output_schema passes."""
        skill = make_skill()
        # Default output_schema is {} so any dict passes.
        pr = PrimitiveResult(status="success", data={"any": "data"})
        validate_step_result(skill, pr, 0)

    def test_final_step_none_data_skips(self):
        """Final step with None data skips validation."""
        skill = make_skill()
        pr = PrimitiveResult(status="success", data=None)
        validate_step_result(skill, pr, 0)

    def test_final_step_non_dict_data_raises(self):
        """Final step with non-dict data raises for output validation."""
        skill = make_skill()
        pr = PrimitiveResult(status="success", data="not-a-dict")
        with pytest.raises(ValueError, match="invalid step output"):
            validate_step_result(skill, pr, 0)

    def test_final_step_missing_required_output_raises(self):
        """Final step missing a required output key raises."""
        manifest = SkillManifest(
            name="test", description="test",
            primitives=["file.read"], inputs={},
            steps=[{"call": "file.read", "args": {}}],
        )
        reg = make_registry("file.read")
        skill = Skill(
            manifest=manifest,
            primitives={"file.read": reg.get("file.read")},
            input_schema={},
            output_schema={
                "type": "object",
                "properties": {"result": {"type": "string"}},
                "required": ["result"],
            },
        )
        pr = PrimitiveResult(status="success", data={"wrong": 1})
        with pytest.raises(ValueError, match="invalid step output"):
            validate_step_result(skill, pr, 0)

    def test_final_step_type_mismatch_raises(self):
        """Final step with wrong type raises."""
        manifest = SkillManifest(
            name="test", description="test",
            primitives=["file.read"], inputs={},
            steps=[{"call": "file.read", "args": {}}],
        )
        reg = make_registry("file.read")
        skill = Skill(
            manifest=manifest,
            primitives={"file.read": reg.get("file.read")},
            input_schema={},
            output_schema={
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "required": ["count"],
            },
        )
        pr = PrimitiveResult(status="success", data={"count": "not-an-int"})
        with pytest.raises(ValueError, match="invalid step output"):
            validate_step_result(skill, pr, 0)
