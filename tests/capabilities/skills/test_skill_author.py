"""
Tests for agent-authored skills pipeline (Phase 3.16.4).

Covers: valid authoring, disallowed primitive rejection, system skill
override rejection, nonexistent primitive rejection, authored skill
execution, discovery, and multi-failure safety reporting.
"""

from __future__ import annotations

import pytest

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveType, PrimitiveResult
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
from src.capabilities.registry.skill_safety import (
    SkillSafetyValidator,
    SafetyResult,
)
from src.capabilities.skills.manifest import SkillManifest
from src.capabilities.skills.skill import CapabilitySkill
from src.capabilities.skills.author import SkillAuthor
from src.capabilities.skills.skill_parser import parse_skill_text


# ---------------------------------------------------------------------------
# Fake primitive
# ---------------------------------------------------------------------------

class FakePrimitive(PrimitiveBase):
    """Minimal concrete primitive for agent-authored skill testing."""

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
        return PrimitiveResult(status="success", data={"result": f"executed {self.name}"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skill_md_text(
    name: str = "agent-skill",
    description: str = "An agent-authored skill",
    primitives: str = "file.read",
    inputs: str | None = None,
    outputs: str | None = None,
    steps: str | None = None,
) -> str:
    """Build a valid .skill.md text string."""
    inp = inputs or """
    type: object
    properties:
      path:
        type: string
    required:
      - path
"""
    out = outputs or """
    type: object
    properties:
      result:
        type: string
    required:
      - result
"""
    step_block = steps if steps is not None else """
  - call: file.read
    args:
      path: "{{path}}"
"""
    return f"""---
name: {name}
description: {description}
primitives:
  - {primitives}
inputs:{inp}
outputs:{out}
steps:{step_block}
---
"""


def make_manifest(**overrides) -> SkillManifest:
    """Create a minimal valid SkillManifest with overrides.

    If ``primitives`` is overridden but ``steps`` is not, the default steps
    reference ``file.read``, so leave ``file.read`` in the primitives list
    as well.
    """
    data: dict[str, object] = {
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def primitive_registry():
    """A registry pre-populated with known primitives."""
    reg = PrimitiveRegistry()
    for name in ("file.read", "file.write", "http.get", "proc.exec"):
        reg.register(name, FakePrimitive(name=name, description=f"Mock {name}"))
    return reg


@pytest.fixture
def skill_registry(primitive_registry):
    """An empty skill registry."""
    return CapabilitySkillRegistry()


@pytest.fixture
def safety(primitive_registry, skill_registry):
    """A default safety validator."""
    return SkillSafetyValidator(primitive_registry, skill_registry)


@pytest.fixture
def author(primitive_registry, skill_registry, safety):
    """A SkillAuthor wired to the test registries."""
    return SkillAuthor(primitive_registry, skill_registry, safety)


# ---------------------------------------------------------------------------
# 3.16.1 — parse_skill_text
# ---------------------------------------------------------------------------

class TestParseSkillText:
    """Tests for parse_skill_text (in-memory .skill.md parsing)."""

    def test_parse_valid_text(self, primitive_registry):
        text = _make_skill_md_text()
        result = parse_skill_text(text, primitive_registry)
        assert result["name"] == "agent-skill"
        assert result["description"] == "An agent-authored skill"
        assert isinstance(result["inputs"], dict)
        assert len(result["primitives"]) == 1
        assert result["primitives"][0].name == "file.read"

    def test_parse_missing_delimiter(self, primitive_registry):
        text = "name: no-delimiter\ndescription: bad"
        with pytest.raises(ValueError, match="missing opening ---"):
            parse_skill_text(text, primitive_registry)

    def test_parse_invalid_yaml(self, primitive_registry):
        text = "---\n{{invalid: yaml: [\n---\n"
        with pytest.raises(ValueError, match="invalid skill manifest"):
            parse_skill_text(text, primitive_registry)

    def test_parse_unknown_primitive(self, primitive_registry):
        text = _make_skill_md_text(primitives="nonexistent.primitive")
        with pytest.raises(ValueError, match="unknown primitive"):
            parse_skill_text(text, primitive_registry)

    def test_parse_missing_required_fields(self, primitive_registry):
        text = "---\nname: x\n---\n"
        with pytest.raises(ValueError, match="missing required key"):
            parse_skill_text(text, primitive_registry)


# ---------------------------------------------------------------------------
# 3.16.2 — SkillSafetyValidator
# ---------------------------------------------------------------------------

class TestSafetyValidator:
    """Tests for SkillSafetyValidator checks."""

    def test_valid_skill_passes(self, safety, primitive_registry):
        manifest = make_manifest()
        skill = CapabilitySkill.from_manifest(manifest, primitive_registry)
        result = safety.validate(skill)
        assert result.passed
        assert result.errors == []

    def test_disallowed_primitive_rejected(self, safety, primitive_registry):
        manifest = make_manifest(
            primitives=["proc.exec"],
            steps=[{"call": "proc.exec", "args": {"cmd": "echo hi"}}],
        )
        skill = CapabilitySkill.from_manifest(manifest, primitive_registry)
        result = safety.validate(skill)
        assert not result.passed
        assert any("disallowed primitive" in e for e in result.errors)

    def test_nonexistent_primitive_rejected(self, safety, primitive_registry):
        """A skill referencing a nonexistent primitive fails parsing."""
        text = _make_skill_md_text(primitives="ghost.primitive")
        with pytest.raises(ValueError):
            parse_skill_text(text, primitive_registry)

    def test_system_skill_override_rejected(self, safety, primitive_registry, skill_registry):
        # Register a system skill first (plugin_name is None).
        sys_manifest = make_manifest(name="sys-skill")
        sys_skill = CapabilitySkill.from_manifest(sys_manifest, primitive_registry)
        skill_registry.register(sys_skill)

        # Try to author a skill with the same name.
        agent_manifest_data: dict[str, object] = {
            "name": "sys-skill",
            "description": "Attempt override",
            "primitives": ["file.read"],
            "inputs": {"type": "object", "properties": {}, "required": []},
            "outputs": {"type": "object", "properties": {}, "required": []},
            "steps": [],
            "plugin_name": "agent",
            "plugin_version": "0.1.0",
        }
        agent_manifest = SkillManifest.from_dict(agent_manifest_data)
        agent_skill = CapabilitySkill.from_manifest(agent_manifest, primitive_registry)

        result = safety.validate(agent_skill)
        assert not result.passed
        assert any("system skill" in e for e in result.errors)

    def test_multi_error_reporting(self, safety, primitive_registry, skill_registry):
        """A skill with multiple safety issues reports all of them."""
        # Register a system skill that this skill will attempt to override.
        sys_manifest = make_manifest(name="bad-skill")
        sys_skill = CapabilitySkill.from_manifest(sys_manifest, primitive_registry)
        skill_registry.register(sys_skill)

        # Now create an agent-authored skill: disallowed primitive + system override
        manifest_data: dict[str, object] = {
            "name": "bad-skill",
            "description": "Multiple problems",
            "primitives": ["proc.exec", "file.read"],
            "inputs": {"type": "object", "properties": {}, "required": []},
            "outputs": {"type": "object", "properties": {}, "required": []},
            "steps": [
                {"call": "proc.exec", "args": {"cmd": "rm -rf /"}},
            ],
            "plugin_name": "agent",
            "plugin_version": "0.1.0",
        }
        manifest = SkillManifest.from_dict(manifest_data)
        skill = CapabilitySkill.from_manifest(manifest, primitive_registry)
        result = safety.validate(skill)
        assert not result.passed
        # Should have at least: disallowed primitive + system override
        assert len(result.errors) >= 2

    def test_custom_disallowed_primitives(self, primitive_registry, skill_registry):
        safety = SkillSafetyValidator(
            primitive_registry,
            skill_registry,
            disallowed_primitives={"http.get", "custom.blocked"},
        )
        assert "http.get" in safety.disallowed_primitives

        manifest_data = {
            "name": "http-skill",
            "description": "Uses http.get",
            "primitives": ["http.get"],
            "inputs": {"type": "object", "properties": {}, "required": []},
            "steps": [{"call": "http.get", "args": {"url": "https://example.com"}}],
            "plugin_name": "agent",
            "plugin_version": "0.1.0",
            "outputs": {"type": "object", "properties": {}, "required": []},
        }
        manifest = SkillManifest.from_dict(manifest_data)
        skill = CapabilitySkill.from_manifest(manifest, primitive_registry)
        result = safety.validate(skill)
        assert not result.passed
        assert any("disallowed primitive 'http.get'" in e for e in result.errors)


# ---------------------------------------------------------------------------
# 3.16.3 — SkillAuthor pipeline
# ---------------------------------------------------------------------------

class TestSkillAuthor:
    """Tests for the full SkillAuthor pipeline."""

    def test_author_valid_skill(self, author, skill_registry):
        text = _make_skill_md_text()
        skill = author.author_skill(text)
        assert skill.manifest.name == "agent-skill"
        assert skill_registry.get("agent-skill") is skill

    def test_author_skill_with_disallowed_primitive(self, author):
        text = _make_skill_md_text(
            name="dangerous-skill",
            primitives="proc.exec",
            steps="""
  - call: proc.exec
    args:
      cmd: "echo oops"
""",
            inputs="""
    type: object
    properties: {}
    required: []
""",
            outputs="""
    type: object
    properties: {}
    required: []
""",
        )
        with pytest.raises(ValueError, match="failed safety validation"):
            author.author_skill(text)

    def test_author_skill_discoverable(self, author, skill_registry):
        """An authored skill appears in discovery results."""
        text = _make_skill_md_text(name="discover-me", description="Find the capital of France")
        author.author_skill(text)

        # It should be in ordered_list.
        skills = skill_registry.ordered_list()
        names = [s.manifest.name for s in skills]
        assert "discover-me" in names

    def test_author_skill_override_system(self, author, skill_registry, primitive_registry):
        """Agent-authored skill cannot override a system skill."""
        # Register a system skill first.
        sys_manifest = make_manifest(name="system-only", primitives=["file.read"])
        sys_skill = CapabilitySkill.from_manifest(sys_manifest, primitive_registry)
        skill_registry.register(sys_skill)

        text = _make_skill_md_text(name="system-only")
        with pytest.raises(ValueError, match="failed safety validation"):
            author.author_skill(text)

    def test_author_multiple_skills(self, author, skill_registry):
        """Multiple agent-authored skills can be registered."""
        for i in range(3):
            text = _make_skill_md_text(name=f"agent-skill-{i}")
            author.author_skill(text)
        skills = skill_registry.ordered_list()
        agent_skills = [s for s in skills if s.manifest.name.startswith("agent-skill")]
        assert len(agent_skills) == 3

    def test_author_skill_plugin_origin(self, author, skill_registry):
        """Authored skill records its plugin origin."""
        text = _make_skill_md_text()
        skill = author.author_skill(text)
        assert skill.manifest.plugin_name == "agent"
        assert skill.manifest.plugin_version == "0.1.0"

    def test_author_skill_custom_plugin_origin(self, author, skill_registry):
        """Authored skill can set a custom plugin origin."""
        text = _make_skill_md_text()
        skill = author.author_skill(text, plugin_name="custom-agent", plugin_version="2.0.0")
        assert skill.manifest.plugin_name == "custom-agent"
        assert skill.manifest.plugin_version == "2.0.0"

    def test_author_skill_has_manifest_hash(self, author):
        """Authored skill gets a stable manifest hash."""
        text = _make_skill_md_text()
        skill = author.author_skill(text)
        assert skill.manifest.manifest_hash is not None
        assert len(skill.manifest.manifest_hash) == 64

    def test_author_skill_duplicate_name_rejected(self, author):
        """Registering the same skill name twice is rejected."""
        text = _make_skill_md_text(name="duplicate-me")
        author.author_skill(text)
        with pytest.raises(ValueError, match="already registered"):
            author.author_skill(text)


# ---------------------------------------------------------------------------
# 3.16.4 — Integration / Edge Cases
# ---------------------------------------------------------------------------

class TestAuthorIntegration:
    """Edge cases and integration scenarios for agent-authored skills."""

    def test_parse_skill_text_then_author(self, author, primitive_registry, skill_registry, safety):
        """Full integration: parse raw text → validate → register."""
        text = _make_skill_md_text(name="integration-test")
        skill = author.author_skill(text)
        retrieved = skill_registry.get("integration-test")
        assert retrieved is skill
        assert retrieved.manifest.name == "integration-test"

    def test_empty_steps_skill(self, author, skill_registry):
        """A skill with no steps is valid (returns outputs directly)."""
        text = """---
name: no-op
description: A skill with no steps
primitives:
  - file.read
inputs:
  type: object
  properties: {}
  required: []
outputs:
  type: object
  properties:
    value:
      type: string
  required: []
steps: []
---
"""
        skill = author.author_skill(text)
        assert skill.manifest.name == "no-op"
        assert skill.manifest.steps == []

    def test_author_with_step_primitive_not_declared(self, author):
        """A step referencing an undeclared primitive fails."""
        text = """---
name: undeclared-step
description: Step uses primitive not in list
primitives:
  - file.read
inputs:
  type: object
  properties: {}
  required: []
outputs:
  type: object
  properties: {}
  required: []
steps:
  - call: http.get
    args:
      url: "https://example.com"
---
"""
        with pytest.raises(ValueError):
            author.author_skill(text)
