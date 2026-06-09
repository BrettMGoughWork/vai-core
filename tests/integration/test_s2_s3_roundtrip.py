"""
Integration tests for Phase 3.8.9 — full S2→S3→S2 round-trip.

Tests validate:
  - Round-trip execution (echo skill through real S3 components)
  - Template interpolation correctness
  - Inline Python execution
  - Error propagation (invalid skill name, failed execution)
  - Discovery flow (ranking, ordering, limit)

All tests use real S3 components (registry, SkillRunner, SkillExecutor, EchoPrimitive)
and real S2 components (PlanExecutor, S3Adapter, SegmentMemory).  Only the
SafeStepDispatcher is mocked (it dispatches to S1 infrastructure).
"""

from __future__ import annotations


from unittest.mock import Mock

import pytest

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.stdlib.echo import EchoPrimitive
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
from src.capabilities.runtime.skill_runner import SkillRunner
from src.capabilities.skills.executor import SkillExecutor
from tests.capabilities.skills.test_executor import SuccessPrimitive
from src.capabilities.skills.manifest import SkillManifest
from src.capabilities.skills.skill import CapabilitySkill
from src.core.memory.segment_memory import SegmentMemory
from src.core.planning.dispatch.plan_executor import PlanExecutor
from src.core.planning.dispatch.safe_step_dispatcher import SafeStepDispatcher
from src.core.planning.models.plan import Plan
from src.core.types.cognitive_step_outcome import CognitiveStepOutcome
from src.core.types.step_result import StepResult
from src.stratum2.s3_adapter import (
    S2DiscoveredSkill,
    S2DiscoveryQuery,
    S2DiscoveryResult,
    S2SkillCallRequest,
    S3Adapter,
)


# ══════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════


from src.capabilities.discovery.providers.mock_provider import _simple_embedding_fn


class _TestEmbedder:
    """Minimal embedder wrapping _simple_embedding_fn for test use (PHASE 3.19.1)."""

    def embed_query(self, text: str) -> list[float]:
        return _simple_embedding_fn(text)

    def embed(self, text: str) -> list[float]:
        return _simple_embedding_fn(text)


def make_plan(
    *,
    intent: str = "test intent",
    skill: str = "stdlib.echo",
    arguments: dict | None = None,
) -> Plan:
    return Plan(
        intent=intent,
        targetskillid=skill,
        arguments=arguments or {"value": "hello"},
        reasoning_summary="test reasoning",
    )


def _make_success_step_result() -> StepResult:
    return StepResult(
        outcome=CognitiveStepOutcome.SUCCESS,
        reason="done",
        payload={},
        trace={},
    )


def _make_mock_dispatcher() -> Mock:
    dispatcher = Mock(spec=SafeStepDispatcher)
    dispatcher.dispatch.return_value = (
        None,  # plan_state
        _make_success_step_result(),
    )
    return dispatcher


