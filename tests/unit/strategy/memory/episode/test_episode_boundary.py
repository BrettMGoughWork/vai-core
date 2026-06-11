"""
Tests for Phase 3.20.3 & 3.20.4 — EpisodeBoundaryManager
(episode summarisation, project-scoped memory retrieval, cross-episode plan shaping)
"""

from __future__ import annotations

from typing import Any

import pytest

from src.strategy.memory.episode.episode_boundary import EpisodeBoundaryManager
from src.strategy.memory.episode.episode_types import (
    EPISODE_END_ABANDONED,
    EPISODE_END_COMPLETED,
    EPISODE_END_TIMEOUT,
    EpisodeRecord,
    EpisodeSummary,
)
from src.strategy.memory.project_memory import ProjectMemory
from src.strategy.memory.user_profile_memory import UserProfileMemory


# ---------------------------------------------------------------------------
# Helpers: minimal duck-typed SemanticMemoryRecord
# ---------------------------------------------------------------------------

class _FakeSemRec:
    """Minimal duck-typed SemanticMemoryRecord for tests."""

    def __init__(
        self,
        topics=(),
        capability_patterns=(),
        outcome="success",
    ):
        self.topics = topics
        self.capability_patterns = capability_patterns
        self.outcome = outcome


# ===========================================================================
# EpisodeRecord validation
# ===========================================================================

class TestEpisodeRecordValidation:
    def test_empty_episode_id_raises(self):
        with pytest.raises(ValueError, match="episode_id"):
            EpisodeRecord(
                episode_id="", started_at=0, ended_at=None,
                end_reason=None, outcome=None,
                topics=(), skills_used=(), drift_count=0, metadata={}
            )

    def test_ended_at_before_started_at_raises(self):
        with pytest.raises(ValueError, match="ended_at"):
            EpisodeRecord(
                episode_id="ep-1", started_at=1000, ended_at=500,
                end_reason="completed", outcome="success",
                topics=(), skills_used=(), drift_count=0, metadata={}
            )

    def test_invalid_end_reason_raises(self):
        with pytest.raises(ValueError, match="end_reason"):
            EpisodeRecord(
                episode_id="ep-1", started_at=0, ended_at=1,
                end_reason="invalid", outcome="success",
                topics=(), skills_used=(), drift_count=0, metadata={}
            )

    def test_invalid_outcome_raises(self):
        with pytest.raises(ValueError, match="outcome"):
            EpisodeRecord(
                episode_id="ep-1", started_at=0, ended_at=1,
                end_reason="completed", outcome="bad",
                topics=(), skills_used=(), drift_count=0, metadata={}
            )

    def test_negative_drift_count_raises(self):
        with pytest.raises(ValueError, match="drift_count"):
            EpisodeRecord(
                episode_id="ep-1", started_at=0, ended_at=None,
                end_reason=None, outcome=None,
                topics=(), skills_used=(), drift_count=-1, metadata={}
            )

    def test_is_active_when_not_ended(self):
        rec = EpisodeRecord(
            episode_id="ep-1", started_at=0, ended_at=None,
            end_reason=None, outcome=None,
            topics=(), skills_used=(), drift_count=0, metadata={}
        )
        assert rec.is_active is True

    def test_is_not_active_when_ended(self):
        rec = EpisodeRecord(
            episode_id="ep-1", started_at=0, ended_at=100,
            end_reason="completed", outcome="success",
            topics=(), skills_used=(), drift_count=0, metadata={}
        )
        assert rec.is_active is False

    def test_metadata_deep_copied(self):
        mutable = {"k": [1]}
        rec = EpisodeRecord(
            episode_id="ep-1", started_at=0, ended_at=None,
            end_reason=None, outcome=None,
            topics=(), skills_used=(), drift_count=0, metadata=mutable
        )
        mutable["k"].append(2)
        assert rec.metadata == {"k": [1]}


# ===========================================================================
# EpisodeBoundaryManager — start_episode
# ===========================================================================

