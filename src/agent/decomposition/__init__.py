"""
Agent Task Decomposition — fan-out/fan-in orchestration engine
===============================================================

Implements deterministic, dependency-aware DAG decomposition for
agents.  When the todo orchestrator determines a task can be broken
into parallel subtasks, the decomposition engine handles:

- DAG validation (cycle detection, missing deps, self-deps)
- Fan-out (enqueue one job per subtask, create JoinHandle)
- Fan-in merge (concat, summarize_llm, select_best, custom)
- Atomicity (all-or-nothing semantics with retry/poison handling)

See ``ROADMAP-agent-decomposition.md`` for full specification.
"""

from __future__ import annotations

from src.agent.decomposition.atomicity import (
    AtomicityEnforcer,
    PlanExecutionResult,
)
from src.agent.decomposition.dag_validator import (
    DagValidationError,
    validate_dag,
    topological_sort,
)
from src.agent.decomposition.merge import (
    MergeError,
    execute_merge,
    get_merge_strategies,
)
from src.agent.decomposition.orchestrator import DecompositionOrchestrator

__all__ = [
    "AtomicityEnforcer",
    "DagValidationError",
    "DecompositionOrchestrator",
    "MergeError",
    "PlanExecutionResult",
    "execute_merge",
    "get_merge_strategies",
    "topological_sort",
    "validate_dag",
]
