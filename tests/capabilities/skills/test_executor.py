"""
Tests for SkillExecutor (Phase 3.3.4).

Covers: sequential execution, success/error results, on_error='continue'
semantics, unknown primitives, and output validation.
"""

from __future__ import annotations

import pytest

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveType, PrimitiveResult
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.skills.manifest import SkillManifest
from src.capabilities.skills.skill import Skill
from src.capabilities.skills.executor import SkillExecutor, SkillResult


# ---------------------------------------------------------------------------
# Fake / Mock primitives
# ---------------------------------------------------------------------------

class SuccessPrimitive(PrimitiveBase):
    """A primitive that always returns success."""

    def __init__(self, *, name: str, return_data=None) -> None:
        super().__init__(name=name, description=f"Mock {name}", primitive_type=PrimitiveType.PYTHON)
        self._return_data = return_data

    def validate_args(self, _args: dict) -> None:
        return

    def execute(self, _args: dict, _context: dict) -> PrimitiveResult:
        return PrimitiveResult(status="success", data=self._return_data)


class ErrorPrimitive(PrimitiveBase):
    """A primitive that always returns an error."""

    def __init__(self, *, name: str, error_msg: str = "mock error") -> None:
        super().__init__(name=name, description=f"Mock {name}", primitive_type=PrimitiveType.PYTHON)
        self._error_msg = error_msg

    def validate_args(self, _args: dict) -> None:
        return

    def execute(self, _args: dict, _context: dict) -> PrimitiveResult:
        return PrimitiveResult(status="error", error=self._error_msg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_skill(*, primitives=None, steps=None, input_schema=None, output_schema=None):
    """Build a minimal Skill with mock primitives."""
    primitive_names = list(primitives.keys()) if primitives else []
    manifest = SkillManifest(
        name="test-skill",
        description="A test skill",
        primitives=primitive_names,
        inputs=input_schema or {},
        steps=steps or [],
    )
    return Skill(
        manifest=manifest,
        primitives=primitives or {},
        input_schema=input_schema or {},
        output_schema=output_schema or {},
    )


# ---------------------------------------------------------------------------
# SkillResult tests
# ---------------------------------------------------------------------------

class TestSkillResult:
    """Tests for the SkillResult dataclass."""

    def test_success_result_defaults(self):
        """Default success result has expected values."""
        result = SkillResult(status="success")
        assert result.status == "success"
        assert result.results == []
        assert result.error is None

    def test_error_result_with_error(self):
        """Error result carries an error message."""
        result = SkillResult(status="error", error="something went wrong")
        assert result.status == "error"
        assert result.error == "something went wrong"

    def test_result_with_primitive_results(self):
        """results field stores PrimitiveResult list."""
        pr = PrimitiveResult(status="success", data={"key": "val"})
        result = SkillResult(status="success", results=[pr])
        assert len(result.results) == 1
        assert result.results[0].data == {"key": "val"}


# ---------------------------------------------------------------------------
# SkillExecutor tests
# ---------------------------------------------------------------------------

class TestSkillExecutor:
    """Tests for SkillExecutor.execute."""

    def test_sequential_execution_returns_success(self):
        """A skill with success-primitive steps returns success."""
        prim_a = SuccessPrimitive(name="a", return_data={"step": "a"})
        prim_b = SuccessPrimitive(name="b", return_data={"step": "b"})
        skill = make_skill(
            primitives={"a": prim_a, "b": prim_b},
            steps=[
                {"call": "a", "args": {}},
                {"call": "b", "args": {}},
            ],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {}, {})
        assert result.status == "success"
        assert len(result.results) == 2
        assert result.results[0].data == {"step": "a"}
        assert result.results[1].data == {"step": "b"}
        assert result.error is None

    def test_single_step_skill(self):
        """A single-step skill executes correctly."""
        prim = SuccessPrimitive(name="only", return_data={"done": True})
        skill = make_skill(
            primitives={"only": prim},
            steps=[{"call": "only", "args": {"x": 1}}],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {}, {})
        assert result.status == "success"
        assert len(result.results) == 1

    def test_error_primitive_returns_error_result(self):
        """When a primitive returns error, executor returns an error SkillResult."""
        prim = ErrorPrimitive(name="fail", error_msg="boom")
        skill = make_skill(
            primitives={"fail": prim},
            steps=[{"call": "fail", "args": {}}],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {}, {})
        assert result.status == "error"
        assert result.error == "boom"
        assert len(result.results) == 1

    def test_error_with_on_error_continue_continues(self):
        """on_error='continue' causes the executor to keep executing."""
        err_prim = ErrorPrimitive(name="soft-fail", error_msg="non-fatal")
        ok_prim = SuccessPrimitive(name="recover", return_data={"recovered": True})
        skill = make_skill(
            primitives={"soft-fail": err_prim, "recover": ok_prim},
            steps=[
                {"call": "soft-fail", "args": {}, "on_error": "continue"},
                {"call": "recover", "args": {}},
            ],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {}, {})
        assert result.status == "success"
        assert len(result.results) == 2
        assert result.results[0].status == "error"
        assert result.results[1].status == "success"

    def test_error_without_on_error_stops_early(self):
        """Without on_error='continue', an error step stops execution immediately."""
        err_prim = ErrorPrimitive(name="hard-fail", error_msg="fatal")
        ok_prim = SuccessPrimitive(name="never-called", return_data={})
        called = []

        class TrackingPrimitive(PrimitiveBase):
            def __init__(self):
                super().__init__(name="never-called", description="", primitive_type=PrimitiveType.PYTHON)
            def validate_args(self, _): pass
            def execute(self, _a, _c):
                called.append(True)
                return PrimitiveResult(status="success")

        skill = make_skill(
            primitives={"hard-fail": err_prim, "never-called": TrackingPrimitive()},
            steps=[
                {"call": "hard-fail", "args": {}},
                {"call": "never-called", "args": {}},
            ],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {}, {})
        assert result.status == "error"
        assert result.error == "fatal"
        assert len(result.results) == 1
        assert called == []  # Second step never executed.

    def test_unknown_primitive_in_step_raises(self):
        """A step referencing an unresolved primitive raises ValueError."""
        prim = SuccessPrimitive(name="a")
        skill = make_skill(
            primitives={"a": prim},
            steps=[{"call": "unknown", "args": {}}],
        )
        executor = SkillExecutor()
        with pytest.raises(ValueError, match="unknown primitive"):
            executor.execute(skill, {}, {})

    def test_no_steps_returns_success(self):
        """A skill with zero steps returns success immediately."""
        skill = make_skill(primitives={}, steps=[])
        executor = SkillExecutor()
        result = executor.execute(skill, {}, {})
        assert result.status == "success"
        assert result.results == []

    def test_inputs_validated_before_execution(self):
        """Input schema validation runs before any step executes."""
        prim = SuccessPrimitive(name="a")
        skill = make_skill(
            primitives={"a": prim},
            steps=[{"call": "a", "args": {}}],
            input_schema={
                "type": "object",
                "properties": {"required_field": {"type": "string"}},
                "required": ["required_field"],
            },
        )
        executor = SkillExecutor()
        with pytest.raises(ValueError, match="missing required key"):
            executor.execute(skill, {}, {})

    def test_output_validation_on_final_step(self):
        """The final step's output is validated against output_schema."""
        prim = SuccessPrimitive(name="a", return_data={"result": "ok"})
        skill = make_skill(
            primitives={"a": prim},
            steps=[{"call": "a", "args": {}}],
            output_schema={
                "type": "object",
                "properties": {"result": {"type": "string"}},
                "required": ["result"],
            },
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {}, {})
        assert result.status == "success"

    def test_output_validation_failure_raises(self):
        """If the final step output fails schema validation, ValueError is raised."""
        prim = SuccessPrimitive(name="a", return_data={"wrong_key": 123})
        skill = make_skill(
            primitives={"a": prim},
            steps=[{"call": "a", "args": {}}],
            output_schema={
                "type": "object",
                "properties": {"result": {"type": "string"}},
                "required": ["result"],
            },
        )
        executor = SkillExecutor()
        with pytest.raises(ValueError, match="missing required key"):
            executor.execute(skill, {}, {})

    def test_context_passed_to_primitives(self):
        """The context dict is forwarded to each primitive's execute method."""
        received_context = []

        class ContextSpy(PrimitiveBase):
            def __init__(self):
                super().__init__(name="spy", description="", primitive_type=PrimitiveType.PYTHON)
            def validate_args(self, _): pass
            def execute(self, _a, context):
                received_context.append(context)
                return PrimitiveResult(status="success")

        skill = make_skill(
            primitives={"spy": ContextSpy()},
            steps=[{"call": "spy", "args": {}}],
        )
        executor = SkillExecutor()
        ctx = {"trace_id": "abc-123", "user": "test"}
        executor.execute(skill, {}, ctx)
        assert received_context == [ctx]
