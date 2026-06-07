"""
Tests for skill metadata validation (Phase 3.4.4).

Covers: primitive resolution, schema validation, and circular reference detection.
"""

from __future__ import annotations

import pytest

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveType, PrimitiveResult
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.registry.skill_metadata_validation import (
    validate_skill_primitives,
    validate_skill_schemas,
    validate_no_circular_references,
)
from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
from src.capabilities.skills.manifest import SkillManifest
from src.capabilities.skills.skill import CapabilitySkill


# ---------------------------------------------------------------------------
# Fake primitive
# ---------------------------------------------------------------------------

class FakePrimitive(PrimitiveBase):
    def __init__(self, *, name: str, description: str = "", primitive_type: PrimitiveType = PrimitiveType.PYTHON) -> None:
        super().__init__(name=name, description=description, primitive_type=primitive_type)

    def validate_args(self, _args: dict) -> None:
        return

    def execute(self, _args: dict, _context: dict) -> PrimitiveResult:
        return PrimitiveResult(status="success", data=None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_primitive_registry(*names: str) -> PrimitiveRegistry:
    registry = PrimitiveRegistry()
    for name in names:
        registry.register(name, FakePrimitive(name=name))
    return registry


def _make_skill(name: str, description: str = "a skill", primitive_names: list[str] | None = None, steps: list[dict] | None = None, input_schema: dict | None = None, output_schema: dict | None = None) -> CapabilitySkill:
    if primitive_names is None:
        primitive_names = ["echo"]
    if steps is None:
        steps = [{"call": "echo", "args": {}}]
    if input_schema is None:
        input_schema = {}
    if output_schema is None:
        output_schema = {}

    prim_registry = PrimitiveRegistry()
    for pn in primitive_names:
        prim_registry.register(pn, FakePrimitive(name=pn))

    manifest = SkillManifest(name=name, description=description, primitives=primitive_names, inputs=input_schema, steps=steps)
    skill = CapabilitySkill.from_manifest(manifest, prim_registry)
    # Override output_schema if needed (from_manifest uses manifest.outputs which doesn't exist on SkillManifest)
    object.__setattr__(skill, "output_schema", output_schema)
    return skill


def _make_skill_with_registry(name: str, prim_registry: PrimitiveRegistry, primitive_names: list[str] | None = None, steps: list[dict] | None = None, *, auto_register: bool = True) -> CapabilitySkill:
    if primitive_names is None:
        primitive_names = ["echo"]
    if steps is None:
        steps = [{"call": "echo", "args": {}}]

    if auto_register:
        for pn in primitive_names:
            if prim_registry.get(pn) is None:
                prim_registry.register(pn, FakePrimitive(name=pn))

    manifest = SkillManifest(name=name, description="a skill", primitives=primitive_names, inputs={}, steps=steps)
    return CapabilitySkill.from_manifest(manifest, prim_registry)


def _make_raw_skill(name: str, primitive_names: list[str], steps: list[dict], primitives: dict[str, FakePrimitive] | None = None, input_schema: dict | None = None, output_schema: dict | None = None) -> CapabilitySkill:
    """Construct a CapabilitySkill directly, bypassing from_manifest validation."""
    if primitives is None:
        primitives = {}
    if input_schema is None:
        input_schema = {}
    if output_schema is None:
        output_schema = {}

    manifest = SkillManifest(name=name, description="a skill", primitives=primitive_names, steps=steps)
    manifest.validate()
    return CapabilitySkill(manifest=manifest, primitives=primitives, input_schema=input_schema, output_schema=output_schema)


# ---------------------------------------------------------------------------
# Primitive validation
# ---------------------------------------------------------------------------

class TestValidateSkillPrimitives:
    def test_valid_skill_passes(self) -> None:
        prim_reg = _make_primitive_registry("echo", "file.read")
        skill = _make_skill_with_registry("test", prim_reg, primitive_names=["echo", "file.read"], steps=[{"call": "echo", "args": {}}, {"call": "file.read", "args": {}}])
        validate_skill_primitives(skill, prim_reg)  # should not raise

    def test_unknown_primitive_raises(self) -> None:
        prim_reg = _make_primitive_registry("echo")
        echo = prim_reg.get("echo")
        skill = _make_raw_skill("test", ["echo", "missing_prim"], [{"call": "echo", "args": {}}],
                                primitives={"echo": echo})
        with pytest.raises(ValueError, match="unknown primitive"):
            validate_skill_primitives(skill, prim_reg)

    def test_step_references_undeclared_primitive_raises(self) -> None:
        prim_reg = _make_primitive_registry("echo")
        echo = prim_reg.get("echo")
        # "hidden" declared in manifest.primitives but NOT registered → validate catches it
        skill = _make_raw_skill("test", ["echo", "hidden"], [{"call": "hidden", "args": {}}],
                                primitives={"echo": echo})
        with pytest.raises(ValueError, match="unknown primitive"):
            validate_skill_primitives(skill, prim_reg)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestValidateSkillSchemas:
    def test_valid_schemas_pass(self) -> None:
        skill = _make_skill("test", input_schema={"type": "object"}, output_schema={"type": "object"})
        validate_skill_schemas(skill)  # should not raise

    def test_non_dict_input_schema_raises(self) -> None:
        skill = _make_skill("test")
        object.__setattr__(skill, "input_schema", "not a dict")
        with pytest.raises(ValueError, match="invalid input schema"):
            validate_skill_schemas(skill)

    def test_non_dict_output_schema_raises(self) -> None:
        skill = _make_skill("test")
        object.__setattr__(skill, "output_schema", 42)
        with pytest.raises(ValueError, match="invalid output schema"):
            validate_skill_schemas(skill)

    def test_non_string_schema_keys_raises(self) -> None:
        skill = _make_raw_skill("test", ["echo"], [{"call": "echo", "args": {}}],
                                primitives={"echo": FakePrimitive(name="echo")},
                                input_schema={1: "value"})  # type: ignore[dict-item]
        with pytest.raises(ValueError, match="invalid input schema"):
            validate_skill_schemas(skill)

    def test_non_json_serializable_schema_raises(self) -> None:
        # A set is not JSON-serializable
        skill = _make_raw_skill("test", ["echo"], [{"call": "echo", "args": {}}],
                                primitives={"echo": FakePrimitive(name="echo")},
                                input_schema={"bad": {1, 2, 3}})  # type: ignore[dict-item]
        with pytest.raises(ValueError, match="invalid input schema"):
            validate_skill_schemas(skill)


# ---------------------------------------------------------------------------
# Circular reference detection
# ---------------------------------------------------------------------------

class TestValidateNoCircularReferences:
    def test_no_cycle_passes(self) -> None:
        registry = CapabilitySkillRegistry()
        skill_a = _make_skill("A", primitive_names=["echo"], steps=[{"call": "echo", "args": {}}])  # A depends on primitives only
        skill_b = _make_skill("B", primitive_names=["echo"], steps=[{"call": "echo", "args": {}}])
        registry.register(skill_a)
        registry.register(skill_b)
        validate_no_circular_references(skill_a, registry)  # should not raise

    def test_self_reference_detected(self) -> None:
        registry = CapabilitySkillRegistry()
        # A step references "A" (the skill's own name); include "A" in primitives
        # so manifest.validate() passes
        skill = _make_skill("A", primitive_names=["echo", "A"], steps=[{"call": "A", "args": {}}])
        registry.register(skill)
        with pytest.raises(ValueError, match="circular skill reference"):
            validate_no_circular_references(skill, registry)

    def test_direct_cycle_detected(self) -> None:
        registry = CapabilitySkillRegistry()
        skill_a = _make_skill("A", primitive_names=["echo", "B"], steps=[{"call": "B", "args": {}}])
        skill_b = _make_skill("B", primitive_names=["echo", "A"], steps=[{"call": "A", "args": {}}])
        registry.register(skill_b)
        registry.register(skill_a)
        with pytest.raises(ValueError, match="circular skill reference"):
            validate_no_circular_references(skill_a, registry)

    def test_indirect_cycle_detected(self) -> None:
        registry = CapabilitySkillRegistry()
        skill_a = _make_skill("A", primitive_names=["echo", "B"], steps=[{"call": "B", "args": {}}])
        skill_b = _make_skill("B", primitive_names=["echo", "C"], steps=[{"call": "C", "args": {}}])
        skill_c = _make_skill("C", primitive_names=["echo", "A"], steps=[{"call": "A", "args": {}}])
        registry.register(skill_c)
        registry.register(skill_b)
        registry.register(skill_a)
        with pytest.raises(ValueError, match="circular skill reference"):
            validate_no_circular_references(skill_a, registry)

    def test_non_circular_dag_accepted(self) -> None:
        registry = CapabilitySkillRegistry()
        skill_a = _make_skill("A", primitive_names=["echo", "B"], steps=[{"call": "B", "args": {}}])
        skill_b = _make_skill("B", primitive_names=["echo", "C"], steps=[{"call": "C", "args": {}}])
        skill_c = _make_skill("C", primitive_names=["echo"], steps=[{"call": "echo", "args": {}}])  # leaf
        registry.register(skill_c)  # Register leaf first
        registry.register(skill_b)
        registry.register(skill_a)
        validate_no_circular_references(skill_a, registry)  # should not raise
