"""
Phase 5.5 — Workflow Engine Unit Tests
=======================================

Tests for WorkflowEngine — the deterministic graph navigator.

Covers start, step dispatch for all 5 step types, condition
evaluation, resume paths, fail, cancel, and edge cases.
"""

from __future__ import annotations

import pytest

from src.agent.workflow.engine import (
    StepOutcome,
    WorkflowEngine,
    WorkflowExecutionState,
    WorkflowStatus,
)
from src.agent.workflow.registry import WorkflowRegistry
from src.agent.workflow.workflow_definition import (
    END_TARGET,
    WorkflowDefinition,
    WorkflowStep,
)
from src.capabilities.patterns.pattern_registry import PatternRegistry
from src.domain.patterns import PatternDefinition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_step(
    step_id: str,
    step_type: str = "llm_call",
    *,
    label: str = "",
    config: dict | None = None,
    transitions: dict | None = None,
) -> WorkflowStep:
    return WorkflowStep(
        step_id=step_id,
        step_type=step_type,
        label=label or f"Step {step_id}",
        config=config or {},
        transitions=transitions or {"on_success": END_TARGET},
    )


def _make_workflow(
    workflow_id: str = "test-wf",
    steps: dict[str, WorkflowStep] | None = None,
    start_step: str = "step_1",
) -> WorkflowDefinition:
    if steps is None:
        steps = {
            "step_1": _make_step("step_1", transitions={"on_success": END_TARGET}),
        }
    return WorkflowDefinition(
        workflow_id=workflow_id,
        name=workflow_id,
        description="Test workflow",
        steps=steps,
        start_step=start_step,
    )


def _make_registry(*defns: WorkflowDefinition) -> WorkflowRegistry:
    reg = WorkflowRegistry()
    for d in defns:
        reg.register(d)
    return reg


# ===================================================================
# 1. start_workflow → creates valid initial state
# ===================================================================


class TestStartWorkflow:
    def test_creates_running_state_with_first_step(self) -> None:
        defn = _make_workflow()
        engine = WorkflowEngine(_make_registry(defn))
        state = engine.start_workflow("test-wf")

        assert state.workflow_id == "test-wf"
        assert state.status == WorkflowStatus.RUNNING
        assert state.current_step_id == "step_1"
        assert state.execution_id != ""

    def test_with_context(self) -> None:
        defn = _make_workflow()
        engine = WorkflowEngine(_make_registry(defn))
        state = engine.start_workflow("test-wf", context={"input": "hello"})

        assert state.context["input"] == "hello"

    def test_unknown_workflow_raises(self) -> None:
        engine = WorkflowEngine(WorkflowRegistry())
        with pytest.raises(ValueError, match="not found"):
            engine.start_workflow("nonexistent")


# ===================================================================
# 2. step() → llm_call outcome
# ===================================================================


class TestStepLlmCall:
    def test_returns_llm_call_outcome(self) -> None:
        step = _make_step(
            "ask", "llm_call", config={"prompt": "Hi"},
            transitions={"on_success": "next"},
        )
        next_step = _make_step("next", transitions={"on_success": END_TARGET})
        defn = _make_workflow(
            steps={"ask": step, "next": next_step}, start_step="ask",
        )
        engine = WorkflowEngine(_make_registry(defn))
        state = engine.start_workflow("test-wf")

        new_state, outcome = engine.step(state)

        assert outcome.type == "llm_call"
        assert outcome.step_id == "ask"
        assert outcome.config == {"prompt": "Hi"}
        assert new_state.current_step_id == "next"

    def test_advances_current_step_id(self) -> None:
        step_a = _make_step("a", transitions={"on_success": "b"})
        step_b = _make_step("b", transitions={"on_success": END_TARGET})
        defn = _make_workflow(steps={"a": step_a, "b": step_b}, start_step="a")
        engine = WorkflowEngine(_make_registry(defn))
        state = engine.start_workflow("test-wf")

        new_state, _outcome = engine.step(state)

        assert new_state.current_step_id == "b"

    def test_completes_on_end_target(self) -> None:
        step = _make_step("only")
        defn = _make_workflow(steps={"only": step}, start_step="only")
        engine = WorkflowEngine(_make_registry(defn))
        state = engine.start_workflow("test-wf")

        new_state, outcome = engine.step(state)

        assert outcome.type == "llm_call"
        assert new_state.current_step_id is None
        assert new_state.status == WorkflowStatus.RUNNING  # engine defers completion to supervisor


