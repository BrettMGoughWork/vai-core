from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple

from .core_step_v2 import CoreStepV2
from .step_state import StepState
from .step_result import StepResult
from .loop_controller import LoopController, LoopPolicy
from .loop_metrics import LoopMetrics


@dataclass(frozen=True)
class LoopOrchestrator:
    """
    Public Stratum-2 loop API.

    Orchestrates:
    - CoreStepV2
    - LoopController
    - LoopTermination
    - LoopMetrics
    """

    core_step: CoreStepV2 = CoreStepV2()
    max_steps: Optional[int] = None
    max_duration: Optional[int] = None
    policy: Optional[LoopPolicy] = None

    def run(self, initial_state: StepState) -> Tuple[StepState, StepResult, LoopMetrics]:
        controller = LoopController(
            core_step=self.core_step,
            max_steps=self.max_steps,
            max_duration=self.max_duration,
            policy=self.policy,
        )
        return controller.run(initial_state)