"""
Phase 3.20.2 — UserProfileMemory
==================================

Pure, deterministic in-memory store for user-level continuity data.

Stores user preferences, constraints, and behavioural patterns observed across
episodes. All operations are deterministic — no LLM, no I/O, no randomness.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.strategy.memory.user_profile_types import (
    UserBehaviouralPatternRecord,
    UserConstraintRecord,
    UserPreferenceRecord,
    UserProfileSnapshot,
)


class UserProfileMemory:
    """
    Pure in-memory store for user-level continuity data.

    Preferences are keyed by key string (last write wins).
    Constraints are keyed by constraint_id.
    Behavioural patterns are keyed by pattern_id.
    """

    def __init__(self) -> None:
        self._preferences: Dict[str, UserPreferenceRecord] = {}
        self._constraints: Dict[str, UserConstraintRecord] = {}
        self._patterns: Dict[str, UserBehaviouralPatternRecord] = {}

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------

    def set_preference(self, record: UserPreferenceRecord) -> None:
        """Store or overwrite a preference (keyed by record.key)."""
        self._preferences[record.key] = record

    def get_preference(self, key: str) -> Optional[UserPreferenceRecord]:
        """Return the preference for key, or None."""
        return self._preferences.get(key)

    def all_preferences(self) -> List[UserPreferenceRecord]:
        """Return all preferences sorted by key ascending."""
        return sorted(self._preferences.values(), key=lambda r: r.key)

    def remove_preference(self, key: str) -> None:
        """Remove the preference for key. No-op if not present."""
        self._preferences.pop(key, None)

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    def add_constraint(self, record: UserConstraintRecord) -> None:
        """Store or overwrite a constraint record."""
        self._constraints[record.constraint_id] = record

    def get_constraint(self, constraint_id: str) -> Optional[UserConstraintRecord]:
        """Return the constraint for constraint_id, or None."""
        return self._constraints.get(constraint_id)

    def constraints_by_type(self, constraint_type: str) -> List[UserConstraintRecord]:
        """Return all constraints of the given type, sorted by created_at asc, then constraint_id."""
        return sorted(
            [r for r in self._constraints.values() if r.constraint_type == constraint_type],
            key=lambda r: (r.created_at, r.constraint_id),
        )

    def all_constraints(self) -> List[UserConstraintRecord]:
        """Return all constraints sorted by created_at ascending, then constraint_id."""
        return sorted(
            self._constraints.values(),
            key=lambda r: (r.created_at, r.constraint_id),
        )

    # ------------------------------------------------------------------
    # Behavioural patterns
    # ------------------------------------------------------------------

    def record_pattern(self, record: UserBehaviouralPatternRecord) -> None:
        """Store or overwrite a behavioural pattern record."""
        self._patterns[record.pattern_id] = record

    def get_pattern(self, pattern_id: str) -> Optional[UserBehaviouralPatternRecord]:
        """Return the pattern for pattern_id, or None."""
        return self._patterns.get(pattern_id)

    def patterns_by_type(
        self, pattern_type: str
    ) -> List[UserBehaviouralPatternRecord]:
        """Return all patterns of the given type, sorted by frequency desc, then pattern_id."""
        return sorted(
            [r for r in self._patterns.values() if r.pattern_type == pattern_type],
            key=lambda r: (-r.frequency, r.pattern_id),
        )

    def behavioural_patterns(
        self, min_frequency: int = 1
    ) -> List[UserBehaviouralPatternRecord]:
        """
        Return patterns seen at least min_frequency times, sorted by frequency
        descending, then pattern_id ascending.
        """
        return sorted(
            [r for r in self._patterns.values() if r.frequency >= min_frequency],
            key=lambda r: (-r.frequency, r.pattern_id),
        )

    # ------------------------------------------------------------------
    # Counts
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        """Return total records across all three stores."""
        return len(self._preferences) + len(self._constraints) + len(self._patterns)

    # ------------------------------------------------------------------
    # Snapshotting
    # ------------------------------------------------------------------

    def snapshot(self) -> UserProfileSnapshot:
        """Return an immutable snapshot of all three stores."""
        return UserProfileSnapshot(
            preferences=tuple(
                sorted(self._preferences.values(), key=lambda r: r.key)
            ),
            constraints=tuple(
                sorted(
                    self._constraints.values(),
                    key=lambda r: (r.created_at, r.constraint_id),
                )
            ),
            behavioural_patterns=tuple(
                sorted(
                    self._patterns.values(),
                    key=lambda r: (-r.frequency, r.pattern_id),
                )
            ),
        )

    def load_snapshot(self, snapshot: UserProfileSnapshot) -> None:
        """Replace all stores with the contents of a snapshot."""
        self._preferences = {r.key: r for r in snapshot.preferences}
        self._constraints = {r.constraint_id: r for r in snapshot.constraints}
        self._patterns = {r.pattern_id: r for r in snapshot.behavioural_patterns}

    def clear(self) -> None:
        """Remove all records from all stores."""
        self._preferences.clear()
        self._constraints.clear()
        self._patterns.clear()
