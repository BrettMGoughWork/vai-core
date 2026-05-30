# Stratum 3
# Outcome classification for agent steps.

from enum import Enum

from src.core.types.result import CoreResult


class StepOutcome(str, Enum):
    """
    Outcome classification for agent steps.
     - SUCCESS: step completed successfully with valid output
     - RECOVERABLE: step failed but can be retried or self-healed
     - FATAL: step failed with unrecoverable error, should halt agent loop
     - NOOP: step did not produce any meaningful output
    """
    SUCCESS = "success"
    RECOVERABLE = "recoverable"
    FATAL = "fatal"
    NOOP = "noop"
    FAILURE = "failure"


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
