"""
Tests for CapabilitySkillRegistry (Phase 3.4.1).

Covers: registration, duplicate handling, get, list (with filter).
"""

from __future__ import annotations

import pytest

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveType, PrimitiveResult
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
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

def _make_skill(name: str, description: str = "a skill", primitive_names: list[str] | None = None, steps: list[dict] | None = None) -> CapabilitySkill:
    if primitive_names is None:
        primitive_names = ["echo"]
    if steps is None:
        steps = [{"call": "echo", "args": {}}]

    prim_registry = PrimitiveRegistry()
    for pn in primitive_names:
        prim_registry.register(pn, FakePrimitive(name=pn))

    manifest = SkillManifest(name=name, description=description, primitives=primitive_names, inputs={}, steps=steps)
    return CapabilitySkill.from_manifest(manifest, prim_registry)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry() -> CapabilitySkillRegistry:
    return CapabilitySkillRegistry()


@pytest.fixture
def echo_skill() -> CapabilitySkill:
    return _make_skill("echo-skill", "echoes input")


@pytest.fixture
def read_skill() -> CapabilitySkill:
    return _make_skill("file.read", "reads a file", primitive_names=["file.read"], steps=[{"call": "file.read", "args": {"path": ""}}])


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_register_succeeds(self, registry: CapabilitySkillRegistry, echo_skill: CapabilitySkill) -> None:
        registry.register(echo_skill)
        assert registry.get("echo-skill") is echo_skill

    def test_duplicate_name_raises(self, registry: CapabilitySkillRegistry, echo_skill: CapabilitySkill) -> None:
        registry.register(echo_skill)
        dup = _make_skill("echo-skill", "different description")
        with pytest.raises(ValueError, match="already registered"):
            registry.register(dup)


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------

class TestGet:
    def test_get_returns_skill(self, registry: CapabilitySkillRegistry, echo_skill: CapabilitySkill) -> None:
        registry.register(echo_skill)
        assert registry.get("echo-skill") is echo_skill

    def test_get_missing_returns_none(self, registry: CapabilitySkillRegistry) -> None:
        assert registry.get("nonexistent") is None


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class TestList:
    def test_list_returns_all(self, registry: CapabilitySkillRegistry, echo_skill: CapabilitySkill, read_skill: CapabilitySkill) -> None:
        registry.register(echo_skill)
        registry.register(read_skill)
        result = registry.list()
        assert len(result) == 2
        names = {s.manifest.name for s in result}
        assert names == {"echo-skill", "file.read"}

    def test_list_empty(self, registry: CapabilitySkillRegistry) -> None:
        assert registry.list() == []

    def test_list_with_filter(self, registry: CapabilitySkillRegistry, echo_skill: CapabilitySkill, read_skill: CapabilitySkill) -> None:
        registry.register(echo_skill)
        registry.register(read_skill)
        result = registry.list(lambda s: "file" in s.manifest.name)
        assert len(result) == 1
        assert result[0].manifest.name == "file.read"
