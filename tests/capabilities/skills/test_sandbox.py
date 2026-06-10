"""Tests for behavioural skill sandbox (Phase 3.17.3 / 3.17.5).

Covers: mock-primitive data generation, timeout configuration,
        SandboxReport/SandboxCall structures, and sandbox execution
        with mock primitives.

Note: The sandbox replaces ALL declared primitives with _MockPrimitive
instances, so timeout and exception paths are defensive (belt-and-suspenders)
that only trigger if the SkillExecutor itself hangs or crashes.  Mock
execution completes near-instantly.
"""

from __future__ import annotations

import pytest

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.skills.manifest import SkillManifest
from src.capabilities.skills.sandbox import (
    SandboxCall,
    SandboxReport,
    SkillSandbox,
)
from src.capabilities.skills.skill import CapabilitySkill


# ── Fake primitive for testing ──────────────────────────────────────────


class _EchoPrimitive(PrimitiveBase):
    """Mock primitive that echoes its arguments."""

    name = "test.echo"
    description = "Echo back args"
    primitive_type = PrimitiveType.PYTHON

    def __init__(self, *, name: str = "test.echo", description: str = "") -> None:
        super().__init__(name=name, description=description or self.description,
                         primitive_type=self.primitive_type)

    def validate_args(self, args: dict) -> None:
        pass

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        return PrimitiveResult(status="success", data={"echoed": args})


# ── Helpers ─────────────────────────────────────────────────────────────


@pytest.fixture
def prim_reg():
    """Registry with test primitives."""
    reg = PrimitiveRegistry()
    reg.register("test.echo", _EchoPrimitive(name="test.echo"))
    return reg


@pytest.fixture
def echo_skill(prim_reg):
    """A trivial valid skill that calls test.echo."""
    manifest = SkillManifest(
        name="sandbox.echo_test",
        description="Sandbox echo test skill",
        primitives=["test.echo"],
        inputs={"value": {"type": "string", "required": True}},
        steps=[{"call": "test.echo", "args": {"value": "{{ value }}"}}],
    )
    return CapabilitySkill.from_manifest(manifest, prim_reg)


@pytest.fixture
def multi_step_skill(prim_reg):
    """A skill with two steps, both calling test.echo."""
    manifest = SkillManifest(
        name="sandbox.multi_test",
        description="Multi-step sandbox test",
        primitives=["test.echo"],
        inputs={},
        steps=[
            {"call": "test.echo", "args": {"value": "step1"}},
            {"call": "test.echo", "args": {"value": "step2"}},
        ],
    )
    return CapabilitySkill.from_manifest(manifest, prim_reg)


@pytest.fixture
def empty_skill(prim_reg):
    """A skill with no steps."""
    manifest = SkillManifest(
        name="sandbox.empty_test",
        description="Empty skill test",
        primitives=[],
        inputs={},
        steps=[],
    )
    return CapabilitySkill.from_manifest(manifest, prim_reg)


# ── Dataclass tests ─────────────────────────────────────────────────────


class TestSandboxDataclasses:
    def test_sandbox_call_creation(self):
        call = SandboxCall(
            primitive_name="test.echo",
            args={"x": 1},
            step_index=0,
            mock_response=PrimitiveResult(status="success", data={"echoed": {"x": 1}}),
        )
        assert call.primitive_name == "test.echo"
        assert call.args == {"x": 1}
        assert call.step_index == 0
        assert call.mock_response.status == "success"

    def test_sandbox_report_defaults(self):
        report = SandboxReport(passed=True)
        assert report.passed is True
        assert report.calls == []
        assert report.warnings == []
        assert report.duration_ms == 0.0
        assert report.timeout_triggered is False
        assert report.error is None

    def test_sandbox_report_failure_with_warnings(self):
        report = SandboxReport(
            passed=False,
            warnings=["undeclared primitive", "timeout"],
            duration_ms=1200.0,
        )
        assert report.passed is False
        assert len(report.warnings) == 2
        assert report.duration_ms == 1200.0


# ── generate_mock_inputs ────────────────────────────────────────────────


