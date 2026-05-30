"""
Phase 2.5.5 — Reflection Loop.

Provides a deterministic, rule-based reflection cycle that evaluates progress,
detects drift, refines subgoal lifecycle states, adjusts plans, and updates
memory — all without LLM calls, inference, or semantic interpretation.
"""
from src.core.planning.reflection.reflection_types import (
    ProgressReport,
    ReflectionDriftReport,
    PlanAdjustment,
    TransitionRecord,
    MemoryUpdateRecord,
    ReflectionTrace,
    ReflectionOutcome,
    ReflectionState,
)
from src.core.planning.reflection.progress_evaluator import evaluate_progress
from src.core.planning.reflection.reflection_loop import ReflectionLoop

__all__ = [
    "ProgressReport",
    "ReflectionDriftReport",
    "PlanAdjustment",
    "TransitionRecord",
    "MemoryUpdateRecord",
    "ReflectionTrace",
    "ReflectionOutcome",
    "ReflectionState",
    "evaluate_progress",
    "ReflectionLoop",
]
