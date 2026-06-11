from __future__ import annotations

from typing import Any, List, Optional, Set, Tuple

from src.strategy.memory.governance.governance_errors import GovernanceViolation
from src.strategy.memory.governance.normalisation import try_normalise_iso_timestamp
from src.strategy.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.strategy.memory.segment_memory_types import SegmentMemoryRecord
from src.strategy.memory.plan_memory_types import PlanMemoryRecord
from src.strategy.memory.drift_memory_types import DriftEvent
from src.strategy.types.subgoal import SubgoalLifecycleState
from src.strategy.types.json_pure import ensure_json_pure


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _json_pure_check(
    value: Any,
    field: str,
    record_id: Optional[str],
) -> List[GovernanceViolation]:
    try:
        ensure_json_pure(value)
        return []
    except Exception as exc:
        return [GovernanceViolation(
            rule="not_json_pure",
            field=field,
            message=f"Field {field!r} is not JSON-serialisable: {exc}",
            record_id=record_id,
        )]


def _require_nonempty(
    value: str,
    field: str,
    rule: str,
    record_id: Optional[str],
) -> List[GovernanceViolation]:
    if not value:
        return [GovernanceViolation(
            rule=rule,
            field=field,
            message=f"Field {field!r} must be non-empty",
            record_id=record_id,
        )]
    return []


# ---------------------------------------------------------------------------
# Per-record validation — pure functions, return list[GovernanceViolation]
# ---------------------------------------------------------------------------

def validate_subgoal_record(record: SubgoalMemoryRecord) -> List[GovernanceViolation]:
    """Validate structural and invariant correctness of a SubgoalMemoryRecord."""
    rid = record.subgoal_id or None
    violations: List[GovernanceViolation] = []

    violations += _require_nonempty(record.subgoal_id, "subgoal_id", "subgoal_id_required", rid)
    violations += _require_nonempty(record.goal, "goal", "goal_required", rid)

    if record.created_at < 0:
        violations.append(GovernanceViolation(
            rule="invalid_created_at",
            field="created_at",
            message=f"created_at must be >= 0, got {record.created_at}",
            record_id=rid,
        ))

    # Validate state is a known SubgoalLifecycleState value
    try:
        SubgoalLifecycleState(record.state)
    except ValueError:
        violations.append(GovernanceViolation(
            rule="invalid_state",
            field="state",
            message=f"state {record.state!r} is not a valid SubgoalLifecycleState",
            record_id=rid,
        ))

    if record.parent_id is not None and record.parent_id == record.subgoal_id:
        violations.append(GovernanceViolation(
            rule="self_parent",
            field="parent_id",
            message="parent_id must not equal subgoal_id",
            record_id=rid,
        ))

    violations += _json_pure_check(record.context, "context", rid)
    violations += _json_pure_check(record.metadata, "metadata", rid)

    return violations


def validate_segment_record(record: SegmentMemoryRecord) -> List[GovernanceViolation]:
    """Validate structural and invariant correctness of a SegmentMemoryRecord."""
    rid = record.segment_id or None
    violations: List[GovernanceViolation] = []

    violations += _require_nonempty(record.segment_id, "segment_id", "segment_id_required", rid)
    violations += _require_nonempty(record.subgoal_id, "subgoal_id", "subgoal_id_required", rid)

    if not record.content:
        violations.append(GovernanceViolation(
            rule="content_empty",
            field="content",
            message="content must not be empty",
            record_id=rid,
        ))
    else:
        non_strings = [i for i, v in enumerate(record.content) if not isinstance(v, str)]
        if non_strings:
            violations.append(GovernanceViolation(
                rule="content_not_strings",
                field="content",
                message=f"content items at indices {non_strings} are not strings",
                record_id=rid,
            ))

    _, ts_violations = try_normalise_iso_timestamp(record.created_at, "created_at", rid)
    violations += ts_violations

    if record.parent_id is not None and record.parent_id == record.segment_id:
        violations.append(GovernanceViolation(
            rule="self_parent",
            field="parent_id",
            message="parent_id must not equal segment_id",
            record_id=rid,
        ))

    violations += _json_pure_check(record.context, "context", rid)
    violations += _json_pure_check(record.metadata, "metadata", rid)

    return violations


def validate_plan_record(record: PlanMemoryRecord) -> List[GovernanceViolation]:
    """Validate structural and invariant correctness of a PlanMemoryRecord."""
    rid = record.plan_id or None
    violations: List[GovernanceViolation] = []

    violations += _require_nonempty(record.plan_id, "plan_id", "plan_id_required", rid)
    violations += _require_nonempty(record.subgoal_id, "subgoal_id", "subgoal_id_required", rid)
    violations += _require_nonempty(record.intent, "intent", "intent_required", rid)

    if not isinstance(record.segments, list):
        violations.append(GovernanceViolation(
            rule="segments_not_list",
            field="segments",
            message="segments must be a list",
            record_id=rid,
        ))
    else:
        non_strings = [i for i, v in enumerate(record.segments) if not isinstance(v, str)]
        if non_strings:
            violations.append(GovernanceViolation(
                rule="segments_not_strings",
                field="segments",
                message=f"segments items at indices {non_strings} are not strings",
                record_id=rid,
            ))

    _, ts_violations = try_normalise_iso_timestamp(record.created_at, "created_at", rid)
    violations += ts_violations

    violations += _json_pure_check(record.metadata, "metadata", rid)
    violations += _json_pure_check(record.arguments, "arguments", rid)

    return violations


