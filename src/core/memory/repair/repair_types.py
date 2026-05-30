from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from src.core.memory.governance.governance_errors import GovernanceViolation
from src.core.memory.plan_memory_types import PlanMemoryRecord


@dataclass(frozen=True)
class BreakageError:
    """
    A structural error that prevents the plan from being valid.

    error_type values:
      MISSING_SEGMENT      — a segment_id in plan.segments is not in SegmentMemory.
      MISSING_SUBGOAL      — the plan's subgoal_id is not in SubgoalMemory.
      BROKEN_PARENT_LINK   — a segment's parent_id references a non-existent segment.
      SUBGOAL_MISMATCH     — a segment's subgoal_id does not match the plan's subgoal_id.
    """
    error_type: str
    record_id: str
    details: Dict[str, Any]


@dataclass(frozen=True)
class BreakageWarning:
    """
    A non-fatal structural concern noted during detection.

    warning_type values:
      DRIFT_FLAG             — a drift event targets a segment in this plan.
      SEGMENT_TIMESTAMP      — a segment's created_at cannot be parsed as ISO 8601.
                               Cannot be repaired (changing it would break segment_id).
      GOVERNANCE_WARNING     — a governance violation that does not require repair action.
    """
    warning_type: str
    record_id: str
    details: Dict[str, Any]


@dataclass(frozen=True)
class InvalidLink:
    """
    A broken referential link detected in the plan graph.

    link_type values:
      parent_child     — segment.parent_id does not resolve.
      subgoal_segment  — segment.subgoal_id ≠ plan.subgoal_id.
      plan_segment     — plan.segments contains an unknown segment_id.
    """
    from_id: str
    to_id: str
    link_type: str
    reason: str


@dataclass(frozen=True)
class DriftFlag:
    """A drift event that references a segment belonging to this plan."""
    segment_id: str
    subgoal_id: str
    signal_type: str
    confidence: float


@dataclass(frozen=True)
class TimestampIssue:
    """
    A timestamp that cannot be parsed or normalised.

    For plan records: repairable via REHYDRATE_TIMESTAMP.
    For segment records: report-only — changing created_at would invalidate segment_id.
    """
    record_id: str
    record_type: str  # "plan" | "segment"
    issue: str


@dataclass(frozen=True)
class PlanBreakageReport:
    """
    Structured result of a plan breakage detection pass.

    All collections use tuples for immutability.
    Use is_clean to determine whether the plan requires repair.
    """
    plan_id: str
    errors: Tuple[BreakageError, ...]
    warnings: Tuple[BreakageWarning, ...]
    missing_segments: Tuple[str, ...]
    invalid_links: Tuple[InvalidLink, ...]
    drift_flags: Tuple[DriftFlag, ...]
    timestamp_issues: Tuple[TimestampIssue, ...]
    governance_violations: Tuple[GovernanceViolation, ...]

    @property
    def is_clean(self) -> bool:
        """True if the plan has no actionable errors."""
        return not (
            self.errors
            or self.missing_segments
            or self.invalid_links
            or self.governance_violations
        )


@dataclass(frozen=True)
class RepairAction:
    """
    A single deterministic structural repair step.

    action_type values:
      REGENERATE_SEGMENT   — create a structural placeholder for a missing segment.
      RECONSTRUCT_CHAIN    — sever a broken parent_id link (set parent_id=None).
      REHYDRATE_TIMESTAMP  — normalise plan.created_at to canonical UTC ISO 8601.
      QUARANTINE_SEGMENT   — remove a subgoal-mismatched segment from plan.segments.
    """
    action_type: str
    target_id: str
    details: Dict[str, Any]


@dataclass(frozen=True)
class RepairPlan:
    """
    The full set of actions needed to repair a plan, derived from a PlanBreakageReport.

    actions: deterministic sequence of repair steps (sorted for reproducibility).
    requires_redecomposition: True if the plan's subgoal is missing (structural only).
    requires_segment_regeneration: segment_ids for which placeholders must be created.
    requires_subgoal_repair: subgoal_ids that are broken/missing.
    """
    actions: Tuple[RepairAction, ...]
    requires_redecomposition: bool
    requires_segment_regeneration: Tuple[str, ...]
    requires_subgoal_repair: Tuple[str, ...]


@dataclass(frozen=True)
class RepairedSegmentRecord:
    """
    Structural placeholder for a missing or invalid segment.

    This is a tombstone type for repair output only. It MUST NOT be passed through
    MemoryGovernance.put_segment() or validate_segment_record() because:
      - steps is always empty (would fail content_empty validation)
      - created_at is a repair-time timestamp, not the original segment's timestamp

    Callers must handle RepairedSegmentRecord separately from real SegmentMemoryRecords.
    Intended use: signal to the caller that a segment needs to be fully re-generated
    via the planning pipeline, or serve as an audit record.

    state is always "pending". steps is always (). metadata always includes repaired=True.
    """
    segment_id: str
    subgoal_id: str
    parent_id: Optional[str]
    steps: Tuple[str, ...]      # always ()
    state: str                  # always "pending"
    metadata: Dict[str, Any]    # always {"repaired": True}
    created_at: str             # UTC ISO 8601 timestamp of repair time


@dataclass(frozen=True)
class RepairOutcome:
    """
    The complete result of a repair() call.

    success:                  True if the plan is clean after all repair attempts.
    repaired_plan:            The corrected PlanMemoryRecord, or None if repair failed.
    regenerated_segments:     Placeholder segments created during repair.
    repair_actions_applied:   Full audit trail of every action executed.
    errors:                   Human-readable failure reasons when success=False.
    attempts:                 Number of repair cycles executed.
    budget_used:              Number of repair actions consumed.
    """
    success: bool
    repaired_plan: Optional[PlanMemoryRecord]
    regenerated_segments: Tuple[RepairedSegmentRecord, ...]
    repair_actions_applied: Tuple[RepairAction, ...]
    errors: Tuple[str, ...]
    attempts: int
    budget_used: int
