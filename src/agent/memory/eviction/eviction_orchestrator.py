"""
EvictionOrchestrator — wires EvictionRules into the four memory stores.

Provides three trigger points that the runtime (MemoryGovernance, etc.) calls
at the appropriate moments. Each trigger snapshots the relevant stores, runs
the corresponding EvictionRules strategy, and applies the resulting decisions
via each store's bulk-remove API.
"""

from __future__ import annotations

import time
from typing import List, Optional

from src.agent.memory.eviction.eviction_rules import EvictionRules, _drift_event_id
from src.agent.memory.eviction.eviction_types import (
    CompletionEvictionSummary,
    EvictionDecision,
)
from src.agent.memory.segment_memory import SegmentMemory
from src.agent.memory.subgoal_memory import SubgoalMemory
from src.agent.memory.plan_memory import PlanMemory
from src.agent.memory.drift_memory import DriftMemory
from src.agent.memory.drift_memory_types import DriftEvent


class EvictionOrchestrator:
    """
    Orchestrates eviction by connecting EvictionRules to memory stores.

    Holds references to all four stores and an EvictionRules instance.
    Public methods correspond to trigger points in the runtime lifecycle.
    """

    def __init__(
        self,
        segment_memory: SegmentMemory,
        subgoal_memory: SubgoalMemory,
        plan_memory: PlanMemory,
        drift_memory: DriftMemory,
        eviction_rules: Optional[EvictionRules] = None,
    ) -> None:
        self._segment_memory = segment_memory
        self._subgoal_memory = subgoal_memory
        self._plan_memory = plan_memory
        self._drift_memory = drift_memory
        self._eviction_rules = eviction_rules or EvictionRules()

    # ------------------------------------------------------------------
    # Public trigger points
    # ------------------------------------------------------------------

    def on_subgoal_completed(
        self,
        subgoal_id: str,
        now: Optional[int] = None,
        evict_plan: bool = False,
    ) -> CompletionEvictionSummary:
        """
        Evict records belonging to a just-completed subgoal.

        Snapshots the three record-based stores, runs
        ``evict_on_subgoal_completion``, and applies decisions.
        """
        now = now or int(time.time() * 1000)

        segments = list(self._segment_memory.snapshot().records)
        drift_events = list(self._drift_memory.snapshot().events)
        plans = list(self._plan_memory.snapshot().records)

        summary = self._eviction_rules.evict_on_subgoal_completion(
            subgoal_id=subgoal_id,
            segments=segments,
            drift_events=drift_events,
            plans=plans,
            now=now,
            evict_plan=evict_plan,
        )

        self._apply_completion(summary, drift_events)
        return summary

    def on_drift_overflow(
        self,
        now: Optional[int] = None,
        threshold_count: int = 5,
        threshold_age_ms: int = 0,
        signal_patterns: Optional[List[str]] = None,
    ) -> None:
        """
        Evict DriftEvents when the drift buffer is near or at capacity.

        Snapshots the drift store and runs ``evict_by_drift`` before the
        new event is appended (caller should invoke this *before* record()).
        """
        now = now or int(time.time() * 1000)

        drift_events = list(self._drift_memory.snapshot().events)

        report = self._eviction_rules.evict_by_drift(
            drift_events=drift_events,
            threshold_count=threshold_count,
            threshold_age_ms=threshold_age_ms,
            signal_patterns=signal_patterns or [],
            now=now,
        )

        self._remove_drift_by_decisions(report.evicted_drift_events, drift_events)

    def on_episode_compacted(self) -> None:
        """
        Placeholder for summary-replacement eviction after episode compaction.

        This will be wired when the SummaryMetadata pipeline is integrated
        with the episode lifecycle. No-op for now.
        """
        pass

    # ------------------------------------------------------------------
    # Internal — decision application
    # ------------------------------------------------------------------

    def _apply_completion(
        self,
        summary: CompletionEvictionSummary,
        drift_events: List[DriftEvent],
    ) -> None:
        """Apply CompletionEvictionSummary decisions to all four stores."""
        # Segments — record_id IS segment_id
        seg_ids = [d.record_id for d in summary.evicted_segments]
        self._segment_memory.remove(seg_ids)

        # Plans — record_id IS plan_id
        plan_ids = [d.record_id for d in summary.evicted_plans]
        self._plan_memory.remove(plan_ids)

        # Drift events — rebuild _drift_event_id mapping
        self._remove_drift_by_decisions(summary.evicted_drift_events, drift_events)

    def _remove_drift_by_decisions(
        self,
        decisions: List[EvictionDecision],
        all_events: List[DriftEvent],
    ) -> None:
        """Remove DriftEvents whose synthetic IDs match eviction decisions."""
        if not decisions:
            return
        sorted_events = sorted(
            all_events, key=lambda e: (e.timestamp, e.subgoal_id, e.signal_type)
        )
        decision_ids = {d.record_id for d in decisions}
        events_to_remove = [
            e
            for i, e in enumerate(sorted_events)
            if _drift_event_id(i, e) in decision_ids
        ]
        self._drift_memory.remove_events(events_to_remove)
