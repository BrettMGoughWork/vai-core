from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.strategy.memory.governance.governance_errors import GovernanceViolation
from src.strategy.memory.segment_memory_types import SegmentMemoryRecord
from src.strategy.memory.plan_memory_types import PlanMemoryRecord


def normalise_iso_timestamp(value: str) -> str:
    """
    Parse an ISO 8601 timestamp string and re-emit in canonical UTC form.

    Treats naive timestamps as UTC. Replaces trailing 'Z' with '+00:00'
    for broad compatibility.

    Raises ValueError if value cannot be parsed.
    """
    normalised = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalised)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def try_normalise_iso_timestamp(
    value: str,
    field: str,
    record_id: Optional[str],
) -> tuple[str, list[GovernanceViolation]]:
    """
    Attempt to normalise an ISO timestamp.

    Returns (normalised_value, []) on success, or (original, [violation]) on failure.
    """
    try:
        return normalise_iso_timestamp(value), []
    except (ValueError, TypeError):
        return value, [
            GovernanceViolation(
                rule="invalid_iso_timestamp",
                field=field,
                message=f"Cannot parse {field!r} as ISO 8601: {value!r}",
                record_id=record_id,
            )
        ]


def normalise_plan_record(record: PlanMemoryRecord) -> PlanMemoryRecord:
    """
    Return a new PlanMemoryRecord with created_at normalised to canonical UTC ISO.

    If created_at is already canonical it is returned unchanged (idempotent).
    Raises ValueError if created_at cannot be parsed.
    """
    canonical = normalise_iso_timestamp(record.created_at)
    if canonical == record.created_at:
        return record
    return PlanMemoryRecord(
        plan_id=record.plan_id,
        subgoal_id=record.subgoal_id,
        segments=record.segments,
        created_at=canonical,
        metadata=record.metadata,
        intent=record.intent,
        targetskillid=record.targetskillid,
        arguments=record.arguments,
        reasoning_summary=record.reasoning_summary,
    )


# NOTE: SegmentMemoryRecord.created_at is intentionally NOT normalised.
# PlanSegment.segment_id is a hash of (subgoal_id, steps, created_at).
# Reformatting created_at would produce a different segment_id, breaking
# all cross-store references. Governance validates parseability only.
