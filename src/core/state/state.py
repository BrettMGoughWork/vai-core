from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, List, Optional

from src.core.types.result import CoreResult


# ---------------------------------------------------------
# Substrate: SubgoalState
# ---------------------------------------------------------

@dataclass
class SubgoalSubstrateState:
    """
    Stratum‑1 substrate representation of subgoals.
    Used by:
      - evaluate_signals()
      - emit_drift_from_subgoals()
      - AgentLoop
    """
    subgoals: List[Any] = field(default_factory=list)

    def active_chain(self):
        """
        Minimal placeholder for signal engine.
        Returns the list itself or a view of it.
        """
        return self.subgoals

    def add(self, subgoal: Any):
        self.subgoals.append(subgoal)


# ---------------------------------------------------------
# SegmentSubstrateState
# ---------------------------------------------------------

@dataclass
class SegmentSubstrateState:
    """
    Stratum‑1 substrate representation of segments.
    Used by:
      - evaluate_signals()
      - emit_drift_from_segments()
      - AgentLoop
    """

    segments: List[Any] = field(default_factory=list)

    # --- Required by drift emitter ---
    repeated_failures: int = 0
    recent_failures: int = 0
    last_failure_step: Optional[int] = None

    @property
    def has_gaps(self) -> bool:
        return False

    @property
    def has_overlaps(self) -> bool:
        return False

    def active_chain(self):
        return self.segments

    def add(self, segment: Any):
        self.segments.append(segment)


# ---------------------------------------------------------
# ConversationState
# ---------------------------------------------------------

@dataclass
class ConversationState:
    """
    Correct substrate state for 2.3.6 agent loop.
    Compatible with evaluate_signals() and the signal engine.
    """

    input: Optional[str] = None
    step_count: int = 0
    last_result: Optional[CoreResult] = None
    trace: List[Any] = field(default_factory=list)

    # Substrate states
    subgoal_state: SubgoalSubstrateState = field(default_factory=SubgoalSubstrateState)
    segment_state: SegmentSubstrateState = field(default_factory=SegmentSubstrateState)

    termination_reason: Optional[str] = None

    @classmethod
    def initial(cls, user_input: str) -> "ConversationState":
        return cls(input=user_input)

    # -----------------------------------------------------
    # State update after each CoreStep
    # -----------------------------------------------------

    def apply_step_result(self, result: CoreResult) -> "ConversationState":
        self.last_result = result
        self.step_count += 1
        self.trace.append(result)
        return self

    # -----------------------------------------------------
    # Termination
    # -----------------------------------------------------

    def with_termination_reason(self, reason: str) -> "ConversationState":
        self.termination_reason = reason
        return self
