"""
Phase 3.20.1 — ProjectMemory
==============================

Pure, deterministic in-memory store for project-level continuity data.

Stores recurring goals, preferred skills, known bad patterns, and domain
policies observed across episodes. All operations are deterministic — no LLM,
no I/O, no randomness.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.strategy.memory.project_memory_types import (
    ProjectBadPatternRecord,
    ProjectGoalRecord,
    ProjectMemorySnapshot,
    ProjectPolicyRecord,
    ProjectSkillRecord,
)


class ProjectMemory:
    """
    Pure in-memory store for project-level continuity data.

    Each of the four stores is keyed by its primary id field.
    All mutating operations return None; callers use snapshot() for
    persistence and load_snapshot() for restoration.
    """

    def __init__(self) -> None:
        self._goals: Dict[str, ProjectGoalRecord] = {}
        self._skills: Dict[str, ProjectSkillRecord] = {}
        self._bad_patterns: Dict[str, ProjectBadPatternRecord] = {}
        self._policies: Dict[str, ProjectPolicyRecord] = {}

    # ------------------------------------------------------------------
    # Goals
    # ------------------------------------------------------------------

    def add_goal(self, record: ProjectGoalRecord) -> None:
        """Store or overwrite a goal record."""
        self._goals[record.goal_id] = record

    def get_goal(self, goal_id: str) -> Optional[ProjectGoalRecord]:
        """Return the goal record for goal_id, or None."""
        return self._goals.get(goal_id)

    def find_goal_by_text(self, goal_text: str) -> Optional[ProjectGoalRecord]:
        """Return the first goal whose goal_text matches exactly, or None."""
        for record in self._goals.values():
            if record.goal_text == goal_text:
                return record
        return None

    def recurring_goals(self, min_frequency: int = 2) -> List[ProjectGoalRecord]:
        """
        Return goals seen at least min_frequency times, sorted by frequency
        descending, then goal_id ascending for determinism.
        """
        return sorted(
            [r for r in self._goals.values() if r.frequency >= min_frequency],
            key=lambda r: (-r.frequency, r.goal_id),
        )

    def all_goals(self) -> List[ProjectGoalRecord]:
        """Return all goal records sorted by last_seen descending, then goal_id."""
        return sorted(
            self._goals.values(),
            key=lambda r: (-r.last_seen, r.goal_id),
        )

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------

    def add_skill(self, record: ProjectSkillRecord) -> None:
        """Store or overwrite a skill record."""
        self._skills[record.skill_id] = record

    def get_skill(self, skill_id: str) -> Optional[ProjectSkillRecord]:
        """Return the skill record for skill_id, or None."""
        return self._skills.get(skill_id)

    def find_skill_by_name(self, capability_name: str) -> Optional[ProjectSkillRecord]:
        """Return the first skill whose capability_name matches exactly, or None."""
        for record in self._skills.values():
            if record.capability_name == capability_name:
                return record
        return None

    def preferred_skills(
        self, min_success_rate: float = 0.7, min_samples: int = 1
    ) -> List[ProjectSkillRecord]:
        """
        Return skills meeting both the success-rate and sample thresholds,
        sorted by success_rate descending, then skill_id ascending.
        """
        return sorted(
            [
                r
                for r in self._skills.values()
                if r.success_rate >= min_success_rate and r.sample_count >= min_samples
            ],
            key=lambda r: (-r.success_rate, r.skill_id),
        )

    def all_skills(self) -> List[ProjectSkillRecord]:
        """Return all skill records sorted by success_rate descending, then skill_id."""
        return sorted(
            self._skills.values(),
            key=lambda r: (-r.success_rate, r.skill_id),
        )

    # ------------------------------------------------------------------
    # Bad patterns
    # ------------------------------------------------------------------

    def add_bad_pattern(self, record: ProjectBadPatternRecord) -> None:
        """Store or overwrite a bad-pattern record."""
        self._bad_patterns[record.pattern_id] = record

    def get_bad_pattern(self, pattern_id: str) -> Optional[ProjectBadPatternRecord]:
        """Return the bad-pattern record for pattern_id, or None."""
        return self._bad_patterns.get(pattern_id)

    def find_bad_pattern_by_capability(
        self, capability_pattern: str
    ) -> Optional[ProjectBadPatternRecord]:
        """Return the first bad-pattern whose capability_pattern matches exactly, or None."""
        for record in self._bad_patterns.values():
            if record.capability_pattern == capability_pattern:
                return record
        return None

    def known_bad_patterns(
        self, min_failures: int = 1
    ) -> List[ProjectBadPatternRecord]:
        """
        Return bad patterns with at least min_failures failures, sorted by
        failure_count descending, then pattern_id ascending.
        """
        return sorted(
            [r for r in self._bad_patterns.values() if r.failure_count >= min_failures],
            key=lambda r: (-r.failure_count, r.pattern_id),
        )

    def all_bad_patterns(self) -> List[ProjectBadPatternRecord]:
        """Return all bad-pattern records sorted by failure_count descending, then pattern_id."""
        return sorted(
            self._bad_patterns.values(),
            key=lambda r: (-r.failure_count, r.pattern_id),
        )

    # ------------------------------------------------------------------
    # Policies
    # ------------------------------------------------------------------

    def add_policy(self, record: ProjectPolicyRecord) -> None:
        """Store or overwrite a policy record."""
        self._policies[record.policy_id] = record

    def get_policy(self, policy_id: str) -> Optional[ProjectPolicyRecord]:
        """Return the policy record for policy_id, or None."""
        return self._policies.get(policy_id)

    def domain_policies(self) -> List[ProjectPolicyRecord]:
        """Return all policies sorted by created_at ascending, then policy_id."""
        return sorted(
            self._policies.values(),
            key=lambda r: (r.created_at, r.policy_id),
        )

    # ------------------------------------------------------------------
    # Counts
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        """Return the total number of records across all four stores."""
        return (
            len(self._goals)
            + len(self._skills)
            + len(self._bad_patterns)
            + len(self._policies)
        )

    # ------------------------------------------------------------------
    # Snapshotting
    # ------------------------------------------------------------------

    def snapshot(self) -> ProjectMemorySnapshot:
        """Return an immutable snapshot of all four stores."""
        return ProjectMemorySnapshot(
            goals=tuple(
                sorted(self._goals.values(), key=lambda r: (-r.last_seen, r.goal_id))
            ),
            skills=tuple(
                sorted(
                    self._skills.values(),
                    key=lambda r: (-r.success_rate, r.skill_id),
                )
            ),
            bad_patterns=tuple(
                sorted(
                    self._bad_patterns.values(),
                    key=lambda r: (-r.failure_count, r.pattern_id),
                )
            ),
            policies=tuple(
                sorted(
                    self._policies.values(),
                    key=lambda r: (r.created_at, r.policy_id),
                )
            ),
        )

    def load_snapshot(self, snapshot: ProjectMemorySnapshot) -> None:
        """Replace all stores with the contents of a snapshot."""
        self._goals = {r.goal_id: r for r in snapshot.goals}
        self._skills = {r.skill_id: r for r in snapshot.skills}
        self._bad_patterns = {r.pattern_id: r for r in snapshot.bad_patterns}
        self._policies = {r.policy_id: r for r in snapshot.policies}

    def clear(self) -> None:
        """Remove all records from all stores."""
        self._goals.clear()
        self._skills.clear()
        self._bad_patterns.clear()
        self._policies.clear()
