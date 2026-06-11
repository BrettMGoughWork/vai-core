"""
Tests for Phase 3.20.1 — ProjectMemory
"""

from __future__ import annotations

import pytest

from src.strategy.memory.project_memory import ProjectMemory
from src.strategy.memory.project_memory_types import (
    ProjectBadPatternRecord,
    ProjectGoalRecord,
    ProjectMemorySnapshot,
    ProjectPolicyRecord,
    ProjectSkillRecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _goal(
    goal_id="g-1",
    goal_text="deploy service",
    frequency=1,
    first_seen=1000,
    last_seen=2000,
):
    return ProjectGoalRecord(
        goal_id=goal_id,
        goal_text=goal_text,
        frequency=frequency,
        first_seen=first_seen,
        last_seen=last_seen,
        metadata={},
    )


def _skill(
    skill_id="sk-1",
    capability_name="stdlib.file.read",
    success_rate=0.9,
    sample_count=5,
    last_seen=2000,
):
    return ProjectSkillRecord(
        skill_id=skill_id,
        capability_name=capability_name,
        success_rate=success_rate,
        sample_count=sample_count,
        last_seen=last_seen,
        metadata={},
    )


def _bad(
    pattern_id="bp-1",
    capability_pattern="stdlib.bad.op",
    failure_count=3,
    last_seen=2000,
):
    return ProjectBadPatternRecord(
        pattern_id=pattern_id,
        capability_pattern=capability_pattern,
        failure_count=failure_count,
        last_seen=last_seen,
        metadata={},
    )


def _policy(policy_id="pol-1", policy_text="Never use root", source="user", created_at=1000):
    return ProjectPolicyRecord(
        policy_id=policy_id,
        policy_text=policy_text,
        source=source,
        created_at=created_at,
        metadata={},
    )


# ===========================================================================
# Type validation
# ===========================================================================

class TestProjectGoalRecordValidation:
    def test_empty_goal_id_raises(self):
        with pytest.raises(ValueError, match="goal_id"):
            ProjectGoalRecord(
                goal_id="", goal_text="x", frequency=1, first_seen=0, last_seen=0, metadata={}
            )

    def test_empty_goal_text_raises(self):
        with pytest.raises(ValueError, match="goal_text"):
            ProjectGoalRecord(
                goal_id="g-1", goal_text="", frequency=1, first_seen=0, last_seen=0, metadata={}
            )

    def test_zero_frequency_raises(self):
        with pytest.raises(ValueError, match="frequency"):
            ProjectGoalRecord(
                goal_id="g-1", goal_text="x", frequency=0, first_seen=0, last_seen=0, metadata={}
            )

    def test_last_seen_before_first_seen_raises(self):
        with pytest.raises(ValueError, match="last_seen"):
            ProjectGoalRecord(
                goal_id="g-1", goal_text="x", frequency=1, first_seen=100, last_seen=50, metadata={}
            )

    def test_metadata_deep_copied(self):
        mutable = {"k": [1, 2]}
        rec = _goal()
        # Use a fresh record with mutable metadata
        rec2 = ProjectGoalRecord(
            goal_id="g-2", goal_text="x", frequency=1,
            first_seen=0, last_seen=0, metadata=mutable,
        )
        mutable["k"].append(3)
        assert rec2.metadata == {"k": [1, 2]}

    def test_record_is_frozen(self):
        rec = _goal()
        with pytest.raises(Exception):
            rec.frequency = 99  # type: ignore[misc]


class TestProjectSkillRecordValidation:
    def test_invalid_success_rate_raises(self):
        with pytest.raises(ValueError, match="success_rate"):
            ProjectSkillRecord(
                skill_id="sk-1", capability_name="cap", success_rate=1.5,
                sample_count=1, last_seen=0, metadata={}
            )

    def test_zero_sample_count_raises(self):
        with pytest.raises(ValueError, match="sample_count"):
            ProjectSkillRecord(
                skill_id="sk-1", capability_name="cap", success_rate=0.9,
                sample_count=0, last_seen=0, metadata={}
            )


class TestProjectBadPatternRecordValidation:
    def test_zero_failure_count_raises(self):
        with pytest.raises(ValueError, match="failure_count"):
            ProjectBadPatternRecord(
                pattern_id="bp-1", capability_pattern="cap",
                failure_count=0, last_seen=0, metadata={}
            )

    def test_empty_pattern_raises(self):
        with pytest.raises(ValueError, match="capability_pattern"):
            ProjectBadPatternRecord(
                pattern_id="bp-1", capability_pattern="",
                failure_count=1, last_seen=0, metadata={}
            )


class TestProjectPolicyRecordValidation:
    def test_empty_policy_text_raises(self):
        with pytest.raises(ValueError, match="policy_text"):
            ProjectPolicyRecord(
                policy_id="pol-1", policy_text="", source="user",
                created_at=0, metadata={}
            )

    def test_empty_source_raises(self):
        with pytest.raises(ValueError, match="source"):
            ProjectPolicyRecord(
                policy_id="pol-1", policy_text="x", source="",
                created_at=0, metadata={}
            )


# ===========================================================================
# ProjectMemory — Goals
# ===========================================================================

class TestProjectMemoryGoals:
    def test_add_and_get_goal(self):
        pm = ProjectMemory()
        rec = _goal()
        pm.add_goal(rec)
        assert pm.get_goal("g-1") == rec

    def test_get_missing_goal_returns_none(self):
        pm = ProjectMemory()
        assert pm.get_goal("nonexistent") is None

    def test_overwrite_goal(self):
        pm = ProjectMemory()
        pm.add_goal(_goal(frequency=1))
        pm.add_goal(_goal(frequency=5))
        assert pm.get_goal("g-1").frequency == 5

    def test_find_goal_by_text(self):
        pm = ProjectMemory()
        pm.add_goal(_goal(goal_text="deploy service"))
        pm.add_goal(_goal(goal_id="g-2", goal_text="run tests"))
        found = pm.find_goal_by_text("deploy service")
        assert found is not None
        assert found.goal_id == "g-1"

    def test_find_goal_by_text_not_found(self):
        pm = ProjectMemory()
        assert pm.find_goal_by_text("unknown") is None

    def test_recurring_goals_filters_by_frequency(self):
        pm = ProjectMemory()
        pm.add_goal(_goal(goal_id="g-1", frequency=1))
        pm.add_goal(_goal(goal_id="g-2", goal_text="build", frequency=3))
        pm.add_goal(_goal(goal_id="g-3", goal_text="lint", frequency=2))
        recurring = pm.recurring_goals(min_frequency=2)
        ids = [r.goal_id for r in recurring]
        assert "g-1" not in ids
        assert "g-2" in ids
        assert "g-3" in ids

    def test_recurring_goals_sorted_by_frequency_desc(self):
        pm = ProjectMemory()
        pm.add_goal(_goal(goal_id="g-a", goal_text="a", frequency=5))
        pm.add_goal(_goal(goal_id="g-b", goal_text="b", frequency=2))
        pm.add_goal(_goal(goal_id="g-c", goal_text="c", frequency=8))
        result = pm.recurring_goals(min_frequency=1)
        assert result[0].frequency >= result[1].frequency >= result[2].frequency

    def test_all_goals_sorted_by_last_seen_desc(self):
        pm = ProjectMemory()
        pm.add_goal(_goal(goal_id="g-1", last_seen=1000))
        pm.add_goal(_goal(goal_id="g-2", goal_text="b", last_seen=3000))
        pm.add_goal(_goal(goal_id="g-3", goal_text="c", last_seen=2000))
        result = pm.all_goals()
        assert result[0].goal_id == "g-2"
        assert result[-1].goal_id == "g-1"


# ===========================================================================
# ProjectMemory — Skills
# ===========================================================================

class TestProjectMemorySkills:
    def test_add_and_get_skill(self):
        pm = ProjectMemory()
        rec = _skill()
        pm.add_skill(rec)
        assert pm.get_skill("sk-1") == rec

    def test_find_skill_by_name(self):
        pm = ProjectMemory()
        pm.add_skill(_skill(capability_name="stdlib.file.read"))
        found = pm.find_skill_by_name("stdlib.file.read")
        assert found is not None

    def test_preferred_skills_threshold(self):
        pm = ProjectMemory()
        pm.add_skill(_skill(skill_id="sk-high", capability_name="cap.high", success_rate=0.95))
        pm.add_skill(_skill(skill_id="sk-low", capability_name="cap.low", success_rate=0.4))
        preferred = pm.preferred_skills(min_success_rate=0.7)
        names = [r.capability_name for r in preferred]
        assert "cap.high" in names
        assert "cap.low" not in names

    def test_preferred_skills_sorted_by_success_rate_desc(self):
        pm = ProjectMemory()
        pm.add_skill(_skill(skill_id="sk-1", capability_name="a", success_rate=0.8))
        pm.add_skill(_skill(skill_id="sk-2", capability_name="b", success_rate=1.0))
        pm.add_skill(_skill(skill_id="sk-3", capability_name="c", success_rate=0.9))
        result = pm.preferred_skills(min_success_rate=0.0)
        rates = [r.success_rate for r in result]
        assert rates == sorted(rates, reverse=True)

    def test_preferred_skills_min_samples_filter(self):
        pm = ProjectMemory()
        pm.add_skill(_skill(skill_id="sk-few", capability_name="few", success_rate=0.9, sample_count=1))
        pm.add_skill(_skill(skill_id="sk-many", capability_name="many", success_rate=0.9, sample_count=5))
        result = pm.preferred_skills(min_success_rate=0.7, min_samples=3)
        names = [r.capability_name for r in result]
        assert "few" not in names
        assert "many" in names


# ===========================================================================
# ProjectMemory — Bad Patterns
# ===========================================================================

class TestProjectMemoryBadPatterns:
    def test_add_and_get_bad_pattern(self):
        pm = ProjectMemory()
        rec = _bad()
        pm.add_bad_pattern(rec)
        assert pm.get_bad_pattern("bp-1") == rec

    def test_find_bad_pattern_by_capability(self):
        pm = ProjectMemory()
        pm.add_bad_pattern(_bad(capability_pattern="stdlib.bad.op"))
        found = pm.find_bad_pattern_by_capability("stdlib.bad.op")
        assert found is not None

    def test_known_bad_patterns_filters(self):
        pm = ProjectMemory()
        pm.add_bad_pattern(_bad(pattern_id="bp-1", failure_count=1))
        pm.add_bad_pattern(_bad(pattern_id="bp-2", capability_pattern="other", failure_count=5))
        result = pm.known_bad_patterns(min_failures=3)
        assert len(result) == 1
        assert result[0].pattern_id == "bp-2"

    def test_known_bad_patterns_sorted_by_failure_count_desc(self):
        pm = ProjectMemory()
        pm.add_bad_pattern(_bad(pattern_id="bp-1", capability_pattern="a", failure_count=2))
        pm.add_bad_pattern(_bad(pattern_id="bp-2", capability_pattern="b", failure_count=7))
        pm.add_bad_pattern(_bad(pattern_id="bp-3", capability_pattern="c", failure_count=4))
        result = pm.known_bad_patterns()
        counts = [r.failure_count for r in result]
        assert counts == sorted(counts, reverse=True)


# ===========================================================================
# ProjectMemory — Policies
# ===========================================================================

class TestProjectMemoryPolicies:
    def test_add_and_get_policy(self):
        pm = ProjectMemory()
        rec = _policy()
        pm.add_policy(rec)
        assert pm.get_policy("pol-1") == rec

    def test_domain_policies_sorted_by_created_at(self):
        pm = ProjectMemory()
        pm.add_policy(_policy(policy_id="p-late", created_at=3000))
        pm.add_policy(_policy(policy_id="p-early", policy_text="Rule B", created_at=1000))
        result = pm.domain_policies()
        assert result[0].policy_id == "p-early"
        assert result[-1].policy_id == "p-late"


# ===========================================================================
# ProjectMemory — len and clear
# ===========================================================================

class TestProjectMemoryMetrics:
    def test_len_empty(self):
        assert len(ProjectMemory()) == 0

    def test_len_counts_across_all_stores(self):
        pm = ProjectMemory()
        pm.add_goal(_goal())
        pm.add_skill(_skill())
        pm.add_bad_pattern(_bad())
        pm.add_policy(_policy())
        assert len(pm) == 4

    def test_clear_empties_all_stores(self):
        pm = ProjectMemory()
        pm.add_goal(_goal())
        pm.add_skill(_skill())
        pm.clear()
        assert len(pm) == 0


# ===========================================================================
# Snapshot round-trip
# ===========================================================================

class TestProjectMemorySnapshot:
    def test_empty_snapshot(self):
        pm = ProjectMemory()
        snap = pm.snapshot()
        assert snap.goals == ()
        assert snap.skills == ()
        assert snap.bad_patterns == ()
        assert snap.policies == ()

    def test_snapshot_and_restore(self):
        pm = ProjectMemory()
        pm.add_goal(_goal())
        pm.add_skill(_skill())
        pm.add_bad_pattern(_bad())
        pm.add_policy(_policy())

        snap = pm.snapshot()
        pm2 = ProjectMemory()
        pm2.load_snapshot(snap)

        assert pm2.get_goal("g-1") == pm.get_goal("g-1")
        assert pm2.get_skill("sk-1") == pm.get_skill("sk-1")
        assert pm2.get_bad_pattern("bp-1") == pm.get_bad_pattern("bp-1")
        assert pm2.get_policy("pol-1") == pm.get_policy("pol-1")

    def test_snapshot_is_typed(self):
        pm = ProjectMemory()
        pm.add_goal(_goal())
        snap = pm.snapshot()
        assert isinstance(snap, ProjectMemorySnapshot)
        assert isinstance(snap.goals[0], ProjectGoalRecord)

    def test_load_snapshot_replaces_existing(self):
        pm = ProjectMemory()
        pm.add_goal(_goal(goal_id="old"))
        snap_empty = ProjectMemorySnapshot(goals=(), skills=(), bad_patterns=(), policies=())
        pm.load_snapshot(snap_empty)
        assert pm.get_goal("old") is None
        assert len(pm) == 0

    def test_snapshot_goals_sorted_by_last_seen_desc(self):
        pm = ProjectMemory()
        pm.add_goal(_goal(goal_id="g-early", first_seen=100, last_seen=100))
        pm.add_goal(_goal(goal_id="g-late", goal_text="late", first_seen=1000, last_seen=9000))
        snap = pm.snapshot()
        assert snap.goals[0].goal_id == "g-late"

    def test_snapshot_skills_sorted_by_success_rate_desc(self):
        pm = ProjectMemory()
        pm.add_skill(_skill(skill_id="sk-low", capability_name="low", success_rate=0.3))
        pm.add_skill(_skill(skill_id="sk-high", capability_name="high", success_rate=0.95))
        snap = pm.snapshot()
        assert snap.skills[0].capability_name == "high"


# ===========================================================================
# Project-scoped memory retrieval (3.20.4)
# ===========================================================================

class TestProjectScopedRetrieval:
    """
    Verifies that project-scoped queries return the correct subset of records.
    This is the 'project-scoped memory retrieval' test from 3.20.4.
    """

    def test_recurring_goals_retrieval(self):
        pm = ProjectMemory()
        pm.add_goal(_goal(goal_id="g-1", goal_text="deploy", frequency=5))
        pm.add_goal(_goal(goal_id="g-2", goal_text="test", frequency=1))
        pm.add_goal(_goal(goal_id="g-3", goal_text="lint", frequency=3))

        recurring = pm.recurring_goals(min_frequency=3)
        texts = {r.goal_text for r in recurring}
        assert "deploy" in texts
        assert "lint" in texts
        assert "test" not in texts

    def test_preferred_skills_retrieval(self):
        pm = ProjectMemory()
        pm.add_skill(_skill(skill_id="sk-a", capability_name="cap.a", success_rate=0.95))
        pm.add_skill(_skill(skill_id="sk-b", capability_name="cap.b", success_rate=0.5))

        preferred = pm.preferred_skills(min_success_rate=0.8)
        names = [r.capability_name for r in preferred]
        assert "cap.a" in names
        assert "cap.b" not in names

    def test_known_bad_patterns_retrieval(self):
        pm = ProjectMemory()
        pm.add_bad_pattern(_bad(pattern_id="bp-a", capability_pattern="bad.op", failure_count=4))
        pm.add_bad_pattern(_bad(pattern_id="bp-b", capability_pattern="ok.op", failure_count=1))

        bad = pm.known_bad_patterns(min_failures=2)
        patterns = [r.capability_pattern for r in bad]
        assert "bad.op" in patterns
        assert "ok.op" not in patterns