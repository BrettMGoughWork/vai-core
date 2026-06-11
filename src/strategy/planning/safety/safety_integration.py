"""
Wire safety policy checks into the agent loop boundary.

This module provides a thin integration layer that applies
``ForbiddenCapabilityPolicy`` and ``PlanTransitionPolicy`` as a
pre-loop guard, adapting ``PlanSegment`` → ``SafetyContext``
so that policies evaluate correctly without modifying the pure
``run_agent_loop`` function.

Also provides ``run_agent_loop_with_episode_management`` which wraps
the safe loop with EpisodeBoundaryManager lifecycle (start, end,
summarise, compact).
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from src.strategy.planning.models.plan import Plan
from src.strategy.planning.models.plan_state import PlanState, PlanStatus
from src.strategy.planning.safety.safety_policies import (
    SafetyContext,
    SafetyPolicy,
    ForbiddenCapabilityPolicy,
    PlanTransitionPolicy,
)
from src.strategy.planning.agent_loop.agent_loop import (
    run_agent_loop,
    AgentLoopResult,
)
from src.strategy.types.plan_segment import PlanSegment
from src.strategy.types.subgoal import Subgoal
from src.strategy.types.errors.plan_errors import PlanSafetyPolicyError
from src.strategy.memory.episode.episode_boundary import EpisodeBoundaryManager
from src.strategy.memory.episode.episode_types import EpisodeRecord, EpisodeSummary
from src.strategy.memory.project_memory import ProjectMemory
from src.strategy.memory.user_profile_memory import UserProfileMemory


def _segment_to_safety_context(segment: PlanSegment) -> SafetyContext:
    """Adapt a ``PlanSegment`` into a ``SafetyContext`` for policy evaluation.

    Maps the segment's first skill to ``Plan.targetskillid`` so that
    ``ForbiddenCapabilityPolicy`` can check it, and creates an initial
    ``PlanState`` with ``PENDING`` status so that ``PlanTransitionPolicy``
    passes (segments always start pending in the loop).
    """
    plan = Plan(
        intent=f"segment_{segment.id}",
        targetskillid=(segment.skills[0] if segment.skills else ""),
        arguments={},
        reasoning_summary="",
    )
    plan_state = PlanState.initial(plan)
    return SafetyContext(
        plan=plan,
        capability={"skills": segment.skills},
        plan_state=plan_state,
    )


def run_safe_agent_loop(
    subgoals: List[Subgoal],
    segments: List[PlanSegment],
    max_cycles: int,
    safety_policies: List[SafetyPolicy] | None = None,
) -> AgentLoopResult:
    """Run the agent loop with optional safety policy enforcement.

    Before delegating to ``run_agent_loop``, each segment is checked
    against the provided safety policies (``pre_execute``). If any policy
    raises ``PlanSafetyPolicyError``, it is propagated immediately and the
    loop does not execute.

    Parameters
    ----------
    subgoals, segments, max_cycles
        Forwarded directly to ``run_agent_loop``.
    safety_policies
        Optional list of ``SafetyPolicy`` instances. Defaults to
        ``[ForbiddenCapabilityPolicy(set()), PlanTransitionPolicy()]``,
        which enforces no restrictions (empty forbidden set).

    Returns
    -------
    AgentLoopResult
        The result from ``run_agent_loop``.

    Raises
    ------
    PlanSafetyPolicyError
        If any segment violates a ``SafetyPolicy.pre_execute`` check.
    """
    if safety_policies is None:
        safety_policies = [
            ForbiddenCapabilityPolicy(forbidden_capabilities=set()),
            PlanTransitionPolicy(),
        ]

    # Pre-loop: check each segment against all safety policies
    for segment in segments:
        ctx = _segment_to_safety_context(segment)
        for policy in safety_policies:
            policy.pre_execute(ctx)

    # Delegate to the pure agent loop
    return run_agent_loop(subgoals, segments, max_cycles)


def run_agent_loop_with_episode_management(
    subgoals: List[Subgoal],
    segments: List[PlanSegment],
    max_cycles: int,
    episode_manager: EpisodeBoundaryManager,
    episode_id: str,
    started_at: int,
    project_memory: ProjectMemory,
    user_profile_memory: UserProfileMemory,
    context: Optional[Dict[str, Any]] = None,
    safety_policies: Optional[List[SafetyPolicy]] = None,
) -> tuple[AgentLoopResult, EpisodeRecord, Optional[EpisodeSummary]]:
    """Run the safe agent loop with episode lifecycle management.

    Wraps ``run_safe_agent_loop`` with ``EpisodeBoundaryManager``
    lifecycle: before the loop an episode is started; after the loop
    it is ended, summarised (with data adapted from the loop trace),
    and compacted into ``project_memory`` and ``user_profile_memory``.

    Parameters
    ----------
    subgoals, segments, max_cycles
        Forwarded directly to ``run_agent_loop``.
    episode_manager
        ``EpisodeBoundaryManager`` instance managing episode lifecycle.
    episode_id
        Unique identifier for this episode.
    started_at
        Epoch-ms timestamp when this episode began.
    project_memory, user_profile_memory
        Memory stores into which the episode summary is compacted.
    context
        Optional dict stored as episode metadata.
    safety_policies
        Optional list of ``SafetyPolicy`` instances (see
        ``run_safe_agent_loop``).

    Returns
    -------
    tuple[AgentLoopResult, EpisodeRecord, EpisodeSummary | None]
        ``(loop_result, episode_record, summary)`` where ``summary`` is
        ``None`` if the episode is still active after the loop (should not
        happen under normal execution).
    """
    # ── 1. Start episode ──
    episode_manager.start_episode(
        episode_id=episode_id,
        started_at=started_at,
        context=context,
    )

    # ── 2. Run the safe agent loop ──
    result = run_safe_agent_loop(
        subgoals=subgoals,
        segments=segments,
        max_cycles=max_cycles,
        safety_policies=safety_policies,
    )

    # ── 3. End episode ──
    ended_at = started_at  # use trace timestamps if available
    if result.trace.cycles:
        last_cycle = result.trace.cycles[-1]
        ended_at = getattr(last_cycle, "timestamp", started_at)

    outcome = (
        "success" if result.is_complete else "failure"
    )
    end_reason = (
        "completed" if result.is_complete else "max_cycles_exceeded"
    )
    if result.error is not None:
        end_reason = "error"
        outcome = "failure"

    # Collect topics and skills from the trace & input data
    topics: List[str] = []
    skills_used: List[str] = []
    semantic_records: List[Dict[str, Any]] = []

    for sg in subgoals:
        topics.append(sg.goal)
        semantic_records.append({
            "topics": (sg.goal,),
            "entities": (),
            "capability_patterns": (),
            "outcome": outcome,
        })

    for seg in segments:
        skills_used.extend(seg.skills)
        semantic_records.append({
            "topics": tuple(seg.skills),
            "entities": (),
            "capability_patterns": tuple(seg.skills),
            "outcome": outcome,
        })

    ep = episode_manager.end_episode(
        episode_id=episode_id,
        ended_at=ended_at,
        end_reason=end_reason,
        outcome=outcome,
        topics=tuple(topics),
        skills_used=tuple(skills_used),
        drift_count=result.trace.drift_count
        if hasattr(result.trace, "drift_count")
        else 0,
    )

    # ── 4. Summarise and compact ──
    generated_at = ended_at
    summary = episode_manager.summarise(
        episode_id=episode_id,
        semantic_records=semantic_records,
        drift_events=result.total_cycles,
        generated_at=generated_at,
    )

    episode_manager.compact(
        summary=summary,
        project_memory=project_memory,
        user_profile_memory=user_profile_memory,
        compacted_at=generated_at,
    )

    return result, ep, summary
