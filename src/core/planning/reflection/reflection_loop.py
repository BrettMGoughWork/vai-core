"""
Phase 2.5.5 — Reflection Loop: ReflectionLoop class.

Orchestrates one reflection cycle:
  1. Snapshot memory stores
  2. Detect drift (scoped to focus subgoal)
  3. Write confirmed drift to DriftMemory
  4. Evaluate progress
  5. Validate focus subgoal
  6. Apply structural subgoal transitions (BLOCK / UNBLOCK / RETRY)
  7. Run plan repair
  8. Persist repaired plan through governance
  9. Produce ReflectionTrace and ReflectionOutcome

All operations are deterministic and rule-based.
No LLM calls, no inference, no side effects outside governed memory writes.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.memory.governance.memory_governance import MemoryGovernance
from src.core.memory.governance.governance_errors import MemoryGovernanceError
from src.core.memory.repair.plan_repair import PlanRepair
from src.core.memory.repair.repair_types import RepairOutcome
from src.core.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.planning.models.plan import Plan
from src.core.planning.drift.drift_context import DriftContext
from src.core.planning.drift.drift_types import DriftClassification, DriftConfirmation
from src.core.planning.drift.full_drift_detector import FullDriftDetector, classify_drift
from src.core.planning.transitions.full_transition_rules import FullTransitionRules
from src.core.planning.subgoals.transition_rules import SubgoalEvent
from src.core.planning.validation.full_validation_engine import FullValidationEngine
from src.core.planning.validation.validation_types import FullValidationResult
from src.core.types.subgoal import Subgoal, SubgoalLifecycleState

from src.core.planning.reflection.progress_evaluator import evaluate_progress
from src.core.planning.reflection.reflection_types import (
    MemoryUpdateRecord,
    PlanAdjustment,
    ProgressReport,
    ReflectionDriftReport,
    ReflectionOutcome,
    ReflectionState,
    ReflectionTrace,
    TransitionRecord,
)


# Classifications that trigger BLOCK on RUNNING subgoals.
_BLOCKING_CLASSIFICATIONS: frozenset[str] = frozenset({
    DriftClassification.SEVERE_DRIFT.value,
    DriftClassification.CRITICAL_DRIFT.value,
})

# Classifications that allow UNBLOCK on BLOCKED subgoals (drift has cleared).
_CLEAR_CLASSIFICATIONS: frozenset[str] = frozenset({
    DriftClassification.NO_DRIFT.value,
    DriftClassification.MINOR_DRIFT.value,
})


def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _record_to_dict(record: Any) -> Dict[str, Any]:
    """Convert a frozen dataclass to a plain dict (JSON-safe scalars only)."""
    try:
        return asdict(record)
    except TypeError:
        return {"repr": str(record)}


def _build_trace(
    cycle: int,
    timestamp: str,
    progress: ProgressReport,
    drift_report: ReflectionDriftReport,
    repair_outcome: Optional[RepairOutcome],
    plan_adjustment: Optional[PlanAdjustment],
    transition_records: List[TransitionRecord],
    memory_updates: List[MemoryUpdateRecord],
) -> ReflectionTrace:
    progress_dict: Dict[str, Any] = {
        "subgoals_complete": progress.subgoals_complete,
        "subgoals_total": progress.subgoals_total,
        "segments_complete": progress.segments_complete,
        "segments_total": progress.segments_total,
        "stalled": progress.stalled,
        "stalled_reasons": list(progress.stalled_reasons),
        "progress_rate": progress.progress_rate,
    }

    drift_dict: Dict[str, Any] = {
        "confirmed": drift_report.confirmation.confirmed,
        "classification": drift_report.classification,
        "confidence": drift_report.confidence,
        "cycles_observed": drift_report.confirmation.cycles_observed,
        "drift_written_to_memory": drift_report.drift_written_to_memory,
        "drift_violations": list(drift_report.drift_violations),
        "trigger": _record_to_dict(drift_report.trigger) if drift_report.trigger else None,
    }

    repairs: list[Dict[str, Any]] = []
    if repair_outcome is not None:
        repairs.append({
            "success": repair_outcome.success,
            "attempts": repair_outcome.attempts,
            "budget_used": repair_outcome.budget_used,
            "actions": [
                {"action_type": a.action_type, "target_id": a.target_id}
                for a in repair_outcome.repair_actions_applied
            ],
            "regenerated_count": len(repair_outcome.regenerated_segments),
            "errors": list(repair_outcome.errors),
        })

    adjustments: list[Dict[str, Any]] = []
    if plan_adjustment is not None:
        adjustments.append({
            "plan_id": plan_adjustment.plan_id,
            "repair_succeeded": plan_adjustment.repair_succeeded,
            "persisted": plan_adjustment.persisted,
            "actions_applied": list(plan_adjustment.actions_applied),
            "segments_regenerated": plan_adjustment.segments_regenerated,
            "requires_segment_regen": plan_adjustment.requires_segment_regen,
            "error": plan_adjustment.error,
        })

    transitions_list: list[Dict[str, Any]] = [
        {
            "subgoal_id": t.subgoal_id,
            "from_state": t.from_state,
            "event": t.event,
            "to_state": t.to_state,
            "success": t.success,
            "reason": t.reason,
        }
        for t in transition_records
    ]

    updates_list: list[Dict[str, Any]] = [
        {
            "store": u.store,
            "operation": u.operation,
            "record_id": u.record_id,
            "details": u.details,
        }
        for u in memory_updates
    ]

    return ReflectionTrace(
        cycle=cycle,
        timestamp=timestamp,
        progress=progress_dict,
        drift=drift_dict,
        repairs=tuple(repairs),
        adjustments=tuple(adjustments),
        transitions=tuple(transitions_list),
        memory_updates=tuple(updates_list),
    )


class ReflectionLoop:
    """
    Orchestrates one deterministic reflection cycle per call.

    Each distinct subgoal_id gets its own FullDriftDetector instance so that
    the confirmation buffer is never shared across subgoals.  The map is keyed
    by subgoal_id and grows lazily.

    All heavy-lifting delegates to:
      - FullDriftDetector   (2.5.3)
      - FullValidationEngine (2.5.4)
      - FullTransitionRules  (2.5.2)
      - PlanRepair           (2.5.1)
      - MemoryGovernance     (2.4.5)
    """

    def __init__(
        self,
        confirmation_cycles: int = 2,
        cooldown_cycles: int = 3,
        repair_budget: int = 10,
        repair_retry_limit: int = 3,
        stall_repair_threshold: int = 3,
    ) -> None:
        self._confirmation_cycles = confirmation_cycles
        self._cooldown_cycles = cooldown_cycles
        self._repair_budget = repair_budget
        self._repair_retry_limit = repair_retry_limit
        self._stall_repair_threshold = stall_repair_threshold

        # Per-subgoal drift detectors (stateful — each holds a ConfirmationBuffer).
        self._detectors: Dict[str, FullDriftDetector] = {}

        self._transition_rules = FullTransitionRules()
        self._validation_engine = FullValidationEngine()
        self._plan_repair = PlanRepair()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_reflection_cycle(self, state: ReflectionState) -> ReflectionOutcome:
        """
        Execute one reflection cycle for the subgoal identified in state.

        Returns a ReflectionOutcome containing the full audit trace.
        Errors that don't prevent completion are collected in outcome.errors.
        """
        now_ms = state.timestamp
        now_iso = _ms_to_iso(now_ms)

        errors: List[str] = []
        transition_records: List[TransitionRecord] = []
        memory_updates: List[MemoryUpdateRecord] = []
        repair_outcome: Optional[RepairOutcome] = None

        # --- 1. Snapshot memory stores ---
        subgoal_snap = state.subgoal_memory.snapshot()
        segment_snap = state.segment_memory.snapshot()

        # Build lookup maps (snapshots use tuples, not dicts).
        all_subgoal_records: Dict[str, SubgoalMemoryRecord] = {
            r.subgoal_id: r for r in subgoal_snap.records
        }
        all_segment_records: Dict[str, SegmentMemoryRecord] = {
            s.segment_id: s for s in segment_snap.records
        }

        # --- 2. Focus objects ---
        focus_record = all_subgoal_records.get(state.subgoal_id)
        focus_subgoal: Optional[Subgoal] = state.subgoal_memory.get(state.subgoal_id)

        # Segments belonging to the focus subgoal only (scoped for drift).
        focus_segment_records: Dict[str, SegmentMemoryRecord] = {
            sid: rec for sid, rec in all_segment_records.items()
            if rec.subgoal_id == state.subgoal_id
        }

        # Plan records scoped to the focus plan only.
        focus_plan_records = {}
        if state.plan_id:
            plan_rec = state.plan_memory.get_record(state.plan_id)
            if plan_rec is not None:
                focus_plan_records[state.plan_id] = plan_rec

        # --- 3. Get or create per-subgoal drift detector ---
        if state.subgoal_id not in self._detectors:
            self._detectors[state.subgoal_id] = FullDriftDetector(
                confirmation_cycles=self._confirmation_cycles,
                cooldown_cycles=self._cooldown_cycles,
            )
        detector = self._detectors[state.subgoal_id]

        # --- 4. Build DriftContext (scoped to focus subgoal) ---
        ctx = DriftContext(
            timestamp=now_ms,
            subgoal_id=state.subgoal_id,
            segment_ids=list(focus_segment_records.keys()),
            plan_id=state.plan_id,
            subgoal_records={state.subgoal_id: focus_record} if focus_record else {},
            segment_records=focus_segment_records,
            plan_records=focus_plan_records,
            governance_violations=[],
            transition_failures=list(state.transition_failures),
            repair_attempts=state.repair_attempts,
            fallback_count=state.fallback_count,
            drift_memory=state.drift_memory,
        )

        # --- 5. Drift detection (multi-cycle) ---
        confirmation: DriftConfirmation = detector.detect(ctx)

        # --- 6. Write confirmed drift to memory ---
        drift_written = False
        drift_violations: List[str] = []
        if confirmation.confirmed:
            viols = detector.write_to_memory(confirmation, ctx, state.drift_memory)
            if viols:
                drift_violations = [v.message for v in viols]
                memory_updates.append(MemoryUpdateRecord(
                    store="drift",
                    operation="reject",
                    record_id=state.subgoal_id,
                    details={"violations": drift_violations},
                ))
            else:
                drift_written = True
                memory_updates.append(MemoryUpdateRecord(
                    store="drift",
                    operation="write",
                    record_id=state.subgoal_id,
                    details={
                        "cycles_observed": confirmation.cycles_observed,
                        "signal_count": len(confirmation.signals),
                    },
                ))

        # --- 7. Compute drift classification ---
        classification_str = classify_drift(list(confirmation.signals)).value
        trigger = detector.get_trigger(confirmation, ctx)

        drift_report = ReflectionDriftReport(
            confirmation=confirmation,
            classification=classification_str,
            confidence=confirmation.confidence,
            trigger=trigger,
            drift_written_to_memory=drift_written,
            drift_violations=tuple(drift_violations),
        )

        # --- 8. Progress evaluation (uses pre-write snapshot — documented in outcome) ---
        progress = evaluate_progress(
            subgoal_snap=subgoal_snap,
            segment_snap=segment_snap,
            drift_report=drift_report,
            repair_attempts=state.repair_attempts,
            stall_repair_threshold=self._stall_repair_threshold,
            prior_progress=state.prior_progress,
        )

        # --- 9. Validate focus subgoal ---
        validation_result: Optional[FullValidationResult] = None
        if focus_record is not None:
            validation_result = self._validation_engine.validate_pipeline(
                subgoal_record=focus_record,
                drift_signals=list(confirmation.signals),
            )

        # --- 10. Governance instance for writes ---
        governance = MemoryGovernance(
            state.subgoal_memory,
            state.segment_memory,
            state.plan_memory,
            state.drift_memory,
        )

        # --- 11. Structural subgoal transitions ---
        if focus_subgoal is not None and focus_record is not None:
            focus_state = SubgoalLifecycleState(focus_record.state)

            # BLOCK: RUNNING → BLOCKED when severe/critical drift confirmed.
            if (
                focus_state == SubgoalLifecycleState.RUNNING
                and confirmation.confirmed
                and classification_str in _BLOCKING_CLASSIFICATIONS
            ):
                self._apply_subgoal_transition(
                    subgoal=focus_subgoal,
                    event=SubgoalEvent.BLOCK,
                    to_state=SubgoalLifecycleState.BLOCKED,
                    governance=governance,
                    subgoal_memory=state.subgoal_memory,
                    transition_records=transition_records,
                    memory_updates=memory_updates,
                    errors=errors,
                    reason="Severe drift confirmed — blocking subgoal",
                )

            # UNBLOCK: BLOCKED → READY when drift has cleared (not confirmed, low classification).
            elif (
                focus_state == SubgoalLifecycleState.BLOCKED
                and not confirmation.confirmed
                and classification_str in _CLEAR_CLASSIFICATIONS
            ):
                self._apply_subgoal_transition(
                    subgoal=focus_subgoal,
                    event=SubgoalEvent.UNBLOCK,
                    to_state=SubgoalLifecycleState.READY,
                    governance=governance,
                    subgoal_memory=state.subgoal_memory,
                    transition_records=transition_records,
                    memory_updates=memory_updates,
                    errors=errors,
                    reason="Drift cleared — unblocking subgoal",
                )

        # --- 12. Plan repair ---
        plan_adjustment: Optional[PlanAdjustment] = None
        if state.plan_id:
            plan_record = state.plan_memory.get_record(state.plan_id)
            if plan_record is not None:
                # Pass all subgoals for full breakage detection.
                subgoals_by_id: Dict[str, SubgoalMemoryRecord] = dict(all_subgoal_records)

                drift_events = state.drift_memory.filter_by_subgoal(state.subgoal_id)

                repair_outcome = self._plan_repair.repair(
                    plan_record=plan_record,
                    real_segments_by_id=dict(all_segment_records),
                    subgoals_by_id=subgoals_by_id,
                    drift_events=drift_events,
                    now=now_ms,
                    repair_budget=self._repair_budget,
                    retry_limit=self._repair_retry_limit,
                )

                # Only persist if no placeholder segments — governance rejects empty content.
                has_placeholders = len(repair_outcome.regenerated_segments) > 0
                persisted = False
                persist_error: Optional[str] = None

                if repair_outcome.success and repair_outcome.repaired_plan and not has_placeholders:
                    repaired = repair_outcome.repaired_plan
                    plan_obj = Plan(
                        intent=repaired.intent,
                        targetskillid=repaired.targetskillid,
                        arguments=dict(repaired.arguments),
                        reasoning_summary=repaired.reasoning_summary,
                    )
                    try:
                        governance.put_plan(
                            plan=plan_obj,
                            plan_id=repaired.plan_id,
                            subgoal_id=repaired.subgoal_id,
                            segments=list(repaired.segments),
                            created_at=repaired.created_at,
                            metadata=dict(repaired.metadata),
                        )
                        persisted = True
                        memory_updates.append(MemoryUpdateRecord(
                            store="plan",
                            operation="write",
                            record_id=repaired.plan_id,
                            details={
                                "actions_applied": len(repair_outcome.repair_actions_applied),
                            },
                        ))

                        # RETRY: FAILED → RETRYING after successful plan repair.
                        refreshed = state.subgoal_memory.get(state.subgoal_id)
                        refreshed_record = state.subgoal_memory.get_record(state.subgoal_id)
                        if (
                            refreshed is not None
                            and refreshed_record is not None
                            and SubgoalLifecycleState(refreshed_record.state) == SubgoalLifecycleState.FAILED
                        ):
                            self._apply_subgoal_transition(
                                subgoal=refreshed,
                                event=SubgoalEvent.RETRY,
                                to_state=SubgoalLifecycleState.RETRYING,
                                governance=governance,
                                subgoal_memory=state.subgoal_memory,
                                transition_records=transition_records,
                                memory_updates=memory_updates,
                                errors=errors,
                                reason="Plan repaired — scheduling retry",
                            )

                    except MemoryGovernanceError as exc:
                        persist_error = f"Plan write failed: {exc}"
                        errors.append(persist_error)
                        memory_updates.append(MemoryUpdateRecord(
                            store="plan",
                            operation="reject",
                            record_id=state.plan_id,
                            details={"error": persist_error},
                        ))

                plan_adjustment = PlanAdjustment(
                    plan_id=state.plan_id,
                    repair_succeeded=repair_outcome.success,
                    persisted=persisted,
                    actions_applied=tuple(
                        a.action_type for a in repair_outcome.repair_actions_applied
                    ),
                    segments_regenerated=len(repair_outcome.regenerated_segments),
                    requires_segment_regen=has_placeholders,
                    error=persist_error or (
                        repair_outcome.errors[0] if repair_outcome.errors else None
                    ),
                )

        # --- 13. Produce trace and outcome ---
        trace = _build_trace(
            cycle=state.cycle,
            timestamp=now_iso,
            progress=progress,
            drift_report=drift_report,
            repair_outcome=repair_outcome,
            plan_adjustment=plan_adjustment,
            transition_records=transition_records,
            memory_updates=memory_updates,
        )

        return ReflectionOutcome(
            cycle=state.cycle,
            timestamp=now_iso,
            progress=progress,
            drift_report=drift_report,
            validation_result=validation_result,
            plan_adjustment=plan_adjustment,
            transitions_applied=tuple(transition_records),
            memory_updates=tuple(memory_updates),
            trace=trace,
            errors=tuple(errors),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_subgoal_transition(
        self,
        subgoal: Subgoal,
        event: SubgoalEvent,
        to_state: SubgoalLifecycleState,
        governance: MemoryGovernance,
        subgoal_memory,
        transition_records: List[TransitionRecord],
        memory_updates: List[MemoryUpdateRecord],
        errors: List[str],
        reason: str,
    ) -> None:
        """
        Attempt an event-driven transition, write the result through governance,
        and record both the transition audit and the memory update.
        """
        from_state = subgoal.state
        result = self._transition_rules.apply_subgoal_transition(from_state, event)

        if result.success:
            updated = subgoal.with_state(to_state)
            try:
                governance.put_subgoal(updated)
                transition_records.append(TransitionRecord(
                    subgoal_id=subgoal.subgoal_id,
                    from_state=from_state.value,
                    event=event.value,
                    to_state=to_state.value,
                    success=True,
                    reason=reason,
                ))
                memory_updates.append(MemoryUpdateRecord(
                    store="subgoal",
                    operation="write",
                    record_id=subgoal.subgoal_id,
                    details={
                        "from_state": from_state.value,
                        "to_state": to_state.value,
                        "event": event.value,
                    },
                ))
            except MemoryGovernanceError as exc:
                err = f"Subgoal write failed for {event.value} transition: {exc}"
                errors.append(err)
                transition_records.append(TransitionRecord(
                    subgoal_id=subgoal.subgoal_id,
                    from_state=from_state.value,
                    event=event.value,
                    to_state=None,
                    success=False,
                    reason=err,
                ))
                memory_updates.append(MemoryUpdateRecord(
                    store="subgoal",
                    operation="reject",
                    record_id=subgoal.subgoal_id,
                    details={"error": err, "event": event.value},
                ))
        else:
            # Transition rules rejected it — record but do not raise.
            rejection_reason = result.error.reason if result.error else "transition rejected"
            transition_records.append(TransitionRecord(
                subgoal_id=subgoal.subgoal_id,
                from_state=from_state.value,
                event=event.value,
                to_state=None,
                success=False,
                reason=rejection_reason,
            ))
