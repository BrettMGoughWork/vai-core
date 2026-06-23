from __future__ import annotations

from enum import Enum
from typing import Dict, Tuple

from src.agent.memory.types.subgoal import SubgoalLifecycleState


class SubgoalEvent(str, Enum):
    VALIDATE = "validate"
    ACTIVATE = "activate"
    START = "start"
    SUCCEED = "succeed"
    FAIL = "fail"
    BLOCK = "block"
    UNBLOCK = "unblock"
    RETRY = "retry"
    RESUME = "resume"


_S = SubgoalLifecycleState

ALLOWED_TRANSITIONS: Dict[Tuple[SubgoalLifecycleState, SubgoalLifecycleState], str] = {
    (_S.CREATED,   _S.VALIDATED): "Subgoal passed validation",
    (_S.VALIDATED, _S.READY):     "Subgoal is ready to run",
    (_S.READY,     _S.RUNNING):   "Subgoal execution started",
    (_S.RUNNING,   _S.SUCCESS):   "Subgoal completed successfully",
    (_S.RUNNING,   _S.FAILED):    "Subgoal execution failed",
    (_S.RUNNING,   _S.BLOCKED):   "Subgoal is blocked",
    (_S.BLOCKED,   _S.READY):     "Subgoal unblocked, returning to ready",
    (_S.FAILED,    _S.RETRYING):  "Subgoal scheduled for retry",
    (_S.RETRYING,  _S.RUNNING):   "Subgoal retry execution started",
}
