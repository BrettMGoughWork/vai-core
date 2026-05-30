"""
Phase 2.5.5 — Reflection Loop: progress evaluation.

Pure, deterministic function that evaluates subgoal/segment progress from
memory snapshots.  No side effects, no LLM calls, no inference.
"""
from __future__ import annotations

from typing import Optional

from src.core.types.subgoal import SubgoalLifecycleState
from src.core.memory.subgoal_memory_types import SubgoalMemorySnapshot
from src.core.memory.segment_memory_types import SegmentMemorySnapshot

from src.core.planning.reflection.reflection_types import ProgressReport, ReflectionDriftReport


# States considered "done" for progress counting.
_COMPLETE_STATES: frozenset[SubgoalLifecycleState] = frozenset({
    SubgoalLifecycleState.SUCCESS,
    SubgoalLifecycleState.SATISFIED,
    SubgoalLifecycleState.CLOSED,
})

# States that indicate the subgoal is stuck.
_PROBLEM_STATES: frozenset[SubgoalLifecycleState] = frozenset({
    SubgoalLifecycleState.BLOCKED,
    SubgoalLifecycleState.FAILED,
})

# Drift classifications considered severe enough to mark progress as stalled.
_SEVERE_CLASSIFICATIONS: frozenset[str] = frozenset({
    "severe_drift",
    "critical_drift",
})


def evaluate_progress(
    subgoal_snap: SubgoalMemorySnapshot,
    segment_snap: SegmentMemorySnapshot,
    drift_report: Optional[ReflectionDriftReport] = None,
    repair_attempts: int = 0,
    stall_repair_threshold: int = 3,
    prior_progress: Optional[ProgressReport] = None,
) -> ProgressReport:
    """
    Evaluate structural progress from memory snapshots.

    subgoal_snap:          All subgoal records in memory (tuple, may be empty).
    segment_snap:          All segment records in memory (tuple, may be empty).
    drift_report:          Current cycle's drift result; None if not yet computed.
    repair_attempts:       How many repair cycles have run (behavioural signal).
    stall_repair_threshold: repair_attempts >= this threshold triggers stall.
    prior_progress:        Previous cycle's ProgressReport for rate comparison.

    All counts are structural — no inference, no semantics.
    'segments_complete' counts segments whose parent subgoal is in a terminal-
    success state, since SegmentMemoryRecord carries no lifecycle state of its own.
    """
    all_subgoal_records = list(subgoal_snap.records)
    subgoals_total = len(all_subgoal_records)

    # Classify subgoal states.
    complete_subgoal_ids: set[str] = set()
    all_in_problem_state = subgoals_total > 0
    subgoals_complete = 0

    for record in all_subgoal_records:
        try:
            state = SubgoalLifecycleState(record.state)
        except ValueError:
            # Unknown state string — treat as non-complete, non-problem.
            all_in_problem_state = False
            continue

        if state in _COMPLETE_STATES:
            subgoals_complete += 1
            complete_subgoal_ids.add(record.subgoal_id)

        if state not in _PROBLEM_STATES:
            all_in_problem_state = False

    # Segment counts: "complete" = belongs to a complete subgoal.
    all_segment_records = list(segment_snap.records)
    segments_total = len(all_segment_records)
    segments_complete = sum(
        1 for s in all_segment_records
        if s.subgoal_id in complete_subgoal_ids
    )

    # Stall detection.
    stalled_reasons: list[str] = []

    if subgoals_total == 0:
        stalled_reasons.append("no_subgoals")
    elif all_in_problem_state:
        stalled_reasons.append("all_subgoals_blocked_or_failed")

    if (
        drift_report is not None
        and drift_report.confirmation.confirmed
        and drift_report.classification in _SEVERE_CLASSIFICATIONS
    ):
        stalled_reasons.append("severe_drift_confirmed")

    if repair_attempts >= stall_repair_threshold > 0:
        stalled_reasons.append("repair_loop")

    stalled = len(stalled_reasons) > 0

    # Progress rate compared against prior cycle.
    if stalled:
        progress_rate = "stalled"
    elif prior_progress is None:
        progress_rate = "steady"
    elif subgoals_complete > prior_progress.subgoals_complete:
        progress_rate = "increasing"
    elif subgoals_complete < prior_progress.subgoals_complete:
        progress_rate = "decreasing"
    else:
        progress_rate = "steady"

    return ProgressReport(
        subgoals_complete=subgoals_complete,
        subgoals_total=subgoals_total,
        segments_complete=segments_complete,
        segments_total=segments_total,
        stalled=stalled,
        stalled_reasons=tuple(stalled_reasons),
        progress_rate=progress_rate,
    )