class TestGenerateMockInputs:
    def test_flat_schema(self):
        schema = {
            "city": {"type": "string"},
            "count": {"type": "integer"},
            "enabled": {"type": "boolean"},
            "score": {"type": "number"},
        }
        inputs = SkillSandbox.generate_mock_inputs(schema)
        assert isinstance(inputs["city"], str)
        assert isinstance(inputs["count"], int)
        assert isinstance(inputs["enabled"], bool)
        assert isinstance(inputs["score"], float)

    def test_json_schema_style(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }
        inputs = SkillSandbox.generate_mock_inputs(schema)
        assert isinstance(inputs["name"], str)
        assert isinstance(inputs["age"], int)

    def test_empty_schema(self):
        inputs = SkillSandbox.generate_mock_inputs({})
        assert inputs == {}

    def test_unknown_type_fallback(self):
        schema = {"thing": {"type": "unknown_xyz"}}
        inputs = SkillSandbox.generate_mock_inputs(schema)
        assert "thing" in inputs
        assert "[MOCK]" in inputs["thing"]

    def test_non_dict_prop_value(self):
        schema = {"tag": "simple_value"}
        inputs = SkillSandbox.generate_mock_inputs(schema)
        assert inputs["tag"] == "mock_value"


# ── run (happy path) ────────────────────────────────────────────────────


class TestSandboxRun:
    def test_valid_skill_passes(self, prim_reg, echo_skill):
        sandbox = SkillSandbox(prim_reg)
        report = sandbox.run(echo_skill, {"value": "hello"})
        assert report.passed is True
        assert len(report.warnings) == 0
        assert len(report.calls) == 1
        assert report.calls[0].primitive_name == "test.echo"
        assert report.calls[0].step_index == 0
        assert report.calls[0].args == {"value": "hello"}
        assert report.calls[0].mock_response.status == "success"
        assert report.duration_ms > 0
        assert report.timeout_triggered is False
        assert report.error is None

    def test_report_includes_duration(self, prim_reg, echo_skill):
        sandbox = SkillSandbox(prim_reg)
        report = sandbox.run(echo_skill, {"value": "x"})
        assert report.duration_ms >= 0

    def test_context_passed_through(self, prim_reg, echo_skill):
        sandbox = SkillSandbox(prim_reg)
        report = sandbox.run(echo_skill, {"value": "x"}, context={"session_id": "abc"})
        assert report.passed is True

    def test_multi_step_skill(self, prim_reg, multi_step_skill):
        sandbox = SkillSandbox(prim_reg)
        report = sandbox.run(multi_step_skill, {})
        assert report.passed is True
        assert len(report.calls) == 2
        assert report.calls[0].args == {"value": "step1"}
        assert report.calls[1].args == {"value": "step2"}

    def test_empty_skill(self, prim_reg, empty_skill):
        sandbox = SkillSandbox(prim_reg)
        report = sandbox.run(empty_skill, {})
        assert report.passed is True
        assert len(report.calls) == 0


# ── timeout (defensive: mocks are instant, but configuration is verified) ─


class TestSandboxTimeout:
    def test_default_timeout_value(self, prim_reg):
        sandbox = SkillSandbox(prim_reg)
        assert sandbox._timeout_s == SkillSandbox.DEFAULT_TIMEOUT_S

    def test_custom_timeout_value(self, prim_reg):
        sandbox = SkillSandbox(prim_reg, timeout_s=2.0)
        assert sandbox._timeout_s == 2.0

    def test_timeout_not_triggered_with_fast_mocks(self, prim_reg, echo_skill):
        """Mock primitives return instantly, so timeout never fires."""
        sandbox = SkillSandbox(prim_reg, timeout_s=5.0)
        report = sandbox.run(echo_skill, {"value": "x"})
        assert report.timeout_triggered is False
        assert report.passed is True


# ── generate_mock_inputs edge cases ─────────────────────────────────────


class TestGenerateMockInputsEdgeCases:
    def test_integer_constraints_ignored(self):
        """Constraints like min/max are ignored by mock generator."""
        schema = {"count": {"type": "integer", "minimum": 0, "maximum": 100}}
        inputs = SkillSandbox.generate_mock_inputs(schema)
        assert isinstance(inputs["count"], int)

    def test_string_with_enum(self):
        """Enum values are ignored — mock generates random string."""
        schema = {"color": {"type": "string", "enum": ["red", "green", "blue"]}}
        inputs = SkillSandbox.generate_mock_inputs(schema)
        assert isinstance(inputs["color"], str)
