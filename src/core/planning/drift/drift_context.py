from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.core.memory.drift_memory import DriftMemory
from src.core.memory.governance.governance_errors import GovernanceViolation
from src.core.memory.plan_memory_types import PlanMemoryRecord
from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.memory.subgoal_memory_types import SubgoalMemoryRecord


@dataclass
class TransitionFailureRecord:
    """
    Records how many times a specific (from_state, event) transition has failed.

    Used by collect_behavioural_signals to detect repeated transition failures.
    count >= TRANSITION_FAILURE_THRESHOLD emits a behavioural DriftSignal.
    """
    from_state: str
    event: str
    count: int


@dataclass
class DriftContext:
    """
    Input container for one drift detection cycle.

    timestamp:              Current ms anchor (UTC epoch ms).
    subgoal_id:             The subgoal being evaluated.
    segment_ids:            Segment IDs belonging to this subgoal context.
    plan_id:                Optional plan being evaluated.

    subgoal_records:        Map of subgoal_id → SubgoalMemoryRecord.
    segment_records:        Map of segment_id → SegmentMemoryRecord.
    plan_records:           Map of plan_id → PlanMemoryRecord.

    governance_violations:  Governance violations detected this cycle.
    transition_failures:    Known transition failure counts this cycle.
    repair_attempts:        Number of repair cycles run against this plan.
    fallback_count:         Number of fallback transitions used this cycle.

    drift_memory:           Optional DriftMemory for temporal pattern checks.
                            Signal collection READS from this — never writes.
                            Writes happen after collection, managed by the caller.
    """
    timestamp: int
    subgoal_id: str
    segment_ids: List[str] = field(default_factory=list)
    plan_id: Optional[str] = None

    subgoal_records: Dict[str, SubgoalMemoryRecord] = field(default_factory=dict)
    segment_records: Dict[str, SegmentMemoryRecord] = field(default_factory=dict)
    plan_records: Dict[str, PlanMemoryRecord] = field(default_factory=dict)

    governance_violations: List[GovernanceViolation] = field(default_factory=list)
    transition_failures: List[TransitionFailureRecord] = field(default_factory=list)
    repair_attempts: int = 0
    fallback_count: int = 0

    drift_memory: Optional[DriftMemory] = None