# ===================================================================
# 3. step() → tool_execute outcome
# ===================================================================


class TestStepToolExecute:
    def test_returns_tool_execute_outcome(self) -> None:
        step = _make_step(
            "run", "tool_execute", config={"tool": "fetch", "url": "..."},
            transitions={"on_success": "next"},
        )
        next_step = _make_step("next", transitions={"on_success": END_TARGET})
        defn = _make_workflow(
            steps={"run": step, "next": next_step}, start_step="run",
        )
        engine = WorkflowEngine(_make_registry(defn))
        state = engine.start_workflow("test-wf")

        _new_state, outcome = engine.step(state)

        assert outcome.type == "tool_execute"
        assert outcome.step_id == "run"
        assert outcome.config["tool"] == "fetch"


# ===================================================================
# 4. step() → waiting_for_input outcome
# ===================================================================


class TestStepUserInput:
    def test_returns_waiting_for_input(self) -> None:
        step = _make_step(
            "ask_user", "user_input",
            config={"prompt": "What do you want?"},
            transitions={"on_success": "after"},
        )
        step_b = _make_step("after", "llm_call")
        defn = _make_workflow(
            steps={"ask_user": step, "after": step_b},
            start_step="ask_user",
        )
        engine = WorkflowEngine(_make_registry(defn))
        state = engine.start_workflow("test-wf")

        new_state, outcome = engine.step(state)

        assert outcome.type == "waiting_for_input"
        assert outcome.step_id == "ask_user"
        assert new_state.status == WorkflowStatus.WAITING_FOR_INPUT
        # current_step_id advances past the input step
        assert new_state.current_step_id == "after"

    def test_resume_with_input_continues(self) -> None:
        ask = _make_step(
            "ask_user", "user_input",
            transitions={"on_success": "after"},
        )
        after = _make_step("after", "llm_call")
        defn = _make_workflow(
            steps={"ask_user": ask, "after": after},
            start_step="ask_user",
        )
        engine = WorkflowEngine(_make_registry(defn))
        state = engine.start_workflow("test-wf")

        # step to WAITING — advances current_step_id to "after"
        wf_state, _outcome = engine.step(state)
        assert wf_state.status == WorkflowStatus.WAITING_FOR_INPUT
        assert wf_state.current_step_id == "after"

        # resume — injects input and returns "continue" (no longer auto-steps)
        resumed, outcome = engine.resume_with_input(wf_state, "my answer")
        assert outcome.type == "continue"
        assert resumed.current_step_id == "after"

        # step explicitly to advance into "after"
        resumed, outcome = engine.step(resumed)

        assert outcome.type == "llm_call"  # "after" is llm_call, on_success: __end__
        assert resumed.current_step_id is None
        assert resumed.status == WorkflowStatus.RUNNING  # engine defers completion to supervisor
        assert resumed.context["_user_input"] == "my answer"


# ===================================================================
# 5. resume_with_result → records and continues
# ===================================================================


class TestResumeWithResult:
    def test_records_result_and_steps(self) -> None:
        step_a = _make_step("a", transitions={"on_success": "b"})
        step_b = _make_step("b", transitions={"on_success": "c"})
        step_c = _make_step("c", transitions={"on_success": END_TARGET})
        defn = _make_workflow(
            steps={"a": step_a, "b": step_b, "c": step_c}, start_step="a",
        )
        engine = WorkflowEngine(_make_registry(defn))
        state = engine.start_workflow("test-wf")
        wf_state, _outcome = engine.step(state)  # a → llm_call, advances to b

        # Resume result for step "a" — stores result and returns "continue"
        resumed, outcome = engine.resume_with_result(wf_state, "a", "output text")
        assert outcome.type == "continue"
        assert resumed.current_step_id == "b"

        # Step explicitly to advance into "b"
        resumed, outcome = engine.step(resumed)

        assert outcome.type == "llm_call"
        assert outcome.step_id == "b"
        assert resumed.step_results["a"] == "output text"
        assert resumed.context["result"] == "output text"


# ===================================================================
# 6. condition → True/False branching
# ===================================================================


