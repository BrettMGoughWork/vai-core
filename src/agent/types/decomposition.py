"""
Agent Task Decomposition — Pure Data Types
============================================

Value objects for the decomposition lifecycle.  All types are frozen
dataclasses — pure data, no I/O, no orchestration logic.

Ownership
---------
- ``DecompositionRequest``  — input to ``S2PlanDecomposer.decompose()``
- ``SubtaskSpec``           — a single atomic subtask in a DAG
- ``DecompositionPlan``     — output of the planner (validated DAG)
- ``MergeResult``           — output of fan-in merge
- ``FanOutResult``          — output of fan-out (child job IDs + handle)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DecompositionRequest:
    """Input to ``S2PlanDecomposer.decompose()``.

    Pure data — the orchestrator assembles this from the parent agent's
    state and passes it to the planner with zero side effects.
    """

    parent_task: str
    parent_context: dict[str, Any]
    available_agents: list[str]
    constraints: dict[str, int] = field(default_factory=lambda: {
        "max_depth": 2,
        "max_children": 8,
    })


@dataclass(frozen=True)
class SubtaskSpec:
    """A single atomic subtask in a decomposition DAG.

    ``depends_on`` references other ``SubtaskSpec.id`` values within the
    same ``DecompositionPlan``.  Empty ``depends_on`` means the subtask
    has no dependencies and may run immediately.
    """

    id: str
    description: str
    target_agent_id: str | None = None
    target_skill_id: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    priority: int = 0
    timeout_seconds: int = 300
    max_retries: int = 2


@dataclass(frozen=True)
class DecompositionPlan:
    """Output of ``S2PlanDecomposer.decompose()``.

    Fully validated — DAG is acyclic, all ``depends_on`` references are
    resolved, and ``merge_strategy`` is one of the known strategies.
    """

    plan_id: str
    parent_task: str
    subtasks: list[SubtaskSpec]
    merge_strategy: str  # "concat" | "summarize_llm" | "select_best" | "custom"
    merge_agent_id: str | None = None
    merge_prompt_template: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MergeResult:
    """Result of fan-in merge.

    Stored in the parent agent's ``supervisor_metadata["decomposition_result"]``
    so the agent loop can inspect it after resuming from ``AWAITING_CHILDREN``.
    """

    output: str
    strategy: str
    selected: str | None = None
    satisfaction_gap: str | None = None
    child_summaries: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FanOutResult:
    """Return value of ``DecompositionOrchestrator.fan_out()``."""

    child_job_ids: list[str]
    join_handle_id: str
    continuation_job_id: str
