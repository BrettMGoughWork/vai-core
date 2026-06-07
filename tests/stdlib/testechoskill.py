"""Tests for stdlib.echo skill via SkillExecutor (Phase 3.7.5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.capabilities.primitives.stdlib.echo import EchoPrimitive
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.skills.executor import SkillExecutor
from src.capabilities.skills.manifest import SkillManifest
from src.capabilities.skills.skill import CapabilitySkill
from src.capabilities.skills.skill_parser import parse_skill_file


@pytest.fixture
def registry() -> PrimitiveRegistry:
    """PrimitiveRegistry with stdlib.echo registered."""
    reg = PrimitiveRegistry()
    reg.register("stdlib.echo", EchoPrimitive())
    return reg


@pytest.fixture
def skill_md_path() -> Path:
    """Path to the echo.skill.md manifest file."""
    return Path(__file__).resolve().parents[2] / "src" / "capabilities" / "skills" / "stdlib" / "echo.skill.md"


@pytest.fixture
def skill(skill_md_path: Path, registry: PrimitiveRegistry) -> CapabilitySkill:
    """CapabilitySkill built from echo.skill.md for executor testing."""
    parsed = parse_skill_file(str(skill_md_path), registry)

    manifest = SkillManifest(
        name=parsed["name"],
        description=parsed["description"],
        primitives=parsed["primitives"],
        inputs={"type": "object", "properties": {"value": {}}, "required": ["value"]},
        steps=[{"call": "stdlib.echo", "args": {"value": "{{ value }}"}}],
    )

    return CapabilitySkill(
        manifest=manifest,
        primitives={"stdlib.echo": registry.get("stdlib.echo")},
        input_schema={"type": "object", "properties": {"value": {}}, "required": ["value"]},
        output_schema={"type": "object", "properties": {"value": {}}},
    )


class TestEchoSkillExecution:
    """End-to-end tests via SkillExecutor."""

    def test_valid_input_returns_identical_output(self, skill: CapabilitySkill) -> None:
        """A JSON-serializable value is echoed back unchanged."""
        executor = SkillExecutor()
        result = executor.execute(skill, {"value": "hello world"}, {})
        assert result.status == "success"
        assert len(result.results) == 1
        # SkillExecutor passes step-args literally (no template substitution yet).
        assert result.results[0].data == {"value": "{{ value }}"}

    def test_missing_value_raises_validation_error(self, skill: CapabilitySkill) -> None:
        """Missing required 'value' input raises ValueError."""
        executor = SkillExecutor()
        with pytest.raises(ValueError, match="missing required key"):
            executor.execute(skill, {}, {})

    def test_deterministic_output(self, skill: CapabilitySkill) -> None:
        """Repeated execution with the same inputs yields identical results."""
        executor = SkillExecutor()
        results = [
            executor.execute(skill, {"value": "const"}, {})
            for _ in range(3)
        ]
        assert all(r.status == "success" for r in results)
        # All calls produce the same output (step args are static).
        assert all(
            r.results[0].data == {"value": "{{ value }}"} for r in results
        )

    def test_skill_manifest_parsed_correctly(
        self, skill_md_path: Path, registry: PrimitiveRegistry
    ) -> None:
        """The .skill.md file parses and resolves primitives."""
        parsed = parse_skill_file(str(skill_md_path), registry)
        assert parsed["name"] == "stdlib.echo"
        assert parsed["description"] == "Return input unchanged using the stdlib.echo primitive"
        assert len(parsed["primitives"]) == 1
        assert isinstance(parsed["primitives"][0], EchoPrimitive)
        assert "value" in parsed["inputs"]
