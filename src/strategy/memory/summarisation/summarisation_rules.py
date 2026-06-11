from __future__ import annotations

from typing import Dict, List, Optional

from src.strategy.types.hashing import stable_hash
from src.strategy.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.strategy.memory.segment_memory_types import SegmentMemoryRecord
from src.strategy.memory.plan_memory_types import PlanMemoryRecord
from src.strategy.memory.drift_memory_types import DriftEvent
from src.strategy.memory.summarisation.summary_types import (
    SummaryMetadata,
    SegmentListSummary,
    SubgoalChainSummary,
    PlanSummary,
    SegmentChainSummary,
    DriftSummary,
)


# ---------------------------------------------------------------------------
# Fingerprint helpers — each hashes the fields that actually drive the summary
# ---------------------------------------------------------------------------

def _segment_list_fingerprint(records: List[SegmentMemoryRecord]) -> str:
    """Hash ordered (segment_id, created_at) pairs — catches reorder and content changes."""
    return stable_hash([[r.segment_id, r.created_at] for r in records])


def _subgoal_chain_fingerprint(records: List[SubgoalMemoryRecord]) -> str:
    """Hash ordered (subgoal_id, parent_id, state) tuples — catches reorder and state changes."""
    return stable_hash([[r.subgoal_id, r.parent_id, r.state] for r in records])


def _plan_fingerprint(record: PlanMemoryRecord) -> str:
    """Hash the fields that drive PlanSummary: segment count, created_at, has_metadata."""
    return stable_hash({
        "plan_id": record.plan_id,
        "segment_count": len(record.segments),
        "created_at": record.created_at,
        "has_metadata": bool(record.metadata),
    })


def _segment_chain_fingerprint(records: List[SegmentMemoryRecord]) -> str:
    """Hash ordered (segment_id, state) pairs — catches reorder and state changes."""
    return stable_hash([[r.segment_id, r.state] for r in records])


def _drift_fingerprint(events: List[DriftEvent]) -> str:
    """Hash all fields of each event that affect the drift summary result."""
    return stable_hash([
        {
            "timestamp": e.timestamp,
            "subgoal_id": e.subgoal_id,
            "segment_id": e.segment_id,
            "step_id": e.step_id,
            "signal_type": e.signal_type,
            "confidence": e.confidence,
        }
        for e in events
    ])


def _make_meta(now: int, count: int, fingerprint: str) -> SummaryMetadata:
    return SummaryMetadata(
        generated_at=now,
        source_count=count,
        source_fingerprint=fingerprint,
    )


# ---------------------------------------------------------------------------
# SummarisationRules
# ---------------------------------------------------------------------------

class SummarisationRules:
    """
    Pure, deterministic, rule-based summarisation over Stratum-2 memory records.

    All methods are pure functions with no side effects, no LLM calls, and no
    semantic inference. Summaries are structural — they describe shape, not meaning.

    Summaries MUST be stored separately from the original records they describe.
    Use SummaryMetadata.source_fingerprint and is_stale() to detect when a
    cached summary no longer reflects the current state of the source records.
    """

    # ------------------------------------------------------------------
    # Structural summarisation
    # ------------------------------------------------------------------

    def summarise_segment_list(
        self,
        records: List[SegmentMemoryRecord],
        now: int,
    ) -> SegmentListSummary:
        """
        Collapse a list of segments into a structural summary.

        Records are sorted by (created_at, segment_id) for deterministic ordering.
        """
        sorted_records = sorted(records, key=lambda r: (r.created_at, r.segment_id))
        fingerprint = _segment_list_fingerprint(sorted_records)
        return SegmentListSummary(
            count=len(sorted_records),
            first_id=sorted_records[0].segment_id if sorted_records else None,
            last_id=sorted_records[-1].segment_id if sorted_records else None,
            meta=_make_meta(now, len(sorted_records), fingerprint),
        )

    def summarise_subgoal_chain(
        self,
        records: List[SubgoalMemoryRecord],
        now: int,
    ) -> SubgoalChainSummary:
        """
        Collapse a subgoal chain into a structural summary.

        Records MUST be passed in root→leaf order (as returned by
        SubgoalMemory.get_chain()). The fingerprint includes parent_id and
        state so reordering or state changes are detected as stale.
        """
        fingerprint = _subgoal_chain_fingerprint(records)
        return SubgoalChainSummary(
            depth=len(records),
            root_id=records[0].subgoal_id if records else None,
            leaf_id=records[-1].subgoal_id if records else None,
            meta=_make_meta(now, len(records), fingerprint),
        )

    # ------------------------------------------------------------------
    # Plan summarisation
    # ------------------------------------------------------------------

    def summarise_plan(
        self,
        record: PlanMemoryRecord,
        now: int,
    ) -> PlanSummary:
        """
        Summarise plan metadata. Does NOT rewrite or compress plan content.
        """
        fingerprint = _plan_fingerprint(record)
        return PlanSummary(
            segment_count=len(record.segments),
            created_at=record.created_at,
            has_metadata=bool(record.metadata),
            meta=_make_meta(now, 1, fingerprint),
        )

    # ------------------------------------------------------------------
    # Segment summarisation
    # ------------------------------------------------------------------

    def summarise_segment_chain(
        self,
        records: List[SegmentMemoryRecord],
        now: int,
    ) -> SegmentChainSummary:
        """
        Summarise a segment chain without rewriting steps.

        Records must be in chain order (root→leaf). terminal_state reflects
        the last record's state, defaulting to "pending" when state is None
        (SegmentMemoryRecord.state is always None until segment state is added).
        """
        terminal = (
            records[-1].state
            if records and records[-1].state is not None
            else "pending"
        )
        fingerprint = _segment_chain_fingerprint(records)
        return SegmentChainSummary(
            chain_length=len(records),
            terminal_state=terminal,
            meta=_make_meta(now, len(records), fingerprint),
        )

    # ------------------------------------------------------------------
    # Drift summarisation
    # ------------------------------------------------------------------

    def summarise_drift(
        self,
        events: List[DriftEvent],
        now: int,
    ) -> DriftSummary:
        """
        Summarise drift frequency and signal types.

        signal_type_counts is sorted by key for deterministic output.
        last_drift_at is the maximum timestamp across all events.
        """
        counts: Dict[str, int] = {}
        for e in events:
            counts[e.signal_type] = counts.get(e.signal_type, 0) + 1

        last_at: Optional[int] = max((e.timestamp for e in events), default=None)
        fingerprint = _drift_fingerprint(events)

        return DriftSummary(
            drift_events=len(events),
            last_drift_at=last_at,
            signal_type_counts=dict(sorted(counts.items())),
            meta=_make_meta(now, len(events), fingerprint),
        )

    # ------------------------------------------------------------------
    # Staleness detection
    # ------------------------------------------------------------------

    def is_stale(
        self,
        meta: SummaryMetadata,
        current_count: int,
        current_fingerprint: str,
    ) -> bool:
        """
        Return True if the summary no longer reflects the current source records.

        A summary is stale when either:
        - the source record count has changed, or
        - the source fingerprint has changed (content/order changed with same count).
        """
        return (
            meta.source_count != current_count
            or meta.source_fingerprint != current_fingerprint
        )