def validate_drift_event(event: DriftEvent) -> List[GovernanceViolation]:
    """Validate structural and invariant correctness of a DriftEvent."""
    rid = event.subgoal_id or None
    violations: List[GovernanceViolation] = []

    if event.timestamp < 0:
        violations.append(GovernanceViolation(
            rule="invalid_timestamp",
            field="timestamp",
            message=f"timestamp must be >= 0, got {event.timestamp}",
            record_id=rid,
        ))

    violations += _require_nonempty(event.subgoal_id, "subgoal_id", "subgoal_id_required", rid)
    violations += _require_nonempty(event.signal_type, "signal_type", "signal_type_required", rid)

    if not (0.0 <= event.confidence <= 1.0):
        violations.append(GovernanceViolation(
            rule="invalid_confidence",
            field="confidence",
            message=f"confidence must be in [0.0, 1.0], got {event.confidence}",
            record_id=rid,
        ))

    violations += _json_pure_check(event.details, "details", rid)

    return violations


# ---------------------------------------------------------------------------
# Cross-store consistency checks — caller provides known ID sets
# ---------------------------------------------------------------------------

def check_segment_consistency(
    record: SegmentMemoryRecord,
    known_subgoal_ids: Set[str],
) -> List[GovernanceViolation]:
    """Check that segment references a known subgoal."""
    violations: List[GovernanceViolation] = []
    if record.subgoal_id not in known_subgoal_ids:
        violations.append(GovernanceViolation(
            rule="unknown_subgoal_reference",
            field="subgoal_id",
            message=f"subgoal_id {record.subgoal_id!r} not found in SubgoalMemory",
            record_id=record.segment_id,
        ))
    return violations


def check_plan_consistency(
    record: PlanMemoryRecord,
    known_subgoal_ids: Set[str],
    known_segment_ids: Set[str],
) -> List[GovernanceViolation]:
    """Check that plan references known subgoal and known segment IDs."""
    violations: List[GovernanceViolation] = []

    if record.subgoal_id not in known_subgoal_ids:
        violations.append(GovernanceViolation(
            rule="unknown_subgoal_reference",
            field="subgoal_id",
            message=f"subgoal_id {record.subgoal_id!r} not found in SubgoalMemory",
            record_id=record.plan_id,
        ))

    for seg_id in record.segments:
        if seg_id not in known_segment_ids:
            violations.append(GovernanceViolation(
                rule="unknown_segment_reference",
                field="segments",
                message=f"segment_id {seg_id!r} not found in SegmentMemory",
                record_id=record.plan_id,
            ))

    return violations


def check_drift_consistency(
    event: DriftEvent,
    known_subgoal_ids: Set[str],
    known_segment_ids: Set[str],
) -> List[GovernanceViolation]:
    """Check that drift event references known subgoal and (if set) known segment."""
    violations: List[GovernanceViolation] = []

    if event.subgoal_id not in known_subgoal_ids:
        violations.append(GovernanceViolation(
            rule="unknown_subgoal_reference",
            field="subgoal_id",
            message=f"subgoal_id {event.subgoal_id!r} not found in SubgoalMemory",
            record_id=None,
        ))

    if event.segment_id is not None and event.segment_id not in known_segment_ids:
        violations.append(GovernanceViolation(
            rule="unknown_segment_reference",
            field="segment_id",
            message=f"segment_id {event.segment_id!r} not found in SegmentMemory",
            record_id=None,
        ))

    return violations


# ---------------------------------------------------------------------------
# Governed transition check — pure, no side effects
# ---------------------------------------------------------------------------

def is_subgoal_write_allowed(
    existing: Optional[SubgoalMemoryRecord],
    incoming: SubgoalMemoryRecord,
) -> Tuple[bool, List[GovernanceViolation]]:
    """
    Determine whether a subgoal memory write is allowed based on state transitions.

    Returns (True, []) if the write is permitted.
    Returns (False, [violation, ...]) if rejected.

    New writes (existing is None) and same-state overwrites are always allowed.
    State changes must be permitted by either the execution lifecycle engine
    (TransitionEngine) or the high-level lifecycle engine (LifecycleTransitionEngine).
    """
    if existing is None or existing.state == incoming.state:
        return True, []

    # Lazy imports to avoid circular dependency at module load time
    from src.strategy.planning.subgoals.transition_engine import TransitionEngine
    from src.strategy.planning.subgoals.transitions import LifecycleTransitionEngine

    rid = incoming.subgoal_id

    try:
        from_state = SubgoalLifecycleState(existing.state)
        to_state = SubgoalLifecycleState(incoming.state)
    except ValueError as exc:
        return False, [GovernanceViolation(
            rule="invalid_state_value",
            field="state",
            message=f"Cannot resolve lifecycle states for transition check: {exc}",
            record_id=rid,
        )]

    exec_engine = TransitionEngine()
    lifecycle_engine = LifecycleTransitionEngine()

    if exec_engine.is_allowed(from_state, to_state) or lifecycle_engine.is_legal(from_state, to_state):
        return True, []

    return False, [GovernanceViolation(
        rule="disallowed_state_transition",
        field="state",
        message=(
            f"Transition {existing.state!r} → {incoming.state!r} "
            "is not permitted by any lifecycle engine"
        ),
        record_id=rid,
    )]
