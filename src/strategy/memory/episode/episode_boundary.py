"""
Phase 3.20.3 — EpisodeBoundaryManager
========================================

Manages episode lifecycle: start, end, summarisation, and compaction.

All operations are pure S2 — deterministic, no LLM, no I/O, no randomness.
Compaction extracts facts from a completed episode and promotes them into
ProjectMemory and UserProfileMemory.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from src.strategy.memory.episode.episode_types import (
    EPISODE_END_COMPLETED,
    VALID_END_REASONS,
    VALID_OUTCOMES,
    EpisodeRecord,
    EpisodeSummary,
)
from src.strategy.memory.project_memory import ProjectMemory
from src.strategy.memory.project_memory_types import (
    ProjectBadPatternRecord,
    ProjectGoalRecord,
    ProjectSkillRecord,
)
from src.strategy.memory.user_profile_memory import UserProfileMemory
from src.strategy.memory.user_profile_types import UserBehaviouralPatternRecord


# ---------------------------------------------------------------------------
# Compaction thresholds (pure S2 constants — no LLM reasoning)
# ---------------------------------------------------------------------------

# A skill is promoted to ProjectMemory.preferred_skills when its success_rate
# within a summary meets this threshold.
_PREFERRED_SKILL_THRESHOLD: float = 0.7

# A pattern is recorded as a bad_pattern when its success_rate within a
# summary falls at or below this threshold (i.e., it always fails).
_BAD_PATTERN_THRESHOLD: float = 0.0


class EpisodeBoundaryManager:
    """
    Manages episode lifecycle for a single session.

    Episodes are stored in an ordered list; a given session typically has one
    active episode at a time. Multiple completed episodes accumulate and can
    each be summarised and compacted.

    Usage::

        mgr = EpisodeBoundaryManager()
        ep  = mgr.start_episode("ep-1", started_at=1000, context={})
        ep  = mgr.end_episode("ep-1", ended_at=2000, end_reason="completed",
                               outcome="success", topics=("file ops",),
                               skills_used=("stdlib.file.read",), drift_count=0)
        summary = mgr.summarise("ep-1", semantic_records=[...], drift_events=0,
                                 generated_at=2001)
        mgr.compact(summary, project_memory, user_profile_memory)
    """

    def __init__(self) -> None:
        self._episodes: Dict[str, EpisodeRecord] = {}

    # ------------------------------------------------------------------
    # Start / end
    # ------------------------------------------------------------------

    def start_episode(
        self,
        episode_id: str,
        started_at: int,
        context: Optional[Dict[str, Any]] = None,
    ) -> EpisodeRecord:
        """
        Create and register a new episode record.

        Raises ValueError if an episode with episode_id already exists.
        """
        if episode_id in self._episodes:
            raise ValueError(
                f"Episode {episode_id!r} already exists; use a unique episode_id"
            )
        record = EpisodeRecord(
            episode_id=episode_id,
            started_at=started_at,
            ended_at=None,
            end_reason=None,
            outcome=None,
            topics=(),
            skills_used=(),
            drift_count=0,
            metadata=dict(context or {}),
        )
        self._episodes[episode_id] = record
        return record

    def end_episode(
        self,
        episode_id: str,
        ended_at: int,
        end_reason: str,
        outcome: str,
        topics: Sequence[str] = (),
        skills_used: Sequence[str] = (),
        drift_count: int = 0,
    ) -> EpisodeRecord:
        """
        Finalise an episode by recording its end state.

        Raises ValueError if:
        - episode_id is not found
        - the episode is already ended
        - end_reason or outcome are invalid
        """
        if episode_id not in self._episodes:
            raise ValueError(f"Episode {episode_id!r} not found")
        existing = self._episodes[episode_id]
        if not existing.is_active:
            raise ValueError(f"Episode {episode_id!r} is already ended")
        if end_reason not in VALID_END_REASONS:
            raise ValueError(
                f"end_reason must be one of {sorted(VALID_END_REASONS)}, "
                f"got {end_reason!r}"
            )
        if outcome not in VALID_OUTCOMES:
            raise ValueError(
                f"outcome must be one of {sorted(VALID_OUTCOMES)}, "
                f"got {outcome!r}"
            )

        updated = EpisodeRecord(
            episode_id=episode_id,
            started_at=existing.started_at,
            ended_at=ended_at,
            end_reason=end_reason,
            outcome=outcome,
            topics=tuple(topics),
            skills_used=tuple(skills_used),
            drift_count=drift_count,
            metadata=dict(existing.metadata),
        )
        self._episodes[episode_id] = updated
        return updated

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_episode(self, episode_id: str) -> Optional[EpisodeRecord]:
        """Return the episode record for episode_id, or None."""
        return self._episodes.get(episode_id)

    def active_episodes(self) -> List[EpisodeRecord]:
        """Return all currently active (not ended) episodes."""
        return [r for r in self._episodes.values() if r.is_active]

    def completed_episodes(self) -> List[EpisodeRecord]:
        """Return all ended episodes sorted by ended_at ascending, then episode_id."""
        return sorted(
            [r for r in self._episodes.values() if not r.is_active],
            key=lambda r: (r.ended_at or 0, r.episode_id),
        )

    # ------------------------------------------------------------------
    # Summarisation
    # ------------------------------------------------------------------

    def summarise(
        self,
        episode_id: str,
        semantic_records: Sequence[Any],
        drift_events: int,
        generated_at: int,
        success_threshold: float = _PREFERRED_SKILL_THRESHOLD,
    ) -> EpisodeSummary:
        """
        Produce a deterministic EpisodeSummary for a completed episode.

        semantic_records should be a sequence of SemanticMemoryRecord objects
        (or duck-typed equivalents with .topics, .entities, .capability_patterns,
        and .outcome fields).

        This method is pure: it does not mutate any memory store.

        Raises ValueError if the episode is not found or not yet ended.
        """
        record = self._episodes.get(episode_id)
        if record is None:
            raise ValueError(f"Episode {episode_id!r} not found")
        if record.is_active:
            raise ValueError(
                f"Episode {episode_id!r} is still active; end it before summarising"
            )

        # --- Aggregate topic counts from semantic records ---
        topic_counts: Dict[str, int] = {}
        skill_successes: Dict[str, int] = {}
        skill_totals: Dict[str, int] = {}

        for sem_rec in semantic_records:
            for topic in getattr(sem_rec, "topics", ()):
                topic_counts[topic] = topic_counts.get(topic, 0) + 1

            caps = getattr(sem_rec, "capability_patterns", ())
            outcome = getattr(sem_rec, "outcome", "unknown")
            is_success = outcome in ("success", "partial_success")

            for cap in caps:
                skill_totals[cap] = skill_totals.get(cap, 0) + 1
                if is_success:
                    skill_successes[cap] = skill_successes.get(cap, 0) + 1

        # Also accumulate from the episode record's own skills_used
        for cap in record.skills_used:
            if cap not in skill_totals:
                skill_totals[cap] = 1
                skill_successes.setdefault(cap, 0)

        # --- Compute success rates ---
        skill_success_rates: Dict[str, float] = {}
        for cap, total in skill_totals.items():
            successes = skill_successes.get(cap, 0)
            skill_success_rates[cap] = successes / total if total > 0 else 0.0

        # --- Dominant topics (descending count, then alpha for determinism) ---
        dominant_topics = tuple(
            t
            for t, _ in sorted(
                topic_counts.items(), key=lambda kv: (-kv[1], kv[0])
            )
        )

        # --- Preferred skills (success_rate >= threshold) ---
        preferred_skills = tuple(
            cap
            for cap, rate in sorted(
                skill_success_rates.items(),
                key=lambda kv: (-kv[1], kv[0]),
            )
            if rate >= success_threshold
        )

        # --- Bad patterns (success_rate == 0.0 and appeared at least once) ---
        bad_patterns = tuple(
            cap
            for cap, rate in sorted(
                skill_success_rates.items(),
                key=lambda kv: (kv[1], kv[0]),
            )
            if rate <= _BAD_PATTERN_THRESHOLD and skill_totals.get(cap, 0) > 0
        )

        return EpisodeSummary(
            episode_id=episode_id,
            outcome=record.outcome or "unknown",
            topic_counts=dict(
                sorted(topic_counts.items(), key=lambda kv: kv[0])
            ),
            skill_success_rates=dict(
                sorted(skill_success_rates.items(), key=lambda kv: kv[0])
            ),
            drift_events=drift_events,
            dominant_topics=dominant_topics,
            preferred_skills=preferred_skills,
            bad_patterns=bad_patterns,
            generated_at=generated_at,
            source_record_count=len(semantic_records),
        )

    # ------------------------------------------------------------------
    # Compaction
    # ------------------------------------------------------------------

    def compact(
        self,
        summary: EpisodeSummary,
        project_memory: ProjectMemory,
        user_profile_memory: UserProfileMemory,
        compacted_at: Optional[int] = None,
    ) -> None:
        """
        Extract continuity facts from a completed EpisodeSummary and promote
        them into ProjectMemory and UserProfileMemory.

        Rules (all deterministic, no LLM):

        ProjectMemory:
        - Each dominant_topic in the summary is recorded as a ProjectGoalRecord.
          If a matching goal_text already exists its frequency and last_seen are
          updated; otherwise a new record is created.
        - Each preferred_skill in the summary is recorded/updated as a
          ProjectSkillRecord using a rolling success_rate average.
        - Each bad_pattern in the summary is recorded/updated as a
          ProjectBadPatternRecord, incrementing its failure_count.

        UserProfileMemory:
        - Each dominant topic triggers a UserBehaviouralPatternRecord of type
          "recurring_topic", incrementing frequency if already present.

        This method mutates project_memory and user_profile_memory in place.
        """
        ts = compacted_at if compacted_at is not None else summary.generated_at

        # --- Promote dominant topics → ProjectGoalRecord ---
        for topic in summary.dominant_topics:
            existing = project_memory.find_goal_by_text(topic)
            if existing is not None:
                updated_goal = ProjectGoalRecord(
                    goal_id=existing.goal_id,
                    goal_text=existing.goal_text,
                    frequency=existing.frequency + 1,
                    first_seen=existing.first_seen,
                    last_seen=ts,
                    metadata=dict(existing.metadata),
                )
                project_memory.add_goal(updated_goal)
            else:
                new_id = f"goal-{summary.episode_id}-{topic[:40].replace(' ', '_')}"
                project_memory.add_goal(
                    ProjectGoalRecord(
                        goal_id=new_id,
                        goal_text=topic,
                        frequency=1,
                        first_seen=ts,
                        last_seen=ts,
                        metadata={},
                    )
                )

        # --- Promote preferred skills → ProjectSkillRecord ---
        for cap in summary.preferred_skills:
            episode_rate = summary.skill_success_rates.get(cap, 1.0)
            existing_skill = project_memory.find_skill_by_name(cap)
            if existing_skill is not None:
                new_samples = existing_skill.sample_count + 1
                new_rate = (
                    existing_skill.success_rate * existing_skill.sample_count
                    + episode_rate
                ) / new_samples
                updated_skill = ProjectSkillRecord(
                    skill_id=existing_skill.skill_id,
                    capability_name=existing_skill.capability_name,
                    success_rate=new_rate,
                    sample_count=new_samples,
                    last_seen=ts,
                    metadata=dict(existing_skill.metadata),
                )
                project_memory.add_skill(updated_skill)
            else:
                new_id = f"skill-{cap.replace('.', '-')}"
                project_memory.add_skill(
                    ProjectSkillRecord(
                        skill_id=new_id,
                        capability_name=cap,
                        success_rate=episode_rate,
                        sample_count=1,
                        last_seen=ts,
                        metadata={},
                    )
                )

        # --- Promote bad patterns → ProjectBadPatternRecord ---
        for pattern in summary.bad_patterns:
            existing_bad = project_memory.find_bad_pattern_by_capability(pattern)
            if existing_bad is not None:
                updated_bad = ProjectBadPatternRecord(
                    pattern_id=existing_bad.pattern_id,
                    capability_pattern=existing_bad.capability_pattern,
                    failure_count=existing_bad.failure_count + 1,
                    last_seen=ts,
                    metadata=dict(existing_bad.metadata),
                )
                project_memory.add_bad_pattern(updated_bad)
            else:
                new_id = f"bad-{pattern.replace('.', '-')}"
                project_memory.add_bad_pattern(
                    ProjectBadPatternRecord(
                        pattern_id=new_id,
                        capability_pattern=pattern,
                        failure_count=1,
                        last_seen=ts,
                        metadata={},
                    )
                )

        # --- Update UserProfileMemory: recurring topics as behavioural patterns ---
        for topic in summary.dominant_topics:
            pattern_id = f"topic-{topic[:40].replace(' ', '_')}"
            existing_pat = user_profile_memory.get_pattern(pattern_id)
            if existing_pat is not None:
                updated_pat = UserBehaviouralPatternRecord(
                    pattern_id=existing_pat.pattern_id,
                    pattern_type=existing_pat.pattern_type,
                    description=existing_pat.description,
                    frequency=existing_pat.frequency + 1,
                    last_seen=ts,
                    metadata=dict(existing_pat.metadata),
                )
                user_profile_memory.record_pattern(updated_pat)
            else:
                user_profile_memory.record_pattern(
                    UserBehaviouralPatternRecord(
                        pattern_id=pattern_id,
                        pattern_type="recurring_topic",
                        description=f"User repeatedly engages with topic: {topic}",
                        frequency=1,
                        last_seen=ts,
                        metadata={},
                    )
                )
