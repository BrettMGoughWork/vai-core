"""
S2 Stratum — Planning Interface
================================

Canonical boundary types for Stratum-2 (Planning / Reasoning).

S2 is a pure planner.  It receives a goal from S5 (Agent Workflow) and
returns a structured plan.  S2 has no knowledge of LLM providers,
tool execution, or transport layers — those are injected as callbacks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol


# ──────────────────────────────────────────────────────────────────────────────
# S5 → S2: plan request
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class PlanRequest:
    """Structured request from S5 (Agent Workflow) to S2 (Planner).

    S5 asks S2: "Here is a subgoal — produce a plan."
    """

    subgoal_id: str
    goal: str
    context: Dict[str, Any] = field(default_factory=dict)
    """Optional context from the workflow (e.g. conversation history, prior outcomes)."""

    max_steps: int = 10
    """Upper bound on plan steps S2 may generate."""


# ──────────────────────────────────────────────────────────────────────────────
# S2 → S5: plan result (one step in the hierarchy)
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class StepNode:
    """A single step within a plan."""

    step_id: str
    description: str
    capability: str
    inputs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanResult:
    """Structured result returned by S2 to S5.

    S5 uses this to drive the Agent Workflow execution.
    """

    plan_id: str
    subgoal: str
    steps: List[StepNode]
    segments: List[str] = field(default_factory=list)
    """Segment IDs written to memory (for traceability / governance)."""


# ──────────────────────────────────────────────────────────────────────────────
# S2 planner protocol (for injection / testing)
# ──────────────────────────────────────────────────────────────────────────────


class Planner(Protocol):
    """Protocol that any S2 planner must satisfy.

    Implementations: SubgoalPlanner, AgentPlanner, or mock planners for testing.
    """

    def plan(self, request: PlanRequest) -> PlanResult:
        ...
