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
    metadata: dict[str, Any] = field(default_factory=dict)
    
    # Substrate states
    subgoal_state: SubgoalSubstrateState = field(default_factory=SubgoalSubstrateState)
    segment_state: SegmentSubstrateState = field(default_factory=SegmentSubstrateState)

    # --- 3.8.8 Segment memory mapping ---
    # Maps segment_id → SegmentMemoryRecord, tracking execution results per segment.
    segment_memory: dict[str, Any] = field(default_factory=dict)

    termination_reason: Optional[str] = None

    # runtime layer
    last_error: Exception | None = None
    llm_history: List[str] = field(default_factory=list)
    tool_history: list[tuple[str, Any]] = field(default_factory=list)
    error_history: list[tuple[str, Exception]] = field(default_factory=list)
    history: list[str] = field(default_factory=list)

    def append_llm(self, text:str):
        self.llm_history.append(text)
        self.history.append(f"LLM: {text}")

    def append_tool(self, tool_name: str, output: Any) -> None:
        self.tool_history.append((tool_name, output))
        self.history.append(f"TOOL ({tool_name}): {output}")

    def append_error(self, tool_name: str, error: Exception) -> None:
        self.error_history.append((tool_name, error))
        self.last_error = error
        self.history.append(f"ERROR ({tool_name}): {error}")

    def reset(self) -> None:
        self.step_count = 0
        self.last_result = None
        self.last_error = None

        self.llm_history.clear()
        self.tool_history.clear()
        self.error_history.clear()
        self.history.clear()
        self.trace.clear()
        self.metadata.clear()
        self.termination_reason = None
        
    def as_prompt(self) -> str:
        """
        Build the prompt from conversation history and input.
        Tests expect:
        - if no history: return user input only
        - otherwise: include history entries then user input
        """
        lines = [f"USER: {self.input}"]
        for entry in self.history:
            lines.append(entry)
        return "\n".join(lines)

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
