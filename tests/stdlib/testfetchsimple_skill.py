"""Tests for stdlib.fetch.url skill (Phase 3.10.3)."""

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


class StubHttpFetchPrimitive(PrimitiveBase):
    """Stub for stdlib.http.fetch primitive (deterministic placeholder)."""

    def __init__(self) -> None:
        super().__init__(
            name="stdlib.http.fetch",
            description="Stub HTTP GET fetch",
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
            data={
                "ok": True,
                "status_code": 200,
                "body": '{"ok": true}',
                "headers": {"content-type": "application/json"},
                "elapsed_ms": 42,
            },
        )


@pytest.fixture
def registry() -> PrimitiveRegistry:
    """PrimitiveRegistry with stub stdlib.http.fetch."""
    reg = PrimitiveRegistry()
    reg.register("stdlib.http.fetch", StubHttpFetchPrimitive())
    return reg


@pytest.fixture
def skill_md_path() -> Path:
    """Path to the fetch.url.skill.md manifest file."""
    return (
        Path(__file__).resolve().parents[2]
        / "src" / "capabilities" / "skills" / "stdlib" / "fetch.url.skill.md"
    )


class TestFetchUrlSkillParsing:
    """Tests for the fetch.url skill manifest."""

    def test_skill_manifest_parses_correctly(
        self, skill_md_path: Path, registry: PrimitiveRegistry
    ) -> None:
        """The .skill.md file parses and resolves primitives."""
        parsed = parse_skill_file(str(skill_md_path), registry)
        assert parsed["name"] == "stdlib.fetch.url"
        assert "HTTP GET fetch skill" in parsed["description"]
        assert len(parsed["primitives"]) == 1
        assert isinstance(parsed["primitives"][0], StubHttpFetchPrimitive)

    def test_manifest_requires_url_input(
        self, skill_md_path: Path, registry: PrimitiveRegistry
    ) -> None:
        """The manifest requires a 'url' input."""
        parsed = parse_skill_file(str(skill_md_path), registry)
        assert "url" in parsed["inputs"]

    def test_manifest_declares_output_fields(
        self, skill_md_path: Path, registry: PrimitiveRegistry
    ) -> None:
        """The manifest declares canonical output fields."""
        parsed = parse_skill_file(str(skill_md_path), registry)
        assert "ok" in parsed["outputs"]
        assert "status_code" in parsed["outputs"]
        assert "body" in parsed["outputs"]
        assert "headers" in parsed["outputs"]
        assert "cookies" in parsed["outputs"]
        assert "elapsed_ms" in parsed["outputs"]


class TestFetchUrlSkillExecution:
    """End-to-end tests through SkillExecutor with stub primitive."""

    @pytest.fixture
    def skill(self, registry: PrimitiveRegistry) -> CapabilitySkill:
        """CapabilitySkill with a single stdlib.http.fetch call step."""
        manifest = SkillManifest(
            name="stdlib.fetch.url",
            description="HTTP GET fetch skill",
            primitives=["stdlib.http.fetch"],
            inputs={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "timeout": {"type": "number"},
                    "headers": {"type": "object"},
                },
                "required": ["url"],
            },
            steps=[{"call": "stdlib.http.fetch", "args": {"url": "{{ url }}"}}],
        )
        return CapabilitySkill(
            manifest=manifest,
            primitives={"stdlib.http.fetch": registry.get("stdlib.http.fetch")},
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "timeout": {"type": "number"},
                    "headers": {"type": "object"},
                },
                "required": ["url"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "status_code": {"type": "integer"},
                    "body": {"type": "string"},
                    "headers": {"type": "object"},
                    "elapsed_ms": {"type": "integer"},
                    "error_type": {},
                    "error_message": {},
                },
            },
        )

    def test_primitive_output_passed_through(
        self, skill: CapabilitySkill
    ) -> None:
        """The stub primitive response is passed through unchanged."""
        executor = SkillExecutor()
        result = executor.execute(skill, {"url": "https://example.com"}, {})
        assert result.status == "success"
        assert len(result.results) == 1
        data = result.results[0].data
        assert data["ok"] is True
        assert data["status_code"] == 200
        assert data["body"] == '{"ok": true}'
        assert data["headers"] == {"content-type": "application/json"}
        assert data["elapsed_ms"] == 42

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

    def test_error_result_passed_through(
        self, registry: PrimitiveRegistry
    ) -> None:
        """An error from the primitive is passed through unchanged."""
        class ErrorHttpFetchPrimitive(PrimitiveBase):
            def __init__(self) -> None:
                super().__init__(
                    name="stdlib.http.fetch",
                    description="Failing stub",
                    primitive_type=PrimitiveType.PYTHON,
                )
            def validate_args(self, args: dict) -> None:
                pass
            def execute(self, args: dict, context: dict) -> PrimitiveResult:
                return PrimitiveResult(
                    status="error",
                    data={
                        "ok": False,
                        "error_type": "ConnectionError",
                        "error_message": "DNS resolution failed",
                        "elapsed_ms": 1500,
                    },
                )

        err_reg = PrimitiveRegistry()
        err_reg.register("stdlib.http.fetch", ErrorHttpFetchPrimitive())
        manifest = SkillManifest(
            name="stdlib.fetch.url",
            description="HTTP GET fetch skill",
            primitives=["stdlib.http.fetch"],
            inputs={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            steps=[{"call": "stdlib.http.fetch", "args": {"url": "{{ url }}"}}],
        )
        skill = CapabilitySkill(
            manifest=manifest,
            primitives={"stdlib.http.fetch": err_reg.get("stdlib.http.fetch")},
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "error_type": {},
                    "error_message": {},
                    "elapsed_ms": {"type": "integer"},
                },
            },
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {"url": "https://example.com"}, {})
        assert result.status == "error"
        data = result.results[0].data
        assert data["ok"] is False
        assert data["error_type"] == "ConnectionError"
        assert data["error_message"] == "DNS resolution failed"
        assert data["elapsed_ms"] == 1500
