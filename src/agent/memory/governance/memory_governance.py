from __future__ import annotations

import copy
from typing import List, Optional

from src.agent.memory.subgoal_memory import SubgoalMemory
from src.agent.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.agent.memory.segment_memory import SegmentMemory
from src.agent.memory.segment_memory_types import SegmentMemoryRecord
from src.agent.memory.plan_memory import PlanMemory
from src.agent.memory.plan_memory_types import PlanMemoryRecord
from src.agent.memory.drift_memory import DriftMemory
from src.agent.memory.drift_memory_types import DriftEvent
from src.agent.memory.eviction.eviction_orchestrator import EvictionOrchestrator
from src.agent.memory.governance.governance_errors import MemoryGovernanceError, GovernanceViolation
from src.agent.memory.governance.validation import (
    validate_subgoal_record,
    validate_segment_record,
    validate_plan_record,
    validate_drift_event,
    check_segment_consistency,
    check_plan_consistency,
    check_drift_consistency,
    is_subgoal_write_allowed,
)
from src.agent.memory.governance.normalisation import (
    normalise_plan_record,
    try_normalise_iso_timestamp,
)
from src.agent.memory.types.subgoal import Subgoal, SubgoalLifecycleState
from src.agent.memory.types.plan_segment import PlanSegment
from src.agent.types.plan import Plan


def _raise_if(violations: List[GovernanceViolation]) -> None:
    if violations:
        raise MemoryGovernanceError(violations)


