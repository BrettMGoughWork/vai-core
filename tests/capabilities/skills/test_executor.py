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
from src.capabilities.skills.skill import CapabilitySkill
from src.capabilities.skills.executor import SkillExecutor, SkillExecutionResult


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
    """Build a minimal CapabilitySkill with mock primitives."""
    primitive_names = list(primitives.keys()) if primitives else []
    manifest = SkillManifest(
        name="test-skill",
        description="A test skill",
        primitives=primitive_names,
        inputs=input_schema or {},
        steps=steps or [],
    )
    return CapabilitySkill(
        manifest=manifest,
        primitives=primitives or {},
        input_schema=input_schema or {},
        output_schema=output_schema or {},
    )


# ---------------------------------------------------------------------------
# SkillExecutionResult tests
# ---------------------------------------------------------------------------

class TestSkillExecutionResult:
    """Tests for the SkillExecutionResult dataclass."""

    def test_success_result_defaults(self):
        """Default success result has expected values."""
        result = SkillExecutionResult(status="success")
        assert result.status == "success"
        assert result.results == []
        assert result.error is None

    def test_error_result_with_error(self):
        """Error result carries an error message."""
        result = SkillExecutionResult(status="error", error="something went wrong")
        assert result.status == "error"
        assert result.error == "something went wrong"

    def test_result_with_primitive_results(self):
        """results field stores PrimitiveResult list."""
        pr = PrimitiveResult(status="success", data={"key": "val"})
        result = SkillExecutionResult(status="success", results=[pr])
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
        """When a primitive returns error, executor returns an error SkillExecutionResult."""
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


# ---------------------------------------------------------------------------
# Template interpolation tests (Phase 3.8.3)
# ---------------------------------------------------------------------------

class ArgCapturePrimitive(PrimitiveBase):
    """A primitive that captures the args it receives, for interpolation testing."""

    def __init__(self, *, name: str = "capture") -> None:
        super().__init__(name=name, description="Captures args", primitive_type=PrimitiveType.PYTHON)
        self.received_args: dict[str, Any] | None = None

    def validate_args(self, _args: dict) -> None:
        return

    def execute(self, args: dict, _context: dict) -> PrimitiveResult:
        self.received_args = dict(args)
        return PrimitiveResult(status="success", data=self.received_args)


class TestTemplateInterpolation:
    """Tests for SkillExecutor._interpolate_args template resolution."""

    def test_simple_interpolation(self):
        """{{ key }} tokens are replaced with input values."""
        prim = ArgCapturePrimitive()
        skill = make_skill(
            primitives={"capture": prim},
            steps=[{"call": "capture", "args": {"msg": "{{ value }}"}}],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {"value": "hello"}, {})
        assert result.status == "success"
        assert prim.received_args == {"msg": "hello"}

    def test_nested_interpolation(self):
        """Deeply nested dict keys are interpolated."""
        prim = ArgCapturePrimitive()
        skill = make_skill(
            primitives={"capture": prim},
            steps=[{"call": "capture", "args": {"outer": {"inner": "{{ x }}"}}}],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {"x": "nested-val"}, {})
        assert result.status == "success"
        assert prim.received_args == {"outer": {"inner": "nested-val"}}

    def test_multiple_tokens_in_one_string(self):
        """Multiple {{ tokens }} in a single string are all resolved."""
        prim = ArgCapturePrimitive()
        skill = make_skill(
            primitives={"capture": prim},
            steps=[{"call": "capture", "args": {"combined": "{{ a }}-{{ b }}"}}],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {"a": "first", "b": "second"}, {})
        assert result.status == "success"
        assert prim.received_args == {"combined": "first-second"}

    def test_prefix_suffix_template(self):
        """Template in the middle of other text is resolved."""
        prim = ArgCapturePrimitive()
        skill = make_skill(
            primitives={"capture": prim},
            steps=[{"call": "capture", "args": {"path": "prefix-{{ id }}-suffix"}}],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {"id": "42"}, {})
        assert result.status == "success"
        assert prim.received_args == {"path": "prefix-42-suffix"}

    def test_missing_key_raises_keyerror(self):
        """Referencing an unknown token key raises KeyError."""
        prim = ArgCapturePrimitive()
        skill = make_skill(
            primitives={"capture": prim},
            steps=[{"call": "capture", "args": {"msg": "{{ missing_key }}"}}],
        )
        executor = SkillExecutor()
        with pytest.raises(KeyError, match="missing_key"):
            executor.execute(skill, {}, {})

    def test_non_string_values_passed_through(self):
        """Integer, float, bool, None, and list values are unchanged."""
        prim = ArgCapturePrimitive()
        skill = make_skill(
            primitives={"capture": prim},
            steps=[
                {
                    "call": "capture",
                    "args": {
                        "int_val": 42,
                        "float_val": 3.14,
                        "bool_val": True,
                        "none_val": None,
                        "list_val": [1, 2, "{{ x }}"],
                    },
                }
            ],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {"x": "replaced"}, {})
        assert result.status == "success"
        assert prim.received_args == {
            "int_val": 42,
            "float_val": 3.14,
            "bool_val": True,
            "none_val": None,
            "list_val": [1, 2, "replaced"],
        }

    def test_no_template_tokens_passthrough(self):
        """Args with no {{ }} tokens pass through unchanged."""
        prim = ArgCapturePrimitive()
        skill = make_skill(
            primitives={"capture": prim},
            steps=[{"call": "capture", "args": {"plain": "no template here"}}],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {"unused": "ignored"}, {})
        assert result.status == "success"
        assert prim.received_args == {"plain": "no template here"}

    def test_entire_value_is_template(self):
        """When the entire string is {{ key }}, the resolved value is passed as-is (stringified)."""
        prim = ArgCapturePrimitive()
        skill = make_skill(
            primitives={"capture": prim},
            steps=[{"call": "capture", "args": {"value": "{{ name }}"}}],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {"name": "world"}, {})
        assert result.status == "success"
        assert prim.received_args == {"value": "world"}


