"""
Phase 5.5 — Workflow Definition Model Unit Tests
=================================================

Tests for WorkflowStep, WorkflowDefinition, graph validation,
YAML loading, and WorkflowRegistry.

Covers 10 test scenarios as specified in the roadmap.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.agent.workflow.loaders.yaml_loader import (
    load_workflow_from_string,
)
from src.agent.workflow.registry import (
    DuplicateWorkflowError,
    WorkflowNotFoundError,
    WorkflowRegistry,
)
from src.agent.workflow.workflow_definition import (
    END_TARGET,
    WorkflowDefinition,
    WorkflowStep,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_YAML = """
workflow_id: test-workflow
name: Test Workflow
description: A test workflow
version: "1.0.0"
trigger_on:
  - workflow.start
steps:
  step_a:
    step_id: step_a
    step_type: llm_call
    label: "Step A"
    config:
      system_prompt: "Hello"
    transitions:
      on_success: step_b
  step_b:
    step_id: step_b
    step_type: llm_call
    label: "Step B"
    config:
      system_prompt: "World"
    transitions:
      on_success: __end__
start_step: step_a
"""


def _make_valid_defn(**overrides: dict) -> dict:
    """Return a valid WorkflowDefinition-compatible dict, merged with overrides."""
    base = {
        "workflow_id": "test-wf",
        "name": "Test Workflow",
        "description": "A test workflow",
        "steps": {
            "step_a": WorkflowStep(
                step_id="step_a",
                step_type="llm_call",
                label="Step A",
                config={"system_prompt": "Hello"},
                transitions={"on_success": "step_b"},
            ),
            "step_b": WorkflowStep(
                step_id="step_b",
                step_type="llm_call",
                label="Step B",
                config={"system_prompt": "World"},
                transitions={"on_success": END_TARGET},
            ),
        },
        "start_step": "step_a",
    }
    base.update(overrides)
    return base


# ===================================================================
# 1. Valid workflow — all fields match input
# ===================================================================


class TestValidWorkflow:
    def test_all_fields_match(self) -> None:
        defn = WorkflowDefinition(**_make_valid_defn())

        assert defn.workflow_id == "test-wf"
        assert defn.name == "Test Workflow"
        assert defn.description == "A test workflow"
        assert defn.version == "1.0.0"
        assert defn.trigger_on == []
        assert defn.start_step == "step_a"
        assert len(defn.steps) == 2
        assert defn.steps["step_a"].step_type == "llm_call"
        assert defn.steps["step_b"].transitions["on_success"] == END_TARGET

    def test_custom_version_and_trigger(self) -> None:
        defn = WorkflowDefinition(
            workflow_id="wf-2",
            name="WF 2",
            description="Second workflow",
            version="2.1.0",
            trigger_on=["workflow.start", "workflow.scheduled"],
            steps={
                "only": WorkflowStep(
                    step_id="only",
                    step_type="condition",
                    label="Only step",
                    transitions={"on_success": END_TARGET},
                ),
            },
            start_step="only",
        )
        assert defn.version == "2.1.0"
        assert defn.trigger_on == ["workflow.start", "workflow.scheduled"]


# ===================================================================
# 2. Missing start_step → raises ValidationError
# ===================================================================


class TestMissingStartStep:
    def test_empty_start_step(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowDefinition(
                workflow_id="wf",
                name="WF",
                description="Missing start",
                steps={
                    "a": WorkflowStep(
                        step_id="a",
                        step_type="llm_call",
                        label="A",
                        transitions={"on_success": END_TARGET},
                    ),
                },
                start_step="",  # empty string
            )

    def test_start_step_not_in_steps(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowDefinition(
                workflow_id="wf",
                name="WF",
                description="Start not in steps",
                steps={
                    "a": WorkflowStep(
                        step_id="a",
                        step_type="llm_call",
                        label="A",
                        transitions={"on_success": END_TARGET},
                    ),
                },
                start_step="nonexistent",
            )


# ===================================================================
# 3. Transition to non-existent step → raises ValidationError
# ===================================================================


class TestOrphanTransition:
    def test_transition_to_missing_step(self) -> None:
        with pytest.raises((ValueError, ValidationError)):
            WorkflowDefinition(
                workflow_id="wf",
                name="WF",
                description="Orphan transition",
                steps={
                    "a": WorkflowStep(
                        step_id="a",
                        step_type="llm_call",
                        label="A",
                        transitions={"on_success": "missing_step"},
                    ),
                },
                start_step="a",
            )

    def test_transition_to_end_is_valid(self) -> None:
        """Transition to __end__ is always allowed."""
        defn = WorkflowDefinition(
            workflow_id="wf",
            name="WF",
            description="End target",
            steps={
                "a": WorkflowStep(
                    step_id="a",
                    step_type="llm_call",
                    label="A",
                    transitions={"on_success": END_TARGET},
                ),
            },
            start_step="a",
        )
        assert defn.steps["a"].transitions["on_success"] == END_TARGET


# ===================================================================
# 4. Cyclic graph (A→B→C→A) → raises ValidationError
# ===================================================================


class TestCyclicGraph:
    def test_simple_cycle(self) -> None:
        with pytest.raises((ValueError, ValidationError)):
            WorkflowDefinition(
                workflow_id="wf",
                name="WF",
                description="Cycle",
                steps={
                    "a": WorkflowStep(
                        step_id="a",
                        step_type="llm_call",
                        label="A",
                        transitions={"on_success": "b"},
                    ),
                    "b": WorkflowStep(
                        step_id="b",
                        step_type="llm_call",
                        label="B",
                        transitions={"on_success": "c"},
                    ),
                    "c": WorkflowStep(
                        step_id="c",
                        step_type="llm_call",
                        label="C",
                        transitions={"on_success": "a"},
                    ),
                },
                start_step="a",
            )

    def test_self_loop(self) -> None:
        with pytest.raises((ValueError, ValidationError)):
            WorkflowDefinition(
                workflow_id="wf",
                name="WF",
                description="Self loop",
                steps={
                    "a": WorkflowStep(
                        step_id="a",
                        step_type="llm_call",
                        label="A",
                        transitions={"on_success": "a"},
                    ),
                },
                start_step="a",
            )

    def test_acyclic_is_valid(self) -> None:
        """Sanity: a properly acyclic graph passes validation."""
        defn = WorkflowDefinition(
            workflow_id="wf",
            name="WF",
            description="Acyclic",
            steps={
                "a": WorkflowStep(
                    step_id="a",
                    step_type="llm_call",
                    label="A",
                    transitions={"on_success": "b"},
                ),
                "b": WorkflowStep(
                    step_id="b",
                    step_type="llm_call",
                    label="B",
                    transitions={"on_success": END_TARGET},
                ),
            },
            start_step="a",
        )
        assert defn.workflow_id == "wf"


# ===================================================================
# 5. No transitions dict → raises ValidationError
# ===================================================================


class TestMissingTransitions:
    def test_empty_transitions_raises(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowStep(
                step_id="a",
                step_type="llm_call",
                label="A",
                transitions={},
            )

    def test_missing_transitions_field_default(self) -> None:
        """When transitions is omitted, it defaults to {} — valid by default."""
        step = WorkflowStep(
            step_id="a",
            step_type="llm_call",
            label="A",
        )
        assert step.transitions == {}


# ===================================================================
# 6. YAML round-trip: load → serialize → match
# ===================================================================


class TestYAMLRoundTrip:
    def test_load_from_string(self) -> None:
        defn = load_workflow_from_string(_VALID_YAML)
        assert defn.workflow_id == "test-workflow"
        assert defn.name == "Test Workflow"
        assert defn.start_step == "step_a"
        assert len(defn.steps) == 2

    def test_round_trip_to_dict(self) -> None:
        defn = load_workflow_from_string(_VALID_YAML)
        as_dict = defn.model_dump()
        rehydrated = WorkflowDefinition.model_validate(as_dict)
        assert rehydrated == defn

    def test_invalid_yaml_structure_raises(self) -> None:
        with pytest.raises(ValueError):
            load_workflow_from_string("[1, 2, 3]")  # list, not mapping


# ===================================================================
# 7. Empty steps dict → raises ValidationError
# ===================================================================


class TestEmptySteps:
    def test_empty_steps_dict(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowDefinition(
                workflow_id="wf",
                name="WF",
                description="No steps",
                steps={},
                start_step="a",
            )


# ===================================================================
# 8. Invalid step_type → raises ValidationError
# ===================================================================


class TestInvalidStepType:
    def test_unknown_step_type(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowStep(
                step_id="a",
                step_type="invalid_type",
                label="A",
                transitions={"on_success": END_TARGET},
            )


# ===================================================================
# 9. Registry: register → get → returns same definition
# ===================================================================


class TestRegistry:
    def test_register_and_get(self) -> None:
        defn = load_workflow_from_string(_VALID_YAML)
        registry = WorkflowRegistry()
        registry.register(defn)

        retrieved = registry.get("test-workflow")
        assert retrieved is not None
        assert retrieved.workflow_id == "test-workflow"
        assert retrieved == defn

    def test_register_duplicate_raises(self) -> None:
        defn_a = load_workflow_from_string(_VALID_YAML)
        # A different definition with the same workflow_id
        defn_b = WorkflowDefinition(
            workflow_id="test-workflow",
            name="Different Name",
            description="Different description",
            steps={
                "only": WorkflowStep(
                    step_id="only",
                    step_type="llm_call",
                    label="Only step",
                    transitions={"on_success": END_TARGET},
                ),
            },
            start_step="only",
        )
        registry = WorkflowRegistry()
        registry.register(defn_a)
        with pytest.raises(DuplicateWorkflowError):
            registry.register(defn_b)

    def test_get_nonexistent_returns_none(self) -> None:
        registry = WorkflowRegistry()
        assert registry.get("nope") is None

    def test_list_empty(self) -> None:
        registry = WorkflowRegistry()
        assert registry.list() == []

    def test_list_after_register(self) -> None:
        defn = load_workflow_from_string(_VALID_YAML)
        registry = WorkflowRegistry()
        registry.register(defn)
        assert len(registry.list()) == 1

    def test_has_workflow(self) -> None:
        defn = load_workflow_from_string(_VALID_YAML)
        registry = WorkflowRegistry()
        assert not registry.has_workflow("test-workflow")
        registry.register(defn)
        assert registry.has_workflow("test-workflow")

    def test_workflow_count(self) -> None:
        defn = load_workflow_from_string(_VALID_YAML)
        registry = WorkflowRegistry()
        assert registry.workflow_count == 0
        registry.register(defn)
        assert registry.workflow_count == 1

    def test_register_invalid_type_raises(self) -> None:
        registry = WorkflowRegistry()
        with pytest.raises(TypeError):
            registry.register("not a definition")  # type: ignore[arg-type]


# ===================================================================
# 10. Registry: find_by_trigger → returns only matching workflows
# ===================================================================


class TestFindByTrigger:
    def test_find_matching_trigger(self) -> None:
        wf_a = _make_workflow("wf-a", ["workflow.start"])
        wf_b = _make_workflow("wf-b", ["workflow.scheduled"])
        wf_c = _make_workflow("wf-c", ["workflow.start", "workflow.resume"])

        registry = WorkflowRegistry()
        for wf in (wf_a, wf_b, wf_c):
            registry.register(wf)

        start_wfs = registry.find_by_trigger("workflow.start")
        assert len(start_wfs) == 2
        assert {w.workflow_id for w in start_wfs} == {"wf-a", "wf-c"}

    def test_no_matching_trigger(self) -> None:
        wf = _make_workflow("wf-a", ["workflow.start"])
        registry = WorkflowRegistry()
        registry.register(wf)

        results = registry.find_by_trigger("workflow.timeout")
        assert results == []


def _make_workflow(
    workflow_id: str,
    trigger_on: list[str],
) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id=workflow_id,
        name=workflow_id,
        description=f"Workflow {workflow_id}",
        trigger_on=trigger_on,
        steps={
            "only": WorkflowStep(
                step_id="only",
                step_type="llm_call",
                label="Only step",
                transitions={"on_success": END_TARGET},
            ),
        },
        start_step="only",
    )
