"""
Tests for SkillRunner (Phase 3.8.2).

Covers: execute() with valid/missing skills, discover() with matching
and empty results.
"""

from __future__ import annotations

import math

import pytest

from src.capabilities.contracts import (
    SkillCallRequest,
    SkillDiscoveryQuery,
    SkillDiscoveryResult,
)
from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
from src.capabilities.runtime.skill_runner import SkillRunner
from src.capabilities.skills.manifest import SkillManifest
from src.capabilities.skills.skill import CapabilitySkill


# ---------------------------------------------------------------------------
# Fake primitives
# ---------------------------------------------------------------------------

class SuccessPrimitive(PrimitiveBase):
    """A primitive that returns success with configurable data."""

    def __init__(
        self,
        *,
        name: str,
        return_data: dict | None = None,
    ) -> None:
        super().__init__(
            name=name,
            description=f"Mock {name}",
            primitive_type=PrimitiveType.PYTHON,
        )
        self._return_data = return_data

    def validate_args(self, _args: dict) -> None:
        return

    def execute(self, _args: dict, _context: dict) -> PrimitiveResult:
        return PrimitiveResult(status="success", data=self._return_data)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skill(
    name: str,
    description: str = "a skill",
    primitive_names: list[str] | None = None,
    steps: list[dict] | None = None,
    return_data: dict | None = None,
) -> CapabilitySkill:
    """Build a minimal CapabilitySkill with a SuccessPrimitive."""
    if primitive_names is None:
        primitive_names = ["echo"]
    if steps is None:
        steps = [{"call": "echo", "args": {}}]

    prim_registry = PrimitiveRegistry()
    for pn in primitive_names:
        prim_registry.register(pn, SuccessPrimitive(name=pn, return_data=return_data))

    manifest = SkillManifest(
        name=name,
        description=description,
        primitives=primitive_names,
        inputs={},
        steps=steps,
    )
    return CapabilitySkill.from_manifest(manifest, prim_registry)


# ---------------------------------------------------------------------------
# Embedding helpers for discovery tests
# ---------------------------------------------------------------------------

def _simple_embedding_fn(text: str) -> list[float]:
    """
    Deterministic embedding: each character contributes a fixed vector
    component.  Known tokens produce higher similarity for predictable
    ordering in tests.
    """
    vec = [0.0] * 8
    for ch in text:
        idx = ord(ch) % 8
        vec[idx] += 1.0
    magnitude = math.sqrt(sum(v * v for v in vec))
    if magnitude > 0:
        vec = [v / magnitude for v in vec]
    return vec


# ---------------------------------------------------------------------------
# Execution path tests
# ---------------------------------------------------------------------------

class TestSkillRunnerExecute:
    """Tests for SkillRunner.execute()."""

    def test_execute_valid_skill_returns_success(self) -> None:
        """execute() calls the correct skill and returns SkillResult."""
        registry = CapabilitySkillRegistry()
        skill = _make_skill(
            "file.read",
            description="reads a file",
            return_data={"content": "hello"},
        )
        registry.register(skill)
        runner = SkillRunner(registry=registry)

        result = runner.execute(SkillCallRequest(
            skill_name="file.read",
            arguments={},
            request_id="req-001",
        ))

        assert result.request_id == "req-001"
        assert result.success is True
        assert result.output == {"content": "hello"}
        assert result.error is None

    def test_execute_missing_skill_returns_error(self) -> None:
        """execute() handles missing skill and returns SkillResult with error."""
        runner = SkillRunner()

        result = runner.execute(SkillCallRequest(
            skill_name="nonexistent.skill",
            arguments={},
            request_id="req-002",
        ))

        assert result.request_id == "req-002"
        assert result.success is False
        assert result.output is None
        assert result.error is not None
        assert "nonexistent" in result.error.lower() or "NoneType" in result.error


# ---------------------------------------------------------------------------
# Discovery path tests
# ---------------------------------------------------------------------------

class TestSkillRunnerDiscover:
    """Tests for SkillRunner.discover()."""

    def test_discover_returns_skill_discovery_result(self) -> None:
        """discover() returns SkillDiscoveryResult with sorted, limited skills."""
        registry = CapabilitySkillRegistry()
        registry.register(_make_skill("file.read", "reads files from disk"))
        registry.register(_make_skill("file.write", "writes data to files"))
        runner = SkillRunner(registry=registry, embedding_fn=_simple_embedding_fn)

        result = runner.discover(SkillDiscoveryQuery(
            query="file operations",
            limit=2,
        ))

        assert isinstance(result, SkillDiscoveryResult)
        assert len(result.skills) <= 2
        assert len(result.skills) > 0

        # Verify descending-score ordering
        for i in range(1, len(result.skills)):
            assert result.skills[i - 1].score >= result.skills[i].score

    def test_discover_empty_when_no_match(self) -> None:
        """discover() returns empty list when no skills match the query."""
        # Registry with skills that won't match the query semantically
        registry = CapabilitySkillRegistry()
        runner = SkillRunner(registry=registry, embedding_fn=_simple_embedding_fn)

        result = runner.discover(SkillDiscoveryQuery(
            query="something completely unrelated",
            limit=5,
        ))

        assert result.skills == []

    def test_discover_respects_limit(self) -> None:
        """discover() returns at most limit skills."""
        registry = CapabilitySkillRegistry()
        for i in range(5):
            registry.register(_make_skill(f"skill.{i}", f"skill number {i}"))
        runner = SkillRunner(registry=registry, embedding_fn=_simple_embedding_fn)

        result = runner.discover(SkillDiscoveryQuery(
            query="skill",
            limit=2,
        ))

        assert len(result.skills) <= 2

    def test_discover_raises_without_embedding_fn(self) -> None:
        """discover() raises ValueError when no embedding_fn is provided."""
        runner = SkillRunner()

        with pytest.raises(ValueError, match="embedding_fn"):
            runner.discover(SkillDiscoveryQuery(query="test", limit=5))
