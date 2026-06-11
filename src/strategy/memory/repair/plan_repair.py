from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from src.strategy.types.hashing import stable_hash
from src.strategy.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.strategy.memory.segment_memory_types import SegmentMemoryRecord
from src.strategy.memory.plan_memory_types import PlanMemoryRecord
from src.strategy.memory.drift_memory_types import DriftEvent
from src.strategy.memory.governance.validation import (
    validate_plan_record,
    validate_segment_record,
)
from src.strategy.memory.governance.normalisation import try_normalise_iso_timestamp
from src.strategy.memory.governance.governance_errors import GovernanceViolation
from src.strategy.memory.repair.repair_types import (
    BreakageError,
    BreakageWarning,
    InvalidLink,
    DriftFlag,
    TimestampIssue,
    PlanBreakageReport,
    RepairAction,
    RepairPlan,
    RepairedSegmentRecord,
    RepairOutcome,
    RepairStrategyContext,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ms_to_iso(now_ms: int) -> str:
    """Convert a millisecond timestamp to a timezone-aware UTC ISO 8601 string."""
    return datetime.fromtimestamp(now_ms / 1000.0, tz=timezone.utc).isoformat()


def _breakage_fingerprint(report: PlanBreakageReport) -> str:
    """
    Deterministic hash of the actionable breakage state.

    Used to detect circular repair loops — if the same fingerprint appears twice,
    the repair is not making progress.
    """
    return stable_hash({
        "errors": sorted([[e.error_type, e.record_id] for e in report.errors]),
        "missing": sorted(list(report.missing_segments)),
        "links": sorted([[l.from_id, l.to_id, l.link_type] for l in report.invalid_links]),
        "gov": sorted([[v.rule, str(v.record_id)] for v in report.governance_violations]),
    })


def _updated_plan(plan: PlanMemoryRecord, **kwargs) -> PlanMemoryRecord:
    """Return a new PlanMemoryRecord with specific fields replaced."""
    return PlanMemoryRecord(
        plan_id=kwargs.get("plan_id", plan.plan_id),
        subgoal_id=kwargs.get("subgoal_id", plan.subgoal_id),
        segments=kwargs.get("segments", plan.segments),
        created_at=kwargs.get("created_at", plan.created_at),
        metadata=kwargs.get("metadata", plan.metadata),
        intent=plan.intent,
        targetskillid=plan.targetskillid,
        arguments=plan.arguments,
        reasoning_summary=plan.reasoning_summary,
    )


def _updated_segment(seg: SegmentMemoryRecord, **kwargs) -> SegmentMemoryRecord:
    """Return a new SegmentMemoryRecord with specific fields replaced."""
    return SegmentMemoryRecord(
        segment_id=kwargs.get("segment_id", seg.segment_id),
        parent_id=kwargs.get("parent_id", seg.parent_id),
        subgoal_id=kwargs.get("subgoal_id", seg.subgoal_id),
        state=kwargs.get("state", seg.state),
        content=kwargs.get("content", seg.content),
        created_at=kwargs.get("created_at", seg.created_at),
        context=kwargs.get("context", seg.context),
        metadata=kwargs.get("metadata", seg.metadata),
        skills=kwargs.get("skills", seg.skills),
        last_output=kwargs.get("last_output", seg.last_output),
        previous_output=kwargs.get("previous_output", seg.previous_output),
        behavioural_delta=kwargs.get("behavioural_delta", seg.behavioural_delta),
        behavioural_signals=kwargs.get("behavioural_signals", seg.behavioural_signals),
        error=kwargs.get("error", seg.error),
    )


# ---------------------------------------------------------------------------
# PlanRepair
# ---------------------------------------------------------------------------

class PlanRepair:
    """
    Pure, deterministic, rule-based plan repair for the Stratum-2 runtime.

    All methods are pure functions: they accept data, return structured results,
    and never write to memory stores. Callers apply the outcomes.

    No LLM calls. No semantic inference. No content generation.
    All repairs are structural, auditable, and reversible.

    When a SemanticMemoryIndex is provided (PHASE 2.16.4), the repair engine
    consults semantic memory to enrich repair outcomes with strategy context
    derived from historically successful and failed repair patterns.
    """

    def __init__(
        self,
        memory_index: Optional[Any] = None,
    ) -> None:
        self._memory_index = memory_index  # SemanticMemoryIndex or None

    # ------------------------------------------------------------------
    # 1. Detection
    # ------------------------------------------------------------------

    def detect_breakages(
        self,
        plan_record: PlanMemoryRecord,
        real_segments_by_id: Dict[str, SegmentMemoryRecord],
        regenerated_ids: Set[str],
        subgoals_by_id: Dict[str, SubgoalMemoryRecord],
        drift_events: List[DriftEvent],
        now: int,
    ) -> PlanBreakageReport:
        """
        Detect all structural breakages in a plan and its segments.

        real_segments_by_id: actual SegmentMemoryRecords found for this plan's segment_ids.
        regenerated_ids:     segment_ids already handled by a prior repair cycle
                             (placeholders); these are not re-flagged as missing.
        subgoals_by_id:      all subgoals in SubgoalMemory.
        drift_events:        all drift events (filtered to relevant ones internally).
        now:                 current ms timestamp (for logging / report provenance only).
        """
        plan_id = plan_record.plan_id
        plan_segment_ids = set(plan_record.segments)

        errors: List[BreakageError] = []
        warnings: List[BreakageWarning] = []
        missing_segments: List[str] = []
        invalid_links: List[InvalidLink] = []
        drift_flags: List[DriftFlag] = []
        timestamp_issues: List[TimestampIssue] = []
        gov_violations: List[GovernanceViolation] = []

        # 1. Missing subgoal
        if plan_record.subgoal_id not in subgoals_by_id:
            errors.append(BreakageError(
                error_type="MISSING_SUBGOAL",
                record_id=plan_record.subgoal_id,
                details={"plan_id": plan_id},
            ))

        # 2. Missing segments (not in real_segments and not already regenerated)
        known_ids = set(real_segments_by_id.keys()) | regenerated_ids
        for seg_id in plan_record.segments:
            if seg_id not in known_ids:
                missing_segments.append(seg_id)
                errors.append(BreakageError(
                    error_type="MISSING_SEGMENT",
                    record_id=seg_id,
                    details={"plan_id": plan_id},
                ))
                invalid_links.append(InvalidLink(
                    from_id=plan_id,
                    to_id=seg_id,
                    link_type="plan_segment",
                    reason="segment not found in SegmentMemory",
                ))

        # 3–4. Per-segment checks (only real segments; regenerated are trusted)
        subgoal_id = plan_record.subgoal_id
        for seg_id, seg in real_segments_by_id.items():
            if seg_id not in plan_segment_ids:
                # Segment was fetched but is not in the plan's list — skip
                continue

            # 3. Broken parent link
            if seg.parent_id is not None and seg.parent_id not in known_ids:
                errors.append(BreakageError(
                    error_type="BROKEN_PARENT_LINK",
                    record_id=seg_id,
                    details={"broken_parent_id": seg.parent_id},
                ))
                invalid_links.append(InvalidLink(
                    from_id=seg_id,
                    to_id=seg.parent_id,
                    link_type="parent_child",
                    reason="parent_id not found in SegmentMemory or regenerated set",
                ))

            # 4. Subgoal mismatch
            if seg.subgoal_id != subgoal_id:
                errors.append(BreakageError(
                    error_type="SUBGOAL_MISMATCH",
                    record_id=seg_id,
                    details={
                        "segment_subgoal_id": seg.subgoal_id,
                        "plan_subgoal_id": subgoal_id,
                    },
                ))
                invalid_links.append(InvalidLink(
                    from_id=seg_id,
                    to_id=subgoal_id,
                    link_type="subgoal_segment",
                    reason=f"segment.subgoal_id {seg.subgoal_id!r} ≠ plan.subgoal_id {subgoal_id!r}",
                ))

            # Segment timestamp — report-only (cannot repair without breaking segment_id)
            _, ts_viol = try_normalise_iso_timestamp(seg.created_at, "created_at", seg_id)
            if ts_viol:
                warnings.append(BreakageWarning(
                    warning_type="SEGMENT_TIMESTAMP",
                    record_id=seg_id,
                    details={"created_at": seg.created_at, "note": "not repairable without segment regeneration"},
                ))
                timestamp_issues.append(TimestampIssue(
                    record_id=seg_id,
                    record_type="segment",
                    issue=ts_viol[0].message,
                ))

            # Governance validation per segment
            for v in validate_segment_record(seg):
                gov_violations.append(v)

        # 5. Plan timestamp (repairable)
        _, ts_viol = try_normalise_iso_timestamp(plan_record.created_at, "created_at", plan_id)
        if ts_viol:
            timestamp_issues.append(TimestampIssue(
                record_id=plan_id,
                record_type="plan",
                issue=ts_viol[0].message,
            ))

        # 6. Governance validation on the plan record
        already_missing = set(missing_segments)
        for v in validate_plan_record(plan_record):
            # De-dup: missing segment references are already in errors/missing_segments
            if v.rule == "unknown_segment_reference" and v.record_id and v.record_id in already_missing:
                continue
            gov_violations.append(v)

        # 7. Drift flags — events referencing segments in this plan
        for event in drift_events:
            if event.segment_id in plan_segment_ids:
                drift_flags.append(DriftFlag(
                    segment_id=event.segment_id,
                    subgoal_id=event.subgoal_id,
                    signal_type=event.signal_type,
                    confidence=event.confidence,
                ))
                warnings.append(BreakageWarning(
                    warning_type="DRIFT_FLAG",
                    record_id=event.segment_id,
                    details={"signal_type": event.signal_type, "confidence": event.confidence},
                ))

        return PlanBreakageReport(
            plan_id=plan_id,
            errors=tuple(errors),
            warnings=tuple(warnings),
            missing_segments=tuple(missing_segments),
            invalid_links=tuple(invalid_links),
            drift_flags=tuple(drift_flags),
            timestamp_issues=tuple(timestamp_issues),
            governance_violations=tuple(gov_violations),
        )

    # ------------------------------------------------------------------
    # 2. Minimal-fix identification
    # ------------------------------------------------------------------

    def build_repair_plan(
        self,
        breakage: PlanBreakageReport,
    ) -> RepairPlan:
        """
        Derive the minimal set of deterministic repair actions from a PlanBreakageReport.

        Actions are sorted by (action_type, target_id) for full reproducibility.
        """
        actions: List[RepairAction] = []
        requires_redecomposition = False
        requires_segment_regeneration: List[str] = []
        requires_subgoal_repair: List[str] = []

        seen_targets: Set[Tuple[str, str]] = set()

        def _add(action_type: str, target_id: str, details: Dict) -> None:
            key = (action_type, target_id)
            if key not in seen_targets:
                seen_targets.add(key)
                actions.append(RepairAction(action_type=action_type, target_id=target_id, details=details))

        for error in breakage.errors:
            if error.error_type == "MISSING_SEGMENT":
                _add("REGENERATE_SEGMENT", error.record_id, {"plan_id": breakage.plan_id})
                if error.record_id not in requires_segment_regeneration:
                    requires_segment_regeneration.append(error.record_id)

            elif error.error_type == "MISSING_SUBGOAL":
                requires_redecomposition = True
                if error.record_id not in requires_subgoal_repair:
                    requires_subgoal_repair.append(error.record_id)
                # No structural action possible — flagged for caller to re-decompose

            elif error.error_type == "BROKEN_PARENT_LINK":
                _add(
                    "RECONSTRUCT_CHAIN",
                    error.record_id,
                    {"broken_parent_id": error.details.get("broken_parent_id"), "repair": "set_parent_to_none"},
                )

            elif error.error_type == "SUBGOAL_MISMATCH":
                _add(
                    "QUARANTINE_SEGMENT",
                    error.record_id,
                    {
                        "segment_subgoal_id": error.details.get("segment_subgoal_id"),
                        "plan_subgoal_id": error.details.get("plan_subgoal_id"),
                        "reason": "subgoal_id mismatch cannot be repaired without regeneration",
                    },
                )

        # Plan timestamp issue → REHYDRATE_TIMESTAMP
        for ts_issue in breakage.timestamp_issues:
            if ts_issue.record_type == "plan":
                _add("REHYDRATE_TIMESTAMP", ts_issue.record_id, {"issue": ts_issue.issue})

        # Sort for determinism: action_type then target_id
        sorted_actions = tuple(sorted(actions, key=lambda a: (a.action_type, a.target_id)))

        return RepairPlan(
            actions=sorted_actions,
            requires_redecomposition=requires_redecomposition,
            requires_segment_regeneration=tuple(sorted(requires_segment_regeneration)),
            requires_subgoal_repair=tuple(sorted(requires_subgoal_repair)),
        )

    # ------------------------------------------------------------------
    # 2.6. Memory-aware repair context (PHASE 2.16.4)
    # ------------------------------------------------------------------

    def get_repair_context(
        self,
        plan_record: PlanMemoryRecord,
        breakage: PlanBreakageReport,
        k: int = 5,
    ) -> RepairStrategyContext:
        """
        Query the semantic memory index for repair strategy hints relevant to
        the plan and its detected breakages.

        Returns an empty RepairStrategyContext when no index is configured.
        """
        if self._memory_index is None:
            return RepairStrategyContext()

        topics = self._extract_repair_topics(plan_record, breakage)
        entities = self._extract_repair_entities(plan_record, breakage)
        capabilities = self._extract_repair_capabilities(breakage)

        # Find similar subgoals for historical success/failure patterns
        similar_subgoals = self._memory_index.find_similar_subgoals(
            topics=topics,
            entities=entities,
            capability_patterns=capabilities,
            k=k,
        )

        # Find similar drifts for failure-prone patterns
        similar_drifts = self._memory_index.find_similar_drifts(
            topics=topics,
            entities=entities,
            capability_patterns=capabilities,
            k=k,
        )

        all_records = list(similar_subgoals) + list(similar_drifts)
        if not all_records:
            return RepairStrategyContext()

        preferred: List[str] = []
        avoid: List[str] = []
        successful_patterns: List[str] = []
        drift_risks: List[str] = []

        success_count = 0
        failure_count = 0

        for record in similar_subgoals:
            caps = list(record.capability_patterns)
            if record.outcome in ("success", "partial_success"):
                success_count += 1
                preferred.extend(caps)
                if caps:
                    successful_patterns.append("→".join(caps))
            else:
                failure_count += 1
                avoid.extend(caps)
                if caps:
                    drift_risks.append("→".join(caps))

        for record in similar_drifts:
            caps = list(record.capability_patterns)
            failure_count += 1
            avoid.extend(caps)
            if caps:
                drift_risks.append("→".join(caps))

        total = len(all_records)
        confidence = success_count / total if total > 0 else 0.0

        # Deduplicate while preserving first-seen order
        def _dedup(seq: List[str]) -> Tuple[str, ...]:
            seen: set = set()
            result: List[str] = []
            for item in seq:
                if item not in seen:
                    seen.add(item)
                    result.append(item)
            return tuple(result)

        return RepairStrategyContext(
            preferred_capabilities=_dedup(preferred),
            avoid_capabilities=_dedup(avoid),
            successful_patterns=_dedup(successful_patterns),
            drift_risks=_dedup(drift_risks),
            confidence=confidence,
            matches=total,
        )

    # ------------------------------------------------------------------
    # 3. Segment regeneration
    # ------------------------------------------------------------------

    def regenerate_segment(
        self,
        segment_id: str,
        subgoal_id: str,
        parent_id: Optional[str],
        now: int,
    ) -> RepairedSegmentRecord:
        """
        Create a structural placeholder for a missing segment.

        The placeholder always has steps=(), state="pending", and metadata={"repaired": True}.
        It MUST NOT be written through MemoryGovernance — it is a tombstone for repair output.
        Callers signal via RepairOutcome.regenerated_segments that re-generation is needed.
        """
        return RepairedSegmentRecord(
            segment_id=segment_id,
            subgoal_id=subgoal_id,
            parent_id=parent_id,
            steps=(),
            state="pending",
            metadata={"repaired": True},
            created_at=_ms_to_iso(now),
        )

    # ------------------------------------------------------------------
    # 4 & 5. Repair loop with budget + retry limits
    # ------------------------------------------------------------------

    def repair(
        self,
        plan_record: PlanMemoryRecord,
        real_segments_by_id: Dict[str, SegmentMemoryRecord],
        subgoals_by_id: Dict[str, SubgoalMemoryRecord],
        drift_events: List[DriftEvent],
        now: int,
        repair_budget: int,
        retry_limit: int,
    ) -> RepairOutcome:
        """
        Iteratively detect and apply repairs until the plan is clean, the budget is
        exhausted, or the retry limit is reached.

        repair_budget: maximum total number of repair actions allowed across all cycles.
        retry_limit:   maximum number of detect→repair cycles. Must be >= 1.

        Abort conditions (success=False):
          - Circular repair loop: same breakage fingerprint appears twice.
          - No actionable repairs: repair_plan has no actions and no redecomposition needed.
          - Budget exceeded: next batch would exceed repair_budget.
          - Retry limit exhausted: plan still broken after retry_limit cycles.

        Returned RepairOutcome.repaired_plan is None on failure.
        Regenerated segment placeholders are always returned for caller visibility.

        When a memory index is configured, RepairOutcome.strategy_context contains
        semantic-memory-derived repair hints (PHASE 2.16.4).
        """
        if repair_budget <= 0:
            raise ValueError(f"repair_budget must be > 0, got {repair_budget}")
        if retry_limit < 1:
            raise ValueError(f"retry_limit must be >= 1, got {retry_limit}")

        working_plan = plan_record
        working_segments: Dict[str, SegmentMemoryRecord] = dict(real_segments_by_id)
        regenerated: Dict[str, RepairedSegmentRecord] = {}
        accumulated_actions: List[RepairAction] = []
        budget_used = 0
        seen_fingerprints: Set[str] = set()

        # Compute strategy context once from the initial breakage report (2.16.4)
        initial_breakage = self.detect_breakages(
            working_plan,
            working_segments,
            set(),
            subgoals_by_id,
            drift_events,
            now,
        )
        strategy_ctx = self.get_repair_context(plan_record, initial_breakage)

        for attempt in range(1, retry_limit + 1):
            breakage = self.detect_breakages(
                working_plan,
                working_segments,
                set(regenerated.keys()),
                subgoals_by_id,
                drift_events,
                now,
            )

            if breakage.is_clean:
                return RepairOutcome(
                    success=True,
                    repaired_plan=working_plan,
                    regenerated_segments=tuple(regenerated.values()),
                    repair_actions_applied=tuple(accumulated_actions),
                    errors=(),
                    attempts=attempt,
                    budget_used=budget_used,
                    strategy_context=strategy_ctx,
                )

            fp = _breakage_fingerprint(breakage)
            if fp in seen_fingerprints:
                return RepairOutcome(
                    success=False,
                    repaired_plan=None,
                    regenerated_segments=tuple(regenerated.values()),
                    repair_actions_applied=tuple(accumulated_actions),
                    errors=("Circular repair loop detected — breakage state unchanged after repair",),
                    attempts=attempt,
                    budget_used=budget_used,
                    strategy_context=strategy_ctx,
                )
            seen_fingerprints.add(fp)

            repair_plan = self.build_repair_plan(breakage)

            if not repair_plan.actions and not repair_plan.requires_redecomposition:
                return RepairOutcome(
                    success=False,
                    repaired_plan=None,
                    regenerated_segments=tuple(regenerated.values()),
                    repair_actions_applied=tuple(accumulated_actions),
                    errors=("No actionable repairs available for remaining breakages",),
                    attempts=attempt,
                    budget_used=budget_used,
                    strategy_context=strategy_ctx,
                )

            n_actions = len(repair_plan.actions)
            if budget_used + n_actions > repair_budget:
                return RepairOutcome(
                    success=False,
                    repaired_plan=None,
                    regenerated_segments=tuple(regenerated.values()),
                    repair_actions_applied=tuple(accumulated_actions),
                    errors=(
                        f"Repair budget exceeded: {budget_used + n_actions} actions needed, "
                        f"{repair_budget} budgeted",
                    ),
                    attempts=attempt,
                    budget_used=budget_used,
                    strategy_context=strategy_ctx,
                )

            # Apply all actions for this cycle
            working_plan, working_segments, new_regenerated = self._apply_actions(
                repair_plan.actions,
                working_plan,
                working_segments,
                now,
            )
            regenerated.update(new_regenerated)
            accumulated_actions.extend(repair_plan.actions)
            budget_used += n_actions

        # Retry limit exhausted — do a final detection pass
        final_breakage = self.detect_breakages(
            working_plan,
            working_segments,
            set(regenerated.keys()),
            subgoals_by_id,
            drift_events,
            now,
        )
        success = final_breakage.is_clean
        return RepairOutcome(
            success=success,
            repaired_plan=working_plan if success else None,
            regenerated_segments=tuple(regenerated.values()),
            repair_actions_applied=tuple(accumulated_actions),
            errors=() if success else ("Retry limit exhausted with breakages remaining",),
            attempts=retry_limit,
            budget_used=budget_used,
            strategy_context=strategy_ctx,
        )

    # ------------------------------------------------------------------
    # Internal: apply one repair cycle's actions
    # ------------------------------------------------------------------

    def _apply_actions(
        self,
        actions: Tuple[RepairAction, ...],
        plan: PlanMemoryRecord,
        segments: Dict[str, SegmentMemoryRecord],
        now: int,
    ) -> Tuple[PlanMemoryRecord, Dict[str, SegmentMemoryRecord], Dict[str, RepairedSegmentRecord]]:
        """
        Apply a set of repair actions and return updated working state.

        Returns (updated_plan, updated_segments_dict, newly_regenerated_dict).
        Does not mutate inputs — all changes produce new objects.
        """
        working_plan = plan
        working_segments = dict(segments)
        new_regenerated: Dict[str, RepairedSegmentRecord] = {}

        for action in actions:
            if action.action_type == "REGENERATE_SEGMENT":
                seg_id = action.target_id
                placeholder = self.regenerate_segment(
                    segment_id=seg_id,
                    subgoal_id=working_plan.subgoal_id,
                    parent_id=None,
                    now=now,
                )
                new_regenerated[seg_id] = placeholder
                # Ensure the segment is in the plan's segment list
                if seg_id not in list(working_plan.segments):
                    working_plan = _updated_plan(
                        working_plan,
                        segments=list(working_plan.segments) + [seg_id],
                    )

            elif action.action_type == "RECONSTRUCT_CHAIN":
                seg_id = action.target_id
                if seg_id in working_segments:
                    old_seg = working_segments[seg_id]
                    # Sever the broken parent link — make this segment a chain root
                    working_segments[seg_id] = _updated_segment(old_seg, parent_id=None)

            elif action.action_type == "REHYDRATE_TIMESTAMP":
                # Only applies to plan records
                normalised, _ = try_normalise_iso_timestamp(
                    working_plan.created_at, "created_at", working_plan.plan_id
                )
                if normalised != working_plan.created_at:
                    working_plan = _updated_plan(working_plan, created_at=normalised)
                else:
                    # created_at is totally unparseable — fall back to now
                    working_plan = _updated_plan(working_plan, created_at=_ms_to_iso(now))

            elif action.action_type == "QUARANTINE_SEGMENT":
                seg_id = action.target_id
                # Remove mismatched segment from plan and working set
                new_segments = [s for s in list(working_plan.segments) if s != seg_id]
                working_plan = _updated_plan(working_plan, segments=new_segments)
                working_segments.pop(seg_id, None)

        return working_plan, working_segments, new_regenerated

    # ------------------------------------------------------------------
    # Internal: extraction helpers for memory-aware repair (2.16.4)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_repair_topics(
        plan_record: PlanMemoryRecord,
        breakage: PlanBreakageReport,
    ) -> List[str]:
        """
        Deterministic extraction of topic-like terms from plan data and breakage report.

        Uses plan intent, skill id, breakage error types, and drift signal types.
        No NLP, no randomness.
        """
        topics: List[str] = []
        if plan_record.intent and plan_record.intent.strip():
            topics.append(plan_record.intent.strip())
        if plan_record.targetskillid and plan_record.targetskillid.strip():
            topics.append(plan_record.targetskillid.strip())
        # Add breakage error types as topics (e.g. "MISSING_SEGMENT")
        for error in breakage.errors:
            topics.append(error.error_type)
        # Add drift signal types
        for drift in breakage.drift_flags:
            topics.append(drift.signal_type)
        return topics

    @staticmethod
    def _extract_repair_entities(
        plan_record: PlanMemoryRecord,
        breakage: PlanBreakageReport,
    ) -> List[str]:
        """
        Deterministic extraction of entity-like terms from plan and breakage data.

        Uses plan_id, subgoal_id, affected segment IDs, and missing segment IDs.
        """
        entities: List[str] = [plan_record.plan_id, plan_record.subgoal_id]
        for error in breakage.errors:
            if error.record_id not in entities:
                entities.append(error.record_id)
        for seg_id in breakage.missing_segments:
            if seg_id not in entities:
                entities.append(seg_id)
        for link in breakage.invalid_links:
            if link.from_id not in entities:
                entities.append(link.from_id)
            if link.to_id not in entities:
                entities.append(link.to_id)
        return entities

    @staticmethod
    def _extract_repair_capabilities(
        breakage: PlanBreakageReport,
    ) -> List[str]:
        """
        Deterministic extraction of repair-action types as capability-like terms.

        Maps breakage errors to their corresponding repair action types, which
        serve as capability patterns for semantic memory lookups.
        """
        caps: List[str] = []

        # Map error types to their standard repair actions
        action_map = {
            "MISSING_SEGMENT": "REGENERATE_SEGMENT",
            "BROKEN_PARENT_LINK": "RECONSTRUCT_CHAIN",
            "SUBGOAL_MISMATCH": "QUARANTINE_SEGMENT",
            "MISSING_SUBGOAL": "REDECOMPOSE_SUBGOAL",
        }

        seen: Set[str] = set()
        for error in breakage.errors:
            action = action_map.get(error.error_type)
            if action and action not in seen:
                seen.add(action)
                caps.append(action)

        return caps
