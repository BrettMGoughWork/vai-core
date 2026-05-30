from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LoopPolicy:
    """
    Pure deterministic loop policy for Stratum 2 cognitive loops.

    All fields are logical (not wall-clock) to preserve determinism.
    """

    max_steps: int = 50
    max_retries: int = 3
    max_duration: Optional[int] = None # logical ticks, not real time

    def allows_step(self, step_count: int) -> bool:
        return step_count < self.max_steps

    def allows_retry(self, retry_count: int) -> bool:
        return retry_count < self.max_retries

    def allows_duration(self, duration: int) -> bool:
        if self.max_duration is None:
            return True
        return duration < self.max_duration

    def allows_continue(
        self,
        state,
        result,
        step_count: int,
    ) -> bool:
        return self.allows_step(step_count)