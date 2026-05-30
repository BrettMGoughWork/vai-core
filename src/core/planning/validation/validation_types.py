"""
Phase 2.5.4 — Full Validation Rules: result types.

All types are frozen dataclasses — pure, deterministic, JSON-serialisable
via dataclasses.asdict().  No inference, no side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class ValidationIssue:
    """
    A single validation finding.

    code:     machine-readable identifier (e.g. "subgoal_id_required").
    message:  human-readable description.
    field:    offending field name, or None if not field-specific.
    severity: "error" (blocks valid=True) | "warning" (informational only).
    """
    code: str
    message: str
    field: Optional[str]
    severity: str  # "error" | "warning"


# ---------------------------------------------------------------------------
# Per-record validation results
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SubgoalValidationResult:
    """
    Outcome of validating a single SubgoalMemoryRecord.

    state:           the record's state string at validation time.
    metadata_ok:     True if metadata and context fields are JSON-pure.
    drift_affected:  True if caller-supplied drift signals are non-empty.
    repair_affected: True if metadata["repair_in_progress"] is set.
    """
    valid: bool
    errors: Tuple[ValidationIssue, ...]
    warnings: Tuple[ValidationIssue, ...]
    state: str
    metadata_ok: bool
    drift_affected: bool
    repair_affected: bool


@dataclass(frozen=True)
class SegmentValidationResult:
    """
    Outcome of validating a single SegmentMemoryRecord.

    segment_id:      the record's segment_id at validation time.
    chain_ok:        True if parent_id is resolvable; None if context not provided.
    subgoal_ok:      True if subgoal_id is known; None if context not provided.
    steps_ok:        True if content is a non-empty list of strings.
    timestamp_ok:    True if created_at is a valid ISO 8601 string.
    drift_affected:  True if caller-supplied drift signals are non-empty.
    repair_affected: True if metadata["repair_in_progress"] is set.
    """
    valid: bool
    errors: Tuple[ValidationIssue, ...]
    warnings: Tuple[ValidationIssue, ...]
    segment_id: str
    chain_ok: Optional[bool]
    subgoal_ok: Optional[bool]
    steps_ok: bool
    timestamp_ok: bool
    drift_affected: bool
    repair_affected: bool


@dataclass(frozen=True)
class PlanRecordValidationResult:
    """
    Outcome of validating a single PlanMemoryRecord.

    Named PlanRecordValidationResult to distinguish from the pre-execution
    PlanValidationResult in src/core/planning/validators/plan_validation.py,
    which validates a Plan dict before execution.

    plan_id:        the record's plan_id at validation time.
    metadata_ok:    True if metadata and arguments fields are JSON-pure.
    structural_ok:  True if segments is a list of strings (may be empty).
    consistency_ok: True if all cross-store references resolved; None if context not provided.
    drift_affected: True if caller-supplied drift signals are non-empty.
    """
    valid: bool
    errors: Tuple[ValidationIssue, ...]
    warnings: Tuple[ValidationIssue, ...]
    plan_id: str
    metadata_ok: bool
    structural_ok: bool
    consistency_ok: Optional[bool]
    drift_affected: bool


@dataclass(frozen=True)
class MemoryValidationResult:
    """
    Outcome of validating all four memory stores.

    *_count:        number of records in each store.
    referential_ok: True if all cross-store ID references resolved.
    chain_ok:       True if all segment parent_id chains resolved.
    """
    valid: bool
    errors: Tuple[ValidationIssue, ...]
    warnings: Tuple[ValidationIssue, ...]
    subgoal_count: int
    segment_count: int
    plan_count: int
    drift_count: int
    referential_ok: bool
    chain_ok: bool


@dataclass(frozen=True)
class SafetyValidationResult:
    """
    Outcome of safety validation for a SubgoalMemoryRecord.

    forbidden_state:      True if the state value is not a valid SubgoalLifecycleState.
    forbidden_transition: True if the current state is lifecycle-terminal (no exits).
    drift_blocked:        True if SEVERE/CRITICAL drift signals block an active state.
    governance_blocked:   True if governance validation found violations.
    repair_blocked:       True if repair_in_progress metadata blocks an active state.
    """
    valid: bool
    errors: Tuple[ValidationIssue, ...]
    warnings: Tuple[ValidationIssue, ...]
    forbidden_transition: bool
    forbidden_state: bool
    drift_blocked: bool
    governance_blocked: bool
    repair_blocked: bool


# ---------------------------------------------------------------------------
# Transition validation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TransitionValidationError:
    """
    Structured error produced when a transition fails validation.

    from_state: state value at validation time.
    event:      event value (or "[direct]" / "[post-transition]").
    reason:     human-readable explanation.
    stage:      "pre" (before applying) | "post" (after applying).
    allowed:    always False; included for JSON parity with TransitionError.
    """
    from_state: str
    event: str
    reason: str
    stage: str
    allowed: bool = False


# ---------------------------------------------------------------------------
# Composable pipeline result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FullValidationResult:
    """
    Aggregated output of the full validation pipeline.

    errors and warnings are aggregated from all completed stages.
    Sub-result fields are None when the corresponding stage was skipped
    (no input record or memory store was provided for that stage).
    """
    valid: bool
    errors: Tuple[ValidationIssue, ...]
    warnings: Tuple[ValidationIssue, ...]
    subgoal: Optional[SubgoalValidationResult]
    segment: Optional[SegmentValidationResult]
    plan: Optional[PlanRecordValidationResult]
    memory: Optional[MemoryValidationResult]
    safety: Optional[SafetyValidationResult]
