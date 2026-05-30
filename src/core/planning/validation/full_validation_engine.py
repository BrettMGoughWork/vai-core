"""
Phase 2.5.4 — Full Validation Rules: FullValidationEngine.

Integrates all validation layers into a single, deterministic, composable
engine.  Delegates to:
  - 2.3.x structural validators (via 2.4.5 governance validation functions)
  - 2.4.5 memory governance (cross-store consistency)
  - 2.5.2 transition rules (FullTransitionRules)
  - 2.5.3 drift signals (DriftSignal, classify_drift)

No LLM calls, no inference, no side effects, no mutation.
All outputs are JSON-serialisable via dataclasses.asdict().
"""
from __future__ import annotations

from typing import List, Optional, Set

from src.core.memory.governance.governance_errors import GovernanceViolation
from src.core.memory.governance.validation import (
    validate_subgoal_record,
    validate_segment_record,
    validate_plan_record,
    validate_drift_event,
    check_segment_consistency,
    check_plan_consistency,
    check_drift_consistency,
)
from src.core.memory.subgoal_memory import SubgoalMemory
from src.core.memory.segment_memory import SegmentMemory
from src.core.memory.plan_memory import PlanMemory
from src.core.memory.drift_memory import DriftMemory
from src.core.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.memory.plan_memory_types import PlanMemoryRecord

from src.core.types.subgoal import SubgoalLifecycleState
from src.core.planning.subgoals.transition_rules import SubgoalEvent
from src.core.planning.transitions.full_transition_rules import FullTransitionRules
from src.core.planning.transitions.subgoal_table import (
    SUBGOAL_EVENT_TRANSITIONS,
    SUBGOAL_DIRECT_TRANSITIONS,
    LIFECYCLE_TERMINAL_STATES,
)
from src.core.planning.drift.drift_types import DriftClassification, DriftSignal
from src.core.planning.drift.full_drift_detector import classify_drift

from src.core.planning.validation.validation_types import (
    ValidationIssue,
    SubgoalValidationResult,
    SegmentValidationResult,
    PlanRecordValidationResult,
    MemoryValidationResult,
    SafetyValidationResult,
    TransitionValidationError,
    FullValidationResult,
)

# States in which active execution is occurring — drift/repair blocking applies here.
_ACTIVE_EXECUTION_STATES: frozenset[str] = frozenset({"running", "active"})

# Classifications that block transitions into active execution states.
_BLOCKING_CLASSIFICATIONS: frozenset[DriftClassification] = frozenset({
    DriftClassification.SEVERE_DRIFT,
    DriftClassification.CRITICAL_DRIFT,
})


def _violation_to_issue(v: GovernanceViolation, severity: str = "error") -> ValidationIssue:
    """Convert a GovernanceViolation to a ValidationIssue."""
    return ValidationIssue(
        code=v.rule,
        message=v.message,
        field=v.field,
        severity=severity,
    )


