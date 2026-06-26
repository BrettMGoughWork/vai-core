"""
Atomicity Enforcer — Agent Decomposition
==========================================

Implements all-or-nothing semantics for decomposition plans.

When a plan is executed, either ALL subtasks succeed and the merged
result is delivered, or the plan is marked FAILED and a per-subtask
rollback / compensation is triggered.

Responsibilities:
  - Track execution outcomes per subtask (success / retryable / poison).
  - Enforce the plan-level timeout.
  - On failure: execute compensation functions for completed subtasks.
  - Prevent partial results from reaching the parent agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class SubtaskOutcome(str, Enum):
    """Outcome of a single subtask execution."""

    SUCCESS = "success"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class PlanExecutionResult:
    """Final result of a decomposition plan execution.

    ``all_succeeded`` is the atomicity invariant — the parent agent
    should only use ``merged_output`` if this is ``True``.
    """

    plan_id: str
    all_succeeded: bool
    merged_output: str | None = None
    subtask_outcomes: dict[str, SubtaskOutcome] = field(default_factory=dict)
    failure_reason: str | None = None
    compensations_executed: list[str] = field(default_factory=list)


CompensationFn = Callable[[str, dict[str, Any]], None]
"""Signature: ``(subtask_id, result) -> None``."""


class AtomicityEnforcer:
    """All-or-nothing semantics for decomposition plans.

    Usage::

        enforcer = AtomicityEnforcer(plan_id="plan-1")

        # Record outcomes as subtasks complete
        enforcer.record_outcome("subtask-1", SubtaskOutcome.SUCCESS, result={...})
        enforcer.record_outcome("subtask-2", SubtaskOutcome.PERMANENT_FAILURE)

        # Finalise — will run compensations if any subtask failed
        result = enforcer.finalise(
            merged_output="...",
            compensation_fn=my_compensation,
        )
    """

    def __init__(self, plan_id: str) -> None:
        self._plan_id = plan_id
        self._outcomes: dict[str, SubtaskOutcome] = {}
        self._results: dict[str, dict[str, Any]] = {}

    def record_outcome(
        self,
        subtask_id: str,
        outcome: SubtaskOutcome,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Record the outcome of a single subtask."""
        self._outcomes[subtask_id] = outcome
        if result is not None:
            self._results[subtask_id] = result

    def is_plan_failed(self) -> bool:
        """Return ``True`` if any subtask has permanently failed."""
        return any(
            o in (SubtaskOutcome.PERMANENT_FAILURE, SubtaskOutcome.TIMEOUT)
            for o in self._outcomes.values()
        )

    def all_succeeded(self) -> bool:
        """Return ``True`` if all subtasks succeeded."""
        if not self._outcomes:
            return False
        return all(o == SubtaskOutcome.SUCCESS for o in self._outcomes.values())

    def finalise(
        self,
        merged_output: str | None = None,
        compensation_fn: CompensationFn | None = None,
    ) -> PlanExecutionResult:
        """Finalise plan execution.

        If any subtask permanently failed, this runs compensation
        functions for all completed subtasks and returns a failed result.
        """
        compensations_executed: list[str] = []

        if self.is_plan_failed():
            # Run compensations for successfully completed subtasks
            if compensation_fn is not None:
                for sid, outcome in self._outcomes.items():
                    if outcome == SubtaskOutcome.SUCCESS:
                        compensation_fn(sid, self._results.get(sid, {}))
                        compensations_executed.append(sid)

            return PlanExecutionResult(
                plan_id=self._plan_id,
                all_succeeded=False,
                subtask_outcomes=dict(self._outcomes),
                failure_reason=self._build_failure_reason(),
                compensations_executed=compensations_executed,
            )

        if not self.all_succeeded():
            # Some still retryable — not yet final
            return PlanExecutionResult(
                plan_id=self._plan_id,
                all_succeeded=False,
                subtask_outcomes=dict(self._outcomes),
                failure_reason="Not all subtasks completed successfully",
            )

        return PlanExecutionResult(
            plan_id=self._plan_id,
            all_succeeded=True,
            merged_output=merged_output,
            subtask_outcomes=dict(self._outcomes),
        )

    # ── Internal ──────────────────────────────────────────────────────────

    def _build_failure_reason(self) -> str:
        failures: list[str] = []
        for sid, outcome in self._outcomes.items():
            if outcome != SubtaskOutcome.SUCCESS:
                failures.append(f"{sid}: {outcome.value}")
        return "; ".join(failures)
