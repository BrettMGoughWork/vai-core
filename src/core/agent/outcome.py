from enum import Enum

from src.core.types.result import CoreResult


class StepOutcome(str, Enum):
    SUCCESS = "success"
    RECOVERABLE = "recoverable"
    FATAL = "fatal"
    NOOP = "noop"


def classify_step(result: CoreResult) -> StepOutcome:
    if result.is_error:
        return StepOutcome.FATAL
    if result.is_text:
        return StepOutcome.SUCCESS
    if result.is_tool:
        if result.tool_output is None:
            return StepOutcome.NOOP
        return StepOutcome.RECOVERABLE
    return StepOutcome.NOOP
