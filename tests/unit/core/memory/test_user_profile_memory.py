"""
Tests for Phase 3.20.2 — UserProfileMemory
"""

from __future__ import annotations

import pytest

from src.core.memory.user_profile_memory import UserProfileMemory
from src.core.memory.user_profile_types import (
    UserBehaviouralPatternRecord,
    UserConstraintRecord,
    UserPreferenceRecord,
    UserProfileSnapshot,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pref(key="output_format", value="json", confidence=1.0, updated_at=1000):
    return UserPreferenceRecord(
        key=key, value=value, confidence=confidence, updated_at=updated_at, metadata={}
    )


def _constraint(
    constraint_id="con-1",
    constraint_type="max_steps",
    value="10",
    created_at=1000,
):
    return UserConstraintRecord(
        constraint_id=constraint_id,
        constraint_type=constraint_type,
        value=value,
        created_at=created_at,
        metadata={},
    )


def _pattern(
    pattern_id="pat-1",
    pattern_type="prefers_detail",
    description="User prefers detailed output",
    frequency=3,
    last_seen=2000,
):
    return UserBehaviouralPatternRecord(
        pattern_id=pattern_id,
        pattern_type=pattern_type,
        description=description,
        frequency=frequency,
        last_seen=last_seen,
        metadata={},
    )


# ===========================================================================
# Type validation
# ===========================================================================

class TestUserPreferenceRecordValidation:
    def test_empty_key_raises(self):
        with pytest.raises(ValueError, match="key"):
            UserPreferenceRecord(key="", value="v", confidence=1.0, updated_at=0, metadata={})

    def test_confidence_above_one_raises(self):
        with pytest.raises(ValueError, match="confidence"):
            UserPreferenceRecord(key="k", value="v", confidence=1.5, updated_at=0, metadata={})

    def test_negative_confidence_raises(self):
        with pytest.raises(ValueError, match="confidence"):
            UserPreferenceRecord(key="k", value="v", confidence=-0.1, updated_at=0, metadata={})

    def test_negative_updated_at_raises(self):
        with pytest.raises(ValueError, match="updated_at"):
            UserPreferenceRecord(key="k", value="v", confidence=1.0, updated_at=-1, metadata={})

    def test_metadata_deep_copied(self):
        mutable = {"x": [1]}
        rec = UserPreferenceRecord(key="k", value="v", confidence=1.0, updated_at=0, metadata=mutable)
        mutable["x"].append(2)
        assert rec.metadata == {"x": [1]}

    def test_record_is_frozen(self):
        rec = _pref()
        with pytest.raises(Exception):
            rec.value = "changed"  # type: ignore[misc]


class TestUserConstraintRecordValidation:
    def test_empty_constraint_id_raises(self):
        with pytest.raises(ValueError, match="constraint_id"):
            UserConstraintRecord(
                constraint_id="", constraint_type="t", value="v", created_at=0, metadata={}
            )

    def test_empty_constraint_type_raises(self):
        with pytest.raises(ValueError, match="constraint_type"):
            UserConstraintRecord(
                constraint_id="c-1", constraint_type="", value="v", created_at=0, metadata={}
            )


class TestUserBehaviouralPatternRecordValidation:
    def test_empty_pattern_id_raises(self):
        with pytest.raises(ValueError, match="pattern_id"):
            UserBehaviouralPatternRecord(
                pattern_id="", pattern_type="t", description="d",
                frequency=1, last_seen=0, metadata={}
            )

    def test_zero_frequency_raises(self):
        with pytest.raises(ValueError, match="frequency"):
            UserBehaviouralPatternRecord(
                pattern_id="p-1", pattern_type="t", description="d",
                frequency=0, last_seen=0, metadata={}
            )

    def test_empty_description_raises(self):
        with pytest.raises(ValueError, match="description"):
            UserBehaviouralPatternRecord(
                pattern_id="p-1", pattern_type="t", description="",
                frequency=1, last_seen=0, metadata={}
            )


# ===========================================================================
# UserProfileMemory — Preferences
# ===========================================================================

class TestUserProfileMemoryPreferences:
    def test_set_and_get_preference(self):
        mem = UserProfileMemory()
        rec = _pref()
        mem.set_preference(rec)
        assert mem.get_preference("output_format") == rec

    def test_overwrite_preference(self):
        mem = UserProfileMemory()
        mem.set_preference(_pref(value="json"))
        mem.set_preference(_pref(value="yaml"))
        assert mem.get_preference("output_format").value == "yaml"

    def test_get_missing_preference_returns_none(self):
        mem = UserProfileMemory()
        assert mem.get_preference("nonexistent") is None

    def test_all_preferences_sorted_by_key(self):
        mem = UserProfileMemory()
        mem.set_preference(_pref(key="verbosity", value="high"))
        mem.set_preference(_pref(key="output_format", value="json"))
        mem.set_preference(_pref(key="auto_confirm", value="true"))
        result = mem.all_preferences()
        keys = [r.key for r in result]
        assert keys == sorted(keys)

    def test_remove_preference(self):
        mem = UserProfileMemory()
        mem.set_preference(_pref())
        mem.remove_preference("output_format")
        assert mem.get_preference("output_format") is None

    def test_remove_missing_preference_is_noop(self):
        mem = UserProfileMemory()
        mem.remove_preference("nonexistent")  # Should not raise


# ===========================================================================
# UserProfileMemory — Constraints
# ===========================================================================

class TestUserProfileMemoryConstraints:
    def test_add_and_get_constraint(self):
        mem = UserProfileMemory()
        rec = _constraint()
        mem.add_constraint(rec)
        assert mem.get_constraint("con-1") == rec

    def test_get_missing_constraint_returns_none(self):
        mem = UserProfileMemory()
        assert mem.get_constraint("nonexistent") is None

    def test_overwrite_constraint(self):
        mem = UserProfileMemory()
        mem.add_constraint(_constraint(value="10"))
        mem.add_constraint(_constraint(value="5"))
        assert mem.get_constraint("con-1").value == "5"

    def test_constraints_by_type(self):
        mem = UserProfileMemory()
        mem.add_constraint(_constraint(constraint_id="c-1", constraint_type="max_steps", value="10"))
        mem.add_constraint(_constraint(constraint_id="c-2", constraint_type="avoid_tool", value="rm"))
        mem.add_constraint(_constraint(constraint_id="c-3", constraint_type="max_steps", value="5"))
        result = mem.constraints_by_type("max_steps")
        assert len(result) == 2
        assert all(r.constraint_type == "max_steps" for r in result)

    def test_all_constraints_sorted_by_created_at(self):
        mem = UserProfileMemory()
        mem.add_constraint(_constraint(constraint_id="c-late", created_at=3000))
        mem.add_constraint(_constraint(constraint_id="c-early", created_at=100))
        result = mem.all_constraints()
        assert result[0].constraint_id == "c-early"


# ===========================================================================
# UserProfileMemory — Behavioural Patterns
# ===========================================================================

class TestUserProfileMemoryPatterns:
    def test_record_and_get_pattern(self):
        mem = UserProfileMemory()
        rec = _pattern()
        mem.record_pattern(rec)
        assert mem.get_pattern("pat-1") == rec

    def test_overwrite_pattern(self):
        mem = UserProfileMemory()
        mem.record_pattern(_pattern(frequency=1))
        mem.record_pattern(_pattern(frequency=5))
        assert mem.get_pattern("pat-1").frequency == 5

    def test_patterns_by_type(self):
        mem = UserProfileMemory()
        mem.record_pattern(_pattern(pattern_id="p-1", pattern_type="prefers_detail"))
        mem.record_pattern(_pattern(pattern_id="p-2", pattern_type="iterative", description="x"))
        mem.record_pattern(_pattern(pattern_id="p-3", pattern_type="prefers_detail", description="y"))
        result = mem.patterns_by_type("prefers_detail")
        assert len(result) == 2
        assert all(r.pattern_type == "prefers_detail" for r in result)

    def test_behavioural_patterns_min_frequency(self):
        mem = UserProfileMemory()
        mem.record_pattern(_pattern(pattern_id="p-rare", frequency=1))
        mem.record_pattern(_pattern(pattern_id="p-common", pattern_type="x", description="x", frequency=5))
        result = mem.behavioural_patterns(min_frequency=3)
        ids = [r.pattern_id for r in result]
        assert "p-common" in ids
        assert "p-rare" not in ids

    def test_behavioural_patterns_sorted_by_frequency_desc(self):
        mem = UserProfileMemory()
        mem.record_pattern(_pattern(pattern_id="p-1", frequency=2))
        mem.record_pattern(_pattern(pattern_id="p-2", pattern_type="x", description="x", frequency=7))
        mem.record_pattern(_pattern(pattern_id="p-3", pattern_type="y", description="y", frequency=4))
        result = mem.behavioural_patterns()
        freqs = [r.frequency for r in result]
        assert freqs == sorted(freqs, reverse=True)


# ===========================================================================
# UserProfileMemory — len and clear
# ===========================================================================

class TestUserProfileMemoryMetrics:
    def test_len_empty(self):
        assert len(UserProfileMemory()) == 0

    def test_len_counts_all_stores(self):
        mem = UserProfileMemory()
        mem.set_preference(_pref())
        mem.add_constraint(_constraint())
        mem.record_pattern(_pattern())
        assert len(mem) == 3

    def test_clear_empties_all(self):
        mem = UserProfileMemory()
        mem.set_preference(_pref())
        mem.add_constraint(_constraint())
        mem.record_pattern(_pattern())
        mem.clear()
        assert len(mem) == 0


# ===========================================================================
# Snapshot round-trip
# ===========================================================================

class TestUserProfileMemorySnapshot:
    def test_empty_snapshot(self):
        mem = UserProfileMemory()
        snap = mem.snapshot()
        assert snap.preferences == ()
        assert snap.constraints == ()
        assert snap.behavioural_patterns == ()

    def test_snapshot_and_restore(self):
        mem = UserProfileMemory()
        mem.set_preference(_pref())
        mem.add_constraint(_constraint())
        mem.record_pattern(_pattern())

        snap = mem.snapshot()
        mem2 = UserProfileMemory()
        mem2.load_snapshot(snap)

        assert mem2.get_preference("output_format") == mem.get_preference("output_format")
        assert mem2.get_constraint("con-1") == mem.get_constraint("con-1")
        assert mem2.get_pattern("pat-1") == mem.get_pattern("pat-1")

    def test_snapshot_is_typed(self):
        mem = UserProfileMemory()
        mem.set_preference(_pref())
        snap = mem.snapshot()
        assert isinstance(snap, UserProfileSnapshot)
        assert isinstance(snap.preferences[0], UserPreferenceRecord)

    def test_load_snapshot_replaces_existing(self):
        mem = UserProfileMemory()
        mem.set_preference(_pref(key="old_key"))
        empty_snap = UserProfileSnapshot(
            preferences=(), constraints=(), behavioural_patterns=()
        )
        mem.load_snapshot(empty_snap)
        assert mem.get_preference("old_key") is None

    def test_snapshot_preferences_sorted_by_key(self):
        mem = UserProfileMemory()
        mem.set_preference(_pref(key="zzz", value="last"))
        mem.set_preference(_pref(key="aaa", value="first"))
        snap = mem.snapshot()
        assert snap.preferences[0].key == "aaa"

    def test_snapshot_patterns_sorted_by_frequency_desc(self):
        mem = UserProfileMemory()
        mem.record_pattern(_pattern(pattern_id="p-low", frequency=1))
        mem.record_pattern(_pattern(pattern_id="p-high", pattern_type="x", description="x", frequency=9))
        snap = mem.snapshot()
        assert snap.behavioural_patterns[0].frequency >= snap.behavioural_patterns[1].frequency