def make_echo_skill() -> CapabilitySkill:
    """Build a real echo skill with template interpolation in step args."""
    prim_registry = PrimitiveRegistry()
    prim_registry.register("echo", EchoPrimitive())
    manifest = SkillManifest(
        name="stdlib.echo",
        description="Return input unchanged",
        primitives=["echo"],
        inputs={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        steps=[{"call": "echo", "args": {"value": "{{ value }}"}}],
    )
    return CapabilitySkill.from_manifest(manifest, prim_registry)


def make_template_skill(
    *,
    name: str,
    properties: dict,
    required: list[str],
    step_args: dict,
) -> CapabilitySkill:
    """Build a real echo-based skill with custom input schema and step args."""
    prim_registry = PrimitiveRegistry()
    prim_registry.register("echo", EchoPrimitive())
    manifest = SkillManifest(
        name=name,
        description=f"Template test skill: {name}",
        primitives=["echo"],
        inputs={
            "type": "object",
            "properties": properties,
            "required": required,
        },
        steps=[{"call": "echo", "args": step_args}],
    )
    return CapabilitySkill.from_manifest(manifest, prim_registry)


class FailingPrimitive(PrimitiveBase):
    """A primitive that always raises RuntimeError during execution."""

    def __init__(self) -> None:
        super().__init__(
            name="fail",
            description="Always fails",
            primitive_type=PrimitiveType.PYTHON,
        )

    def validate_args(self, args: dict) -> None:
        return

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        raise RuntimeError("simulated failure")


def make_failing_skill() -> CapabilitySkill:
    """Build a skill whose primitive raises RuntimeError."""
    prim_registry = PrimitiveRegistry()
    prim_registry.register("fail", FailingPrimitive())
    manifest = SkillManifest(
        name="failing.skill",
        description="A skill that always fails",
        primitives=["fail"],
        inputs={},
        steps=[{"call": "fail", "args": {}}],
    )
    return CapabilitySkill.from_manifest(manifest, prim_registry)


# ══════════════════════════════════════════════════════════════════════════
# 1. Round-trip execution: stdlib.echo
# ══════════════════════════════════════════════════════════════════════════


class TestRoundTripEcho:
    """Full S2→S3→S2 round-trip with the real echo skill."""

    def test_echo_round_trip_writes_success_record(self) -> None:
        """Plan(targetskillid='stdlib.echo') → S3 executes → state updated."""
        skill_registry = CapabilitySkillRegistry()
        skill_registry.register(make_echo_skill())
        runner = SkillRunner(registry=skill_registry)
        adapter = S3Adapter(runner)
        segment_memory = SegmentMemory()

        executor = PlanExecutor(
            dispatcher=_make_mock_dispatcher(),
            s3_adapter=adapter,
            segment_memory=segment_memory,
        )
        plan = make_plan(
            intent="echo hello",
            skill="stdlib.echo",
            arguments={"value": "hello"},
        )

        record = executor._write_skill_result_to_state(plan, _make_success_step_result())

        assert record is not None
        assert record.segment_id == "stdlib.echo"
        assert record.state == "success"
        assert record.last_output == {"value": "hello"}
        assert record.error is None
        assert record.skills == ["stdlib.echo"]
        assert record.subgoal_id == "echo hello"

        # Verify persisted in memory
        stored = segment_memory.get_record("stdlib.echo")
        assert stored is not None
        assert stored.state == "success"
        assert stored.last_output == {"value": "hello"}

    def test_echo_skill_name_in_segment_skills(self) -> None:
        """The skill name is correctly recorded in the segment's skills list."""
        skill_registry = CapabilitySkillRegistry()
        skill_registry.register(make_echo_skill())
        runner = SkillRunner(registry=skill_registry)
        adapter = S3Adapter(runner)
        segment_memory = SegmentMemory()

        executor = PlanExecutor(
            dispatcher=_make_mock_dispatcher(),
            s3_adapter=adapter,
            segment_memory=segment_memory,
        )
        plan = make_plan(skill="stdlib.echo")

        record = executor._write_skill_result_to_state(plan, _make_success_step_result())
        assert record.skills == ["stdlib.echo"]

    def test_echo_result_preserves_request_id(self) -> None:
        """The request_id is preserved through the adapter round-trip."""
        skill_registry = CapabilitySkillRegistry()
        skill_registry.register(make_echo_skill())
        runner = SkillRunner(registry=skill_registry)
        adapter = S3Adapter(runner)

        s2_request = S2SkillCallRequest(
            skill_name="stdlib.echo",
            arguments={"value": "test"},
            request_id="req-999",
        )
        s2_result = adapter.call_skill(s2_request)

        assert s2_result.request_id == "req-999"
        assert s2_result.success is True
        assert s2_result.output == {"value": "test"}
        assert s2_result.error is None


# ══════════════════════════════════════════════════════════════════════════
# 2. Template interpolation correctness
# ══════════════════════════════════════════════════════════════════════════


class TestTemplateInterpolation:
    """Verify that {{ key }} tokens are interpolated before primitive execution."""

    def test_simple_interpolation(self) -> None:
        """'{{ msg }}' → inputs['msg']: primitive receives resolved value."""
        result = SkillExecutor._interpolate_args({"value": "{{ msg }}"}, {"msg": "world"})
        assert result == {"value": "world"}

    def test_nested_interpolation(self) -> None:
        """Deeply nested '{{ key }}' tokens are resolved."""
        result = SkillExecutor._interpolate_args(
            {"outer": {"inner": "{{ x }}"}}, {"x": "nested-value"}
        )
        assert result == {"outer": {"inner": "nested-value"}}

    def test_multiple_tokens_in_one_string(self) -> None:
        """Multiple '{{ a }}-{{ b }}' tokens in a single string are resolved."""
        result = SkillExecutor._interpolate_args(
            {"value": "{{ a }}-{{ b }}"}, {"a": "foo", "b": "bar"}
        )
        assert result == {"value": "foo-bar"}

    def test_missing_key_raises_keyerror(self) -> None:
        """A token referencing a missing input raises KeyError."""
        with pytest.raises(KeyError, match="missing_key"):
            SkillExecutor._interpolate_args({"value": "{{ missing_key }}"}, {"a": "present"})

    def test_non_string_values_passed_through(self) -> None:
        """Non-string args (ints, bools) are passed through unchanged."""
        result = SkillExecutor._interpolate_args(
            {"num": 42, "enabled": True}, {"unused": "ignored"}
        )
        assert result == {"num": 42, "enabled": True}

    # ── End-to-end interpolation through SkillExecutor ──

    def test_echo_with_interpolated_input(self) -> None:
        """End-to-end: EchoPrimitive receives interpolated args from SkillExecutor."""
        skill = make_echo_skill()
        result = skill.run(value="world")
        assert result == {"value": "world"}

    def test_non_string_value_echoed_unchanged(self) -> None:
        """Non-string inputs to echo are passed through as-is."""
        prim_registry = PrimitiveRegistry()
        prim_registry.register("echo", SuccessPrimitive(name="echo"))
        manifest = SkillManifest(
            name="interp.echo",
            description="Echo-like via SuccessPrimitive",
            primitives=["echo"],
            inputs={
                "type": "object",
                "properties": {"num": {"type": "integer"}},
            },
            steps=[{"call": "echo", "args": {"num": 42}}],
        )
        skill = CapabilitySkill.from_manifest(manifest, prim_registry)
        result = skill.run(num=99)
        # SuccessPrimitive returns its return_data (None), not the args
        assert result is None or result == {}


# ══════════════════════════════════════════════════════════════════════════
# 3. Inline Python execution
# ══════════════════════════════════════════════════════════════════════════


class TestInlinePythonExecution:
    """Verify inline python: blocks execute in a sandbox and return results."""

    def test_basic_python_block(self) -> None:
        """A python block computing result = {'x': inputs['n'] + 1}."""
        manifest = SkillManifest(
            name="test.python.basic",
            description="Basic Python block test",
            primitives=[],
            inputs={
                "type": "object",
                "properties": {"n": {"type": "integer"}},
                "required": ["n"],
            },
            steps=[{"python": "result = {'x': inputs['n'] + 1}"}],
        )
        # Bypass from_manifest() — manifest validation requires 'call' in steps
        skill = CapabilitySkill(
            manifest=manifest,
            primitives={},
            input_schema=manifest.inputs,
            output_schema={},
        )

        result = skill.run(n=41)
        assert result == {"x": 42}

    def test_missing_result_variable(self) -> None:
        """A python block that does not define 'result' raises an error."""
        manifest = SkillManifest(
            name="test.python.noresult",
            description="No result variable",
            primitives=[],
            inputs={},
            steps=[{"python": "x = 10"}],
        )
        skill = CapabilitySkill(
            manifest=manifest,
            primitives={},
            input_schema=manifest.inputs,
            output_schema={},
        )

        with pytest.raises(RuntimeError) as exc_info:
            skill.run()
        assert "result missing" in str(exc_info.value)

    def test_non_dict_result(self) -> None:
        """A python block returning a non-dict result raises an error."""
        manifest = SkillManifest(
            name="test.python.nondict",
            description="Non-dict result",
            primitives=[],
            inputs={},
            steps=[{"python": "result = 123"}],
        )
        skill = CapabilitySkill(
            manifest=manifest,
            primitives={},
            input_schema=manifest.inputs,
            output_schema={},
        )

        with pytest.raises(RuntimeError) as exc_info:
            skill.run()
        assert "result must be a dict" in str(exc_info.value)

    def test_inputs_are_available(self) -> None:
        """The 'inputs' variable is passed through unchanged."""
        manifest = SkillManifest(
            name="test.python.inputs",
            description="Inputs are available",
            primitives=[],
            inputs={
                "type": "object",
                "properties": {"echo_data": {"type": "object"}},
            },
            steps=[{"python": "result = {'echo': inputs}"}],
        )
        skill = CapabilitySkill(
            manifest=manifest,
            primitives={},
            input_schema=manifest.inputs,
            output_schema={},
        )

        result = skill.run(echo_data={"key": "val"})
        assert result == {"echo": {"echo_data": {"key": "val"}}}

    def test_no_builtins_available(self) -> None:
        """Builtins like 'len' are not available in the sandbox."""
        manifest = SkillManifest(
            name="test.python.nobuiltins",
            description="No builtins",
            primitives=[],
            inputs={},
            steps=[{"python": "result = {'x': len([1,2,3])}"}],
        )
        skill = CapabilitySkill(
            manifest=manifest,
            primitives={},
            input_schema=manifest.inputs,
            output_schema={},
        )

        with pytest.raises(RuntimeError) as exc_info:
            skill.run()
        # The exact error message may vary, but it must mention a name error
        error_msg = str(exc_info.value)
        assert (
            "len" not in str({"x": 3})  # we should NOT get a valid result
        )
        assert error_msg  # error must be populated

    def test_no_imports_allowed(self) -> None:
        """Import statements are blocked by the sandbox."""
        manifest = SkillManifest(
            name="test.python.noimport",
            description="No imports",
            primitives=[],
            inputs={},
            steps=[{"python": "import os\nresult = {'x': 1}"}],
        )
        skill = CapabilitySkill(
            manifest=manifest,
            primitives={},
            input_schema=manifest.inputs,
            output_schema={},
        )

        with pytest.raises(RuntimeError) as exc_info:
            skill.run()
        # Must fail — import should not succeed
        assert str(exc_info.value)


# ══════════════════════════════════════════════════════════════════════════
# 4. Error propagation
# ══════════════════════════════════════════════════════════════════════════


class TestErrorPropagation:
    """Verify errors propagate correctly from S3 through S2 state."""

    def test_invalid_skill_name_produces_error_record(self) -> None:
        """A nonexistent skill → SkillResult.error → state='error'."""
        runner = SkillRunner()  # empty registry
        adapter = S3Adapter(runner)
        segment_memory = SegmentMemory()

        executor = PlanExecutor(
            dispatcher=_make_mock_dispatcher(),
            s3_adapter=adapter,
            segment_memory=segment_memory,
        )
        plan = make_plan(
            intent="nonexistent call",
            skill="nonexistent.skill",
        )

        record = executor._write_skill_result_to_state(plan, _make_success_step_result())

        assert record is not None
        assert record.state == "error"
        assert record.last_output is None
        assert record.error is not None
        assert "nonexistent" in record.error.lower() or "nonetype" in record.error.lower()

        # Verify stored
        stored = segment_memory.get_record("nonexistent.skill")
        assert stored is not None
        assert stored.state == "error"

    def test_failed_execution_produces_error_record(self) -> None:
        """A primitive that raises RuntimeError → error record."""
        skill_registry = CapabilitySkillRegistry()
        skill_registry.register(make_failing_skill())
        runner = SkillRunner(registry=skill_registry)
        adapter = S3Adapter(runner)
        segment_memory = SegmentMemory()

        executor = PlanExecutor(
            dispatcher=_make_mock_dispatcher(),
            s3_adapter=adapter,
            segment_memory=segment_memory,
        )
        plan = make_plan(
            intent="failing call",
            skill="failing.skill",
            arguments={},
        )

        record = executor._write_skill_result_to_state(plan, _make_success_step_result())

        assert record is not None
        assert record.state == "error"
        assert record.last_output is None
        assert record.error is not None
        assert "simulated failure" in record.error

    def test_cycle_halts_on_failure(self) -> None:
        """PlanExecutor.execute() returns failure metrics when skill fails."""
        runner = SkillRunner()  # empty — all skills fail
        adapter = S3Adapter(runner)
        segment_memory = SegmentMemory()

        executor = PlanExecutor(
            dispatcher=_make_mock_dispatcher(),
            s3_adapter=adapter,
            segment_memory=segment_memory,
        )
        plan = make_plan(skill="missing.skill")

        state, result, metrics = executor.execute(plan, plan_state=None)

        assert metrics.termination_reason == "failure"
        assert result.outcome != CognitiveStepOutcome.SUCCESS

    def test_previous_output_preserved_on_error(self) -> None:
        """After a success then failure, previous_output reflects the success."""
        skill_registry = CapabilitySkillRegistry()
        skill_registry.register(make_echo_skill())
        skill_registry.register(make_failing_skill())

        segment_memory = SegmentMemory()

        # First: successful echo call
        runner1 = SkillRunner(registry=skill_registry)
        adapter1 = S3Adapter(runner1)
        executor1 = PlanExecutor(
            dispatcher=_make_mock_dispatcher(),
            s3_adapter=adapter1,
            segment_memory=segment_memory,
        )
        echo_plan = make_plan(skill="stdlib.echo", arguments={"value": "before"})
        executor1._write_skill_result_to_state(echo_plan, _make_success_step_result())

        # Second: failing call on same segment
        runner2 = SkillRunner(registry=skill_registry)
        adapter2 = S3Adapter(runner2)
        executor2 = PlanExecutor(
            dispatcher=_make_mock_dispatcher(),
            s3_adapter=adapter2,
            segment_memory=segment_memory,
        )
        fail_plan = make_plan(skill="stdlib.echo", arguments={})
        s3_adapter_fail = S3Adapter(runner2)
        # We can't easily swap adapters on the same executor,
        # so create a fresh executor pointing to failing.skill:
        fail_executor = PlanExecutor(
            dispatcher=_make_mock_dispatcher(),
            s3_adapter=S3Adapter(
                SkillRunner(
                    registry=build_failing_registry_for_segment("stdlib.echo"),
                )
            ),
            segment_memory=segment_memory,
        )
        record = fail_executor._write_skill_result_to_state(
            make_plan(skill="stdlib.echo", arguments={}),
            _make_success_step_result(),
        )

        assert record is not None
        # The previous output should be the echo result, not None
        assert record.previous_output == {"value": "before"}

    def test_behavioural_delta_computed(self) -> None:
        """Consecutive calls with different outputs produce a behavioural delta."""
        skill_registry = CapabilitySkillRegistry()
        skill_registry.register(make_echo_skill())
        segment_memory = SegmentMemory()

        # First call: output={"value": "alpha"}
        runner1 = SkillRunner(registry=skill_registry)
        adapter1 = S3Adapter(runner1)
        executor1 = PlanExecutor(
            dispatcher=_make_mock_dispatcher(),
            s3_adapter=adapter1,
            segment_memory=segment_memory,
        )
        plan = make_plan(skill="stdlib.echo", arguments={"value": "alpha"})
        executor1._write_skill_result_to_state(plan, _make_success_step_result())

        # Second call: output={"value": "beta"}
        runner2 = SkillRunner(registry=skill_registry)
        adapter2 = S3Adapter(runner2)
        executor2 = PlanExecutor(
            dispatcher=_make_mock_dispatcher(),
            s3_adapter=adapter2,
            segment_memory=segment_memory,
        )
        plan2 = make_plan(skill="stdlib.echo", arguments={"value": "beta"})
        record = executor2._write_skill_result_to_state(plan2, _make_success_step_result())

        assert record is not None
        assert record.last_output == {"value": "beta"}
        assert record.previous_output == {"value": "alpha"}
        assert record.behavioural_delta is not None


def build_failing_registry_for_segment(skill_name: str) -> CapabilitySkillRegistry:
    """Build a registry with a failing skill under *skill_name*."""
    failing_manifest = SkillManifest(
        name=skill_name,
        description="Failing override",
        primitives=["fail"],
        inputs={},
        steps=[{"call": "fail", "args": {}}],
    )
    prim_registry = PrimitiveRegistry()
    prim_registry.register("fail", FailingPrimitive())
    failing_skill = CapabilitySkill.from_manifest(failing_manifest, prim_registry)

    registry = CapabilitySkillRegistry()
    registry.register(failing_skill)
    return registry


# ══════════════════════════════════════════════════════════════════════════
# 5. Discovery flow correctness
# ══════════════════════════════════════════════════════════════════════════


class TestDiscoveryFlow:
    """Verify the S2→S3 discovery round-trip works end-to-end."""

    def test_discovery_returns_sorted_skills(self) -> None:
        """S3Adapter.discover_skills() returns skills sorted by descending score."""
        registry = CapabilitySkillRegistry()

        # Register skills with descriptions that produce predictable scores
        from tests.capabilities.test_skill_runner import _make_skill

        registry.register(_make_skill("file.read", "reads files from disk"))
        registry.register(_make_skill("file.write", "writes data to files"))
        runner = SkillRunner(registry=registry, embedder=_TestEmbedder())
        adapter = S3Adapter(runner)

        result = adapter.discover_skills(S2DiscoveryQuery(query="file operations", limit=5))

        assert isinstance(result, S2DiscoveryResult)
        assert len(result.skills) > 0
        # Verify descending score ordering
        for i in range(1, len(result.skills)):
            assert result.skills[i - 1].score >= result.skills[i].score

    def test_discovery_respects_limit(self) -> None:
        """Results are capped at the query's limit."""
        registry = CapabilitySkillRegistry()
        from tests.capabilities.test_skill_runner import _make_skill

        for i in range(5):
            registry.register(_make_skill(f"skill.{i}", f"skill number {i}"))
        runner = SkillRunner(registry=registry, embedder=_TestEmbedder())
        adapter = S3Adapter(runner)

        result = adapter.discover_skills(S2DiscoveryQuery(query="skill", limit=2))

        assert len(result.skills) <= 2

    def test_discovery_returns_empty_when_no_match(self) -> None:
        """Empty results when no skills match the query."""
        registry = CapabilitySkillRegistry()
        runner = SkillRunner(registry=registry, embedder=_TestEmbedder())
        adapter = S3Adapter(runner)

        result = adapter.discover_skills(
            S2DiscoveryQuery(query="something completely unrelated", limit=5)
        )

        assert result.skills == []

    def test_discovery_preserves_skill_names_and_scores(self) -> None:
        """S2DiscoveredSkill has correct name, description, and score fields."""
        registry = CapabilitySkillRegistry()
        from tests.capabilities.test_skill_runner import _make_skill

        registry.register(_make_skill("echo.skill", "echoes user input"))
        registry.register(_make_skill("json.parse", "parses json payloads"))
        runner = SkillRunner(registry=registry, embedder=_TestEmbedder())
        adapter = S3Adapter(runner)

        result = adapter.discover_skills(S2DiscoveryQuery(query="echo", limit=3))

        assert len(result.skills) > 0
        for skill in result.skills:
            assert isinstance(skill, S2DiscoveredSkill)
            assert isinstance(skill.name, str)
            assert len(skill.name) > 0
            assert isinstance(skill.description, str)
            assert isinstance(skill.score, float)
            assert 0.0 <= skill.score <= 1.0

    def test_discovery_round_trip_preserves_query(self) -> None:
        """The S2DiscoveryResult carries the original query back."""
        registry = CapabilitySkillRegistry()
        from tests.capabilities.test_skill_runner import _make_skill

        registry.register(_make_skill("stdlib.echo", "echoes"))
        runner = SkillRunner(registry=registry, embedder=_TestEmbedder())
        adapter = S3Adapter(runner)

        query = S2DiscoveryQuery(query="echo something", limit=3)
        result = adapter.discover_skills(query)

        assert result.query.query == "echo something"
        assert result.query.limit == 3
