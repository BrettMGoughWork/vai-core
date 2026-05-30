"""
Planning dispatch tests.

Covers:
- OutcomeClassifier.classify(): all label mappings, fallbacks, purity guard
- StepResultFactory: success/failure/tool_needed/continue_reasoning
- ForbiddenCapabilityPolicy and PlanTransitionPolicy (safety policies)
- SafeStepDispatcher: pre/post hooks called in order
"""
import pytest
from types import SimpleNamespace

from src.core.planning.dispatch.outcome_classifier import OutcomeClassifier
from src.core.planning.dispatch import step_result_factory as factory
from src.core.planning.safety.safety_policies import (
    ForbiddenCapabilityPolicy,
    PlanTransitionPolicy,
    SafetyContext,
)
from src.core.planning.dispatch.safe_step_dispatcher import SafeStepDispatcher
from src.core.planning.models.plan import Plan
from src.core.planning.models.plan_state import PlanState, PlanStatus
from src.core.planning.models.step_state import StepState, StepStatus
from src.core.types.step_result import StepResult
from src.core.types.cognitive_step_outcome import CognitiveStepOutcome as StepOutcome
from src.core.types.errors.plan_errors import PlanSafetyPolicyError, PlanTransitionSafetyError
from src.core.types.errors import ValidationError


# ── Helpers ───────────────────────────────────────────────────────────────────

def _state():
    return StepState(step_id="t", cognitive_input={}, created_at=0)


def _plan(skill="echo"):
    return Plan(intent="test", targetskillid=skill, arguments={}, reasoning_summary="ok")


def _plan_state(status=PlanStatus.PENDING):
    return PlanState(
        plan_id="p1", steps=[], current_step_index=0,
        status=status, last_result=None, trace=[], created_at=0, updated_at=0,
    )


class FakeCoreStep:
    """Returns a fixed StepResult for any state."""
    def __init__(self, outcome=StepOutcome.SUCCESS):
        self._outcome = outcome

    def run(self, state):
        result = StepResult(outcome=self._outcome, reason="fake", payload={}, trace={})
        new_state = state.replace(status=StepStatus.DONE)
        return new_state, result

    @property
    def capabilities(self):
        return {"echo": {"description": "echo tool"}}


# ── OutcomeClassifier ─────────────────────────────────────────────────────────

class TestOutcomeClassifier:
    def _classify(self, raw):
        return OutcomeClassifier().classify(_state(), raw)

    def test_success_label_maps_to_success(self):
        r = self._classify({"label": "success", "reason": "done"})
        assert r.outcome == StepOutcome.SUCCESS

    def test_failure_label_maps_to_failure(self):
        r = self._classify({"label": "failure", "reason": "broke"})
        assert r.outcome == StepOutcome.FAILURE

    def test_tool_needed_label_maps_correctly(self):
        r = self._classify({"label": "tool_needed", "reason": "need it"})
        assert r.outcome == StepOutcome.TOOL_NEEDED

    def test_continue_label_maps_correctly(self):
        r = self._classify({"label": "continue", "reason": "not done"})
        assert r.outcome == StepOutcome.CONTINUE

    def test_label_is_case_insensitive_upper(self):
        r = self._classify({"label": "SUCCESS"})
        assert r.outcome == StepOutcome.SUCCESS

    def test_label_is_stripped_of_whitespace(self):
        r = self._classify({"label": "  success  "})
        assert r.outcome == StepOutcome.SUCCESS

    def test_unknown_label_returns_failure(self):
        r = self._classify({"label": "banana"})
        assert r.outcome == StepOutcome.FAILURE

    def test_missing_label_returns_failure(self):
        r = self._classify({"reason": "no label"})
        assert r.outcome == StepOutcome.FAILURE

    def test_none_label_returns_failure(self):
        r = self._classify({"label": None})
        assert r.outcome == StepOutcome.FAILURE

    def test_reason_is_passed_through(self):
        r = self._classify({"label": "success", "reason": "goal achieved"})
        assert r.reason == "goal achieved"

    def test_missing_reason_gets_default(self):
        r = self._classify({"label": "success"})
        assert "No reason" in r.reason

    def test_metadata_is_passed_to_payload(self):
        r = self._classify({"label": "success", "metadata": {"score": 42}})
        assert r.payload == {"score": 42}

    def test_impure_input_tuple_returns_failure(self):
        r = self._classify((1, 2, 3))  # tuple — not pure
        assert r.outcome == StepOutcome.FAILURE


# ── StepResultFactory ─────────────────────────────────────────────────────────

class TestStepResultFactory:
    def test_success_returns_success_outcome(self):
        r = factory.success("done")
        assert r.outcome == StepOutcome.SUCCESS
        assert r.reason == "done"

    def test_success_with_payload(self):
        r = factory.success("ok", {"k": "v"})
        assert r.payload == {"k": "v"}

    def test_failure_returns_failure_outcome(self):
        r = factory.failure("broke")
        assert r.outcome == StepOutcome.FAILURE

    def test_failure_with_empty_payload(self):
        r = factory.failure("broke")
        assert r.payload == {}

    def test_tool_needed_returns_tool_needed_outcome(self):
        r = factory.tool_needed("need it", {"tool": "echo", "args": {}})
        assert r.outcome == StepOutcome.TOOL_NEEDED

    def test_tool_needed_without_tool_key_raises(self):
        with pytest.raises(ValidationError):
            factory.tool_needed("need it", {"args": {}})

    def test_tool_needed_with_empty_payload_raises(self):
        with pytest.raises(ValidationError):
            factory.tool_needed("need it", {})

    def test_continue_reasoning_returns_continue_outcome(self):
        r = factory.continue_reasoning("keep going")
        assert r.outcome == StepOutcome.CONTINUE

    def test_impure_payload_raises_in_success(self):
        with pytest.raises(Exception):
            factory.success("done", {"bad": (1, 2)})

    def test_impure_payload_raises_in_failure(self):
        with pytest.raises(Exception):
            factory.failure("broke", {"bad": set()})

    def test_impure_payload_raises_in_continue(self):
        with pytest.raises(Exception):
            factory.continue_reasoning("go", {"bad": b"bytes"})


