"""
Phase 3.20.2 — UserProfile Memory Types
=========================================

Frozen dataclasses for user-level continuity memory.

All types are pure S2 — no LLM, no I/O, no randomness.
JSON-serialisable and immutable by construction.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class UserPreferenceRecord:
    """
    A single user preference as a key/value pair.

    key:        Preference name (e.g. "output_format", "verbosity").
    value:      Preference value (plain string).
    confidence: How confident the system is in this preference [0.0, 1.0].
                1.0 = explicitly stated by user; lower values inferred.
    updated_at: Logical timestamp (ms) of the most recent update.
    metadata:   Arbitrary JSON-pure payload.
    """

    key: str
    value: str
    confidence: float
    updated_at: int
    metadata: Dict[str, Any]

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("key must be non-empty")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )
        if self.updated_at < 0:
            raise ValueError(f"updated_at must be >= 0, got {self.updated_at}")
        object.__setattr__(self, "metadata", copy.deepcopy(self.metadata))


@dataclass(frozen=True)
class UserConstraintRecord:
    """
    A constraint expressed or inferred from user behaviour.

    constraint_id:   Unique identifier for this constraint entry.
    constraint_type: Category of constraint (e.g. "max_steps", "avoid_tool",
                     "require_confirmation").
    value:           Constraint value as a plain string.
    created_at:      Logical timestamp (ms) when this constraint was first recorded.
    metadata:        Arbitrary JSON-pure payload.
    """

    constraint_id: str
    constraint_type: str
    value: str
    created_at: int
    metadata: Dict[str, Any]

    def __post_init__(self) -> None:
        if not self.constraint_id:
            raise ValueError("constraint_id must be non-empty")
        if not self.constraint_type:
            raise ValueError("constraint_type must be non-empty")
        if self.created_at < 0:
            raise ValueError(f"created_at must be >= 0, got {self.created_at}")
        object.__setattr__(self, "metadata", copy.deepcopy(self.metadata))


@dataclass(frozen=True)
class UserBehaviouralPatternRecord:
    """
    An observed pattern in how the user interacts with the agent.

    pattern_id:   Unique identifier for this pattern entry.
    pattern_type: Category label (e.g. "prefers_detail", "iterative_refinement",
                  "explicit_confirmation").
    description:  Human-readable description of the pattern.
    frequency:    Number of episodes in which this pattern was observed.
    last_seen:    Logical timestamp (ms) of the most recent observation.
    metadata:     Arbitrary JSON-pure payload.
    """

    pattern_id: str
    pattern_type: str
    description: str
    frequency: int
    last_seen: int
    metadata: Dict[str, Any]

    def __post_init__(self) -> None:
        if not self.pattern_id:
            raise ValueError("pattern_id must be non-empty")
        if not self.pattern_type:
            raise ValueError("pattern_type must be non-empty")
        if not self.description:
            raise ValueError("description must be non-empty")
        if self.frequency < 1:
            raise ValueError(f"frequency must be >= 1, got {self.frequency}")
        if self.last_seen < 0:
            raise ValueError(f"last_seen must be >= 0, got {self.last_seen}")
        object.__setattr__(self, "metadata", copy.deepcopy(self.metadata))


@dataclass(frozen=True)
class UserProfileSnapshot:
    """
    Immutable snapshot of all three UserProfileMemory stores.

    preferences:          Tuple of UserPreferenceRecord, sorted by key asc.
    constraints:          Tuple of UserConstraintRecord, sorted by created_at asc then constraint_id.
    behavioural_patterns: Tuple of UserBehaviouralPatternRecord, sorted by frequency desc then pattern_id.
    """

    preferences: Tuple[UserPreferenceRecord, ...]
    constraints: Tuple[UserConstraintRecord, ...]
    behavioural_patterns: Tuple[UserBehaviouralPatternRecord, ...]
