from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class AccessRecord:
    """
    Per-store access tracking entry for LRU/LFU eviction.

    IMPORTANT: access_log MUST be scoped to a single memory store (e.g., all
    SegmentMemoryRecords, or all PlanMemoryRecords) to prevent cross-store ID
    collisions. Never mix record types in one access_log.

    record_id:        the store's primary key (segment_id, plan_id, subgoal_id…).
    record_type:      string label for the record kind — carried into audit decisions.
    access_count:     number of times the record has been read since it was stored.
    last_accessed_at: ms timestamp of the most recent read (or write if never read).
    """
    record_id: str
    record_type: str
    access_count: int
    last_accessed_at: int


@dataclass(frozen=True)
class EvictionDecision:
    """
    Audit record for a single eviction decision.

    record_id:   primary key of the evicted record within its store.
    record_type: kind of record evicted ("segment", "plan", "subgoal", "drift_event").
    reason:      eviction strategy that produced this decision
                 ("LRU", "LFU", "DRIFT", "SUBGOAL_COMPLETE", "SUMMARY_REPLACEMENT").
    evicted_at:  ms timestamp when the decision was produced.
    details:     JSON-pure supplementary information (strategy-specific).
    """
    record_id: str
    record_type: str
    reason: str
    evicted_at: int
    details: Dict[str, Any]


@dataclass(frozen=True)
class EvictionReport:
    """
    Structured result of an LRU, LFU, or summary-replacement eviction pass.

    decisions uses a tuple (not list) so the frozen dataclass is truly immutable.
    """
    decisions: Tuple[EvictionDecision, ...]
    eviction_count: int
    generated_at: int
    reason: str


@dataclass(frozen=True)
class DriftEvictionReport:
    """
    Structured result of a drift-triggered eviction pass.

    evicted_drift_events: decisions for each evicted DriftEvent.
    preserved_segment_id: segment_id of the triggering (last) event — never evicted.
    generated_at:         ms timestamp when the report was produced.
    """
    evicted_drift_events: Tuple[EvictionDecision, ...]
    preserved_segment_id: Optional[str]
    generated_at: int


@dataclass(frozen=True)
class CompletionEvictionSummary:
    """
    Structured result of a subgoal-completion eviction pass.

    Tuples used throughout so the frozen dataclass is truly immutable.
    """
    subgoal_id: str
    evicted_segments: Tuple[EvictionDecision, ...]
    evicted_drift_events: Tuple[EvictionDecision, ...]
    evicted_plans: Tuple[EvictionDecision, ...]
    generated_at: int