class TestEpisodeBoundaryManagerStart:
    def test_start_episode_returns_active_record(self):
        mgr = EpisodeBoundaryManager()
        rec = mgr.start_episode("ep-1", started_at=1000)
        assert rec.episode_id == "ep-1"
        assert rec.started_at == 1000
        assert rec.is_active

    def test_start_episode_stores_context(self):
        mgr = EpisodeBoundaryManager()
        rec = mgr.start_episode("ep-1", started_at=1000, context={"project": "myapp"})
        assert rec.metadata["project"] == "myapp"

    def test_start_duplicate_episode_raises(self):
        mgr = EpisodeBoundaryManager()
        mgr.start_episode("ep-1", started_at=1000)
        with pytest.raises(ValueError, match="ep-1"):
            mgr.start_episode("ep-1", started_at=2000)

    def test_start_multiple_episodes(self):
        mgr = EpisodeBoundaryManager()
        mgr.start_episode("ep-1", started_at=1000)
        mgr.start_episode("ep-2", started_at=2000)
        assert mgr.get_episode("ep-1") is not None
        assert mgr.get_episode("ep-2") is not None

    def test_get_missing_episode_returns_none(self):
        mgr = EpisodeBoundaryManager()
        assert mgr.get_episode("nonexistent") is None


# ===========================================================================
# EpisodeBoundaryManager — end_episode
# ===========================================================================

class TestEpisodeBoundaryManagerEnd:
    def test_end_episode_records_state(self):
        mgr = EpisodeBoundaryManager()
        mgr.start_episode("ep-1", started_at=1000)
        rec = mgr.end_episode(
            "ep-1", ended_at=2000, end_reason="completed", outcome="success",
            topics=("file ops",), skills_used=("stdlib.file.read",), drift_count=1,
        )
        assert rec.ended_at == 2000
        assert rec.end_reason == "completed"
        assert rec.outcome == "success"
        assert rec.topics == ("file ops",)
        assert rec.skills_used == ("stdlib.file.read",)
        assert rec.drift_count == 1
        assert not rec.is_active

    def test_end_missing_episode_raises(self):
        mgr = EpisodeBoundaryManager()
        with pytest.raises(ValueError, match="ep-999"):
            mgr.end_episode("ep-999", ended_at=1000, end_reason="completed", outcome="success")

    def test_end_already_ended_episode_raises(self):
        mgr = EpisodeBoundaryManager()
        mgr.start_episode("ep-1", started_at=1000)
        mgr.end_episode("ep-1", ended_at=2000, end_reason="completed", outcome="success")
        with pytest.raises(ValueError, match="already ended"):
            mgr.end_episode("ep-1", ended_at=3000, end_reason="completed", outcome="success")

    def test_end_invalid_end_reason_raises(self):
        mgr = EpisodeBoundaryManager()
        mgr.start_episode("ep-1", started_at=1000)
        with pytest.raises(ValueError, match="end_reason"):
            mgr.end_episode("ep-1", ended_at=2000, end_reason="oops", outcome="success")

    def test_end_invalid_outcome_raises(self):
        mgr = EpisodeBoundaryManager()
        mgr.start_episode("ep-1", started_at=1000)
        with pytest.raises(ValueError, match="outcome"):
            mgr.end_episode("ep-1", ended_at=2000, end_reason="completed", outcome="oops")

    @pytest.mark.parametrize("end_reason", [EPISODE_END_COMPLETED, EPISODE_END_ABANDONED, EPISODE_END_TIMEOUT])
    def test_all_valid_end_reasons(self, end_reason):
        mgr = EpisodeBoundaryManager()
        mgr.start_episode(end_reason, started_at=0)
        rec = mgr.end_episode(end_reason, ended_at=1, end_reason=end_reason, outcome="unknown")
        assert rec.end_reason == end_reason

    def test_active_and_completed_episode_lists(self):
        mgr = EpisodeBoundaryManager()
        mgr.start_episode("ep-active", started_at=1000)
        mgr.start_episode("ep-done", started_at=500)
        mgr.end_episode("ep-done", ended_at=600, end_reason="completed", outcome="success")

        active = mgr.active_episodes()
        done = mgr.completed_episodes()

        assert len(active) == 1
        assert active[0].episode_id == "ep-active"
        assert len(done) == 1
        assert done[0].episode_id == "ep-done"