class FullValidationEngine:
    """
    Composable, deterministic validation engine for Stratum-2 records.

    All methods are pure — no state, no side effects, no LLM calls.
    Each validate_* method accepts a record (and optional context) and returns
    a structured result without mutating any input.

    Delegates to governance validation (2.4.5) for per-record checks,
    FullTransitionRules (2.5.2) for transition validation, and
    classify_drift (2.5.3) for drift-severity computation.
    """

    def __init__(self) -> None:
        self._transition_rules = FullTransitionRules()

    # ------------------------------------------------------------------
    # Stage 1 — Subgoal validation
    # ------------------------------------------------------------------

    def validate_subgoal(
        self,
        record: SubgoalMemoryRecord,
        drift_signals: Optional[List[DriftSignal]] = None,
    ) -> SubgoalValidationResult:
        """
        Validate a SubgoalMemoryRecord.

        Applies 2.4.5 governance rules (which encapsulate 2.3.x structural rules)
        and annotates the result with drift/repair context from the caller.
        """
        drift_signals = drift_signals or []

        gov_violations = validate_subgoal_record(record)
        errors: List[ValidationIssue] = [_violation_to_issue(v) for v in gov_violations]
        warnings: List[ValidationIssue] = []

        metadata_ok = not any(
            v.field in ("metadata", "context") for v in gov_violations
        )
        drift_affected = len(drift_signals) > 0
        repair_affected = bool(record.metadata.get("repair_in_progress"))

        return SubgoalValidationResult(
            valid=len(errors) == 0,
            errors=tuple(errors),
            warnings=tuple(warnings),
            state=record.state,
            metadata_ok=metadata_ok,
            drift_affected=drift_affected,
            repair_affected=repair_affected,
        )

    # ------------------------------------------------------------------
    # Stage 2 — Segment validation
    # ------------------------------------------------------------------

    def validate_segment(
        self,
        record: SegmentMemoryRecord,
        known_subgoal_ids: Optional[Set[str]] = None,
        known_segment_ids: Optional[Set[str]] = None,
        drift_signals: Optional[List[DriftSignal]] = None,
    ) -> SegmentValidationResult:
        """
        Validate a SegmentMemoryRecord.

        Cross-store checks (subgoal_ok, chain_ok) are performed only when the
        corresponding ID sets are supplied.  Missing context yields None flags.
        """
        drift_signals = drift_signals or []

        gov_violations = validate_segment_record(record)
        errors: List[ValidationIssue] = [_violation_to_issue(v) for v in gov_violations]
        warnings: List[ValidationIssue] = []

        # Cross-store: subgoal reference
        subgoal_ok: Optional[bool] = None
        if known_subgoal_ids is not None:
            cross = check_segment_consistency(record, known_subgoal_ids)
            errors.extend(_violation_to_issue(v) for v in cross)
            subgoal_ok = record.subgoal_id in known_subgoal_ids

        # Cross-store: parent chain integrity
        chain_ok: Optional[bool] = None
        if known_segment_ids is not None:
            if record.parent_id is not None and record.parent_id not in known_segment_ids:
                chain_ok = False
                errors.append(ValidationIssue(
                    code="broken_parent_chain",
                    message=(
                        f"parent_id {record.parent_id!r} not found in SegmentMemory"
                    ),
                    field="parent_id",
                    severity="error",
                ))
            else:
                chain_ok = True

        steps_ok = not any(
            v.rule in ("content_empty", "content_not_strings") for v in gov_violations
        )
        timestamp_ok = not any(v.field == "created_at" for v in gov_violations)
        drift_affected = len(drift_signals) > 0
        repair_affected = bool(record.metadata.get("repair_in_progress"))

        return SegmentValidationResult(
            valid=len(errors) == 0,
            errors=tuple(errors),
            warnings=tuple(warnings),
            segment_id=record.segment_id,
            chain_ok=chain_ok,
            subgoal_ok=subgoal_ok,
            steps_ok=steps_ok,
            timestamp_ok=timestamp_ok,
            drift_affected=drift_affected,
            repair_affected=repair_affected,
        )

    # ------------------------------------------------------------------
    # Stage 3 — Plan validation
    # ------------------------------------------------------------------

    def validate_plan(
        self,
        record: PlanMemoryRecord,
        known_subgoal_ids: Optional[Set[str]] = None,
        known_segment_ids: Optional[Set[str]] = None,
        drift_signals: Optional[List[DriftSignal]] = None,
    ) -> PlanRecordValidationResult:
        """
        Validate a PlanMemoryRecord.

        Structural check (structural_ok) verifies that segments is a list of
        strings — an empty list is allowed.  Cross-store checks (consistency_ok)
        require known ID sets to be provided.
        """
        drift_signals = drift_signals or []

        gov_violations = validate_plan_record(record)
        errors: List[ValidationIssue] = [_violation_to_issue(v) for v in gov_violations]
        warnings: List[ValidationIssue] = []

        # metadata_ok: no violations on metadata or arguments fields
        metadata_ok = not any(
            v.field in ("metadata", "arguments") for v in gov_violations
        )

        # structural_ok: segments is a list of strings (governance covers this)
        structural_ok = not any(
            v.rule in ("segments_not_list", "segments_not_strings") for v in gov_violations
        )

        # Cross-store consistency
        consistency_ok: Optional[bool] = None
        if known_subgoal_ids is not None and known_segment_ids is not None:
            cross = check_plan_consistency(record, known_subgoal_ids, known_segment_ids)
            errors.extend(_violation_to_issue(v) for v in cross)
            consistency_ok = len(cross) == 0

        drift_affected = len(drift_signals) > 0

        return PlanRecordValidationResult(
            valid=len(errors) == 0,
            errors=tuple(errors),
            warnings=tuple(warnings),
            plan_id=record.plan_id,
            metadata_ok=metadata_ok,
            structural_ok=structural_ok,
            consistency_ok=consistency_ok,
            drift_affected=drift_affected,
        )

    # ------------------------------------------------------------------
    # Stage 4 — Memory validation
    # ------------------------------------------------------------------

    def validate_memory(
        self,
        subgoal_memory: SubgoalMemory,
        segment_memory: SegmentMemory,
        plan_memory: PlanMemory,
        drift_memory: DriftMemory,
    ) -> MemoryValidationResult:
        """
        Validate all four memory stores.

        Takes snapshots of each store, validates every record individually,
        and runs cross-store referential integrity and parent chain checks.
        Equivalent to MemoryGovernance.check_consistency() but returns a
        structured result rather than raising.
        """
        subgoal_snap = subgoal_memory.snapshot()
        segment_snap = segment_memory.snapshot()
        plan_snap = plan_memory.snapshot()
        drift_snap = drift_memory.snapshot()

        known_subgoal_ids: Set[str] = {r.subgoal_id for r in subgoal_snap.records}
        known_segment_ids: Set[str] = {r.segment_id for r in segment_snap.records}

        errors: List[ValidationIssue] = []
        has_referential_error = False
        has_chain_error = False

        # Subgoal records
        for rec in subgoal_snap.records:
            for v in validate_subgoal_record(rec):
                errors.append(_violation_to_issue(v))

        # Segment records + cross-store + chain
        for rec in segment_snap.records:
            for v in validate_segment_record(rec):
                errors.append(_violation_to_issue(v))

            cross = check_segment_consistency(rec, known_subgoal_ids)
            if cross:
                has_referential_error = True
                errors.extend(_violation_to_issue(v) for v in cross)

            if rec.parent_id is not None and rec.parent_id not in known_segment_ids:
                has_chain_error = True
                errors.append(ValidationIssue(
                    code="broken_parent_chain",
                    message=(
                        f"segment {rec.segment_id!r} parent_id {rec.parent_id!r} "
                        "not found in SegmentMemory"
                    ),
                    field="parent_id",
                    severity="error",
                ))

        # Plan records + cross-store
        for rec in plan_snap.records:
            for v in validate_plan_record(rec):
                errors.append(_violation_to_issue(v))

            cross = check_plan_consistency(rec, known_subgoal_ids, known_segment_ids)
            if cross:
                has_referential_error = True
                errors.extend(_violation_to_issue(v) for v in cross)

        # Drift events + cross-store
        for evt in drift_snap.events:
            for v in validate_drift_event(evt):
                errors.append(_violation_to_issue(v))

            cross = check_drift_consistency(evt, known_subgoal_ids, known_segment_ids)
            if cross:
                has_referential_error = True
                errors.extend(_violation_to_issue(v) for v in cross)

        return MemoryValidationResult(
            valid=len(errors) == 0,
            errors=tuple(errors),
            warnings=(),
            subgoal_count=len(subgoal_snap.records),
            segment_count=len(segment_snap.records),
            plan_count=len(plan_snap.records),
            drift_count=len(drift_snap.events),
            referential_ok=not has_referential_error,
            chain_ok=not has_chain_error,
        )

    # ------------------------------------------------------------------
    # Stage 5 — Safety validation
    # ------------------------------------------------------------------

    def validate_safety(
        self,
        record: SubgoalMemoryRecord,
        drift_signals: Optional[List[DriftSignal]] = None,
    ) -> SafetyValidationResult:
        """
        Safety validation for a SubgoalMemoryRecord.

        Checks: forbidden states, lifecycle-terminal transitions, drift blocking,
        governance violations, and repair-in-progress blocking.

        Safety rules are stateless and lifecycle-focused; they do not require
        segment or plan context.
        """
        drift_signals = drift_signals or []
        errors: List[ValidationIssue] = []
        warnings: List[ValidationIssue] = []

        # ── Forbidden state ─────────────────────────────────────────────────
        forbidden_state = False
        state_valid = True
        try:
            SubgoalLifecycleState(record.state)
        except ValueError:
            forbidden_state = True
            state_valid = False
            errors.append(ValidationIssue(
                code="forbidden_state",
                message=f"State {record.state!r} is not a valid SubgoalLifecycleState",
                field="state",
                severity="error",
            ))

        # ── Forbidden transition (lifecycle-terminal) ───────────────────────
        forbidden_transition = False
        if state_valid and record.state in LIFECYCLE_TERMINAL_STATES:
            forbidden_transition = True
            warnings.append(ValidationIssue(
                code="lifecycle_terminal_state",
                message=(
                    f"State {record.state!r} is lifecycle-terminal — "
                    "no outgoing transitions of any kind are permitted"
                ),
                field="state",
                severity="warning",
            ))

        # ── Drift blocking ──────────────────────────────────────────────────
        drift_blocked = False
        classification = classify_drift(drift_signals)

        if classification in _BLOCKING_CLASSIFICATIONS:
            if state_valid and record.state in _ACTIVE_EXECUTION_STATES:
                drift_blocked = True
                errors.append(ValidationIssue(
                    code="drift_blocked",
                    message=(
                        f"State {record.state!r} is blocked: "
                        f"{classification.value} detected "
                        f"({len(drift_signals)} signal(s))"
                    ),
                    field="state",
                    severity="error",
                ))
        elif classification == DriftClassification.MODERATE_DRIFT:
            if state_valid and record.state in _ACTIVE_EXECUTION_STATES:
                warnings.append(ValidationIssue(
                    code="moderate_drift_in_active_state",
                    message=(
                        f"Moderate drift detected while in active state {record.state!r} "
                        f"({len(drift_signals)} signal(s))"
                    ),
                    field="state",
                    severity="warning",
                ))

        # ── Governance blocked ──────────────────────────────────────────────
        gov_violations = validate_subgoal_record(record)
        governance_blocked = len(gov_violations) > 0
        if governance_blocked:
            for v in gov_violations:
                errors.append(ValidationIssue(
                    code=f"governance_{v.rule}",
                    message=v.message,
                    field=v.field,
                    severity="error",
                ))

        # ── Repair blocked ──────────────────────────────────────────────────
        repair_blocked = False
        if record.metadata.get("repair_in_progress") and state_valid:
            if record.state in _ACTIVE_EXECUTION_STATES:
                repair_blocked = True
                warnings.append(ValidationIssue(
                    code="repair_blocked",
                    message=(
                        f"State {record.state!r} is potentially blocked: "
                        "repair_in_progress is set in metadata"
                    ),
                    field="state",
                    severity="warning",
                ))

        return SafetyValidationResult(
            valid=len(errors) == 0,
            errors=tuple(errors),
            warnings=tuple(warnings),
            forbidden_transition=forbidden_transition,
            forbidden_state=forbidden_state,
            drift_blocked=drift_blocked,
            governance_blocked=governance_blocked,
            repair_blocked=repair_blocked,
        )

    # ------------------------------------------------------------------
    # Transition validation (pre + post)
    # ------------------------------------------------------------------

    def validate_transition_before(
        self,
        current_state: SubgoalLifecycleState,
        event: SubgoalEvent,
        drift_signals: Optional[List[DriftSignal]] = None,
    ) -> Optional[TransitionValidationError]:
        """
        Validate a transition BEFORE applying it.

        Returns None if the transition is permitted.
        Returns a TransitionValidationError if:
          - FullTransitionRules rejects the (state, event) pair, or
          - SEVERE/CRITICAL drift would block the resulting state.
        """
        drift_signals = drift_signals or []

        result = self._transition_rules.apply_subgoal_transition(current_state, event)
        if not result.success:
            return TransitionValidationError(
                from_state=current_state.value,
                event=event.value,
                reason=result.error.reason,
                stage="pre",
            )

        # Drift-blocking: if the target state is an active execution state
        # and drift is severe, block the transition.
        classification = classify_drift(drift_signals)
        if (
            classification in _BLOCKING_CLASSIFICATIONS
            and result.to_state in _ACTIVE_EXECUTION_STATES
        ):
            return TransitionValidationError(
                from_state=current_state.value,
                event=event.value,
                reason=(
                    f"Transition to {result.to_state!r} blocked by "
                    f"{classification.value} ({len(drift_signals)} signal(s))"
                ),
                stage="pre",
            )

        return None

    def validate_transition_after(
        self,
        old_state: str,
        new_state: str,
    ) -> Optional[TransitionValidationError]:
        """
        Validate a transition AFTER it has been applied.

        Checks that new_state is reachable from old_state via any mechanism
        (event-driven or direct).  A same-state write is always permitted.

        Returns None if the post-transition state is valid.
        Returns a TransitionValidationError if the resulting state is unreachable.
        """
        # Same-state: always permitted (no-op write)
        if old_state == new_state:
            return None

        # Event-driven reachability
        event_reachable = any(
            to == new_state
            for (from_s, _), to in SUBGOAL_EVENT_TRANSITIONS.items()
            if from_s == old_state
        )

        # Direct reachability
        direct_reachable = new_state in SUBGOAL_DIRECT_TRANSITIONS.get(old_state, frozenset())

        if event_reachable or direct_reachable:
            return None

        return TransitionValidationError(
            from_state=old_state,
            event="[post-transition]",
            reason=(
                f"State {new_state!r} is not reachable from {old_state!r} "
                "via any event-driven or direct transition"
            ),
            stage="post",
        )

    # ------------------------------------------------------------------
    # Composable pipeline
    # ------------------------------------------------------------------

    def validate_pipeline(
        self,
        subgoal_record: Optional[SubgoalMemoryRecord] = None,
        segment_record: Optional[SegmentMemoryRecord] = None,
        plan_record: Optional[PlanMemoryRecord] = None,
        subgoal_memory: Optional[SubgoalMemory] = None,
        segment_memory: Optional[SegmentMemory] = None,
        plan_memory: Optional[PlanMemory] = None,
        drift_memory: Optional[DriftMemory] = None,
        drift_signals: Optional[List[DriftSignal]] = None,
    ) -> FullValidationResult:
        """
        Run all validation stages in order:
          subgoal → segment → plan → memory → safety → final

        Each stage is skipped (result=None) when its required input is absent.
        Memory stage requires all four stores.
        Safety stage requires a subgoal_record.

        Errors and warnings from completed stages are aggregated at the top level.
        No stage mutates any input.  No LLM calls.
        """
        drift_signals = drift_signals or []
        all_errors: List[ValidationIssue] = []
        all_warnings: List[ValidationIssue] = []

        # Pre-compute known ID sets from memory stores (one snapshot per store).
        known_subgoal_ids: Optional[Set[str]] = None
        known_segment_ids: Optional[Set[str]] = None
        if subgoal_memory is not None:
            known_subgoal_ids = {
                r.subgoal_id for r in subgoal_memory.snapshot().records
            }
        if segment_memory is not None:
            known_segment_ids = {
                r.segment_id for r in segment_memory.snapshot().records
            }

        # ── Stage 1: Subgoal ────────────────────────────────────────────────
        subgoal_result: Optional[SubgoalValidationResult] = None
        if subgoal_record is not None:
            subgoal_result = self.validate_subgoal(subgoal_record, drift_signals)
            all_errors.extend(subgoal_result.errors)
            all_warnings.extend(subgoal_result.warnings)

        # ── Stage 2: Segment ────────────────────────────────────────────────
        segment_result: Optional[SegmentValidationResult] = None
        if segment_record is not None:
            segment_result = self.validate_segment(
                segment_record,
                known_subgoal_ids=known_subgoal_ids,
                known_segment_ids=known_segment_ids,
                drift_signals=drift_signals,
            )
            all_errors.extend(segment_result.errors)
            all_warnings.extend(segment_result.warnings)

        # ── Stage 3: Plan ───────────────────────────────────────────────────
        plan_result: Optional[PlanRecordValidationResult] = None
        if plan_record is not None:
            plan_result = self.validate_plan(
                plan_record,
                known_subgoal_ids=known_subgoal_ids,
                known_segment_ids=known_segment_ids,
                drift_signals=drift_signals,
            )
            all_errors.extend(plan_result.errors)
            all_warnings.extend(plan_result.warnings)

        # ── Stage 4: Memory ─────────────────────────────────────────────────
        memory_result: Optional[MemoryValidationResult] = None
        if all(
            m is not None
            for m in (subgoal_memory, segment_memory, plan_memory, drift_memory)
        ):
            memory_result = self.validate_memory(
                subgoal_memory, segment_memory, plan_memory, drift_memory  # type: ignore[arg-type]
            )
            all_errors.extend(memory_result.errors)
            all_warnings.extend(memory_result.warnings)

        # ── Stage 5: Safety ─────────────────────────────────────────────────
        safety_result: Optional[SafetyValidationResult] = None
        if subgoal_record is not None:
            safety_result = self.validate_safety(subgoal_record, drift_signals)
            all_errors.extend(safety_result.errors)
            all_warnings.extend(safety_result.warnings)

        return FullValidationResult(
            valid=len(all_errors) == 0,
            errors=tuple(all_errors),
            warnings=tuple(all_warnings),
            subgoal=subgoal_result,
            segment=segment_result,
            plan=plan_result,
            memory=memory_result,
            safety=safety_result,
        )
