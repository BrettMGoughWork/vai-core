"""
CognitiveStepOutcome — Stratum 2 (domain) enum.

Describes WHAT THE MODEL DECIDED at the end of a reasoning step.
This is distinct from StepOutcome (Stratum 3 / state) which describes
HOW THE RUNTIME SHOULD REACT to an execution result.
"""

from enum import Enum


class CognitiveStepOutcome(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TOOL_NEEDED = "tool_needed"
    CONTINUE = "continue"