# ===========================================================================
# EpisodeBoundaryManager — summarise (3.20.4: episode summarisation)
# ===========================================================================

class TestEpisodeSummarisation:
    """
    Phase 3.20.4 — episode summarisation tests.
    Verifies that summarise() produces correct deterministic aggregates.
    """

    def _setup(self, sem_records=(), drift_events=0, outcome="success"):
        mgr = EpisodeBoundaryManager()
        mgr.start_episode("ep-1", started_at=1000)
        mgr.end_episode(
            "ep-1", ended_at=2000, end_reason="completed", outcome=outcome,
            topics=(), skills_used=(), drift_count=drift_events,
        )
        return mgr.summarise(
            "ep-1",
            semantic_records=sem_records,
            drift_events=drift_events,
            generated_at=2001,
        )

    def test_empty_episode_summary(self):
        summary = self._setup()
        assert summary.episode_id == "ep-1"
        assert summary.outcome == "success"
        assert summary.topic_counts == {}
        assert summary.skill_success_rates == {}
        assert summary.drift_events == 0
        assert summary.dominant_topics == ()
        assert summary.preferred_skills == ()
        assert summary.bad_patterns == ()
        assert summary.source_record_count == 0

    def test_topic_counts_aggregated(self):
        records = [
            _FakeSemRec(topics=("file ops", "read"), outcome="success"),
            _FakeSemRec(topics=("file ops",), outcome="success"),
            _FakeSemRec(topics=("network",), outcome="failure"),
        ]
        summary = self._setup(sem_records=records)
        assert summary.topic_counts["file ops"] == 2
        assert summary.topic_counts["read"] == 1
        assert summary.topic_counts["network"] == 1

    def test_dominant_topics_sorted_by_count_desc(self):
        records = [
            _FakeSemRec(topics=("a",), outcome="success"),
            _FakeSemRec(topics=("b", "a"), outcome="success"),
            _FakeSemRec(topics=("b",), outcome="success"),
            _FakeSemRec(topics=("c",), outcome="success"),
        ]
        summary = self._setup(sem_records=records)
        # "b" and "a" both appear twice, "c" once
        assert summary.dominant_topics[0] in ("a", "b")  # tied — either is first
        assert "c" in summary.dominant_topics
        assert len(summary.dominant_topics) == 3

    def test_skill_success_rates_computed(self):
        records = [
            _FakeSemRec(capability_patterns=("stdlib.file.read",), outcome="success"),
            _FakeSemRec(capability_patterns=("stdlib.file.read",), outcome="success"),
            _FakeSemRec(capability_patterns=("stdlib.bad.op",), outcome="failure"),
        ]
        summary = self._setup(sem_records=records)
        assert summary.skill_success_rates["stdlib.file.read"] == 1.0
        assert summary.skill_success_rates["stdlib.bad.op"] == 0.0

    def test_preferred_skills_above_threshold(self):
        records = [
            _FakeSemRec(capability_patterns=("cap.good",), outcome="success"),
            _FakeSemRec(capability_patterns=("cap.poor",), outcome="failure"),
        ]
        summary = self._setup(sem_records=records)
        assert "cap.good" in summary.preferred_skills
        assert "cap.poor" not in summary.preferred_skills

    def test_bad_patterns_have_zero_success_rate(self):
        records = [
            _FakeSemRec(capability_patterns=("cap.good",), outcome="success"),
            _FakeSemRec(capability_patterns=("cap.always_fails",), outcome="failure"),
            _FakeSemRec(capability_patterns=("cap.always_fails",), outcome="failure"),
        ]
        summary = self._setup(sem_records=records)
        assert "cap.always_fails" in summary.bad_patterns
        assert "cap.good" not in summary.bad_patterns

    def test_partial_success_counts_as_preferred(self):
        records = [
            _FakeSemRec(capability_patterns=("cap.partial",), outcome="partial_success"),
        ]
        summary = self._setup(sem_records=records)
        assert "cap.partial" in summary.preferred_skills

    def test_drift_events_propagated(self):
        summary = self._setup(drift_events=3)
        assert summary.drift_events == 3

    def test_source_record_count(self):
        records = [_FakeSemRec() for _ in range(4)]
        summary = self._setup(sem_records=records)
        assert summary.source_record_count == 4

    def test_summarise_active_episode_raises(self):
        mgr = EpisodeBoundaryManager()
        mgr.start_episode("ep-1", started_at=1000)
        with pytest.raises(ValueError, match="still active"):
            mgr.summarise("ep-1", semantic_records=[], drift_events=0, generated_at=1001)

    def test_summarise_missing_episode_raises(self):
        mgr = EpisodeBoundaryManager()
        with pytest.raises(ValueError, match="not found"):
            mgr.summarise("ep-nope", semantic_records=[], drift_events=0, generated_at=1)

    def test_summary_topic_counts_sorted_by_key(self):
        records = [
            _FakeSemRec(topics=("z_topic", "a_topic"), outcome="success"),
        ]
        summary = self._setup(sem_records=records)
        keys = list(summary.topic_counts.keys())
        assert keys == sorted(keys)

    def test_summary_is_frozen(self):
        summary = self._setup()
        with pytest.raises(Exception):
            summary.outcome = "changed"  # type: ignore[misc]


