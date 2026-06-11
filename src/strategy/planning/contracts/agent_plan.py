"""
AgentPlan — versioned, frozen planning contract (Phase 2.15.1).

This is the canonical representation of a complete plan produced by S2.
It unifies Plan content with PlanMemoryRecord identity fields and adds
contract versioning for stability across releases.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List

from src.strategy.planning.models.plan import Plan
from src.strategy.planning.models.plan_state import PlanStatus
from src.strategy.memory.plan_memory_types import PlanMemoryRecord


CURRENT_CONTRACT_VERSION = "1.0"


@dataclass(frozen=True)
class AgentPlan:
    """Versioned, frozen plan contract.

    Combines Plan content with PlanMemoryRecord identity fields,
    plus contract versioning and multi-subgoal support.

    This is the single source of truth for plans crossing S2↔S1
    and S2↔S3 boundaries.
    """

    # ── Identity ──
    plan_id: str
    subgoal_id: str
    segments: List[str]  # ordered list of segment_ids

    # ── Plan content ──
    intent: str
    targetskillid: str
    arguments: Dict[str, Any]
    reasoning_summary: str

    # ── Metadata ──
    created_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ── Multi-subgoal support ──
    subgoals: List[str] = field(default_factory=list)
    """Ordered list of subgoal_ids covered by this plan.
    Single-subgoal plans have exactly one entry matching ``subgoal_id``."""

    # ── Contract version ──
    version: str = CURRENT_CONTRACT_VERSION

    # ── Runtime state (not part of the frozen contract identity) ──
    status: PlanStatus = PlanStatus.PENDING

    def __post_init__(self) -> None:
        # Validate required strings are non-empty
        if not self.plan_id:
            raise ValueError("plan_id must be non-empty")
        if not self.subgoal_id:
            raise ValueError("subgoal_id must be non-empty")
        if not self.intent:
            raise ValueError("intent must be non-empty")
        if not self.targetskillid:
            raise ValueError("targetskillid must be non-empty")
        if not self.created_at:
            raise ValueError("created_at must be non-empty")
        if not self.version:
            raise ValueError("version must be non-empty")

        # Ensure subgoals is consistent: subgoal_id must appear in subgoals
        if not self.subgoals:
            object.__setattr__(self, "subgoals", [self.subgoal_id])
        elif self.subgoal_id not in self.subgoals:
            object.__setattr__(self, "subgoals", [self.subgoal_id] + list(self.subgoals))

    # ── Serialization ──

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dict (round-trip safe)."""
        return {
            "plan_id": self.plan_id,
            "subgoal_id": self.subgoal_id,
            "segments": self.segments,
            "intent": self.intent,
            "targetskillid": self.targetskillid,
            "arguments": self.arguments,
            "reasoning_summary": self.reasoning_summary,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "subgoals": self.subgoals,
            "version": self.version,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AgentPlan":
        """Deserialize from a dict produced by ``to_dict()``."""
        return cls(
            plan_id=d["plan_id"],
            subgoal_id=d["subgoal_id"],
            segments=d.get("segments", []),
            intent=d["intent"],
            targetskillid=d["targetskillid"],
            arguments=d.get("arguments", {}),
            reasoning_summary=d.get("reasoning_summary", ""),
            created_at=d["created_at"],
            metadata=d.get("metadata", {}),
            subgoals=d.get("subgoals", []),
            version=d.get("version", CURRENT_CONTRACT_VERSION),
            status=PlanStatus(d.get("status", PlanStatus.PENDING.value)),
        )

    # ── Construction from existing types ──

    @classmethod
    def from_plan_and_record(
        cls,
        plan: Plan,
        record: PlanMemoryRecord,
        *,
        subgoals: List[str] | None = None,
    ) -> "AgentPlan":
        """Construct an AgentPlan from a Plan and its PlanMemoryRecord.

        This is the primary migration path from pre-2.15 types.
        """
        return cls(
            plan_id=record.plan_id,
            subgoal_id=record.subgoal_id,
            segments=list(record.segments),
            intent=plan.intent,
            targetskillid=plan.targetskillid,
            arguments=copy.deepcopy(plan.arguments),
            reasoning_summary=plan.reasoning_summary,
            created_at=record.created_at,
            metadata=copy.deepcopy(record.metadata),
            subgoals=subgoals if subgoals else [record.subgoal_id],
        )

    # ── Properties ──

    @property
    def is_multi_subgoal(self) -> bool:
        """True if this plan spans more than one subgoal."""
        return len(self.subgoals) > 1

    @property
    def segment_count(self) -> int:
        """Number of segments in this plan."""
        return len(self.segments)
