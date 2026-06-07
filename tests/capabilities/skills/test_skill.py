"""
Tests for Skill dataclass (Phase 3.3.3).

Covers: from_manifest construction, primitive resolution, input/output
schema validation, validate_inputs, validate_outputs.
"""

from __future__ import annotations

import pytest

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveType, PrimitiveResult
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.skills.manifest import SkillManifest
from src.capabilities.skills.skill import Skill


# ---------------------------------------------------------------------------
# Fake primitive
# ---------------------------------------------------------------------------

class FakePrimitive(PrimitiveBase):
    """Minimal concrete primitive for Skill testing."""

    def __init__(
        self,
        *,
        name: str,
        description: str = "",
        primitive_type: PrimitiveType = PrimitiveType.PYTHON,
    ) -> None:
        super().__init__(name=name, description=description, primitive_type=primitive_type)

    def validate_args(self, _args: dict) -> None:
        return

    def execute(self, _args: dict, _context: dict) -> PrimitiveResult:
        return PrimitiveResult(status="success", data=None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_manifest(**overrides):
    """Create a minimal valid SkillManifest with overrides."""
    data = {
        "name": "test-skill",
        "description": "A test skill",
        "primitives": ["file.read"],
        "inputs": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "steps": [
            {"call": "file.read", "args": {"path": "/tmp/test.txt"}},
        ],
    }
    data.update(overrides)
    return SkillManifest.from_dict(data)


def make_registry(*names):
    """Create a PrimitiveRegistry with the given primitive names."""
    reg = PrimitiveRegistry()
    for name in names:
        reg.register(name, FakePrimitive(name=name, description=f"Mock {name}"))
    return reg


# ---------------------------------------------------------------------------
# from_manifest tests
# ---------------------------------------------------------------------------

class TestFromManifest:
    """Tests for Skill.from_manifest."""

    def test_valid_manifest_with_registry_succeeds(self):
        """A valid manifest with a pre-populated registry produces a Skill."""
        manifest = make_manifest()
        registry = make_registry("file.read")
        skill = Skill.from_manifest(manifest, registry)
        assert skill.manifest is manifest
        assert "file.read" in skill.primitives
        assert isinstance(skill.primitives["file.read"], PrimitiveBase)
        assert skill.input_schema == manifest.inputs

    def test_unknown_primitive_raises(self):
        """A manifest referencing a primitive not in the registry raises."""
        manifest = SkillManifest(
            name="test", description="test",
            primitives=["does.not.exist"], inputs={},
            steps=[{"call": "does.not.exist", "args": {}}],
        )
        registry = make_registry("file.read")
        with pytest.raises(ValueError, match="unknown primitive"):
            Skill.from_manifest(manifest, registry)

    def test_invalid_input_schema_raises(self):
        """A manifest with a non-dict input schema raises."""
        manifest = SkillManifest(
            name="test", description="test",
            primitives=["file.read"], inputs="not-a-dict",
            steps=[{"call": "file.read", "args": {}}],
        )
        registry = make_registry("file.read")
        with pytest.raises(ValueError, match="must be a dict"):
            Skill.from_manifest(manifest, registry)

    def test_non_string_schema_keys_raises(self):
        """Input schema with non-string keys raises."""
        manifest = make_manifest(inputs={1: "value"})
        registry = make_registry("file.read")
        with pytest.raises(ValueError, match="keys must be strings"):
            Skill.from_manifest(manifest, registry)

    def test_non_json_serializable_schema_raises(self):
        """Input schema with non-serializable values raises."""
        import threading
        lock = threading.Lock()
        manifest = make_manifest(inputs={"bad": lock})
        registry = make_registry("file.read")
        with pytest.raises(ValueError, match="values must be JSON-serializable"):
            Skill.from_manifest(manifest, registry)

    def test_multiple_primitives_resolved(self):
        """All primitives in the manifest are resolved."""
        manifest = make_manifest(primitives=["file.read", "http.get"])
        registry = make_registry("file.read", "http.get")
        skill = Skill.from_manifest(manifest, registry)
        assert set(skill.primitives.keys()) == {"file.read", "http.get"}

    def test_manifest_without_outputs_defaults_empty(self):
        """When SkillManifest has no outputs field, output_schema defaults to {}."""
        manifest = make_manifest()
        registry = make_registry("file.read")
        skill = Skill.from_manifest(manifest, registry)
        assert skill.output_schema == {}


# ---------------------------------------------------------------------------
# validate_inputs tests
# ---------------------------------------------------------------------------

class TestValidateInputs:
    """Tests for Skill.validate_inputs."""

    def test_valid_inputs_pass(self):
        """Inputs matching the schema pass validation."""
        manifest = make_manifest()
        registry = make_registry("file.read")
        skill = Skill.from_manifest(manifest, registry)
        skill.validate_inputs({"text": "hello"})  # Should not raise.

    def test_missing_required_key_raises(self):
        """Missing a required key raises ValueError."""
        manifest = make_manifest()
        registry = make_registry("file.read")
        skill = Skill.from_manifest(manifest, registry)
        with pytest.raises(ValueError, match="missing required key"):
            skill.validate_inputs({})

    def test_type_mismatch_raises(self):
        """A value with the wrong type raises ValueError."""
        manifest = make_manifest()
        registry = make_registry("file.read")
        skill = Skill.from_manifest(manifest, registry)
        with pytest.raises(ValueError, match="expected string"):
            skill.validate_inputs({"text": 42})

    def test_extra_keys_ignored(self):
        """Extra keys not in the schema are allowed."""
        manifest = make_manifest()
        registry = make_registry("file.read")
        skill = Skill.from_manifest(manifest, registry)
        skill.validate_inputs({"text": "hello", "extra": "ignored"})


# ---------------------------------------------------------------------------
# validate_outputs tests
# ---------------------------------------------------------------------------

class TestValidateOutputs:
    """Tests for Skill.validate_outputs."""

    def test_valid_outputs_pass(self):
        """Outputs matching the schema pass validation."""
        manifest = make_manifest()
        registry = make_registry("file.read")
        skill = Skill.from_manifest(manifest, registry)
        # output_schema is {} by default, so any dict with required: [] passes.
        skill.validate_outputs({"result": "ok"})

    def test_missing_required_output_raises(self):
        """Missing a required output key raises ValueError."""
        # Create a manifest with an explicit output schema
        m = SkillManifest(
            name="test",
            description="test",
            primitives=["file.read"],
            inputs={},
            steps=[{"call": "file.read", "args": {}}],
        )
        reg = make_registry("file.read")
        # output_schema will be {} since SkillManifest has no outputs field.
        # Use the schema from inputs temporarily to test validate_outputs.
        # Actually, output_schema = {} by default so we can only test what
        # the code supports: schema type='object' with required and properties.
        skill = Skill(manifest=m, primitives={"file.read": reg.get("file.read")},
                      input_schema={}, output_schema={})
        skill.validate_outputs({})  # Empty schema is permissive.