# ===========================================================================
# EpisodeBoundaryManager — compact (3.20.4: compaction + plan shaping)
# ===========================================================================

class TestEpisodeCompaction:
    """
    Phase 3.20.4 — tests for compact() and cross-episode plan shaping.
    """

    def _make_summary(
        self,
        episode_id="ep-1",
        outcome="success",
        topic_counts=None,
        skill_success_rates=None,
        dominant_topics=(),
        preferred_skills=(),
        bad_patterns=(),
        drift_events=0,
        generated_at=3000,
        source_record_count=1,
    ):
        return EpisodeSummary(
            episode_id=episode_id,
            outcome=outcome,
            topic_counts=topic_counts or {},
            skill_success_rates=skill_success_rates or {},
            dominant_topics=dominant_topics,
            preferred_skills=preferred_skills,
            bad_patterns=bad_patterns,
            drift_events=drift_events,
            generated_at=generated_at,
            source_record_count=source_record_count,
        )

    def test_compact_promotes_preferred_skill(self):
        mgr = EpisodeBoundaryManager()
        pm = ProjectMemory()
        upm = UserProfileMemory()

        summary = self._make_summary(
            preferred_skills=("stdlib.file.read",),
            skill_success_rates={"stdlib.file.read": 1.0},
        )
        mgr.compact(summary, pm, upm)

        found = pm.find_skill_by_name("stdlib.file.read")
        assert found is not None
        assert found.success_rate == 1.0
        assert found.sample_count == 1

    def test_compact_promotes_bad_pattern(self):
        mgr = EpisodeBoundaryManager()
        pm = ProjectMemory()
        upm = UserProfileMemory()

        summary = self._make_summary(bad_patterns=("cap.always_fails",))
        mgr.compact(summary, pm, upm)

        found = pm.find_bad_pattern_by_capability("cap.always_fails")
        assert found is not None
        assert found.failure_count == 1

    def test_compact_promotes_dominant_topic_as_project_goal(self):
        mgr = EpisodeBoundaryManager()
        pm = ProjectMemory()
        upm = UserProfileMemory()

        summary = self._make_summary(dominant_topics=("file operations",))
        mgr.compact(summary, pm, upm)

        found = pm.find_goal_by_text("file operations")
        assert found is not None
        assert found.frequency == 1

    def test_compact_updates_user_behavioural_patterns(self):
        mgr = EpisodeBoundaryManager()
        pm = ProjectMemory()
        upm = UserProfileMemory()

        summary = self._make_summary(dominant_topics=("file operations",))
        mgr.compact(summary, pm, upm)

        patterns = upm.behavioural_patterns()
        assert len(patterns) == 1
        assert patterns[0].pattern_type == "recurring_topic"

    def test_compact_increments_skill_sample_count_on_second_episode(self):
        mgr = EpisodeBoundaryManager()
        pm = ProjectMemory()
        upm = UserProfileMemory()

        s1 = self._make_summary(
            episode_id="ep-1",
            preferred_skills=("stdlib.file.read",),
            skill_success_rates={"stdlib.file.read": 1.0},
        )
        s2 = self._make_summary(
            episode_id="ep-2",
            preferred_skills=("stdlib.file.read",),
            skill_success_rates={"stdlib.file.read": 0.5},
        )
        mgr.compact(s1, pm, upm)
        mgr.compact(s2, pm, upm)

        found = pm.find_skill_by_name("stdlib.file.read")
        assert found.sample_count == 2
        assert 0.5 < found.success_rate < 1.0  # rolling average of 1.0 and 0.5

    def test_compact_increments_bad_pattern_failure_count(self):
        mgr = EpisodeBoundaryManager()
        pm = ProjectMemory()
        upm = UserProfileMemory()

        s1 = self._make_summary(episode_id="ep-1", bad_patterns=("cap.bad",))
        s2 = self._make_summary(episode_id="ep-2", bad_patterns=("cap.bad",))
        mgr.compact(s1, pm, upm)
        mgr.compact(s2, pm, upm)

        found = pm.find_bad_pattern_by_capability("cap.bad")
        assert found.failure_count == 2

    def test_compact_increments_goal_frequency_on_second_episode(self):
        mgr = EpisodeBoundaryManager()
        pm = ProjectMemory()
        upm = UserProfileMemory()

        s1 = self._make_summary(episode_id="ep-1", dominant_topics=("deploy",))
        s2 = self._make_summary(episode_id="ep-2", dominant_topics=("deploy",))
        mgr.compact(s1, pm, upm)
        mgr.compact(s2, pm, upm)

        found = pm.find_goal_by_text("deploy")
        assert found.frequency == 2

    def test_compact_increments_user_pattern_frequency(self):
        mgr = EpisodeBoundaryManager()
        pm = ProjectMemory()
        upm = UserProfileMemory()

        s1 = self._make_summary(episode_id="ep-1", dominant_topics=("deploy",))
        s2 = self._make_summary(episode_id="ep-2", dominant_topics=("deploy",))
        mgr.compact(s1, pm, upm)
        mgr.compact(s2, pm, upm)

        patterns = upm.behavioural_patterns()
        assert patterns[0].frequency == 2

    def test_compact_empty_summary_changes_nothing(self):
        mgr = EpisodeBoundaryManager()
        pm = ProjectMemory()
        upm = UserProfileMemory()

        summary = self._make_summary()
        mgr.compact(summary, pm, upm)
        assert len(pm) == 0
        assert len(upm) == 0


