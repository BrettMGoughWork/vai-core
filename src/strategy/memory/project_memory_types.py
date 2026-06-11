"""
Phase 3.20.1 — ProjectMemory Types
====================================

Frozen dataclasses for project-level continuity memory.

All types are pure S2 — no LLM, no I/O, no randomness.
JSON-serialisable and immutable by construction.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class ProjectGoalRecord:
    """
    A recurring goal observed across episodes.

    goal_id:     Unique identifier for this goal entry.
    goal_text:   Canonical text of the recurring goal.
    frequency:   Number of episodes in which this goal has been observed.
    first_seen:  Logical timestamp (ms) of the first observation.
    last_seen:   Logical timestamp (ms) of the most recent observation.
    metadata:    Arbitrary JSON-pure payload.
    """

    goal_id: str
    goal_text: str
    frequency: int
    first_seen: int
    last_seen: int
    metadata: Dict[str, Any]

    def __post_init__(self) -> None:
        if not self.goal_id:
            raise ValueError("goal_id must be non-empty")
        if not self.goal_text:
            raise ValueError("goal_text must be non-empty")
        if self.frequency < 1:
            raise ValueError(f"frequency must be >= 1, got {self.frequency}")
        if self.first_seen < 0:
            raise ValueError(f"first_seen must be >= 0, got {self.first_seen}")
        if self.last_seen < self.first_seen:
            raise ValueError("last_seen must be >= first_seen")
        object.__setattr__(self, "metadata", copy.deepcopy(self.metadata))


@dataclass(frozen=True)
class ProjectSkillRecord:
    """
    A skill (capability) identified as preferred for this project.

    skill_id:        Unique identifier for this skill entry.
    capability_name: Canonical capability name / pattern (e.g. "stdlib.file.read").
    success_rate:    Historical success rate [0.0, 1.0].
    sample_count:    Number of episodes that informed this rate.
    last_seen:       Logical timestamp (ms) of the most recent successful use.
    metadata:        Arbitrary JSON-pure payload.
    """

    skill_id: str
    capability_name: str
    success_rate: float
    sample_count: int
    last_seen: int
    metadata: Dict[str, Any]

    def __post_init__(self) -> None:
        if not self.skill_id:
            raise ValueError("skill_id must be non-empty")
        if not self.capability_name:
            raise ValueError("capability_name must be non-empty")
        if not (0.0 <= self.success_rate <= 1.0):
            raise ValueError(
                f"success_rate must be in [0.0, 1.0], got {self.success_rate}"
            )
        if self.sample_count < 1:
            raise ValueError(f"sample_count must be >= 1, got {self.sample_count}")
        if self.last_seen < 0:
            raise ValueError(f"last_seen must be >= 0, got {self.last_seen}")
        object.__setattr__(self, "metadata", copy.deepcopy(self.metadata))


@dataclass(frozen=True)
class ProjectBadPatternRecord:
    """
    A capability pattern known to cause failures in this project.

    pattern_id:          Unique identifier for this bad-pattern entry.
    capability_pattern:  The problematic capability name / chain pattern.
    failure_count:       Number of times this pattern has caused failure.
    last_seen:           Logical timestamp (ms) of the most recent failure.
    metadata:            Arbitrary JSON-pure payload.
    """

    pattern_id: str
    capability_pattern: str
    failure_count: int
    last_seen: int
    metadata: Dict[str, Any]

    def __post_init__(self) -> None:
        if not self.pattern_id:
            raise ValueError("pattern_id must be non-empty")
        if not self.capability_pattern:
            raise ValueError("capability_pattern must be non-empty")
        if self.failure_count < 1:
            raise ValueError(
                f"failure_count must be >= 1, got {self.failure_count}"
            )
        if self.last_seen < 0:
            raise ValueError(f"last_seen must be >= 0, got {self.last_seen}")
        object.__setattr__(self, "metadata", copy.deepcopy(self.metadata))


@dataclass(frozen=True)
class ProjectPolicyRecord:
    """
    A domain-level policy or constraint for this project.

    policy_id:   Unique identifier for this policy entry.
    policy_text: Human-readable policy statement.
    source:      Where this policy originated (e.g. "user", "repair_learning").
    created_at:  Logical timestamp (ms) when this policy was recorded.
    metadata:    Arbitrary JSON-pure payload.
    """

    policy_id: str
    policy_text: str
    source: str
    created_at: int
    metadata: Dict[str, Any]

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise ValueError("policy_id must be non-empty")
        if not self.policy_text:
            raise ValueError("policy_text must be non-empty")
        if not self.source:
            raise ValueError("source must be non-empty")
        if self.created_at < 0:
            raise ValueError(f"created_at must be >= 0, got {self.created_at}")
        object.__setattr__(self, "metadata", copy.deepcopy(self.metadata))


@dataclass(frozen=True)
class ProjectMemorySnapshot:
    """
    Immutable snapshot of all four ProjectMemory stores.

    goals:        Tuple of ProjectGoalRecord, sorted by last_seen desc then goal_id.
    skills:       Tuple of ProjectSkillRecord, sorted by success_rate desc then skill_id.
    bad_patterns: Tuple of ProjectBadPatternRecord, sorted by failure_count desc then pattern_id.
    policies:     Tuple of ProjectPolicyRecord, sorted by created_at asc then policy_id.
    """

    goals: Tuple[ProjectGoalRecord, ...]
    skills: Tuple[ProjectSkillRecord, ...]
    bad_patterns: Tuple[ProjectBadPatternRecord, ...]
    policies: Tuple[ProjectPolicyRecord, ...]