class MemoryGovernance:
    """
    Pure, deterministic governance layer over the four memory stores.

    All writes are validated, consistency-checked, and (where applicable)
    normalised before being delegated to the underlying stores.
    All reads are validated before the domain object is returned.

    No LLM calls, no inference, no side effects beyond delegating to stores.
    """

    def __init__(
        self,
        subgoal_memory: SubgoalMemory,
        segment_memory: SegmentMemory,
        plan_memory: PlanMemory,
        drift_memory: DriftMemory,
        eviction_orchestrator: Optional[EvictionOrchestrator] = None,
        compaction_orchestrator: Optional[object] = None,
    ) -> None:
        self._subgoal_memory = subgoal_memory
        self._segment_memory = segment_memory
        self._plan_memory = plan_memory
        self._drift_memory = drift_memory
        self._eviction_orchestrator = eviction_orchestrator
        self._compaction_orchestrator = compaction_orchestrator

    # ------------------------------------------------------------------
    # Governed writes
    # ------------------------------------------------------------------

    def put_subgoal(self, subgoal: Subgoal) -> None:
        """
        Validate and write a Subgoal.

        Enforces structural validity and state-transition rules.
        Raises GovernanceError if any rule is violated.
        """
        incoming = SubgoalMemoryRecord(
            subgoal_id=subgoal.subgoal_id,
            parent_id=subgoal.parent_id,
            state=subgoal.state.value,
            goal=subgoal.goal,
            context=copy.deepcopy(dict(subgoal.context)),
            metadata=copy.deepcopy(dict(subgoal.metadata)),
            created_at=subgoal.created_at,
        )
        violations = validate_subgoal_record(incoming)

        existing = self._subgoal_memory.get_record(subgoal.subgoal_id)
        allowed, trans_violations = is_subgoal_write_allowed(existing, incoming)
        if not allowed:
            violations.extend(trans_violations)

        _raise_if(violations)
        self._subgoal_memory.put(subgoal)

        # Trigger eviction when a subgoal transitions to CLOSED
        if self._eviction_orchestrator is not None and existing is not None:
            prev_state = existing.state.lower()
            new_state = incoming.state.lower()
            if prev_state != "closed" and new_state == "closed":
                self._eviction_orchestrator.on_subgoal_completed(subgoal.subgoal_id)

        # Notify compaction when a subgoal closes
        if self._compaction_orchestrator is not None and existing is not None:
            prev_state = existing.state.lower()
            new_state = incoming.state.lower()
            if prev_state != "closed" and new_state == "closed":
                self._compaction_orchestrator.on_subgoal_closed(
                    subgoal_id=subgoal.subgoal_id,
                    goal=subgoal.goal,
                    context=str(subgoal.context),
                )

    def put_segment(
        self,
        segment: PlanSegment,
        parent_id: Optional[str] = None,
    ) -> None:
        """
        Validate, consistency-check, and write a PlanSegment.

        Enforces structural validity and cross-store consistency
        (subgoal_id must exist in SubgoalMemory).
        Raises GovernanceError if any rule is violated.
        """
        record = SegmentMemoryRecord(
            segment_id=segment.segment_id,
            parent_id=parent_id,
            subgoal_id=segment.subgoal_id,
            state=None,
            content=list(segment.steps),
            created_at=segment.created_at,
            context=copy.deepcopy(dict(segment.context)),
            metadata=copy.deepcopy(dict(segment.metadata)),
            skills=list(segment.skills),
        )
        violations = validate_segment_record(record)

        known_subgoal_ids = {r.subgoal_id for r in self._subgoal_memory.snapshot().records}
        violations += check_segment_consistency(record, known_subgoal_ids)

        _raise_if(violations)
        self._segment_memory.put(segment, parent_id=parent_id)

    def put_plan(
        self,
        plan: Plan,
        plan_id: str,
        subgoal_id: str,
        segments: List[str],
        created_at: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """
        Validate, normalise, and write a Plan.

        Enforces structural validity, ISO timestamp normalisation, and
        cross-store consistency (subgoal_id and all segment_ids must exist).
        Raises GovernanceError if any rule is violated.
        """
        record = PlanMemoryRecord(
            plan_id=plan_id,
            subgoal_id=subgoal_id,
            segments=list(segments),
            created_at=created_at,
            metadata=copy.deepcopy(metadata or {}),
            intent=plan.intent,
            targetskillid=plan.targetskillid,
            arguments=copy.deepcopy(plan.arguments),
            reasoning_summary=plan.reasoning_summary,
        )
        violations = validate_plan_record(record)

        known_subgoal_ids = {r.subgoal_id for r in self._subgoal_memory.snapshot().records}
        known_segment_ids = {r.segment_id for r in self._segment_memory.snapshot().records}
        violations += check_plan_consistency(record, known_subgoal_ids, known_segment_ids)

        _raise_if(violations)

        # Normalise created_at before writing
        normalised_created_at, _ = try_normalise_iso_timestamp(created_at, "created_at", plan_id)
        self._plan_memory.put(
            plan,
            plan_id=plan_id,
            subgoal_id=subgoal_id,
            segments=segments,
            created_at=normalised_created_at,
            metadata=metadata,
        )

    def record_drift(self, event: DriftEvent) -> None:
        """
        Validate and record a DriftEvent.

        Enforces structural validity and cross-store consistency
        (subgoal_id must exist; segment_id if set must exist).
        Raises GovernanceError if any rule is violated.
        """
        violations = validate_drift_event(event)

        known_subgoal_ids = {r.subgoal_id for r in self._subgoal_memory.snapshot().records}
        known_segment_ids = {r.segment_id for r in self._segment_memory.snapshot().records}
        violations += check_drift_consistency(event, known_subgoal_ids, known_segment_ids)

        _raise_if(violations)

        # Evict before appending when the buffer is at capacity
        if self._eviction_orchestrator is not None and len(self._drift_memory) >= self._drift_memory.capacity:
            self._eviction_orchestrator.on_drift_overflow()

        self._drift_memory.record(event)

    # ------------------------------------------------------------------
    # Governed reads
    # ------------------------------------------------------------------

    def get_subgoal(self, subgoal_id: str) -> Optional[Subgoal]:
        """
        Return a validated Subgoal, or None if not found.

        Raises GovernanceError if the stored record is structurally invalid.
        """
        record = self._subgoal_memory.get_record(subgoal_id)
        if record is None:
            return None
        violations = validate_subgoal_record(record)
        _raise_if(violations)
        return self._subgoal_memory.get(subgoal_id)

    def get_segment(self, segment_id: str) -> Optional[PlanSegment]:
        return self._segment_memory.get(segment_id)

    def get_plan(self, plan_id: str) -> Optional[Plan]:
        """
        Return a validated Plan, or None if not found.

        Raises GovernanceError if the stored record is structurally invalid.
        """
        record = self._plan_memory.get_record(plan_id)
        if record is None:
            return None
        violations = validate_plan_record(record)
        _raise_if(violations)
        return self._plan_memory.get(plan_id)

    def get_plan_record(self, plan_id: str) -> Optional[PlanMemoryRecord]:
        """Return the PlanMemoryRecord for *plan_id*, or None if not found."""
        return self._plan_memory.get_record(plan_id)

    # ------------------------------------------------------------------
    # Cross-store consistency check
    # ------------------------------------------------------------------

    def check_consistency(self) -> List[GovernanceViolation]:
        """
        Run a full cross-store consistency audit.

        Returns all violations found. An empty list means all stores are consistent.
        Pure and deterministic — no side effects.
        """
        violations: List[GovernanceViolation] = []

        subgoal_snap = self._subgoal_memory.snapshot()
        segment_snap = self._segment_memory.snapshot()
        plan_snap = self._plan_memory.snapshot()
        drift_snap = self._drift_memory.snapshot()

        known_subgoal_ids = {r.subgoal_id for r in subgoal_snap.records}
        known_segment_ids = {r.segment_id for r in segment_snap.records}

        # Validate each record in each store
        for record in subgoal_snap.records:
            violations += validate_subgoal_record(record)

        for record in segment_snap.records:
            violations += validate_segment_record(record)
            violations += check_segment_consistency(record, known_subgoal_ids)

        for record in plan_snap.records:
            violations += validate_plan_record(record)
            violations += check_plan_consistency(record, known_subgoal_ids, known_segment_ids)

        for event in drift_snap.events:
            violations += validate_drift_event(event)
            violations += check_drift_consistency(event, known_subgoal_ids, known_segment_ids)

        return violations

    # ------------------------------------------------------------------
    # Governed transition check (pure, no side effects)
    # ------------------------------------------------------------------

    def is_subgoal_write_allowed(
        self,
        existing: Optional[SubgoalMemoryRecord],
        incoming: SubgoalMemoryRecord,
    ) -> tuple[bool, List[GovernanceViolation]]:
        """
        Pure function: determine whether a subgoal state update is permitted.

        Delegates to is_subgoal_write_allowed() in validation.py.
        No side effects.
        """
        return is_subgoal_write_allowed(existing, incoming)
