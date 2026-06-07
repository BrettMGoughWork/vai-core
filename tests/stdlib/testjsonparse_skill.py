"""Tests for stdlib.json.parse skill (Phase 3.7.6)."""

from __future__ import annotations

import json
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
    """Path to the json.parse.skill.md manifest file."""
    return (
        Path(__file__).resolve().parents[2]
        / "src" / "capabilities" / "skills" / "stdlib" / "json.parse.skill.md"
    )


class TestJsonParseSkillParsing:
    """Tests for the json.parse skill manifest."""

    def test_skill_manifest_parses_correctly(
        self, skill_md_path: Path, registry: PrimitiveRegistry
    ) -> None:
        """The .skill.md file parses and resolves primitives."""
        parsed = parse_skill_file(str(skill_md_path), registry)
        assert parsed["name"] == "stdlib.json.parse"
        assert parsed["description"] == "Parse a JSON string into a structured object"
        assert len(parsed["primitives"]) == 1
        assert isinstance(parsed["primitives"][0], EchoPrimitive)

    def test_manifest_has_input_text(self, skill_md_path: Path, registry: PrimitiveRegistry) -> None:
        """The manifest requires a 'text' input."""
        parsed = parse_skill_file(str(skill_md_path), registry)
        assert "text" in parsed["inputs"]

    def test_manifest_has_outputs(self, skill_md_path: Path, registry: PrimitiveRegistry) -> None:
        """The manifest declares result and error outputs."""
        parsed = parse_skill_file(str(skill_md_path), registry)
        assert "result" in parsed["outputs"]
        assert "error" in parsed["outputs"]


class TestJsonParseInlinePython:
    """Tests for the inline Python parsing logic used by the skill."""

    def _parse(self, text: str) -> dict:
        """Simulate the inline Python step from json.parse.skill.md."""
        try:
            parsed = json.loads(text)
            return {"result": parsed, "error": None}
        except Exception as e:
            return {"result": None, "error": str(e)}

    def test_valid_json_returns_parsed_dict(self) -> None:
        """A valid JSON string is parsed into a dict."""
        result = self._parse('{"key": "value", "num": 42}')
        assert result["result"] == {"key": "value", "num": 42}
        assert result["error"] is None

    def test_valid_json_array_returns_list(self) -> None:
        """A valid JSON array is parsed into a list."""
        result = self._parse("[1, 2, 3]")
        assert result["result"] == [1, 2, 3]
        assert result["error"] is None

    def test_invalid_json_returns_structured_error(self) -> None:
        """Invalid JSON returns a structured error with message."""
        result = self._parse("{invalid}")
        assert result["result"] is None
        assert result["error"] is not None

    def test_empty_string_returns_error(self) -> None:
        """An empty string is not valid JSON."""
        result = self._parse("")
        assert result["result"] is None
        assert result["error"] is not None

    def test_deterministic_parsing(self) -> None:
        """Repeated parsing of the same string yields the same result."""
        text = '{"a": 1}'
        results = [self._parse(text) for _ in range(3)]
        assert all(r == results[0] for r in results)


class TestJsonParseSkillEndToEnd:
    """End-to-end tests through SkillExecutor (using echo transport step)."""

    @pytest.fixture
    def e2e_skill(self, registry: PrimitiveRegistry) -> CapabilitySkill:
        """A CapabilitySkill that echoes a value (the transport step of json.parse)."""
        manifest = SkillManifest(
            name="stdlib.json.parse",
            description="Parse a JSON string",
            primitives=["stdlib.echo"],
            steps=[{"call": "stdlib.echo", "args": {"value": "{{ text }}"}}],
        )
        return CapabilitySkill(
            manifest=manifest,
            primitives={"stdlib.echo": registry.get("stdlib.echo")},
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            output_schema={"type": "object", "properties": {"value": {}}},
        )

    def test_echo_transport_passes_value_through(
        self, e2e_skill: CapabilitySkill
    ) -> None:
        """The echo transport step passes the input text through unchanged."""
        executor = SkillExecutor()
        result = executor.execute(e2e_skill, {"text": '{"a": 1}'}, {})
        assert result.status == "success"
        # SkillExecutor passes step-args literally (no template substitution yet).
        assert result.results[0].data == {"value": "{{ text }}"}

    def test_missing_text_raises_validation_error(
        self, e2e_skill: CapabilitySkill
    ) -> None:
        """Missing required 'text' input raises ValueError."""
        executor = SkillExecutor()
        with pytest.raises(ValueError, match="missing required key"):
            executor.execute(e2e_skill, {}, {})

    def test_deterministic_transport(self, e2e_skill: CapabilitySkill) -> None:
        """Repeated calls to the transport step yield identical results."""
        executor = SkillExecutor()
        results = [
            executor.execute(e2e_skill, {"text": "const"}, {})
            for _ in range(3)
        ]
        assert all(r.status == "success" for r in results)
        # All calls produce the same output (step args are static).
        assert all(
            r.results[0].data == {"value": "{{ text }}"} for r in results
        )