class TestCondition:
    def test_true_follows_on_success(self) -> None:
        cond = _make_step(
            "check", "condition",
            config={"expression": "context.get('x', 0) > 0"},
            transitions={"on_success": "pass", "on_failure": "fail"},
        )
        pass_step = _make_step("pass", transitions={"on_success": END_TARGET})
        fail_step = _make_step("fail", transitions={"on_success": END_TARGET})
        defn = _make_workflow(
            steps={"check": cond, "pass": pass_step, "fail": fail_step},
            start_step="check",
        )
        engine = WorkflowEngine(_make_registry(defn))

        state = engine.start_workflow("test-wf", context={"x": 42})
        new_state, outcome = engine.step(state)

        assert outcome.type == "continue"
        assert outcome.next_step_id == "pass"
        assert new_state.current_step_id == "pass"

    def test_false_follows_on_failure(self) -> None:
        cond = _make_step(
            "check", "condition",
            config={"expression": "context.get('x', 0) > 0"},
            transitions={"on_success": "pass", "on_failure": "fail"},
        )
        pass_step = _make_step("pass", transitions={"on_success": END_TARGET})
        fail_step = _make_step("fail", transitions={"on_success": END_TARGET})
        defn = _make_workflow(
            steps={"check": cond, "pass": pass_step, "fail": fail_step},
            start_step="check",
        )
        engine = WorkflowEngine(_make_registry(defn))

        state = engine.start_workflow("test-wf", context={"x": 0})
        new_state, outcome = engine.step(state)

        assert outcome.type == "continue"
        assert outcome.next_step_id == "fail"
        assert new_state.current_step_id == "fail"

    def test_invalid_expression_returns_failed(self) -> None:
        cond = _make_step(
            "check", "condition",
            config={"expression": "invalid syntax!!!"},
        )
        defn = _make_workflow(steps={"check": cond}, start_step="check")
        engine = WorkflowEngine(_make_registry(defn))

        state = engine.start_workflow("test-wf")
        new_state, outcome = engine.step(state)

        assert outcome.type == "failed"
        assert "condition evaluation failed" in (outcome.error or "")


# ===================================================================
# 7. sub_workflow → returns sub-workflow outcome
# ===================================================================


class TestSubWorkflow:
    def test_returns_sub_workflow_outcome(self) -> None:
        sub = _make_step(
            "sub", "sub_workflow",
            config={"workflow_id": "sub-wf"},
            transitions={"on_success": "done"},
        )
        done = _make_step("done", transitions={"on_success": END_TARGET})
        defn = _make_workflow(steps={"sub": sub, "done": done}, start_step="sub")
        sub_defn = _make_workflow(workflow_id="sub-wf")
        reg = _make_registry(defn, sub_defn)
        engine = WorkflowEngine(reg)

        state = engine.start_workflow("test-wf")
        new_state, outcome = engine.step(state)

        assert outcome.type == "sub_workflow"
        assert outcome.workflow_id == "sub-wf"
        assert new_state.current_step_id == "done"  # advanced past sub → done

    def test_missing_workflow_id_returns_failed(self) -> None:
        sub = _make_step(
            "sub", "sub_workflow",
            config={},  # no workflow_id
        )
        defn = _make_workflow(steps={"sub": sub}, start_step="sub")
        engine = WorkflowEngine(_make_registry(defn))

        state = engine.start_workflow("test-wf")
        _new_state, outcome = engine.step(state)

        assert outcome.type == "failed"
        assert "missing" in (outcome.error or "").lower()


# ===================================================================
# 8. fail_step → on_failure transition or FAILED status
# ===================================================================


