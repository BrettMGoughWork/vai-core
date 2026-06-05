from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any


# ──────────────────────────────────────────────────────────────────────────────
# Segment State Enum
# ──────────────────────────────────────────────────────────────────────────────

class SegmentState(str, Enum):
    """Deterministic segment lifecycle states.

    States:
        PENDING  — segment has not started execution
        ACTIVE   — segment is currently executing
        COMPLETE — segment has finished execution
    """
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETE = "complete"


# ──────────────────────────────────────────────────────────────────────────────
# Segment Execution State Dataclass
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SegmentExecutionState:
    """Pure, deterministic snapshot of segment-level execution progress.

    Fields:
        index — 0-based index of the current segment
        state — current SegmentState value (pending | active | complete)
    """
    index: int = 0
    state: str = SegmentState.PENDING.value


# ──────────────────────────────────────────────────────────────────────────────
# Pure Transition Functions
# ──────────────────────────────────────────────────────────────────────────────

def transition_segment_state(current: str, is_complete: bool) -> str:
    """Deterministic segment state machine.

    Transition rules:
        pending → active
        active  → complete  (if is_complete)
        active  → active    (if not complete)
        complete → complete (terminal)

    Args:
        current: The current segment state string.
        is_complete: Whether the active segment has completed execution.

    Returns:
        The next segment state string.

    Raises:
        ValueError: If current is not a valid SegmentState value.
    """
    if current not in (SegmentState.PENDING, SegmentState.ACTIVE, SegmentState.COMPLETE):
        raise ValueError(
            f"Invalid segment state: {current!r}. "
            f"Expected one of: {[s.value for s in SegmentState]}"
        )

    if current == SegmentState.PENDING:
        return SegmentState.ACTIVE

    if current == SegmentState.ACTIVE:
        return SegmentState.COMPLETE if is_complete else SegmentState.ACTIVE

    # current == COMPLETE — terminal
    return SegmentState.COMPLETE


def advance_segment_index(current_index: int, total_segments: int) -> int:
    """Advance to the next segment index if one is available.

    Rules:
        - If current_index + 1 < total_segments → return current_index + 1
        - Otherwise → return current_index (already at final segment)

    Args:
        current_index: 0-based index of the current segment.
        total_segments: Total number of segments in the plan.

    Returns:
        The next segment index (clamped to valid range).

    Raises:
        ValueError: If current_index is negative or total_segments is non-positive.
    """
    if current_index < 0:
        raise ValueError(
            f"current_index must be >= 0, got {current_index}"
        )
    if total_segments < 0:
        raise ValueError(
            f"total_segments must be >= 0, got {total_segments}"
        )

    if total_segments == 0:
        return current_index

    next_index = current_index + 1
    if next_index < total_segments:
        return next_index
    return current_index


def update_segment_execution_state(
    exec_state: SegmentExecutionState,
    is_complete: bool,
    total_segments: int,
) -> SegmentExecutionState:
    """Apply transition rules and advance index when a segment completes.

    Applies transition_segment_state to determine the new state.  If the state
    *transitions to* COMPLETE (was not already COMPLETE), also advances the
    segment index via advance_segment_index.

    Args:
        exec_state: Current segment execution state.
        is_complete: Whether the active segment has completed.
        total_segments: Total number of segments in the plan.

    Returns:
        A new SegmentExecutionState reflecting the transition result.

    Raises:
        ValueError: If current state is invalid or index/total out of range.
    """
    # Validate index before any transition
    if exec_state.index < 0:
        raise ValueError(
            f"SegmentExecutionState index must be >= 0, got {exec_state.index}"
        )
    if total_segments < 0:
        raise ValueError(
            f"total_segments must be >= 0, got {total_segments}"
        )

    was_complete = exec_state.state == SegmentState.COMPLETE
    new_state = transition_segment_state(exec_state.state, is_complete)
    new_index = exec_state.index
    # Only advance index when the state actually transitions to COMPLETE
    if not was_complete and new_state == SegmentState.COMPLETE:
        new_index = advance_segment_index(exec_state.index, total_segments)
    return SegmentExecutionState(index=new_index, state=new_state)


# ──────────────────────────────────────────────────────────────────────────────
# Structural Summary Hooks (filled in 2.11.2+)
# ──────────────────────────────────────────────────────────────────────────────

def segment_progress_summary(exec_state: SegmentExecutionState) -> Dict[str, Any]:
    """Produce a deterministic structural summary of segment progress.

    Placeholder for Phase 2.11.2 — currently returns minimal state snapshot.

    Args:
        exec_state: Current segment execution state.

    Returns:
        Dict with index, state keys.
    """
    return {
        "index": exec_state.index,
        "state": exec_state.state,
    }


def segment_completion_summary(exec_state: SegmentExecutionState) -> Dict[str, Any]:
    """Produce a deterministic structural summary of segment completion.

    Placeholder for Phase 2.11.2 — currently returns minimal completion flag.

    Args:
        exec_state: Current segment execution state.

    Returns:
        Dict with is_complete flag.
    """
    return {
        "is_complete": exec_state.state == SegmentState.COMPLETE,
    }
