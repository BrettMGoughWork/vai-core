from dataclasses import dataclass
from src.core.planning.safety.loop_policy import LoopPolicy
from core.types.errors import ValidationError


@dataclass(frozen=True)
class LoopPolicyEnforcer:
    """
    Pure enforcement of LoopPolicy constraints.
    """

    policy: LoopPolicy

    def check_step_limit(self, step_count: int) -> None:
        if not self.policy.allows_step(step_count):
            raise ValidationError(f"LoopPolicy: max_steps exceeded ({step_count})")

    def check_retry_limit(self, retry_count: int) -> None:
        if not self.policy.allows_retry(retry_count):
            raise ValidationError(f"LoopPolicy: max_retries exceeded ({retry_count})")

    def check_duration_limit(self, duration: int) -> None:
        if not self.policy.allows_duration(duration):
            raise ValidationError(f"LoopPolicy: max_duration exceeded ({duration})")