class TestFailStep:
    def test_with_on_failure_follows_transition(self) -> None:
        risky = _make_step(
            "risky", "llm_call",
            transitions={"on_success": END_TARGET, "on_failure": "fallback"},
        )
        fallback = _make_step("fallback", transitions={"on_success": END_TARGET})
        defn = _make_workflow(
            steps={"risky": risky, "fallback": fallback},
            start_step="risky",
        )
        engine = WorkflowEngine(_make_registry(defn))
        state = engine.start_workflow("test-wf")

        new_state, outcome = engine.fail_step(state, "risky", "something broke")

        assert outcome.type == "continue"
        assert new_state.current_step_id == "fallback"
        assert new_state.step_results["risky"]["status"] == "failed"

    def test_without_on_failure_marks_failed(self) -> None:
        risky = _make_step("risky", "llm_call")
        defn = _make_workflow(steps={"risky": risky}, start_step="risky")
        engine = WorkflowEngine(_make_registry(defn))
        state = engine.start_workflow("test-wf")

        new_state, outcome = engine.fail_step(state, "risky", "broke")

        assert outcome.type == "failed"
        assert new_state.status == WorkflowStatus.FAILED
        assert "broke" in (outcome.error or "")

    def test_on_failure_to_end_completes(self) -> None:
        risky = _make_step(
            "risky", "llm_call",
            transitions={"on_success": "next", "on_failure": END_TARGET},
        )
        nxt = _make_step("next", transitions={"on_success": END_TARGET})
        defn = _make_workflow(
            steps={"risky": risky, "next": nxt},
            start_step="risky",
        )
        engine = WorkflowEngine(_make_registry(defn))
        state = engine.start_workflow("test-wf")

        new_state, outcome = engine.fail_step(state, "risky", "broke")

        assert outcome.type == "completed"
        assert new_state.status == WorkflowStatus.COMPLETED


# ===================================================================
# 9. cancel → CANCELLED
# ===================================================================


class TestCancel:
    def test_sets_cancelled(self) -> None:
        defn = _make_workflow()
        engine = WorkflowEngine(_make_registry(defn))
        state = engine.start_workflow("test-wf")

        cancelled = engine.cancel(state)

        assert cancelled.status == WorkflowStatus.CANCELLED


# ===================================================================
# 10. Edge cases
# ===================================================================


class TestEdgeCases:
    def test_step_on_completed_is_noop(self) -> None:
        defn = _make_workflow()
        engine = WorkflowEngine(_make_registry(defn))
        state = engine.start_workflow("test-wf")
        completed, _outcome = engine.step(state)

        again_state, outcome = engine.step(completed)

        assert outcome.type == "completed"
        assert again_state.status == WorkflowStatus.COMPLETED

    def test_step_on_failed_is_noop(self) -> None:
        defn = _make_workflow()
        engine = WorkflowEngine(_make_registry(defn))
        state = engine.start_workflow("test-wf")
        failed, _outcome = engine.fail_step(state, "step_1", "error")

        again_state, outcome = engine.step(failed)

        assert outcome.type == "failed"

    def test_step_on_unknown_step_id_returns_failed(self) -> None:
        step = _make_step("a", transitions={"on_success": END_TARGET})
        defn = _make_workflow(steps={"a": step}, start_step="a")
        engine = WorkflowEngine(_make_registry(defn))
        state = engine.start_workflow("test-wf")

        state = WorkflowExecutionState(
            execution_id=state.execution_id,
            workflow_id=state.workflow_id,
            status=WorkflowStatus.RUNNING,
            current_step_id="nonexistent",
        )
        _new_state, outcome = engine.step(state)

        assert outcome.type == "failed"

    def test_unknown_workflow_in_step_returns_failed(self) -> None:
        engine = WorkflowEngine(WorkflowRegistry())
        state = WorkflowExecutionState(
            execution_id="x",
            workflow_id="missing",
            status=WorkflowStatus.RUNNING,
            current_step_id="a",
        )
        _new_state, outcome = engine.step(state)

        assert outcome.type == "failed"
        assert "not found" in (outcome.error or "")

    def test_unknown_step_type_returns_failed(self) -> None:
        bad = WorkflowStep.model_construct(
            step_id="bad",
            step_type="unknown_type",
            label="Bad",
            config={},
            transitions={"on_success": END_TARGET},
        )
        defn = _make_workflow(steps={"bad": bad}, start_step="bad")
        engine = WorkflowEngine(_make_registry(defn))
        state = engine.start_workflow("test-wf")

        _new_state, outcome = engine.step(state)

        assert outcome.type == "failed"
        assert "unknown step type" in (outcome.error or "")


# ===================================================================
# 11. apply_pattern → resolves pattern and emits enriched llm_call
# ===================================================================


def _make_pattern_registry(
    pattern_id: str = "reply_to_email",
    name: str = "Reply to Email",
    instructions: str = "Use gmail_read then gmail_send.",
    primitives: list[str] | None = None,
) -> PatternRegistry:
    reg = PatternRegistry()
    reg.register(PatternDefinition(
        pattern_id=pattern_id,
        name=name,
        primitives=primitives or ["gmail_read", "gmail_send"],
        instructions=instructions,
    ))
    return reg


