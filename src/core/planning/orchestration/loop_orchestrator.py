from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Tuple

from ..models.step_state import StepState
from ...types.step_result import StepResult
from .loop_controller import LoopController
from ..safety.loop_policy import LoopPolicy
from .loop_metrics import LoopMetrics


@dataclass(frozen=True)
class LoopOrchestrator:
    """
    Public Stratum-2 loop API.

    Orchestrates:
    - CoreStep
    - LoopController
    - LoopTermination
    - LoopMetrics
    """

    core_step: Any
    max_steps: int
    max_duration: int
    policy: LoopPolicy

    def run(self, initial_state: StepState) -> Tuple[StepState, StepResult, LoopMetrics]:
        controller = LoopController(
            core_step=self.core_step,
            max_steps=self.max_steps,
            max_duration=self.max_duration,
            policy=self.policy,
        )
        return controller.run(initial_state)