# ===========================================================================
# Cross-episode plan shaping (3.20.4)
# ===========================================================================

class TestCrossEpisodePlanShaping:
    """
    Phase 3.20.4 — cross-episode plan shaping.

    Demonstrates the full loop:
      Episode 1 succeeds with 'stdlib.file.read'
      → compact → ProjectMemory stores preferred skill
      → Episode 2's PlanGenerator.get_strategy_context() returns 'stdlib.file.read'
        in preferred_capabilities.
    """

    def test_preferred_skill_surfaces_in_strategy_context(self):
        from src.strategy.planning.generator.plan_generator import PlanGenerator
        from src.strategy.planning.models.step_state import StepState, StepStatus

        # --- Episode 1: compact a successful skill into ProjectMemory ---
        mgr = EpisodeBoundaryManager()
        pm = ProjectMemory()
        upm = UserProfileMemory()

        summary = EpisodeSummary(
            episode_id="ep-1",
            outcome="success",
            topic_counts={"file ops": 2},
            skill_success_rates={"stdlib.file.read": 1.0},
            dominant_topics=("file ops",),
            preferred_skills=("stdlib.file.read",),
            bad_patterns=(),
            drift_events=0,
            generated_at=2000,
            source_record_count=2,
        )
        mgr.compact(summary, pm, upm)

        # --- Episode 2: PlanGenerator with project_memory ---
        gen = PlanGenerator(capabilities={}, memory_index=None, project_memory=pm)
        state = StepState(
            step_id="s-1",
            cognitive_input={"task": "read files"},
            status=StepStatus.PENDING,
            created_at=1,
        )
        ctx = gen.get_strategy_context(state)

        assert "stdlib.file.read" in ctx.preferred_capabilities

    def test_bad_pattern_surfaces_in_avoid_capabilities(self):
        from src.strategy.planning.generator.plan_generator import PlanGenerator
        from src.strategy.planning.models.step_state import StepState, StepStatus

        mgr = EpisodeBoundaryManager()
        pm = ProjectMemory()
        upm = UserProfileMemory()

        summary = EpisodeSummary(
            episode_id="ep-1",
            outcome="failure",
            topic_counts={},
            skill_success_rates={"cap.dangerous": 0.0},
            dominant_topics=(),
            preferred_skills=(),
            bad_patterns=("cap.dangerous",),
            drift_events=2,
            generated_at=2000,
            source_record_count=1,
        )
        mgr.compact(summary, pm, upm)

        gen = PlanGenerator(capabilities={}, memory_index=None, project_memory=pm)
        state = StepState(
            step_id="s-1",
            cognitive_input={"task": "do something"},
            status=StepStatus.PENDING,
            created_at=1,
        )
        ctx = gen.get_strategy_context(state)

        assert "cap.dangerous" in ctx.avoid_capabilities

    def test_no_project_memory_returns_empty_context(self):
        from src.strategy.planning.generator.plan_generator import PlanGenerator
        from src.strategy.planning.models.step_state import StepState, StepStatus

        gen = PlanGenerator(capabilities={}, memory_index=None, project_memory=None)
        state = StepState(
            step_id="s-1",
            cognitive_input={},
            status=StepStatus.PENDING,
            created_at=1,
        )
        ctx = gen.get_strategy_context(state)
        assert ctx.preferred_capabilities == ()
        assert ctx.avoid_capabilities == ()
        assert ctx.matches == 0

    def test_project_memory_and_semantic_index_combined(self):
        """
        ProjectMemory and SemanticMemoryIndex both contribute to StrategyContext.
        """
        from src.strategy.memory.semantic_memory_index import SemanticMemoryIndex
        from src.strategy.memory.semantic_memory_types import SemanticMemoryRecord
        from src.strategy.planning.generator.plan_generator import PlanGenerator
        from src.strategy.planning.models.step_state import StepState, StepStatus

        # Semantic index with a historical subgoal success
        index = SemanticMemoryIndex()
        index.add(
            SemanticMemoryRecord(
                record_id="sem-1",
                memory_type="subgoal",
                source_id="sg-1",
                topics=("deploy",),
                entities=(),
                capability_patterns=("cap.deploy",),
                embedding_vector=None,
                outcome="success",
                metadata={},
                created_at=1,
            )
        )

        # ProjectMemory with a preferred skill from a different source
        mgr = EpisodeBoundaryManager()
        pm = ProjectMemory()
        upm = UserProfileMemory()
        summary = EpisodeSummary(
            episode_id="ep-1",
            outcome="success",
            topic_counts={},
            skill_success_rates={"stdlib.file.read": 1.0},
            dominant_topics=(),
            preferred_skills=("stdlib.file.read",),
            bad_patterns=(),
            drift_events=0,
            generated_at=1000,
            source_record_count=1,
        )
        mgr.compact(summary, pm, upm)

        gen = PlanGenerator(capabilities={}, memory_index=index, project_memory=pm)
        state = StepState(
            step_id="s-1",
            cognitive_input={"topic": "deploy"},
            status=StepStatus.PENDING,
            created_at=1,
        )
        ctx = gen.get_strategy_context(state)

        # From semantic index
        assert "cap.deploy" in ctx.preferred_capabilities
        # From project memory
        assert "stdlib.file.read" in ctx.preferred_capabilities