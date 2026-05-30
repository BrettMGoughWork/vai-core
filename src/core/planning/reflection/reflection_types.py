"""
Phase 2.5.5 — Reflection Loop: type definitions.

All types are JSON-serialisable. Frozen dataclasses where the data is immutable;
plain dataclass for ReflectionState which holds mutable memory stores.

No inference, no semantics, no LLM calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.core.memory.subgoal_memory import SubgoalMemory
from src.core.memory.segment_memory import SegmentMemory
from src.core.memory.plan_memory import PlanMemory
from src.core.memory.drift_memory import DriftMemory
from src.core.planning.drift.drift_types import DriftConfirmation, DriftTrigger
from src.core.planning.drift.drift_context import TransitionFailureRecord
from src.core.planning.validation.validation_types import FullValidationResult


# ---------------------------------------------------------------------------
# Input: ReflectionState
# ---------------------------------------------------------------------------

@dataclass
class ReflectionState:
    """
    Input container for one reflection cycle.

    cycle:              Monotonically increasing cycle counter (caller-managed).
    timestamp:          Current anchor time (UTC epoch ms).
    subgoal_id:         The subgoal this cycle is focused on.
    subgoal_memory:     Mutable SubgoalMemory store (all subgoals).
    segment_memory:     Mutable SegmentMemory store (all segments).
    plan_memory:        Mutable PlanMemory store.
    drift_memory:       Mutable DriftMemory ring buffer.
    plan_id:            Optional plan_id to include in drift context and repair.
    repair_attempts:    Number of repair cycles already run (behavioural signal).
    fallback_count:     Number of fallback transitions used (behavioural signal).
    transition_failures: Known transition failure counts this cycle.
    prior_progress:     ProgressReport from the previous cycle, for rate comparison.
    """
    cycle: int
    timestamp: int
    subgoal_id: str
    subgoal_memory: SubgoalMemory
    segment_memory: SegmentMemory
    plan_memory: PlanMemory
    drift_memory: DriftMemory
    plan_id: Optional[str] = None
    repair_attempts: int = 0
    fallback_count: int = 0
    transition_failures: List[TransitionFailureRecord] = field(default_factory=list)
    prior_progress: Optional["ProgressReport"] = None


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProgressReport:
    """
    Structural progress summary for one reflection cycle.

    subgoals_complete:  Subgoals in terminal-success states (SUCCESS, SATISFIED, CLOSED).
    subgoals_total:     Total subgoals in memory.
    segments_complete:  Segments whose parent subgoal is in a terminal-success state.
    segments_total:     Total segments in memory.
    stalled:            True if any stall condition is detected.
    stalled_reasons:    Machine-readable stall reason codes.
    progress_rate:      "increasing" | "steady" | "decreasing" | "stalled"
                        Compared against prior_progress.subgoals_complete when available.
    """
    subgoals_complete: int
    subgoals_total: int
    segments_complete: int
    segments_total: int
    stalled: bool
    stalled_reasons: Tuple[str, ...]
    progress_rate: str


# ---------------------------------------------------------------------------
# Drift
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReflectionDriftReport:
    """
    Drift detection result produced during one reflection cycle.

    confirmation:            Raw multi-cycle confirmation object from FullDriftDetector.
    classification:          DriftClassification value string (e.g. "severe_drift").
    confidence:              Confidence score in [0.0, 1.0].
    trigger:                 DriftTrigger for PlanRepair, or None if not confirmed.
    drift_written_to_memory: True if the confirmed event was written to DriftMemory.
    drift_violations:        Violation messages if write was blocked by governance.
    """
    confirmation: DriftConfirmation
    classification: str
    confidence: float
    trigger: Optional[DriftTrigger]
    drift_written_to_memory: bool
    drift_violations: Tuple[str, ...]


# ---------------------------------------------------------------------------
# Plan adjustment
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlanAdjustment:
    """
    Outcome of one plan repair attempt during a reflection cycle.

    plan_id:                  The plan that was evaluated.
    repair_succeeded:         True if PlanRepair computed a clean outcome.
    persisted:                True if the repaired plan was written through governance.
    actions_applied:          Repair action_type strings applied by PlanRepair.
    segments_regenerated:     Count of structural placeholder segments produced.
    requires_segment_regen:   True if placeholders exist and need external resolution.
    error:                    First error string from RepairOutcome, or None.
    """
    plan_id: str
    repair_succeeded: bool
    persisted: bool
    actions_applied: Tuple[str, ...]
    segments_regenerated: int
    requires_segment_regen: bool
    error: Optional[str]


# ---------------------------------------------------------------------------
# Transition and memory audit records
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TransitionRecord:
    """
    Audit record for a single lifecycle transition applied during a reflection cycle.

    from_state / to_state are state value strings.
    event is a SubgoalEvent value string.
    success=False means the transition was attempted but rejected.
    reason is either the explanation (success) or the rejection reason (failure).
    """
    subgoal_id: str
    from_state: str
    event: str
    to_state: Optional[str]
    success: bool
    reason: str


@dataclass(frozen=True)
class MemoryUpdateRecord:
    """
    Audit record for a single memory store write or rejection.

    store:     "subgoal" | "segment" | "plan" | "drift"
    operation: "write" | "reject"
    record_id: The ID of the record being written or rejected.
    details:   JSON-pure metadata (must contain only str/int/float/bool/None/list/dict).
    """
    store: str
    operation: str
    record_id: str
    details: Dict[str, Any]


# ---------------------------------------------------------------------------
# Trace and outcome
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReflectionTrace:
    """
    Append-only, JSON-serialisable record of one reflection cycle's work.

    All nested values are plain dicts/lists/scalars — no dataclasses or enums.
    """
    cycle: int
    timestamp: str
    progress: Dict[str, Any]
    drift: Dict[str, Any]
    repairs: Tuple[Dict[str, Any], ...]
    adjustments: Tuple[Dict[str, Any], ...]
    transitions: Tuple[Dict[str, Any], ...]
    memory_updates: Tuple[Dict[str, Any], ...]


@dataclass(frozen=True)
class ReflectionOutcome:
    """
    Complete, deterministic result of one reflection cycle.

    cycle / timestamp identify the cycle.
    progress:            Structural progress at cycle start.
    drift_report:        Drift detection result.
    validation_result:   Full validation pipeline result (focus subgoal), or None.
    plan_adjustment:     Plan repair outcome, or None if no plan was targeted.
    transitions_applied: Lifecycle transitions applied this cycle.
    memory_updates:      Governed memory writes and rejections this cycle.
    trace:               JSON-serialisable audit trace.
    errors:              Non-fatal errors encountered (cycle still produced output).
    """
    cycle: int
    timestamp: str
    progress: ProgressReport
    drift_report: ReflectionDriftReport
    validation_result: Optional[FullValidationResult]
    plan_adjustment: Optional[PlanAdjustment]
    transitions_applied: Tuple[TransitionRecord, ...]
    memory_updates: Tuple[MemoryUpdateRecord, ...]
    trace: ReflectionTrace
    errors: Tuple[str, ...]