def _make_apply_pattern_step(
    step_id: str,
    pattern_id: str,
    *,
    label: str = "",
    config_overrides: dict | None = None,
    transitions: dict | None = None,
) -> WorkflowStep:
    config = {"pattern_id": pattern_id}
    if config_overrides:
        config.update(config_overrides)
    return _make_step(
        step_id,
        "apply_pattern",
        label=label or f"Apply pattern {pattern_id}",
        config=config,
        transitions=transitions or {"on_success": END_TARGET},
    )


class TestApplyPattern:
    def test_emits_enriched_llm_call_outcome(self) -> None:
        """apply_pattern step resolves pattern and emits llm_call with instructions."""
        pattern_reg = _make_pattern_registry()
        step = _make_apply_pattern_step("apply", "reply_to_email")
        defn = _make_workflow(steps={"apply": step}, start_step="apply")
        engine = WorkflowEngine(_make_registry(defn), pattern_registry=pattern_reg)
        state = engine.start_workflow("test-wf")

        new_state, outcome = engine.step(state)

        assert outcome.type == "llm_call"
        assert outcome.step_id == "apply"
        assert "pattern_instructions" in outcome.config
        instructions = outcome.config["pattern_instructions"]
        assert len(instructions) == 1
        assert instructions[0]["pattern_id"] == "reply_to_email"
        assert instructions[0]["name"] == "Reply to Email"
        assert instructions[0]["instructions"] == "Use gmail_read then gmail_send."
        assert new_state.current_step_id is None  # transition to __end__

    def test_missing_pattern_id_in_config_fails(self) -> None:
        """apply_pattern without config.pattern_id returns failed outcome."""
        pattern_reg = _make_pattern_registry()
        step = _make_step("apply", "apply_pattern", config={})
        defn = _make_workflow(steps={"apply": step}, start_step="apply")
        engine = WorkflowEngine(_make_registry(defn), pattern_registry=pattern_reg)
        state = engine.start_workflow("test-wf")

        _new_state, outcome = engine.step(state)

        assert outcome.type == "failed"
        assert "missing" in (outcome.error or "").lower()

    def test_pattern_not_in_registry_fails(self) -> None:
        """apply_pattern with unknown pattern_id returns failed outcome."""
        pattern_reg = _make_pattern_registry()
        step = _make_apply_pattern_step("apply", "nonexistent_pattern")
        defn = _make_workflow(steps={"apply": step}, start_step="apply")
        engine = WorkflowEngine(_make_registry(defn), pattern_registry=pattern_reg)
        state = engine.start_workflow("test-wf")

        _new_state, outcome = engine.step(state)

        assert outcome.type == "failed"
        assert "not found" in (outcome.error or "").lower()

    def test_no_pattern_registry_configured_fails(self) -> None:
        """apply_pattern without a pattern_registry on the engine returns failed."""
        step = _make_apply_pattern_step("apply", "reply_to_email")
        defn = _make_workflow(steps={"apply": step}, start_step="apply")
        engine = WorkflowEngine(_make_registry(defn))  # no pattern_registry
        state = engine.start_workflow("test-wf")

        _new_state, outcome = engine.step(state)

        assert outcome.type == "failed"
        assert "no pattern_registry" in (outcome.error or "").lower()

    def test_on_failure_for_step_failure_respected(self) -> None:
        """fail_step respects on_failure transitions (runtime error path)."""
        step = _make_apply_pattern_step(
            "apply", "reply_to_email",
            transitions={"on_success": "next", "on_failure": "fallback"},
        )
        next_step = _make_step("next", transitions={"on_success": END_TARGET})
        fallback = _make_step("fallback", transitions={"on_success": END_TARGET})
        defn = _make_workflow(
            steps={"apply": step, "next": next_step, "fallback": fallback},
            start_step="apply",
        )
        pattern_reg = _make_pattern_registry()
        engine = WorkflowEngine(_make_registry(defn), pattern_registry=pattern_reg)
        state = engine.start_workflow("test-wf")

        # Simulate runtime failure via fail_step → should follow on_failure
        new_state, outcome = engine.fail_step(state, "apply", "runtime error")

        assert outcome.type == "continue"
        assert new_state.current_step_id == "fallback"
