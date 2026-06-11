from dataclasses import dataclass
from typing import Optional

from src.strategy.state.step_outcome import StepOutcome


@dataclass
class StepTrace:
    step: int
    outcome: StepOutcome
    summary: str
    error: Optional[str] = None
