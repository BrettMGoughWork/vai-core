"""
Phase 2.5.6 — Agent Loop V2: type definitions.

All types are JSON-serialisable (frozen dataclasses where immutable,
plain dataclass for AgentState which holds mutable memory stores).

No inference, no semantics, no LLM calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from src.core.memory.subgoal_memory import SubgoalMemory
from src.core.memory.segment_memory import SegmentMemory
from src.core.memory.plan_memory import PlanMemory
from src.core.memory.drift_memory import DriftMemory
from src.core.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.memory.plan_memory_types import PlanMemoryRecord
from src.core.memory.drift_memory_types import DriftEvent
from src.core.planning.reflection.reflection_types import (
    ProgressReport,
    ReflectionOutcome,
    ReflectionTrace,
)


# ---------------------------------------------------------------------------
# Termination reason
# ---------------------------------------------------------------------------

class TerminationReason(str, Enum):
    """
    Why the agent loop stopped.

    TERMINAL — all subgoals reached terminal states without error
    ERROR    — some subgoals exhausted repair budget and are permanently failed
    SAFETY   — a safety violation was detected (forbidden state or invalid record)
    BUDGET   — max_cycles reached before terminal state
    """
    TERMINAL = "terminal"
    ERROR    = "error"
    SAFETY   = "safety"
    BUDGET   = "budget"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentLoopConfig:
    """
    Immutable budget and limit configuration for one agent loop run.

    repair_budget:          Max repair cycles per subgoal before marking permanently failed.
    repair_retry_limit:     Max retry attempts inside a single PlanRepair call.
    confirmation_cycles:    Drift confirmation threshold (N cycles before confirming drift).
    cooldown_cycles:        Drift cooldown (M drift-free cycles resets confirmation state).
    stall_repair_threshold: Repair attempts before considering a subgoal stalled.
    max_errors_before_abort: Accumulated error count before aborting the entire run.
    """
    repair_budget: int = 10
    repair_retry_limit: int = 3
    confirmation_cycles: int = 2
    cooldown_cycles: int = 3
    stall_repair_threshold: int = 3
    max_errors_before_abort: int = 5


# ---------------------------------------------------------------------------
# Per-subgoal runtime counters
# ---------------------------------------------------------------------------

@dataclass
class SubgoalRuntimeState:
    """
    Mutable runtime counters tracked per subgoal across agent cycles.

    Scoped per subgoal_id so that behavioural signals for one subgoal
    do not contaminate the drift or progress evaluation of another.
    """
    repair_attempts: int = 0
    fallback_count: int = 0
    failed_consecutive: int = 0


# ---------------------------------------------------------------------------
# Error record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentLoopError:
    """
    Structured error record produced during an agent cycle.

    error_type values:
      "validation"  — FullValidationEngine rejected a record
      "governance"  — MemoryGovernance write was rejected
      "transition"  — FullTransitionRules rejected a transition
      "repair"      — PlanRepair returned an error
      "safety"      — safety gate triggered (forbidden state or unrecognised state)
      "reflection"  — ReflectionLoop reported a non-fatal error
      "unknown"     — unexpected exception
    """
    cycle: int
    error_type: str
    message: str
    subgoal_id: Optional[str]


# ---------------------------------------------------------------------------
# Memory snapshot (serialisable view)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MemorySnapshot:
    """
    JSON-serialisable point-in-time snapshot of all four memory stores.

    Captured at the end of each agent cycle for audit and replay.
    All fields are tuples of frozen dataclasses — safe for asdict().
    """
    subgoals: Tuple[SubgoalMemoryRecord, ...]
    segments: Tuple[SegmentMemoryRecord, ...]
    plans: Tuple[PlanMemoryRecord, ...]
    drift_events: Tuple[DriftEvent, ...]
    snapshot_timestamp: str  # ISO 8601


# ---------------------------------------------------------------------------
# AgentState (mutable, holds live stores)
# ---------------------------------------------------------------------------

@dataclass
class AgentState:
    """
    Mutable runtime state for one agent loop run.

    Holds live memory stores for direct read/write access.
    Use to_snapshot() to obtain a JSON-serialisable view.

    subgoal_memory / segment_memory / plan_memory / drift_memory:
        The four governed memory stores.  All writes go through MemoryGovernance.

    cycle:
        Monotonically increasing cycle counter, incremented at the start of each cycle.

    config:
        Immutable budget and limit configuration.

    subgoal_runtime:
        Per-subgoal runtime counters keyed by subgoal_id.
        Automatically created on first access via AgentLoopV2._get_subgoal_runtime().

    last_cycle_progress:
        ProgressReport from the previous agent cycle (or None on first cycle).
        Passed as prior_progress to all ReflectionState instances within a cycle.

    last_reflection_trace / last_error:
        Most recent reflection trace and most recent AgentLoopError (may be None).

    accumulated_errors:
        All AgentLoopErrors from every cycle in this run.
    """
    subgoal_memory: SubgoalMemory
    segment_memory: SegmentMemory
    plan_memory: PlanMemory
    drift_memory: DriftMemory
    cycle: int = 0
    config: AgentLoopConfig = field(default_factory=AgentLoopConfig)
    subgoal_runtime: Dict[str, SubgoalRuntimeState] = field(default_factory=dict)
    last_cycle_progress: Optional[ProgressReport] = None
    last_reflection_trace: Optional[ReflectionTrace] = None
    last_error: Optional[AgentLoopError] = None
    accumulated_errors: List[AgentLoopError] = field(default_factory=list)

    def to_snapshot(self, timestamp: str) -> MemorySnapshot:
        """Return an immutable, JSON-serialisable snapshot of the current memory state."""
        sg_snap = self.subgoal_memory.snapshot()
        seg_snap = self.segment_memory.snapshot()
        plan_snap = self.plan_memory.snapshot()
        drift_snap = self.drift_memory.snapshot()
        return MemorySnapshot(
            subgoals=sg_snap.records,
            segments=seg_snap.records,
            plans=plan_snap.records,
            drift_events=drift_snap.events,
            snapshot_timestamp=timestamp,
        )


# ---------------------------------------------------------------------------
# Per-subgoal cycle result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SubgoalCycleResult:
    """
    Per-subgoal result within one agent cycle.

    reflection_outcome:  Full ReflectionOutcome, or None if reflection was skipped.
    skipped:             True if no reflection cycle ran for this subgoal.
    skip_reason:         Machine-readable reason for skipping, or None.
    safety_blocked:      True if a safety gate fired during or after reflection.
    safety_errors:       Safety error messages (empty if no safety block).
    closed:              True if this cycle applied a CLOSED direct transition.
    retry_applied:       True if this cycle applied a RETRY + RESUME transition.
    """
    subgoal_id: str
    reflection_outcome: Optional[ReflectionOutcome]
    skipped: bool
    skip_reason: Optional[str]
    safety_blocked: bool
    safety_errors: Tuple[str, ...]
    closed: bool
    retry_applied: bool


# ---------------------------------------------------------------------------
# Cycle and run outcomes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentCycleOutcome:
    """
    Complete, deterministic result of one agent cycle.

    cycle:               The cycle counter at the time of this outcome.
    timestamp:           ISO 8601 anchor timestamp for this cycle.
    subgoal_results:     Per-subgoal results (one per subgoal in memory).
    memory_snapshot:     Point-in-time memory snapshot at cycle end.
    errors:              All AgentLoopErrors produced this cycle.
    terminal:            True if the loop should stop after this cycle.
    termination_reason:  TerminationReason.value string, or None if not terminal.
    """
    cycle: int
    timestamp: str
    subgoal_results: Tuple[SubgoalCycleResult, ...]
    memory_snapshot: MemorySnapshot
    errors: Tuple[AgentLoopError, ...]
    terminal: bool
    termination_reason: Optional[str]


@dataclass(frozen=True)
class AgentRunTrace:
    """
    Full append-only audit trace for one agent loop run.

    cycles:               All AgentCycleOutcomes produced, oldest-first.
    terminated:           True if the loop stopped due to a terminal/error/safety condition.
                          False if it stopped only because max_cycles was reached.
    termination_reason:   TerminationReason.value string.
    total_cycles:         Number of cycles executed.
    total_errors:         Total AgentErrors accumulated across all cycles.
    """
    cycles: Tuple[AgentCycleOutcome, ...]
    terminated: bool
    termination_reason: str
    total_cycles: int
    total_errors: int
