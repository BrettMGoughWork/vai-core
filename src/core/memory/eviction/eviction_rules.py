from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from src.core.types.hashing import stable_hash
from src.core.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.memory.plan_memory_types import PlanMemoryRecord
from src.core.memory.drift_memory_types import DriftEvent
from src.core.memory.summarisation.summary_types import SummaryMetadata
from src.core.memory.summarisation.summarisation_rules import SummarisationRules
from src.core.memory.eviction.eviction_types import (
    AccessRecord,
    EvictionDecision,
    EvictionReport,
    DriftEvictionReport,
    CompletionEvictionSummary,
)

_summarisation_rules = SummarisationRules()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _drift_event_id(ordinal: int, event: DriftEvent) -> str:
    """
    Stable synthetic ID for a DriftEvent.

    DriftEvent has no primary key. We use ordinal (position in a sorted list) +
    a hash of all identifying fields. The ordinal prevents hash-identical duplicate
    events from producing the same ID in the same eviction batch.
    """
    fields = {
        "timestamp": event.timestamp,
        "subgoal_id": event.subgoal_id,
        "segment_id": event.segment_id,
        "step_id": event.step_id,
        "signal_type": event.signal_type,
        "confidence": event.confidence,
    }
    return f"{ordinal}:{stable_hash(fields)}"


def _empty_report(now: int, reason: str) -> EvictionReport:
    return EvictionReport(decisions=(), eviction_count=0, generated_at=now, reason=reason)


# ---------------------------------------------------------------------------
# EvictionRules
# ---------------------------------------------------------------------------

