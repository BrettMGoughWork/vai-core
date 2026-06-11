from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any


# ──────────────────────────────────────────────────────────────────────────────
# Subgoal Execution Phase Enum
# ──────────────────────────────────────────────────────────────────────────────

class SubgoalExecutionPhase(str, Enum):
    """Deterministic subgoal execution-phase states.

    These are **execution‑order** states for the multi‑subgoal pipeline,
    distinct from the richer SubgoalLifecycleState used by the transition engine.

    States:
        PENDING  — subgoal has not started execution
        ACTIVE   — subgoal is currently executing
        COMPLETE — subgoal has finished execution
    """
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETE = "complete"


# ──────────────────────────────────────────────────────────────────────────────
# Subgoal Execution State Dataclass
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SubgoalExecutionState:
    """Pure, deterministic snapshot of subgoal-level execution progress.

    Fields:
        index — 0-based index of the current subgoal in the ordered list
        state — current SubgoalExecutionPhase value (pending | active | complete)
    """
    index: int = 0
    state: str = SubgoalExecutionPhase.PENDING.value


# ──────────────────────────────────────────────────────────────────────────────
# Pure Transition Functions
# ──────────────────────────────────────────────────────────────────────────────

def transition_subgoal_state(current: str, is_complete: bool) -> str:
    """Deterministic subgoal state machine.

    Transition rules:
        pending  → active
        active   → complete  (if is_complete)
        active   → active    (if not complete)
        complete → complete  (terminal)

    Args:
        current: The current subgoal state string.
        is_complete: Whether the active subgoal has completed execution.

    Returns:
        The next subgoal state string.

    Raises:
        ValueError: If current is not a valid SubgoalExecutionPhase value.
    """
    if current not in (
        SubgoalExecutionPhase.PENDING,
        SubgoalExecutionPhase.ACTIVE,
        SubgoalExecutionPhase.COMPLETE,
    ):
        raise ValueError(
            f"Invalid subgoal state: {current!r}. "
            f"Expected one of: {[s.value for s in SubgoalExecutionPhase]}"
        )

    if current == SubgoalExecutionPhase.PENDING:
        return SubgoalExecutionPhase.ACTIVE

    if current == SubgoalExecutionPhase.ACTIVE:
        return SubgoalExecutionPhase.COMPLETE if is_complete else SubgoalExecutionPhase.ACTIVE

    # current == COMPLETE — terminal
    return SubgoalExecutionPhase.COMPLETE


def advance_subgoal_index(current_index: int, total_subgoals: int) -> int:
    """Advance to the next subgoal index if one is available.

    Rules:
        - If current_index + 1 < total_subgoals → return current_index + 1
        - Otherwise → return current_index (already at final subgoal)

    Args:
        current_index: 0-based index of the current subgoal.
        total_subgoals: Total number of subgoals.

    Returns:
        The next subgoal index (clamped to valid range).

    Raises:
        ValueError: If current_index is negative or total_subgoals is non-positive.
    """
    if current_index < 0:
        raise ValueError(
            f"current_index must be >= 0, got {current_index}"
        )
    if total_subgoals < 0:
        raise ValueError(
            f"total_subgoals must be >= 0, got {total_subgoals}"
        )

    if total_subgoals == 0:
        return current_index

    next_index = current_index + 1
    if next_index < total_subgoals:
        return next_index
    return current_index


def update_subgoal_execution_state(
    exec_state: SubgoalExecutionState,
    is_complete: bool,
    total_subgoals: int,
) -> SubgoalExecutionState:
    """Apply transition rules and advance index when a subgoal completes.

    Applies transition_subgoal_state to determine the new state.  If the state
    *transitions to* COMPLETE (was not already COMPLETE), also advances the
    subgoal index via advance_subgoal_index.

    Args:
        exec_state: Current subgoal execution state.
        is_complete: Whether the active subgoal has completed.
        total_subgoals: Total number of subgoals.

    Returns:
        A new SubgoalExecutionState reflecting the transition result.

    Raises:
        ValueError: If current state is invalid or index/total out of range.
    """
    # Validate index before any transition
    if exec_state.index < 0:
        raise ValueError(
            f"SubgoalExecutionState index must be >= 0, got {exec_state.index}"
        )
    if total_subgoals < 0:
        raise ValueError(
            f"total_subgoals must be >= 0, got {total_subgoals}"
        )

    was_complete = exec_state.state == SubgoalExecutionPhase.COMPLETE
    new_state = transition_subgoal_state(exec_state.state, is_complete)
    new_index = exec_state.index
    # Only advance index when the state actually transitions to COMPLETE
    if not was_complete and new_state == SubgoalExecutionPhase.COMPLETE:
        advanced = advance_subgoal_index(exec_state.index, total_subgoals)
        # When the final subgoal completes, advance the index *past* the
        # last valid position so the caller can distinguish "final subgoal
        # actually completed" from "previous subgoal advanced to the final
        # index and awaits execution".
        if advanced == exec_state.index and total_subgoals > 0:
            new_index = total_subgoals
        else:
            new_index = advanced
    return SubgoalExecutionState(index=new_index, state=new_state)


# ──────────────────────────────────────────────────────────────────────────────
# Agent Completion Detection
# ──────────────────────────────────────────────────────────────────────────────

def is_agent_complete(
    exec_state: SubgoalExecutionState,
    total_subgoals: int,
) -> bool:
    """Determine whether the agent has completed all subgoals.

    An agent is complete when:
        - The current subgoal state is COMPLETE
        - The index is at the final subgoal (no more to advance to)

    Args:
        exec_state: Current subgoal execution state.
        total_subgoals: Total number of subgoals.

    Returns:
        True if agent execution is complete, False otherwise.
    """
    if total_subgoals <= 0:
        return True

    at_final_index = advance_subgoal_index(exec_state.index, total_subgoals) == exec_state.index
    return exec_state.state == SubgoalExecutionPhase.COMPLETE and at_final_index


# ──────────────────────────────────────────────────────────────────────────────
# Structural Summary Hooks (filled in 2.12.2+)
# ──────────────────────────────────────────────────────────────────────────────

def subgoal_progress_summary(exec_state: SubgoalExecutionState) -> Dict[str, Any]:
    """Produce a deterministic structural summary of subgoal progress.

    Placeholder for Phase 2.12.2 — currently returns minimal state snapshot.

    Args:
        exec_state: Current subgoal execution state.

    Returns:
        Dict with index, state keys.
    """
    return {
        "index": exec_state.index,
        "state": exec_state.state,
    }


def subgoal_completion_summary(exec_state: SubgoalExecutionState) -> Dict[str, Any]:
    """Produce a deterministic structural summary of subgoal completion.

    Placeholder for Phase 2.12.2 — currently returns minimal completion flag.

    Args:
        exec_state: Current subgoal execution state.

    Returns:
        Dict with is_complete flag.
    """
    return {
        "is_complete": exec_state.state == SubgoalExecutionPhase.COMPLETE,
    }
