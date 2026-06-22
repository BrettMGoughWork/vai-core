"""
Phase 5.5 — Workflow Definition Model
======================================

Pydantic models for declarative workflow definitions.  A workflow is a
directed graph of steps that share context.  Validation catches graph
errors (cycles, orphan steps, missing transitions) at load time.

Step types:
    llm_call       — Call Runtime with a prompt
    tool_execute   — Submit job to S4b Platform
    sub_workflow   — Invoke another workflow
    user_input     — Await human input
    condition      — Branch logic based on context expression
    apply_pattern  — Apply pattern instructions as LLM guidance
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


StepType = Literal[
    "llm_call",
    "tool_execute",
    "sub_workflow",
    "user_input",
    "condition",
    "apply_pattern",
]

VALID_STEP_TYPES: frozenset[str] = frozenset({
    "llm_call",
    "tool_execute",
    "sub_workflow",
    "user_input",
    "condition",
    "apply_pattern",
})

# Reserved transition target (means "workflow complete")
END_TARGET = "__end__"


# ---------------------------------------------------------------------------
# WorkflowStep
# ---------------------------------------------------------------------------


class WorkflowStep(BaseModel):
    """A single step in a workflow definition."""

    step_id: str
    step_type: StepType
    label: str
    description: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)
    transitions: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: Optional[float] = None
    retry_policy: Optional[dict] = None

    @field_validator("step_id")
    @classmethod
    def _step_id_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("step_id must be non-empty")
        return v

    @field_validator("label")
    @classmethod
    def _label_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("label must be non-empty")
        return v

    @field_validator("step_type")
    @classmethod
    def _validate_step_type(cls, v: str) -> str:
        if v not in VALID_STEP_TYPES:
            raise ValueError(
                f"invalid step_type {v!r}; valid: {sorted(VALID_STEP_TYPES)}"
            )
        return v

    @field_validator("transitions")
    @classmethod
    def _validate_transitions(cls, v: dict[str, str]) -> dict[str, str]:
        if not v:
            raise ValueError(
                "transitions must contain at least one of "
                "on_success, on_failure, on_timeout, on_cancel"
            )
        valid_keys = {"on_success", "on_failure", "on_timeout", "on_cancel"}
        for key in v:
            if key not in valid_keys:
                raise ValueError(
                    f"invalid transition key {key!r}; "
                    f"valid: {sorted(valid_keys)}"
                )
        if not isinstance(v, dict):
            raise ValueError("transitions must be a dict")
        return v


# ---------------------------------------------------------------------------
# WorkflowDefinition
# ---------------------------------------------------------------------------


class WorkflowDefinition(BaseModel):
    """Complete definition of a workflow — a directed graph of steps."""

    workflow_id: str
    name: str
    description: str
    version: str = "1.0.0"
    trigger_on: list[str] = Field(default_factory=list)
    input_schema: Optional[dict] = None
    steps: dict[str, WorkflowStep]
    start_step: str
    shared_context_schema: Optional[dict] = None
    timeout: Optional[float] = None
    # Note: required_agent_tags was part of a Phase 5.8 Agent Selection design
    # that was removed. The field is retained for backward compatibility but
    # is not used by the deterministic engine. Agent selection is determined
    # at definition time (step config), not at runtime.
    required_agent_tags: list[str] = Field(default_factory=list)

    @field_validator("workflow_id")
    @classmethod
    def _wf_id_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("workflow_id must be non-empty")
        return v

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("name must be non-empty")
        return v

    @field_validator("steps")
    @classmethod
    def _steps_not_empty(cls, v: dict[str, WorkflowStep]) -> dict[str, WorkflowStep]:
        if not v:
            raise ValueError("steps dict must not be empty")
        return v

    @field_validator("start_step")
    @classmethod
    def _start_step_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("start_step must be non-empty")
        return v

    # ------------------------------------------------------------------
    # Cross-field graph validation (called after individual fields pass)
    # ------------------------------------------------------------------

    @field_validator("start_step")
    @classmethod
    def _start_step_exists(cls, v: str, info: Any) -> str:
        if "steps" in info.data and v not in info.data["steps"]:
            raise ValueError(
                f"start_step {v!r} does not exist in steps"
            )
        return v

    def model_post_init(self, __context: Any) -> None:
        """Run full graph validation after model construction."""
        self._validate_no_orphan_steps()
        self._validate_no_duplicate_ids()
        self._validate_graph_is_acyclic()
        super().model_post_init(__context)

    # ------------------------------------------------------------------
    # Graph validation helpers
    # ------------------------------------------------------------------

    def _validate_no_orphan_steps(self) -> None:
        """Every transition target must reference a valid step_id or __end__."""
        for step_id, step in self.steps.items():
            for key, target in step.transitions.items():
                if target == END_TARGET:
                    continue
                if target not in self.steps:
                    raise ValueError(
                        f"step {step_id!r} transitions.{key} "
                        f"references non-existent step {target!r}"
                    )

    def _validate_no_duplicate_ids(self) -> None:
        """No duplicate step_id values (enforced by dict, but explicit check)."""
        pass  # Dict keys enforce uniqueness automatically

    def _validate_graph_is_acyclic(self) -> None:
        """Use Kahn's algorithm (topological sort) to detect cycles."""
        # Build adjacency list — only consider on_success transitions for the main path
        in_degree: dict[str, int] = {sid: 0 for sid in self.steps}
        adjacency: dict[str, list[str]] = {sid: [] for sid in self.steps}

        for step_id, step in self.steps.items():
            target = step.transitions.get("on_success")
            if target and target != END_TARGET and target in adjacency:
                adjacency[step_id].append(target)
                in_degree[target] = in_degree.get(target, 0) + 1

        # Kahn's algorithm
        queue: deque[str] = deque(
            sid for sid, deg in in_degree.items() if deg == 0
        )
        visited = 0

        while queue:
            current = queue.popleft()
            visited += 1
            for neighbor in adjacency.get(current, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited != len(self.steps):
            raise ValueError(
                "workflow graph contains a cycle — topological sort "
                f"visited {visited}/{len(self.steps)} nodes"
            )