# ── ForbiddenCapabilityPolicy ─────────────────────────────────────────────────

class TestForbiddenCapabilityPolicy:
    def _ctx(self, skill="echo", plan_state=None):
        return SafetyContext(
            plan=_plan(skill=skill),
            capability={},
            plan_state=plan_state,
        )

    def test_forbidden_capability_raises_on_pre_execute(self):
        policy = ForbiddenCapabilityPolicy(forbidden_capabilities={"echo"})
        with pytest.raises(PlanSafetyPolicyError, match="forbidden"):
            policy.pre_execute(self._ctx(skill="echo"))

    def test_allowed_capability_passes_pre_execute(self):
        policy = ForbiddenCapabilityPolicy(forbidden_capabilities={"delete"})
        policy.pre_execute(self._ctx(skill="echo"))  # no exception

    def test_empty_forbidden_set_allows_everything(self):
        policy = ForbiddenCapabilityPolicy(forbidden_capabilities=set())
        policy.pre_execute(self._ctx(skill="anything"))  # no exception

    def test_post_execute_always_passes(self):
        policy = ForbiddenCapabilityPolicy(forbidden_capabilities={"echo"})
        result = StepResult(outcome=StepOutcome.SUCCESS, reason="ok", payload={}, trace={})
        policy.post_execute(self._ctx(), result)  # no exception


# ── PlanTransitionPolicy ──────────────────────────────────────────────────────

class TestPlanTransitionPolicy:
    def _ctx(self, plan_state):
        return SafetyContext(plan=_plan(), capability={}, plan_state=plan_state)

    def test_none_plan_state_always_passes(self):
        PlanTransitionPolicy().pre_execute(self._ctx(plan_state=None))

    def test_pending_status_passes(self):
        PlanTransitionPolicy().pre_execute(self._ctx(_plan_state(PlanStatus.PENDING)))

    def test_running_status_passes(self):
        PlanTransitionPolicy().pre_execute(self._ctx(_plan_state(PlanStatus.RUNNING)))

    def test_completed_status_raises(self):
        with pytest.raises(PlanTransitionSafetyError):
            PlanTransitionPolicy().pre_execute(self._ctx(_plan_state(PlanStatus.COMPLETED)))

    def test_failed_status_raises(self):
        with pytest.raises(PlanTransitionSafetyError):
            PlanTransitionPolicy().pre_execute(self._ctx(_plan_state(PlanStatus.FAILED)))

    def test_post_execute_always_passes(self):
        result = StepResult(outcome=StepOutcome.SUCCESS, reason="ok", payload={}, trace={})
        PlanTransitionPolicy().post_execute(self._ctx(None), result)  # no exception


# ── SafeStepDispatcher ────────────────────────────────────────────────────────

class TestSafeStepDispatcher:
    class SpyPolicy:
        def __init__(self):
            self.pre_calls = []
            self.post_calls = []

        def pre_execute(self, ctx):
            self.pre_calls.append(ctx)

        def post_execute(self, ctx, result):
            self.post_calls.append((ctx, result))

    class FailingPrePolicy:
        def pre_execute(self, ctx):
            raise PlanSafetyPolicyError("blocked by policy")
        def post_execute(self, ctx, result):
            pass

    def _dispatcher(self, outcome=StepOutcome.SUCCESS):
        from src.core.planning.dispatch.step_dispatcher import StepDispatcher
        return StepDispatcher(core_step=FakeCoreStep(outcome=outcome))

    def test_pre_and_post_hooks_are_called(self):
        spy = self.SpyPolicy()
        safe = SafeStepDispatcher(
            dispatcher=self._dispatcher(),
            safety_policies=[spy],
        )
        safe.dispatch(_plan())

        assert len(spy.pre_calls) == 1
        assert len(spy.post_calls) == 1

    def test_pre_hook_called_before_dispatch(self):
        calls = []

        class OrderSpy:
            def pre_execute(self, ctx):
                calls.append("pre")
            def post_execute(self, ctx, result):
                calls.append("post")

        safe = SafeStepDispatcher(
            dispatcher=self._dispatcher(),
            safety_policies=[OrderSpy()],
        )
        safe.dispatch(_plan())
        assert calls == ["pre", "post"]

    def test_policy_violation_in_pre_stops_execution(self):
        safe = SafeStepDispatcher(
            dispatcher=self._dispatcher(),
            safety_policies=[self.FailingPrePolicy()],
        )
        with pytest.raises(PlanSafetyPolicyError, match="blocked by policy"):
            safe.dispatch(_plan())

    def test_multiple_policies_all_called(self):
        spy1 = self.SpyPolicy()
        spy2 = self.SpyPolicy()
        safe = SafeStepDispatcher(
            dispatcher=self._dispatcher(),
            safety_policies=[spy1, spy2],
        )
        safe.dispatch(_plan())

        assert len(spy1.pre_calls) == 1
        assert len(spy2.pre_calls) == 1

    def test_no_policies_dispatches_cleanly(self):
        safe = SafeStepDispatcher(
            dispatcher=self._dispatcher(),
            safety_policies=[],
        )
        state, result = safe.dispatch(_plan())
        assert result.outcome == StepOutcome.SUCCESS