# ---------------------------------------------------------------------------
# Inline Python step tests (Phase 3.8.4)
# ---------------------------------------------------------------------------


class TestInlinePythonSteps:
    """Tests for SkillExecutor inline Python block execution."""

    def test_basic_python_block(self):
        """python: block computes result from inputs."""
        skill = make_skill(
            primitives={},
            steps=[{"python": "result = {'x': inputs['value'] + 1}"}],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {"value": 41}, {})
        assert result.status == "success"
        assert len(result.results) == 1
        assert result.results[0].data == {"x": 42}

    def test_missing_result_variable(self):
        """python: block that does not define 'result' returns error."""
        skill = make_skill(
            primitives={},
            steps=[{"python": "x = 10"}],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {}, {})
        assert result.status == "error"
        assert "result missing" in result.error

    def test_non_dict_result(self):
        """python: block with a non-dict result returns error."""
        skill = make_skill(
            primitives={},
            steps=[{"python": "result = 123"}],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {}, {})
        assert result.status == "error"
        assert "result must be a dict" in result.error

    def test_inputs_are_available(self):
        """The inputs dict is accessible inside the python block."""
        skill = make_skill(
            primitives={},
            steps=[{"python": "result = {'echo': inputs}"}],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {"a": 1, "b": "two"}, {})
        assert result.status == "success"
        assert result.results[0].data == {"echo": {"a": 1, "b": "two"}}

    def test_no_access_to_builtins(self):
        """Builtins like len() are not available in the sandbox."""
        skill = make_skill(
            primitives={},
            steps=[{"python": "result = {'x': len([1,2,3])}"}],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {}, {})
        assert result.status == "error"
        assert "len" in result.error

    def test_no_imports_allowed(self):
        """Import statements are blocked in the sandbox."""
        skill = make_skill(
            primitives={},
            steps=[{"python": "import os\nresult = {'x': 1}"}],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {}, {})
        assert result.status == "error"

    def test_python_and_call_mutual_exclusivity(self):
        """A step with both 'python' and 'call' raises ValueError."""
        prim = SuccessPrimitive(name="a")
        skill = make_skill(
            primitives={"a": prim},
            steps=[{"python": "result = {}", "call": "a", "args": {}}],
        )
        executor = SkillExecutor()
        with pytest.raises(ValueError, match="both"):
            executor.execute(skill, {}, {})

    def test_neither_python_nor_call_raises(self):
        """A step without 'python' or 'call' raises ValueError."""
        skill = make_skill(
            primitives={},
            steps=[{"description": "no python or call here"}],
        )
        executor = SkillExecutor()
        with pytest.raises(ValueError, match="must contain"):
            executor.execute(skill, {}, {})

    def test_python_step_on_error_continue(self):
        """A python step with on_error='continue' proceeds to next step."""
        skill = make_skill(
            primitives={},
            steps=[
                {"python": "x = 10", "on_error": "continue"},
                {"python": "result = {'recovered': True}"},
            ],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {}, {})
        assert result.status == "success"
        assert len(result.results) == 2
        assert result.results[0].status == "error"
        assert result.results[1].status == "success"

    def test_python_step_on_error_stops(self):
        """A python step without on_error stops execution on failure."""
        skill = make_skill(
            primitives={},
            steps=[
                {"python": "x = 10"},
                {"python": "result = {'never': True}"},
            ],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {}, {})
        assert result.status == "error"
        assert len(result.results) == 1

    def test_mixed_python_and_call_steps(self):
        """A skill can mix python: and call: steps sequentially."""
        prim = SuccessPrimitive(name="echo", return_data={"from_primitive": True})
        skill = make_skill(
            primitives={"echo": prim},
            steps=[
                {"python": "result = {'computed': inputs['x'] * 2}"},
                {"call": "echo", "args": {}},
            ],
        )
        executor = SkillExecutor()
        result = executor.execute(skill, {"x": 5}, {})
        assert result.status == "success"
        assert len(result.results) == 2
        assert result.results[0].data == {"computed": 10}
        assert result.results[1].data == {"from_primitive": True}
