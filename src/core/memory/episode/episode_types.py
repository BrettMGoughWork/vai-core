"""
Phase 3.20.3 — Episode Types
==============================

Frozen dataclasses and constants for the episode boundary system.

All types are pure S2 — no LLM, no I/O, no randomness.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Episode end-reason constants (string-based, following project convention)
# ---------------------------------------------------------------------------

EPISODE_END_COMPLETED = "completed"
EPISODE_END_ABANDONED = "abandoned"
EPISODE_END_TIMEOUT = "timeout"

VALID_END_REASONS = frozenset(
    {EPISODE_END_COMPLETED, EPISODE_END_ABANDONED, EPISODE_END_TIMEOUT}
)

VALID_OUTCOMES = frozenset({"success", "partial_success", "failure", "unknown"})


# ---------------------------------------------------------------------------
# EpisodeRecord
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EpisodeRecord:
    """
    Lifecycle record for a single episode.

    An episode corresponds to one user goal/request cycle from start to
    completion, abandonment, or timeout.

    episode_id:  Unique identifier for this episode.
    started_at:  Logical timestamp (ms) when the episode began.
    ended_at:    Logical timestamp (ms) when the episode ended, or None if
                 still active.
    end_reason:  One of VALID_END_REASONS, or None if still active.
    outcome:     One of VALID_OUTCOMES, or None if still active.
    topics:      Ordered tuple of topic strings observed during this episode.
    skills_used: Ordered tuple of capability names used during this episode.
    drift_count: Number of drift events detected in this episode.
    metadata:    Arbitrary JSON-pure payload.
    """

    episode_id: str
    started_at: int
    ended_at: Optional[int]
    end_reason: Optional[str]
    outcome: Optional[str]
    topics: Tuple[str, ...]
    skills_used: Tuple[str, ...]
    drift_count: int
    metadata: Dict[str, Any]

    def __post_init__(self) -> None:
        if not self.episode_id:
            raise ValueError("episode_id must be non-empty")
        if self.started_at < 0:
            raise ValueError(f"started_at must be >= 0, got {self.started_at}")
        if self.ended_at is not None:
            if self.ended_at < self.started_at:
                raise ValueError("ended_at must be >= started_at")
        if self.end_reason is not None and self.end_reason not in VALID_END_REASONS:
            raise ValueError(
                f"end_reason must be one of {sorted(VALID_END_REASONS)}, "
                f"got {self.end_reason!r}"
            )
        if self.outcome is not None and self.outcome not in VALID_OUTCOMES:
            raise ValueError(
                f"outcome must be one of {sorted(VALID_OUTCOMES)}, "
                f"got {self.outcome!r}"
            )
        if self.drift_count < 0:
            raise ValueError(f"drift_count must be >= 0, got {self.drift_count}")
        object.__setattr__(self, "metadata", copy.deepcopy(self.metadata))

    @property
    def is_active(self) -> bool:
        """True if the episode has not yet ended."""
        return self.ended_at is None


# ---------------------------------------------------------------------------
# EpisodeSummary
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EpisodeSummary:
    """
    Structural summary of a completed episode.

    Produced by EpisodeBoundaryManager.summarise() from the episode's memory
    records. All fields are deterministic aggregates — no LLM involved.

    episode_id:          Source episode identifier.
    outcome:             Final outcome of the episode.
    topic_counts:        Mapping of topic → occurrence count, sorted by key.
    skill_success_rates: Mapping of capability_name → success_rate [0.0, 1.0].
    drift_events:        Total drift events detected.
    dominant_topics:     Ordered tuple of topics by descending occurrence count.
    preferred_skills:    Capability names with success_rate >= success_threshold.
    bad_patterns:        Capability names that only failed (success_rate == 0.0)
                         and were called at least once.
    generated_at:        Logical timestamp (ms) when this summary was produced.
    source_record_count: Number of SemanticMemoryRecords that fed this summary.
    """

    episode_id: str
    outcome: str
    topic_counts: Dict[str, int]
    skill_success_rates: Dict[str, float]
    drift_events: int
    dominant_topics: Tuple[str, ...]
    preferred_skills: Tuple[str, ...]
    bad_patterns: Tuple[str, ...]
    generated_at: int
    source_record_count: int

    def __post_init__(self) -> None:
        if not self.episode_id:
            raise ValueError("episode_id must be non-empty")
        if self.outcome not in VALID_OUTCOMES:
            raise ValueError(
                f"outcome must be one of {sorted(VALID_OUTCOMES)}, "
                f"got {self.outcome!r}"
            )
        if self.drift_events < 0:
            raise ValueError(f"drift_events must be >= 0, got {self.drift_events}")
        if self.generated_at < 0:
            raise ValueError(f"generated_at must be >= 0, got {self.generated_at}")
        if self.source_record_count < 0:
            raise ValueError(
                f"source_record_count must be >= 0, got {self.source_record_count}"
            )
        object.__setattr__(
            self, "topic_counts", copy.deepcopy(self.topic_counts)
        )
        object.__setattr__(
            self, "skill_success_rates", copy.deepcopy(self.skill_success_rates)
        )
