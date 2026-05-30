from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class SummaryMetadata:
    """
    Staleness-detection metadata common to all summary types.

    generated_at:       logical ms timestamp supplied by caller.
    source_count:       number of source records at generation time.
    source_fingerprint: stable hash of the canonical inputs that drove the
                        summary result. A changed fingerprint means the summary
                        is stale even if the record count is unchanged.
    """
    generated_at: int
    source_count: int
    source_fingerprint: str


@dataclass(frozen=True)
class SegmentListSummary:
    """
    Structural summary of a list of segments.

    count:    total number of segments.
    first_id: segment_id of the earliest segment (by created_at, then segment_id).
    last_id:  segment_id of the latest segment.
    """
    count: int
    first_id: Optional[str]
    last_id: Optional[str]
    meta: SummaryMetadata


@dataclass(frozen=True)
class SubgoalChainSummary:
    """
    Structural summary of a subgoal chain (root → leaf).

    depth:   number of records in the chain.
    root_id: subgoal_id of the first (root) record.
    leaf_id: subgoal_id of the last (leaf) record.

    Records are expected in root→leaf order (as returned by SubgoalMemory.get_chain()).
    """
    depth: int
    root_id: Optional[str]
    leaf_id: Optional[str]
    meta: SummaryMetadata


@dataclass(frozen=True)
class PlanSummary:
    """
    Structural summary of plan metadata (not plan content).

    segment_count: number of segment IDs referenced by the plan.
    created_at:    plan creation timestamp (ISO string, unmodified).
    has_metadata:  True if the plan's metadata dict is non-empty.
    """
    segment_count: int
    created_at: str
    has_metadata: bool
    meta: SummaryMetadata


@dataclass(frozen=True)
class SegmentChainSummary:
    """
    Structural summary of a segment chain.

    chain_length:   number of records in the chain.
    terminal_state: state of the final segment record, or "pending" if None.
                    Currently always "pending" — SegmentMemoryRecord.state is
                    always None (PlanSegment carries no lifecycle state).
                    Reserved for future use when segment state is introduced.
    """
    chain_length: int
    terminal_state: str
    meta: SummaryMetadata


@dataclass(frozen=True)
class DriftSummary:
    """
    Structural summary of drift events.

    drift_events:      total number of events.
    last_drift_at:     timestamp (ms) of the most recent event, or None if empty.
    signal_type_counts: count of events per signal_type, sorted by key.
    """
    drift_events: int
    last_drift_at: Optional[int]
    signal_type_counts: Dict[str, int]
    meta: SummaryMetadata

    def __post_init__(self) -> None:
        # Deep-copy to prevent external mutation of the stored dict
        object.__setattr__(
            self, "signal_type_counts", copy.deepcopy(self.signal_type_counts)
        )
