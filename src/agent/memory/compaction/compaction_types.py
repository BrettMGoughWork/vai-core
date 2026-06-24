"""Data types for the compaction pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class CompactionTrigger(str, Enum):
    """What caused a compaction to fire."""

    CONTEXT_PRESSURE = "context_pressure"
    """Input tokens exceeded the configured threshold of the model's context window."""

    TURN_COUNT = "turn_count"
    """Number of user+assistant turn pairs exceeded the configured threshold."""

    SUBGOAL_CLOSED = "subgoal_closed"
    """A subgoal transitioned to CLOSED, triggering subgoal compaction."""

    MANUAL = "manual"
    """Compaction was triggered explicitly."""


@dataclass
class CompactionConfig:
    """Configuration for the compaction pipeline.

    Attributes:
        enabled: Master switch. When False, no compaction occurs.
        context_pressure_threshold: (0.0-1.0) Input tokens as fraction of
            context limit above which compaction fires. Default 0.8.
        turn_count_threshold: Compact every N user+assistant turn pairs.
            Default 10.
        keep_recent_turns: Always keep the last N turns un-compacted.
            Default 4.
        summary_style: "prose" for paragraph summary (Phase 1),
            "structured" for JSON (Phase 3). Default "prose".
        min_tokens_for_compaction: Minimum total tokens in conversation
            history before compaction will fire. Prevents pointless LLM
            calls on short conversations. Default 2000.
    """

    enabled: bool = True
    context_pressure_threshold: float = 0.8
    turn_count_threshold: int = 10
    keep_recent_turns: int = 4
    summary_style: str = "prose"
    min_tokens_for_compaction: int = 2000
    tool_output_threshold: int = 10000
    """Character length above which a tool result is summarised rather than
    stored raw.  Default 10 000.  Set to 0 to disable."""

    @classmethod
    def from_dict(cls, d: dict) -> CompactionConfig:
        """Build from a dictionary (e.g. parsed from YAML config)."""
        return cls(
            enabled=d.get("enabled", True),
            context_pressure_threshold=d.get("context_pressure_threshold", 0.8),
            turn_count_threshold=d.get("turn_count_threshold", 10),
            keep_recent_turns=d.get("keep_recent_turns", 4),
            summary_style=d.get("summary_style", "prose"),
            min_tokens_for_compaction=d.get("min_tokens_for_compaction", 2000),
            tool_output_threshold=d.get("tool_output_threshold", 10000),
        )


@dataclass
class StructuredState:
    """Structured state extracted from conversation history (Phase 3).

    Replaces prose summaries with structured JSON fields for better
    context injection and downstream consumption.
    """

    goal: str = ""
    """The user's overall goal."""

    current_focus: str = ""
    """What is being worked on right now."""

    completed: List[str] = field(default_factory=list)
    """List of completed items."""

    blocked: List[str] = field(default_factory=list)
    """Items that can't proceed."""

    next_steps: List[str] = field(default_factory=list)
    """Immediate next actions."""

    important_decisions: List[str] = field(default_factory=list)
    """Decisions made and their rationale."""

    open_questions: List[str] = field(default_factory=list)
    """Questions not yet answered."""

    files_created: List[str] = field(default_factory=list)
    """Files that were created."""

    files_modified: List[str] = field(default_factory=list)
    """Files that were modified."""

    errors_encountered: List[str] = field(default_factory=list)
    """Errors or blockers encountered."""

    @classmethod
    def from_dict(cls, d: dict) -> StructuredState:
        """Build from an untrusted dict (e.g. parsed JSON from LLM response).

        Silently ignores unknown keys and coerces missing fields to defaults.
        """
        return cls(
            goal=d.get("goal", ""),
            current_focus=d.get("current_focus", ""),
            completed=_coerce_str_list(d, "completed"),
            blocked=_coerce_str_list(d, "blocked"),
            next_steps=_coerce_str_list(d, "next_steps"),
            important_decisions=_coerce_str_list(d, "important_decisions"),
            open_questions=_coerce_str_list(d, "open_questions"),
            files_created=_coerce_str_list(d, "files_created"),
            files_modified=_coerce_str_list(d, "files_modified"),
            errors_encountered=_coerce_str_list(d, "errors_encountered"),
        )

    def format_for_injection(self) -> str:
        """Format as a readable '[CURRENT STATE]' block for system-message injection."""
        lines = ["[CURRENT STATE]"]
        if self.goal:
            lines.append(f"Goal: {self.goal}")
        if self.current_focus:
            lines.append(f"Focus: {self.current_focus}")
        if self.completed:
            lines.append(f"Completed: {', '.join(self.completed)}")
        if self.blocked:
            lines.append(f"Blocked: {', '.join(self.blocked)}")
        if self.next_steps:
            lines.append(f"Next: {', '.join(self.next_steps)}")
        if self.important_decisions:
            lines.append(f"Decisions: {'; '.join(self.important_decisions)}")
        if self.open_questions:
            lines.append(f"Questions: {'; '.join(self.open_questions)}")
        if self.files_created:
            lines.append(f"Created: {', '.join(self.files_created)}")
        if self.files_modified:
            lines.append(f"Modified: {', '.join(self.files_modified)}")
        if self.errors_encountered:
            lines.append(f"Errors: {'; '.join(self.errors_encountered)}")
        return "\n".join(lines)


def _coerce_str_list(d: dict, key: str) -> List[str]:
    """Extract a list-of-strings from *d*, coercing unexpected types."""
    raw = d.get(key, [])
    if not isinstance(raw, list):
        return [str(raw)] if raw else []
    return [str(item) for item in raw if item is not None]


@dataclass
class CompactionResult:
    """Result of a compaction operation.

    Attributes:
        triggered: Whether compaction actually ran.
        trigger: What triggered it, or None if it didn't fire.
        turns_before: Number of turn pairs before compaction.
        turns_after: Number of turn pairs after compaction.
        tokens_before: Total tokens in conversation history before.
        tokens_after: Total tokens in conversation history after.
        summary: The generated summary text, if compaction ran.
        error: Error message if the LLM call failed (compaction skipped).
    """

    triggered: bool = False
    trigger: Optional[CompactionTrigger] = None
    turns_before: int = 0
    turns_after: int = 0
    tokens_before: int = 0
    tokens_after: int = 0
    summary: Optional[str] = None
    structured_state: Optional[StructuredState] = None
    """Parsed structured state when summary_style == 'structured'."""
    rolled_back: bool = False
    """True when compaction _ran_ but was rolled back because the summary
    was not smaller than the original content (net-reduction guard)."""
    compacted_subgoal_ids: set[str] = field(default_factory=set)
    """Subgoal IDs that were compacted during this pass."""
    error: Optional[str] = None
