from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Protocol, Tuple

from .dispatch.core_step import CoreStep
from .models.step_state import StepState
from ..types.step_result import StepResult
from .orchestration.loop_metrics import LoopMetrics
from .loop_termination import decide_termination
from src.core.types.hashing import stable_hash


class LoopPolicy(Protocol):
    """
    Stratum-2 policy interface for loop control.

    Implementations can live in loop_policy_enforcer or elsewhere.
    """

    def allows_continue(
        self,
        state: StepState,
        result: StepResult,
        step_count: int,
    ) -> bool:
        ...


@dataclass(frozen=True)
class LoopController:
    """
    Deterministic loop engine (Stratum 2).

    Hybrid termination:
    - terminal StepOutcome
    - OR step budget exceeded
    - OR duration budget exceeded
    - OR policy violation
    """

    core_step: CoreStep
    max_steps: Optional[int] = None
    max_duration: Optional[int] = None # same unit as StepState.created_at
    policy: Optional[LoopPolicy] = None

    def run(self, initial_state: StepState) -> Tuple[StepState, StepResult, LoopMetrics]:
        state = initial_state
        step_count = 0

        metrics = LoopMetrics(
            step_count=0,
            start_created_at=initial_state.created_at,
            end_created_at=initial_state.created_at,
            termination_reason="not_terminated",
        )

        last_result: Optional[StepResult] = None

        while True:
            step_count += 1

            new_state, result = self.core_step.run(state)
            elapsed = new_state.created_at - initial_state.created_at

            if self.policy is not None:
                policy_allows = self.policy.allows_continue(
                    new_state,
                    result,
                    step_count,
                )
            else:
                policy_allows = True

            decision = decide_termination(
                result=result,
                step_count=step_count,
                max_steps=self.max_steps,
                elapsed=elapsed,
                max_duration=self.max_duration,
                policy_allows_continue=policy_allows,
            )

            metrics = LoopMetrics(
                step_count=step_count,
                start_created_at=metrics.start_created_at,
                end_created_at=new_state.created_at,
                termination_reason=decision.reason,
                extra={
                    **metrics.extra,
                    "last_step_hash": stable_hash(
                        {
                            "step_id": new_state.step_id,
                            "created_at": new_state.created_at,
                            "outcome": result.outcome.value,
                        }
                    ),
                },
            )

            state = new_state
            last_result = result

            if decision.should_terminate:
                break

        return state, last_result, metrics # type: ignore[arg-type]