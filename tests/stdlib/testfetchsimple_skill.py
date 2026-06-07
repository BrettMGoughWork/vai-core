"""Tests for stdlib.fetch.simple stub skill (Phase 3.7.7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.skills.executor import SkillExecutor
from src.capabilities.skills.manifest import SkillManifest
from src.capabilities.skills.skill import CapabilitySkill
from src.capabilities.skills.skill_parser import parse_skill_file


class StubHttpGetPrimitive(PrimitiveBase):
    """Stub for the future net.httpget primitive (deterministic placeholder)."""

    def __init__(self) -> None:
        super().__init__(
            name="net.httpget",
            description="Stub HTTP GET",
            primitive_type=PrimitiveType.PYTHON,
        )

    def validate_args(self, args: dict) -> None:
        if not isinstance(args, dict):
            raise ValueError("args must be a dict")
        if "url" not in args:
            raise ValueError("args must contain 'url' key")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        return PrimitiveResult(
            status="success",
            data={"status": 200, "body": '{"ok": true}', "error": None},
        )


@pytest.fixture
def registry() -> PrimitiveRegistry:
    """PrimitiveRegistry with stub net.httpget."""
    reg = PrimitiveRegistry()
    reg.register("net.httpget", StubHttpGetPrimitive())
    return reg


@pytest.fixture
def skill_md_path() -> Path:
    """Path to the fetch.simple.skill.md manifest file."""
    return (
        Path(__file__).resolve().parents[2]
        / "src" / "capabilities" / "skills" / "stdlib" / "fetch.simple.skill.md"
    )


class TestFetchSimpleSkillParsing:
    """Tests for the fetch.simple skill manifest."""

    def test_skill_manifest_parses_correctly(
        self, skill_md_path: Path, registry: PrimitiveRegistry
    ) -> None:
        """The .skill.md file parses and resolves primitives."""
        parsed = parse_skill_file(str(skill_md_path), registry)
        assert parsed["name"] == "stdlib.fetch.simple"
        assert parsed["description"] == (
            "Stub HTTP GET fetch skill; declares net.httpget dependency"
        )
        assert len(parsed["primitives"]) == 1
        assert isinstance(parsed["primitives"][0], StubHttpGetPrimitive)

    def test_manifest_requires_url_input(
        self, skill_md_path: Path, registry: PrimitiveRegistry
    ) -> None:
        """The manifest requires a 'url' input."""
        parsed = parse_skill_file(str(skill_md_path), registry)
        assert "url" in parsed["inputs"]

    def test_manifest_declares_output_fields(
        self, skill_md_path: Path, registry: PrimitiveRegistry
    ) -> None:
        """The manifest declares status, body, and error outputs."""
        parsed = parse_skill_file(str(skill_md_path), registry)
        assert "status" in parsed["outputs"]
        assert "body" in parsed["outputs"]
        assert "error" in parsed["outputs"]


class TestFetchSimpleSkillExecution:
    """End-to-end tests through SkillExecutor with stub primitive."""

    @pytest.fixture
    def skill(self, registry: PrimitiveRegistry) -> CapabilitySkill:
        """CapabilitySkill with a single net.httpget call step."""
        manifest = SkillManifest(
            name="stdlib.fetch.simple",
            description="Stub HTTP GET fetch skill",
            primitives=["net.httpget"],
            inputs={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            steps=[{"call": "net.httpget", "args": {"url": "{{ url }}"}}],
        )
        return CapabilitySkill(
            manifest=manifest,
            primitives={"net.httpget": registry.get("net.httpget")},
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            output_schema={
                "type": "object",
                "properties": {"status": {"type": "integer"}, "body": {"type": "string"}, "error": {}},
            },
        )

    def test_stub_primitive_returns_placeholder(
        self, skill: CapabilitySkill
    ) -> None:
        """The stub primitive returns a deterministic placeholder response."""
        executor = SkillExecutor()
        result = executor.execute(skill, {"url": "https://example.com"}, {})
        assert result.status == "success"
        assert len(result.results) == 1
        data = result.results[0].data
        assert data["status"] == 200
        assert data["body"] == '{"ok": true}'
        assert data["error"] is None

    def test_missing_url_raises_validation_error(self, skill: CapabilitySkill) -> None:
        """Missing required 'url' input raises ValueError."""
        executor = SkillExecutor()
        with pytest.raises(ValueError, match="missing required key"):
            executor.execute(skill, {}, {})

    def test_deterministic_stub_output(self, skill: CapabilitySkill) -> None:
        """Repeated calls to the stub yield identical results."""
        executor = SkillExecutor()
        results = [
            executor.execute(skill, {"url": "https://example.com"}, {})
            for _ in range(3)
        ]
        assert all(r.status == "success" for r in results)
        assert all(r.results[0].data == results[0].results[0].data for r in results)

    def test_python_fallback_logic(self) -> None:
        """The inline Python fallback from fetch.simple.skill.md produces deterministic output."""
        # Simulate the stub Python block from the manifest.
        raw: dict | None = None
        if isinstance(raw, dict) and "status" in raw and "body" in raw:
            result = {
                "status": raw.get("status", 0),
                "body": raw.get("body", ""),
                "error": raw.get("error", None),
            }
        else:
            result = {
                "status": 0,
                "body": "",
                "error": "net.httpget not implemented",
            }
        assert result == {
            "status": 0,
            "body": "",
            "error": "net.httpget not implemented",
        }

        # With a stub dict, it passes through.
        raw = {"status": 200, "body": "ok", "error": None}
        if isinstance(raw, dict) and "status" in raw and "body" in raw:
            result = {
                "status": raw.get("status", 0),
                "body": raw.get("body", ""),
                "error": raw.get("error", None),
            }
        else:
            result = {
                "status": 0,
                "body": "",
                "error": "net.httpget not implemented",
            }
        assert result == {"status": 200, "body": "ok", "error": None}