class EvictionRules:
    """
    Pure, deterministic, rule-based eviction logic for Stratum-2 memory stores.

    All methods are pure functions: they accept data, return structured decisions,
    and never touch memory stores directly. Callers are responsible for applying
    the decisions.

    Four eviction strategies:
      1. LRU — least-recently-read, per-store.
      2. LFU — least-frequently-read, per-store.
      3. Drift-triggered — evict DriftEvents by count, age, or signal pattern.
      4. Subgoal-completion — evict all records for a completed subgoal.
      +  Summary replacement — replace full records with fresh summaries.
    """

    # ------------------------------------------------------------------
    # Reference / chain protection helpers
    # ------------------------------------------------------------------

    @staticmethod
    def compute_segment_refs(
        segments: List[SegmentMemoryRecord],
        plans: List[PlanMemoryRecord],
    ) -> Set[str]:
        """
        Return segment_ids that must not be evicted:
        - parent_id ancestors (evicting them would break chain reconstruction)
        - segment_ids listed in any plan's segments field
        """
        refs: Set[str] = set()
        for s in segments:
            if s.parent_id:
                refs.add(s.parent_id)
        for p in plans:
            refs.update(p.segments)
        return refs

    @staticmethod
    def compute_subgoal_refs(subgoals: List[SubgoalMemoryRecord]) -> Set[str]:
        """Return subgoal_ids referenced as parent_id (ancestors in the chain)."""
        return {s.parent_id for s in subgoals if s.parent_id}

    @staticmethod
    def _ancestor_closure(
        seed_ids: Set[str],
        segments_by_id: Dict[str, SegmentMemoryRecord],
    ) -> Set[str]:
        """
        Walk parent_id links upward from seed_ids and return the full ancestor closure.

        Returns seed_ids ∪ all ancestor segment_ids reachable via parent_id links.
        Used to ensure that retaining a segment also retains its entire ancestry chain.
        """
        closure: Set[str] = set(seed_ids)
        queue = list(seed_ids)
        while queue:
            current_id = queue.pop()
            seg = segments_by_id.get(current_id)
            if seg and seg.parent_id and seg.parent_id in segments_by_id and seg.parent_id not in closure:
                closure.add(seg.parent_id)
                queue.append(seg.parent_id)
        return closure

    # ------------------------------------------------------------------
    # Strategy 1: LRU
    # ------------------------------------------------------------------

    def evict_lru(
        self,
        access_log: Dict[str, AccessRecord],
        protected_ids: Set[str],
        n: int,
        now: int,
    ) -> EvictionReport:
        """
        Evict up to n least-recently-accessed records.

        access_log MUST be scoped to a single memory store (segment, plan, etc.)
        to prevent cross-store ID collisions. protected_ids are record_ids within
        the same store that must not be evicted.

        Sort order: (last_accessed_at ASC, record_id ASC) — fully deterministic.
        """
        if n <= 0:
            return _empty_report(now, "LRU")

        candidates = [ar for rec_id, ar in access_log.items() if rec_id not in protected_ids]
        sorted_candidates = sorted(candidates, key=lambda ar: (ar.last_accessed_at, ar.record_id))
        to_evict = sorted_candidates[:n]

        decisions = tuple(
            EvictionDecision(
                record_id=ar.record_id,
                record_type=ar.record_type,
                reason="LRU",
                evicted_at=now,
                details={
                    "last_accessed_at": ar.last_accessed_at,
                    "access_count": ar.access_count,
                },
            )
            for ar in to_evict
        )
        return EvictionReport(decisions=decisions, eviction_count=len(decisions), generated_at=now, reason="LRU")

    # ------------------------------------------------------------------
    # Strategy 2: LFU
    # ------------------------------------------------------------------

    def evict_lfu(
        self,
        access_log: Dict[str, AccessRecord],
        protected_ids: Set[str],
        n: int,
        now: int,
    ) -> EvictionReport:
        """
        Evict up to n least-frequently-accessed records.

        Primary sort: access_count ASC.
        Tie-break: last_accessed_at ASC (evict the oldest within the same frequency).
        Final tie-break: record_id ASC for full determinism.
        """
        if n <= 0:
            return _empty_report(now, "LFU")

        candidates = [ar for rec_id, ar in access_log.items() if rec_id not in protected_ids]
        sorted_candidates = sorted(
            candidates,
            key=lambda ar: (ar.access_count, ar.last_accessed_at, ar.record_id),
        )
        to_evict = sorted_candidates[:n]

        decisions = tuple(
            EvictionDecision(
                record_id=ar.record_id,
                record_type=ar.record_type,
                reason="LFU",
                evicted_at=now,
                details={
                    "access_count": ar.access_count,
                    "last_accessed_at": ar.last_accessed_at,
                },
            )
            for ar in to_evict
        )
        return EvictionReport(decisions=decisions, eviction_count=len(decisions), generated_at=now, reason="LFU")

    # ------------------------------------------------------------------
    # Strategy 3: Drift-triggered eviction
    # ------------------------------------------------------------------

    def evict_by_drift(
        self,
        drift_events: List[DriftEvent],
        threshold_count: int,
        threshold_age_ms: int,
        signal_patterns: List[str],
        now: int,
    ) -> DriftEvictionReport:
        """
        Evict DriftEvents based on count, age, and signal type patterns.

        Only DriftEvents are affected — segment records are never touched here.
        The last (most recent) event is always preserved, along with its segment_id.

        Eviction candidates (all except last event):
          - Count: events beyond threshold_count are evicted oldest-first.
            threshold_count <= 0 disables count-based eviction.
          - Age: events older than threshold_age_ms (now - timestamp > threshold_age_ms).
            threshold_age_ms <= 0 disables age-based eviction.
          - Pattern: events whose signal_type is in signal_patterns.
            Empty list disables pattern-based eviction.

        Conditions are combined as a UNION: a candidate is evicted if it meets ANY
        enabled condition. This allows fine-grained control via callers.

        Note: DriftMemory's ring buffer already silently drops old events on capacity
        overflow. This method produces explicit audit decisions for intentional eviction.
        """
        if not drift_events:
            return DriftEvictionReport(
                evicted_drift_events=(),
                preserved_segment_id=None,
                generated_at=now,
            )

        sorted_events = sorted(
            drift_events,
            key=lambda e: (e.timestamp, e.subgoal_id, e.signal_type),
        )
        last_event = sorted_events[-1]
        preserved_segment_id = last_event.segment_id
        candidates = sorted_events[:-1]

        to_evict_indices: Set[int] = set()

        # Count threshold
        if threshold_count > 0:
            max_keep_from_candidates = max(0, threshold_count - 1)
            if len(candidates) > max_keep_from_candidates:
                n_by_count = len(candidates) - max_keep_from_candidates
                for i in range(n_by_count):
                    to_evict_indices.add(i)

        # Age threshold
        if threshold_age_ms > 0:
            for i, e in enumerate(candidates):
                if now - e.timestamp > threshold_age_ms:
                    to_evict_indices.add(i)

        # Signal pattern
        if signal_patterns:
            pattern_set = set(signal_patterns)
            for i, e in enumerate(candidates):
                if e.signal_type in pattern_set:
                    to_evict_indices.add(i)

        to_evict = [candidates[i] for i in sorted(to_evict_indices)]

        decisions = tuple(
            EvictionDecision(
                record_id=_drift_event_id(i, e),
                record_type="drift_event",
                reason="DRIFT",
                evicted_at=now,
                details={
                    "timestamp": e.timestamp,
                    "subgoal_id": e.subgoal_id,
                    "signal_type": e.signal_type,
                    "age_ms": now - e.timestamp,
                },
            )
            for i, e in enumerate(to_evict)
        )

        return DriftEvictionReport(
            evicted_drift_events=decisions,
            preserved_segment_id=preserved_segment_id,
            generated_at=now,
        )

    # ------------------------------------------------------------------
    # Strategy 4: Subgoal-completion eviction
    # ------------------------------------------------------------------

    def evict_on_subgoal_completion(
        self,
        subgoal_id: str,
        segments: List[SegmentMemoryRecord],
        drift_events: List[DriftEvent],
        plans: List[PlanMemoryRecord],
        now: int,
        evict_plan: bool = False,
    ) -> CompletionEvictionSummary:
        """
        Evict all records belonging to a completed subgoal.

        Chain safety:
          - Segments externally referenced by other subgoals (via parent_id or plan.segments)
            are never evicted.
          - Their ancestors within the same subgoal are also retained (ancestor closure)
            so that chain reconstruction for any retained segment remains intact.

        Plan eviction (opt-in via evict_plan=True):
          - A plan is only evicted if ALL its segment_ids are confirmed safe-to-evict.
          - Plans belonging to other subgoals that reference these segments block eviction.
        """
        target_segments = [s for s in segments if s.subgoal_id == subgoal_id]
        target_ids = {s.segment_id for s in target_segments}

        # Segments of this subgoal referenced by segments belonging to other subgoals
        external_parent_refs = {
            s.parent_id
            for s in segments
            if s.parent_id and s.subgoal_id != subgoal_id and s.parent_id in target_ids
        }

        # Segments of this subgoal referenced by plans of other subgoals
        plan_refs = {
            seg_id
            for p in plans
            if p.subgoal_id != subgoal_id
            for seg_id in p.segments
            if seg_id in target_ids
        }

        externally_protected = external_parent_refs | plan_refs

        # Expand to ancestor closure: keep all ancestors of any retained segment
        segments_by_id = {s.segment_id: s for s in target_segments}
        retained_closure = self._ancestor_closure(externally_protected, segments_by_id)

        safe_to_evict = [s for s in target_segments if s.segment_id not in retained_closure]
        safe_ids = {s.segment_id for s in safe_to_evict}

        segment_decisions = tuple(
            EvictionDecision(
                record_id=s.segment_id,
                record_type="segment",
                reason="SUBGOAL_COMPLETE",
                evicted_at=now,
                details={"subgoal_id": subgoal_id},
            )
            for s in safe_to_evict
        )

        # Drift events referencing evicted segments or this subgoal
        evictable_drift = sorted(
            (
                e for e in drift_events
                if (e.segment_id in safe_ids) or (e.subgoal_id == subgoal_id and e.segment_id is None)
            ),
            key=lambda e: (e.timestamp, e.subgoal_id, e.signal_type),
        )
        drift_decisions = tuple(
            EvictionDecision(
                record_id=_drift_event_id(i, e),
                record_type="drift_event",
                reason="SUBGOAL_COMPLETE",
                evicted_at=now,
                details={"segment_id": e.segment_id, "subgoal_id": e.subgoal_id},
            )
            for i, e in enumerate(evictable_drift)
        )

        plan_decisions: Tuple[EvictionDecision, ...] = ()
        if evict_plan:
            evictable_plans = [
                p for p in plans
                if p.subgoal_id == subgoal_id
                and all(seg_id in safe_ids for seg_id in p.segments)
            ]
            plan_decisions = tuple(
                EvictionDecision(
                    record_id=p.plan_id,
                    record_type="plan",
                    reason="SUBGOAL_COMPLETE",
                    evicted_at=now,
                    details={"subgoal_id": subgoal_id},
                )
                for p in evictable_plans
            )

        return CompletionEvictionSummary(
            subgoal_id=subgoal_id,
            evicted_segments=segment_decisions,
            evicted_drift_events=drift_decisions,
            evicted_plans=plan_decisions,
            generated_at=now,
        )

    # ------------------------------------------------------------------
    # Summary-state replacement
    # ------------------------------------------------------------------

    def evict_by_summary_replacement(
        self,
        records: List[SegmentMemoryRecord],
        summary_meta: SummaryMetadata,
        current_fingerprint: str,
        protected_ids: Set[str],
        now: int,
    ) -> EvictionReport:
        """
        Replace full segment records with their structural summary.

        Eviction only proceeds when:
          - The summary is fresh (fingerprint and count match current records).
          - The record has no active references (not in protected_ids).

        Full records must be stored separately until they are confirmed evicted.
        Scoped to segments for now; generalise when a second record type requires it.
        """
        is_stale = _summarisation_rules.is_stale(summary_meta, len(records), current_fingerprint)
        if is_stale:
            return _empty_report(now, "SUMMARY_REPLACEMENT")

        safe = [r for r in records if r.segment_id not in protected_ids]
        decisions = tuple(
            EvictionDecision(
                record_id=r.segment_id,
                record_type="segment",
                reason="SUMMARY_REPLACEMENT",
                evicted_at=now,
                details={"summary_fingerprint": current_fingerprint},
            )
            for r in safe
        )
        return EvictionReport(decisions=decisions, eviction_count=len(decisions), generated_at=now, reason="SUMMARY_REPLACEMENT")
