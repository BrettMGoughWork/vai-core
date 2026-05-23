from dataclasses import dataclass, field
from typing import List, Optional, Any
from src.core.types.result import CoreResult
from src.core.agent.trace import StepTrace
from src.core.planning.subgoal_state import SubgoalState
from src.core.planning.segment_state import SegmentState

@dataclass
class ConversationState:
    # The original user input
    input: str

    # Full message history (LLM + tool messages)
    history: List[str] = field(default_factory=list)

    # Last tool call result (CoreResult)
    last_result: Optional[CoreResult] = None

    # Last runtime error message, if any
    last_error: Optional[str] = None

    # Number of completed core steps
    step_count: int = 0

    # Arbitrary metadata (step count, timestamps, etc.)
    metadata: dict = field(default_factory=dict)

    # Loop trace (step outcomes)
    trace: List[StepTrace] = field(default_factory=list)

    subgoals: List[SubgoalState] = field(default_factory=list)
    segments: List[SegmentState] = field(default_factory=list)
    active_subgoal: Optional[str] = None
    active_segment: Optional[str] = None

    def append_llm(self, text: str) -> None:
        self.history.append(f"LLM: {text}")

    def append_tool(self, name: str, output: Any) -> None:
        self.history.append(f"TOOL {name}: {output}")

    def append_error(self, name: str, error: str) -> None:
        self.history.append(f"TOOL {name} ERROR: {error}")

    def as_prompt(self) -> str:
        """
        Convert state into a prompt for the LLM.
        Phase‑1 version: simple concatenation.
        Later phases: structured messages.
        """
        base = f"User: {self.input}"
        if not self.history:
            return base
        return base + "\n" + "\n".join(self.history)

    def reset(self) -> None:
        self.history.clear()
        self.last_result = None
        self.last_error = None
        self.step_count = 0
        self.metadata.clear()
        self.trace.clear()