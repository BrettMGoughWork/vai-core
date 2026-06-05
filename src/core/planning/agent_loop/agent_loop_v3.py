"""
Phase 2.13.1 — Full Agent Loop (V3)
====================================

Deterministic, pure-function agent-level execution loop that coordinates:
- multi-subgoal execution
- multi-segment execution
- multi-cycle execution
- drift-aware execution
- repair-aware execution
- reflection-aware execution
- memory-aware execution (structured JSON state propagation)

Constraints
-----------
- Pure orchestration logic — no side effects, no mutation of inputs.
- No inference, no I/O, no LLM calls.
- Deterministic — identical inputs always produce identical outputs.
- JSON-safe — all output structures are serialisable to JSON.
- Reuses segment + subgoal execution modules from 2.11.x and 2.12.x.
- Does not modify plan structure outside the repair engine.
- Does not introduce new drift or repair semantics.
"""
from __future__ import annotations

import copy
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from src.core.planning.segments.drift import (
    SegmentDriftResult,
    apply_segment_repair,
    evaluate_segment_drift,
)
from src.core.planning.segments.execution import (
    SegmentExecutionState,
    SegmentLifecycle,
    advance_segment_index,
    segment_completion_summary,
    segment_progress_summary,
    transition_segment_state,
    update_segment_execution_state,
)
from src.core.planning.segments.reflection import (
    SegmentReflectionResult,
    evaluate_segment_completion,
    evaluate_segment_progress,
    reflect_on_segment,
)
from src.core.planning.segments.trace import (
    SegmentTrace,
    build_segment_trace,
    execute_segment_cycle,
)
from src.core.planning.subgoals.drift import (
    SubgoalDriftResult,
    apply_subgoal_repair,
    evaluate_subgoal_drift,
)
from src.core.planning.subgoals.execution import (
    SubgoalExecutionPhase,
    SubgoalExecutionState,
    advance_subgoal_index,
    is_agent_complete,
    subgoal_completion_summary,
    subgoal_progress_summary,
    transition_subgoal_state,
    update_subgoal_execution_state,
)
from src.core.planning.subgoals.reflection import (
    SubgoalReflectionResult,
    evaluate_subgoal_completion,
    evaluate_subgoal_progress,
    reflect_on_subgoal,
)
from src.core.planning.subgoals.trace import (
    SubgoalTrace,
    build_subgoal_trace,
    execute_subgoal_cycle,
)
from src.core.types.errors.AgentError import AgentError
from src.core.types.plan_segment import PlanSegment
from src.core.types.subgoal import Subgoal


# ──────────────────────────────────────────────────────────────────────────────
# AgentExecutionState
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentExecutionState:
    """Top-level execution cursor for the agent loop.

    Tracks cycle count, subgoal-level and segment-level execution progress,
    and whether the agent has completed all work.

    Fields
    ------
    cycle
        Monotonically-increasing cycle counter (0-based, incremented per cycle).
    subgoal_state
        Current ``SubgoalExecutionState`` (index + phase).
    segment_state
        Current ``SegmentExecutionState`` (index + phase).
    is_complete
        True when all subgoals and segments are complete.
    """

    cycle: int = 0
    subgoal_state: SubgoalExecutionState = field(
        default_factory=lambda: SubgoalExecutionState(index=0, state=SubgoalExecutionPhase.PENDING.value)
    )
    segment_state: SegmentExecutionState = field(
        default_factory=lambda: SegmentExecutionState(index=0, state=SegmentLifecycle.PENDING.value)
    )
    is_complete: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe summary dict."""
        return {
            "cycle": self.cycle,
            "subgoal_state": {
                "index": self.subgoal_state.index,
                "state": self.subgoal_state.state,
            },
            "segment_state": {
                "index": self.segment_state.index,
                "state": self.segment_state.state,
            },
            "is_complete": self.is_complete,
        }

    def __hash__(self) -> int:
        return hash(
            (
                self.cycle,
                self.subgoal_state.index,
                self.subgoal_state.state,
                self.segment_state.index,
                self.segment_state.state,
                self.is_complete,
            )
        )


# ──────────────────────────────────────────────────────────────────────────────
# AgentCycleRecord — per-cycle trace entry
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentCycleRecord:
    """Deterministic, JSON-safe trace entry for one agent cycle.

    Fields
    ------
    cycle
        Cycle number (0-based).
    subgoal_state
        Dict summary of ``SubgoalExecutionState`` after this cycle.
    segment_state
        Dict summary of ``SegmentExecutionState`` after this cycle.
    subgoal_trace
        ``SubgoalTrace`` for the subgoal-level work in this cycle, or None.
    segment_trace
        ``SegmentTrace`` for the segment-level work in this cycle, or None.
    is_complete
        Whether the agent is complete after this cycle.
    termination_reason
        Reason string if the agent terminated this cycle, else None.
    error
        ``AgentError`` if this cycle surfaced an error, else None.
    """

    cycle: int
    subgoal_state: Dict[str, Any]
    segment_state: Dict[str, Any]
    subgoal_trace: SubgoalTrace | None
    segment_trace: SegmentTrace | None
    is_complete: bool
    termination_reason: str | None = None
    error: AgentError | None = None

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe dict representation."""
        result: Dict[str, Any] = {
            "cycle": self.cycle,
            "subgoal_state": self.subgoal_state,
            "segment_state": self.segment_state,
            "is_complete": self.is_complete,
        }
        if self.subgoal_trace is not None:
            result["subgoal_trace"] = _trace_to_dict(self.subgoal_trace)
        if self.segment_trace is not None:
            result["segment_trace"] = _trace_to_dict(self.segment_trace)
        if self.termination_reason is not None:
            result["termination_reason"] = self.termination_reason
        if self.error is not None:
            result["error"] = self.error.to_dict()
        return result

    def __hash__(self) -> int:
        return hash(
            (
                self.cycle,
                json.dumps(self.subgoal_state, sort_keys=True),
                json.dumps(self.segment_state, sort_keys=True),
                self.subgoal_trace,
                self.segment_trace,
                self.is_complete,
                self.termination_reason,
                json.dumps(self.error.to_dict(), sort_keys=True) if self.error is not None else None,
            )
        )


# ──────────────────────────────────────────────────────────────────────────────
# AgentTrace
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentTrace:
    """Full deterministic trace for one agent loop run.

    Fields
    ------
    cycles
        One ``AgentCycleRecord`` per agent cycle, oldest first.
    subgoals
        All subgoal-level trace entries aggregated across cycles.
    segments
        All segment-level trace entries aggregated across cycles.
    errors
        All ``AgentError`` records surfaced during execution, oldest first.
    """

    cycles: List[Dict[str, Any]]
    subgoals: List[Dict[str, Any]]
    segments: List[Dict[str, Any]]
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycles": self.cycles,
            "subgoals": self.subgoals,
            "segments": self.segments,
            "errors": self.errors,
        }

    def __hash__(self) -> int:
        return hash(
            (
                json.dumps(self.cycles, sort_keys=True),
                json.dumps(self.subgoals, sort_keys=True),
                json.dumps(self.segments, sort_keys=True),
                json.dumps(self.errors, sort_keys=True),
            )
        )


# ──────────────────────────────────────────────────────────────────────────────
# AgentFullTrace
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentFullTrace:
    """Canonical unified trace for the entire agent execution lifecycle.

    Aggregates trace data across all levels: cycle-by-cycle state, agent
    transitions, subgoal/segment traces, drift signals, repair actions,
    reflection summaries, memory snapshots, and error records.

    Fields
    ------
    cycles
        One ``AgentCycleRecord`` per agent cycle, oldest first.
    agent
        Agent-level state transitions across cycles.
    subgoals
        All subgoal-level trace entries aggregated across cycles.
    segments
        All segment-level trace entries aggregated across cycles.
    drift
        Drift signals across all levels (segment + subgoal), per cycle.
    repairs
        Repair actions across all levels, per cycle.
    reflections
        Reflection summaries across all levels, per cycle.
    memory
        Full memory snapshots per cycle.
    errors
        All ``AgentError`` records surfaced during execution, oldest first.
    """

    cycles: List[Dict[str, Any]]
    agent: List[Dict[str, Any]]
    subgoals: List[Dict[str, Any]]
    segments: List[Dict[str, Any]]
    drift: List[Dict[str, Any]]
    repairs: List[Dict[str, Any]]
    reflections: List[Dict[str, Any]]
    memory: List[Dict[str, Any]]
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycles": self.cycles,
            "agent": self.agent,
            "subgoals": self.subgoals,
            "segments": self.segments,
            "drift": self.drift,
            "repairs": self.repairs,
            "reflections": self.reflections,
            "memory": self.memory,
            "errors": self.errors,
        }

    def __hash__(self) -> int:
        return hash(
            (
                json.dumps(self.cycles, sort_keys=True),
                json.dumps(self.agent, sort_keys=True),
                json.dumps(self.subgoals, sort_keys=True),
                json.dumps(self.segments, sort_keys=True),
                json.dumps(self.drift, sort_keys=True),
                json.dumps(self.repairs, sort_keys=True),
                json.dumps(self.reflections, sort_keys=True),
                json.dumps(self.memory, sort_keys=True),
                json.dumps(self.errors, sort_keys=True),
            )
        )


# ──────────────────────────────────────────────────────────────────────────────
# AgentLoopResult
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentLoopResult:
    """Final result of one ``run_agent_loop`` invocation.

    Fields
    ------
    execution_state
        Final ``AgentExecutionState``.
    trace
        Complete ``AgentFullTrace``.
    is_complete
        Whether the agent finished all work (True) or hit max_cycles (False).
    termination_reason
        Machine-readable reason: ``"agent_complete"``, ``"max_cycles_exceeded"``,
        or ``"error"``.
    total_cycles
        Number of cycles actually executed.
    error
        ``AgentError`` if the loop terminated due to an error, else ``None``.
    """

    execution_state: AgentExecutionState
    trace: AgentFullTrace
    is_complete: bool
    termination_reason: str
    total_cycles: int
    error: AgentError | None = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "execution_state": self.execution_state.to_dict(),
            "trace": self.trace.to_dict(),
            "is_complete": self.is_complete,
            "termination_reason": self.termination_reason,
            "total_cycles": self.total_cycles,
        }
        if self.error is not None:
            d["error"] = self.error.to_dict()
        return d


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _trace_to_dict(trace: SubgoalTrace | SegmentTrace) -> Dict[str, Any]:
    """Convert a SubgoalTrace or SegmentTrace to a JSON-safe dict."""
    return {
        "transitions": trace.transitions,
        "drift": trace.drift,
        "repairs": trace.repairs,
        "reflections": trace.reflections,
    }


def _get_segments_for_subgoal(
    subgoal: Subgoal,
    all_segments: List[PlanSegment],
) -> List[PlanSegment]:
    """Filter segments belonging to the given subgoal, ordered deterministically.

    Parameters
    ----------
    subgoal
        The subgoal to filter segments for.
    all_segments
        Full list of segments (may belong to multiple subgoals).

    Returns
    -------
    list[PlanSegment]
        Segments with ``subgoal_id`` matching ``subgoal.subgoal_id``,
        sorted by ``segment_id`` for deterministic ordering.
    """
    matching = [s for s in all_segments if s.subgoal_id == subgoal.subgoal_id]
    matching.sort(key=lambda s: s.segment_id)
    return matching


def _has_remaining_segments(
    segment_exec: SegmentExecutionState,
    total_segments: int,
) -> bool:
    """Check if there are more segments to process after the current one.

    Returns True if segment_exec.index is not at the final segment.
    """
    if total_segments <= 0:
        return False
    return advance_segment_index(segment_exec.index, total_segments) != segment_exec.index


def _should_advance_to_next_segment(
    segment_exec: SegmentExecutionState,
    total_segments: int,
) -> bool:
    """Check whether the segment cursor should advance to the next segment.

    Advances when:
    - Current segment state is COMPLETE
    - There are more segments available
    """
    if segment_exec.state != SegmentLifecycle.COMPLETE:
        return False
    return _has_remaining_segments(segment_exec, total_segments)


def _reset_segment_state_for_new_subgoal() -> SegmentExecutionState:
    """Return a fresh SegmentExecutionState for a new subgoal."""
    return SegmentExecutionState(index=0, state=SegmentLifecycle.PENDING.value)


# ──────────────────────────────────────────────────────────────────────────────
# Pure helper: run one segment operation within a subgoal
# ──────────────────────────────────────────────────────────────────────────────


def _run_segment_in_subgoal(
    segment_exec: SegmentExecutionState,
    sg_segments: List[PlanSegment],
) -> Dict[str, Any]:
    """Run one segment cycle for the current segment in a subgoal.

    Returns a dict with ``execution_state``, ``segment_trace``, and the
    segment result (repaired or original).
    """
    if not sg_segments:
        return {
            "execution_state": segment_exec,
            "segment_trace": None,
            "segment": None,
        }

    seg = sg_segments[min(segment_exec.index, len(sg_segments) - 1)]
    result = execute_segment_cycle(segment_exec, seg, len(sg_segments))
    return {
        "execution_state": result["execution_state"],
        "segment_trace": result["segment_trace"],
        "segment": result["segment"],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Pure helpers: error handling (2.13.2)
# ──────────────────────────────────────────────────────────────────────────────


def _json_ensure_serializable(obj: Any) -> None:
    """Raise ``TypeError`` or ``ValueError`` if *obj* cannot round-trip through JSON."""
    json.dumps(obj, default=str)


def _extract_latest_drift(
    segment_trace: SegmentTrace | None,
    subgoal_trace: SubgoalTrace | None,
) -> Dict[str, Any] | None:
    """Extract the most recent drift data from traces.

    Prefers subgoal-level drift if available, falls back to segment-level.
    Returns ``None`` if no drift data is found.
    """
    if subgoal_trace is not None and hasattr(subgoal_trace, "drift") and subgoal_trace.drift:
        return subgoal_trace.drift[-1] if subgoal_trace.drift else None
    if segment_trace is not None and hasattr(segment_trace, "drift") and segment_trace.drift:
        return segment_trace.drift[-1] if segment_trace.drift else None
    return None


def _extract_latest_repair(
    segment_trace: SegmentTrace | None,
    subgoal_trace: SubgoalTrace | None,
) -> Dict[str, Any] | None:
    """Extract the most recent repair data from traces.

    Prefers subgoal-level repair if available, falls back to segment-level.
    Returns ``None`` if no repair data is found.
    """
    if subgoal_trace is not None and hasattr(subgoal_trace, "repairs") and subgoal_trace.repairs:
        return subgoal_trace.repairs[-1] if subgoal_trace.repairs else None
    if segment_trace is not None and hasattr(segment_trace, "repairs") and segment_trace.repairs:
        return segment_trace.repairs[-1] if segment_trace.repairs else None
    return None


def _make_agent_error(
    error_type: str,
    message: str,
    details: Dict[str, Any] | None = None,
    recoverable: bool = False,
) -> AgentError:
    """Create an ``AgentError`` with consistent timestamp and recoverable flag.

    All errors surfaced during the agent loop are non-recoverable by default,
    as they represent catastrophic states that require loop termination.
    """
    return AgentError(
        type=error_type,
        message=message,
        details=details or {},
        timestamp=datetime.now(timezone.utc).isoformat(),
        recoverable=recoverable,
    )


def classify_catastrophic_drift(drift_result: Dict[str, Any]) -> AgentError | None:
    """Return an ``AgentError`` if *drift* severity is catastrophic.

    Catastrophic drift means the agent cannot self-correct and must stop.
    """
    if not isinstance(drift_result, dict):
        return None

    drift_signals: List[Dict[str, Any]] = drift_result.get("drift") or []
    if not isinstance(drift_signals, list):
        return None

    for signal_dict in drift_signals:
        if not isinstance(signal_dict, dict):
            continue
        severity = signal_dict.get("severity", "")
        if isinstance(severity, str) and severity.lower() == "catastrophic":
            return _make_agent_error(
                error_type="catastrophic_drift",
                message=f"Catastrophic drift detected: {signal_dict.get('signal_type', 'unknown')}",
                details={
                    "drift_signal": signal_dict,
                    "severity": severity,
                },
            )
    return None


def detect_repair_failure(repair_result: Dict[str, Any] | None) -> AgentError | None:
    """Detect catastrophic repair failure.

    Returns an ``AgentError`` if the repair action is ``repair_failed``,
    the repaired structure is invalid, or the output is not JSON‑safe.
    """
    if repair_result is None:
        return None
    if not isinstance(repair_result, dict):
        return _make_agent_error(
            error_type="repair_failure",
            message="Repair result is not a dict (type error).",
            details={"repair_result_type": type(repair_result).__name__},
        )

    action = repair_result.get("action", "")
    if action == "repair_failed":
        return _make_agent_error(
            error_type="repair_failure",
            message="Repair action explicitly failed.",
            details={"repair_result": repair_result},
        )

    # Validate that a repaired subgoal/segment is structurally present
    if action == "repair_subgoal":
        repaired = repair_result.get("repaired")
        if repaired is None:
            return _make_agent_error(
                error_type="repair_failure",
                message="repair_subgoal produced no repaired result.",
                details={"repair_result": repair_result},
            )

    # Check JSON‑safety of the full repair result
    try:
        _json_ensure_serializable(repair_result)
    except (TypeError, ValueError) as exc:
        return _make_agent_error(
            error_type="repair_failure",
            message=f"Repair result is not JSON‑safe: {exc}",
            details={"repair_result_keys": list(repair_result.keys())},
        )

    return None


def validate_memory_state(memory: Dict[str, Any]) -> AgentError | None:
    """Validate *memory* for structural integrity.

    Required keys: ``drift_memory``, ``repair_memory``, ``reflection_memory``.
    Values must be JSON‑safe dicts or lists.
    """
    if not isinstance(memory, dict):
        return _make_agent_error(
            error_type="invalid_memory",
            message="Memory is not a dict.",
            details={"memory_type": type(memory).__name__},
        )

    required_keys = {"drift_memory", "repair_memory", "reflection_memory"}
    missing = required_keys - set(memory.keys())
    if missing:
        return _make_agent_error(
            error_type="invalid_memory",
            message=f"Memory missing required keys: {sorted(missing)}",
            details={"missing_keys": sorted(missing), "present_keys": sorted(memory.keys())},
        )

    for key in required_keys:
        value = memory.get(key)
        if value is None:
            return _make_agent_error(
                error_type="invalid_memory",
                message=f"Memory key '{key}' is None.",
                details={"key": key},
            )
        if not isinstance(value, (dict, list)):
            return _make_agent_error(
                error_type="invalid_memory",
                message=f"Memory key '{key}' has invalid type: {type(value).__name__}.",
                details={"key": key, "type": type(value).__name__},
            )

    # JSON‑safety check
    try:
        _json_ensure_serializable(memory)
    except (TypeError, ValueError) as exc:
        return _make_agent_error(
            error_type="invalid_memory",
            message=f"Memory is not JSON‑safe: {exc}",
            details={"memory_keys": sorted(memory.keys())},
        )

    return None


def validate_subgoal_state(
    subgoal_state: SubgoalExecutionState,
    total_subgoals: int,
) -> AgentError | None:
    """Validate *subgoal_state* index and lifecycle state."""
    if subgoal_state.index < 0:
        return _make_agent_error(
            error_type="invalid_subgoal_state",
            message=f"Subgoal index is negative: {subgoal_state.index}",
            details={"index": subgoal_state.index, "total_subgoals": total_subgoals},
        )
    if total_subgoals > 0 and subgoal_state.index >= total_subgoals:
        # Allow index == total_subgoals as a past-the-end sentinel when the
        # final subgoal has completed (set by update_subgoal_execution_state).
        if not (
            subgoal_state.index == total_subgoals
            and subgoal_state.state == SubgoalExecutionPhase.COMPLETE
        ):
            return _make_agent_error(
                error_type="invalid_subgoal_state",
                message=f"Subgoal index {subgoal_state.index} out of range (total={total_subgoals}).",
                details={"index": subgoal_state.index, "total_subgoals": total_subgoals},
            )

    valid_states = {s.value for s in SubgoalExecutionPhase}
    if subgoal_state.state not in valid_states:
        return _make_agent_error(
            error_type="invalid_subgoal_state",
            message=f"Unknown subgoal state: {subgoal_state.state}",
            details={"state": subgoal_state.state, "valid_states": sorted(valid_states)},
        )
    return None


def validate_segment_state(
    segment_state: SegmentExecutionState,
    total_segments: int,
) -> AgentError | None:
    """Validate *segment_state* index and lifecycle state."""
    if segment_state.index < 0:
        return _make_agent_error(
            error_type="invalid_segment_state",
            message=f"Segment index is negative: {segment_state.index}",
            details={"index": segment_state.index, "total_segments": total_segments},
        )
    if total_segments > 0 and segment_state.index >= total_segments:
        return _make_agent_error(
            error_type="invalid_segment_state",
            message=f"Segment index {segment_state.index} out of range (total={total_segments}).",
            details={"index": segment_state.index, "total_segments": total_segments},
        )

    valid_states = {s.value for s in SegmentLifecycle}
    if segment_state.state not in valid_states:
        return _make_agent_error(
            error_type="invalid_segment_state",
            message=f"Unknown segment state: {segment_state.state}",
            details={"state": segment_state.state, "valid_states": sorted(valid_states)},
        )
    return None


def evaluate_agent_errors(
    agent_state: AgentExecutionState,
    drift_result: Dict[str, Any] | None,
    repair_result: Dict[str, Any] | None,
    memory: Dict[str, Any],
    total_subgoals: int,
    total_segments: int,
) -> AgentError | None:
    """Run all error checks in priority order.

    Returns the first ``AgentError`` encountered, or ``None`` if all checks pass.
    """
    # 1. catastrophic drift
    if drift_result is not None:
        err = classify_catastrophic_drift(drift_result)
        if err is not None:
            return err

    # 2. repair failure
    err = detect_repair_failure(repair_result)
    if err is not None:
        return err

    # 3. invalid memory
    err = validate_memory_state(memory)
    if err is not None:
        return err

    # 4. invalid subgoal state
    err = validate_subgoal_state(agent_state.subgoal_state, total_subgoals)
    if err is not None:
        return err

    # 5. invalid segment state
    err = validate_segment_state(agent_state.segment_state, total_segments)
    if err is not None:
        return err

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Main agent loop
# ──────────────────────────────────────────────────────────────────────────────


def run_agent_loop(
    subgoals: List[Subgoal],
    segments: List[PlanSegment],
    max_cycles: int,
) -> AgentLoopResult:
    """Execute the full agent-level loop across subgoals, segments, and cycles.

    Orchestration order per cycle (deterministic):

    1. Identify current subgoal and its segments.
    2. Run segment-level cycle on the current segment
       (reflect → drift → repair → transition → trace).
    3. If segment transitioned to COMPLETE and more segments exist,
       advance segment index for the next cycle.
    4. After all segments for the subgoal are complete, run subgoal-level cycle
       (reflect → drift → repair → transition → trace).
    5. If subgoal is complete and more subgoals exist, advance subgoal index.
    6. If agent is complete, terminate.
    7. Append cycle record to trace.

    The loop terminates when:
    - All subgoals (and their segments) are complete (``is_complete=True``), or
    - ``max_cycles`` is reached (``is_complete=False``,
      ``termination_reason="max_cycles_exceeded"``).

    Parameters
    ----------
    subgoals
        Ordered list of subgoals to execute.
    segments
        All segments across all subgoals (filtered per subgoal by ``subgoal_id``).
    max_cycles
        Maximum number of agent cycles before forced termination.

    Returns
    -------
    AgentLoopResult
        Final execution state, full trace, completion status, and termination reason.
    """
    total_subgoals = len(subgoals)

    # ── Initialise execution cursors ──────────────────────────────────────
    subgoal_exec = SubgoalExecutionState(index=0, state=SubgoalExecutionPhase.PENDING.value)
    segment_exec = _reset_segment_state_for_new_subgoal()

    # ── Trace accumulators ────────────────────────────────────────────────
    cycle_records: List[Dict[str, Any]] = []
    agent_records: List[Dict[str, Any]] = []
    subgoal_traces_all: List[Dict[str, Any]] = []
    segment_traces_all: List[Dict[str, Any]] = []
    drift_records: List[Dict[str, Any]] = []
    repair_records: List[Dict[str, Any]] = []
    reflection_records: List[Dict[str, Any]] = []
    memory_snapshots: List[Dict[str, Any]] = []
    error_records: List[Dict[str, Any]] = []
    last_error: AgentError | None = None
    agent_is_done = False
    termination_reason: str = "max_cycles_exceeded"

    # ── Memory (structured JSON state passed forward) ─────────────────────
    memory: Dict[str, Any] = {
        "drift_memory": {},
        "repair_memory": {},
        "reflection_memory": {},
    }

    # ── Edge case: no subgoals ────────────────────────────────────────────
    if total_subgoals == 0:
        final_state = AgentExecutionState(
            cycle=0,
            subgoal_state=subgoal_exec,
            segment_state=segment_exec,
            is_complete=True,
        )
        return AgentLoopResult(
            execution_state=final_state,
            trace=AgentFullTrace(
                cycles=[],
                agent=[],
                subgoals=[],
                segments=[],
                drift=[],
                repairs=[],
                reflections=[],
                memory=[],
                errors=[],
            ),
            is_complete=True,
            termination_reason="agent_complete",
            total_cycles=0,
        )

    # ── Main cycle loop ───────────────────────────────────────────────────
    for cycle in range(max_cycles):
        agent_is_done = False
        termination_reason: str | None = None

        # ── Get current subgoal ───────────────────────────────────────────
        sg_index = min(subgoal_exec.index, total_subgoals - 1)
        current_subgoal = subgoals[sg_index]
        sg_segments = _get_segments_for_subgoal(current_subgoal, segments)
        total_sg_segments = len(sg_segments)

        # ── Handle subgoal with no segments (trivially complete) ──────────
        if total_sg_segments == 0:
            # A subgoal with zero segments is trivially complete,
            # so we mark it COMPLETE directly in one cycle.
            subgoal_exec = SubgoalExecutionState(
                index=subgoal_exec.index,
                state=SubgoalExecutionPhase.COMPLETE.value,
            )

            # Check if this was the final subgoal
            if advance_subgoal_index(subgoal_exec.index, total_subgoals) == subgoal_exec.index:
                # Already at final subgoal → agent complete
                agent_is_done = True
            else:
                # Advance cursor to next subgoal, reset to PENDING
                next_idx = advance_subgoal_index(subgoal_exec.index, total_subgoals)
                subgoal_exec = SubgoalExecutionState(
                    index=next_idx,
                    state=SubgoalExecutionPhase.PENDING.value,
                )
                segment_exec = _reset_segment_state_for_new_subgoal()

            # Build cycle record
            cycle_record = AgentCycleRecord(
                cycle=cycle,
                subgoal_state={
                    "index": subgoal_exec.index,
                    "state": subgoal_exec.state,
                },
                segment_state={
                    "index": segment_exec.index,
                    "state": segment_exec.state,
                },
                subgoal_trace=None,
                segment_trace=None,
                is_complete=agent_is_done,
            )
            cycle_records.append(cycle_record.to_dict())

            # ── Full trace entries for empty-segments subgoal ──────────────
            agent_records.append({
                "cycle": cycle,
                "subgoal_index": subgoal_exec.index,
                "subgoal_state": subgoal_exec.state,
                "segment_index": segment_exec.index,
                "segment_state": segment_exec.state,
                "is_complete": agent_is_done,
            })
            # No drift/repair/reflection entries (no segment/subgoal trace)
            memory_snapshots.append({
                "cycle": cycle,
                "memory_snapshot": copy.deepcopy(memory),
            })

            if agent_is_done:
                termination_reason = "agent_complete"
                break
            continue

        # ── Pending → Active: auto-advance segment on first touch ─────────
        if segment_exec.state == SegmentLifecycle.PENDING:
            segment_exec = SegmentExecutionState(
                index=segment_exec.index,
                state=transition_segment_state(segment_exec.state, False),
            )

        # ── Ensure segment index is in bounds ─────────────────────────────
        seg_index = min(segment_exec.index, total_sg_segments - 1)

        # ── 1-3. Run segment cycle
        #   (reflect_on_segment → evaluate_segment_drift → repair → transition) ──
        seg_result = execute_segment_cycle(
            segment_exec,
            sg_segments[seg_index],
            total_sg_segments,
        )
        segment_exec = seg_result["execution_state"]
        segment_trace: SegmentTrace | None = seg_result.get("segment_trace")

        if segment_trace is not None:
            segment_traces_all.append(_trace_to_dict(segment_trace))

        # ── 4. If segment completed and there are more, reset to PENDING
        #      for the next segment so the PENDING→ACTIVE block fires next cycle.
        if (
            segment_exec.state == SegmentLifecycle.COMPLETE
            and _has_remaining_segments(segment_exec, total_sg_segments)
        ):
            segment_exec = SegmentExecutionState(
                index=segment_exec.index,
                state=SegmentLifecycle.PENDING,
            )

        # ── 5. Check subgoal completion — all segments done ───────────────
        all_segments_done = (
            segment_exec.state == SegmentLifecycle.COMPLETE
            and not _has_remaining_segments(segment_exec, total_sg_segments)
        )

        if all_segments_done:
            # ── 6-9. Run subgoal cycle ────────────────────────────────────
            sg_result = execute_subgoal_cycle(subgoal_exec, current_subgoal, total_subgoals)
            subgoal_exec = sg_result["execution_state"]
            subgoal_trace: SubgoalTrace | None = sg_result.get("subgoal_trace")

            if subgoal_trace is not None:
                subgoal_traces_all.append(_trace_to_dict(subgoal_trace))

            # ── 10. If subgoal complete but there are remaining subgoals
            #      to execute, reset both subgoal and segment state so the
            #      next cycle picks up the new subgoal from PENDING.
            if (
                subgoal_exec.state == SubgoalExecutionPhase.COMPLETE
                and subgoal_exec.index < total_subgoals
            ):
                subgoal_exec = SubgoalExecutionState(
                    index=subgoal_exec.index,
                    state=SubgoalExecutionPhase.PENDING.value,
                )
                segment_exec = _reset_segment_state_for_new_subgoal()

            # ── 11. Check agent completion ────────────────────────────────
            # Agent is truly done when subgoal is COMPLETE and index is
            # at-or-past total_subgoals (set by update_subgoal_execution_state
            # when the final subgoal completed).
            if (
                subgoal_exec.state == SubgoalExecutionPhase.COMPLETE
                and subgoal_exec.index >= total_subgoals
            ):
                agent_is_done = True

        # ── 12. Error handling (2.13.2) ──────────────────────────────────
        # Build best-effort drift_result and repair_result from traces.
        drift_result = _extract_latest_drift(segment_trace, subgoal_trace if all_segments_done else None)
        repair_result = _extract_latest_repair(segment_trace, subgoal_trace if all_segments_done else None)

        agent_state = AgentExecutionState(
            cycle=cycle,
            subgoal_state=subgoal_exec,
            segment_state=segment_exec,
            is_complete=False,
        )
        error = evaluate_agent_errors(
            agent_state=agent_state,
            drift_result=drift_result,
            repair_result=repair_result,
            memory=memory,
            total_subgoals=total_subgoals,
            total_segments=total_sg_segments,
        )

        if error is not None:
            last_error = error
            error_records.append({
                "cycle": cycle,
                "error_type": error.type,
                "message": error.message,
                "details": error.details,
            })
            # Update memory with error info
            memory["repair_memory"] = {
                **memory.get("repair_memory", {}),
                f"cycle_{cycle}_error": error.to_dict(),
            }

        # ── Build cycle record ────────────────────────────────────────────
        cycle_record = AgentCycleRecord(
            cycle=cycle,
            subgoal_state={
                "index": subgoal_exec.index,
                "state": subgoal_exec.state,
            },
            segment_state={
                "index": segment_exec.index,
                "state": segment_exec.state,
            },
            subgoal_trace=subgoal_trace if all_segments_done else None,
            segment_trace=segment_trace,
            is_complete=agent_is_done,
            error=error,
        )
        cycle_records.append(cycle_record.to_dict())

        # ── Full trace entries (2.13.3) ───────────────────────────────────

        # Agent-level state transition record
        agent_records.append({
            "cycle": cycle,
            "subgoal_index": subgoal_exec.index,
            "subgoal_state": subgoal_exec.state,
            "segment_index": segment_exec.index,
            "segment_state": segment_exec.state,
            "is_complete": agent_is_done,
        })

        # Drift entries — extract from segment and subgoal traces
        if segment_trace is not None:
            for d in segment_trace.drift:
                drift_records.append({
                    "cycle": cycle,
                    "level": "segment",
                    "index": segment_exec.index,
                    **d,
                })
        if all_segments_done and subgoal_trace is not None:
            for d in subgoal_trace.drift:
                drift_records.append({
                    "cycle": cycle,
                    "level": "subgoal",
                    "index": subgoal_exec.index,
                    **d,
                })

        # Repair entries — extract from segment and subgoal traces
        if segment_trace is not None:
            for r in segment_trace.repairs:
                repair_records.append({
                    "cycle": cycle,
                    "level": "segment",
                    "action": r.get("action", "none"),
                    "repaired": r.get("repaired"),
                })
        if all_segments_done and subgoal_trace is not None:
            for r in subgoal_trace.repairs:
                repair_records.append({
                    "cycle": cycle,
                    "level": "subgoal",
                    "action": r.get("action", "none"),
                    "repaired": r.get("repaired"),
                })

        # Reflection entries — extract from segment and subgoal traces
        if segment_trace is not None:
            for rfl in segment_trace.reflections:
                reflection_records.append({
                    "cycle": cycle,
                    "level": "segment",
                    "progress": rfl.get("progress"),
                    "drift": rfl.get("drift"),
                    "repair": rfl.get("repair"),
                    "is_complete": rfl.get("is_complete"),
                })
        if all_segments_done and subgoal_trace is not None:
            for rfl in subgoal_trace.reflections:
                reflection_records.append({
                    "cycle": cycle,
                    "level": "subgoal",
                    "progress": rfl.get("progress"),
                    "drift": rfl.get("drift"),
                    "repair": rfl.get("repair"),
                    "is_complete": rfl.get("is_complete"),
                })

        # Memory snapshot per cycle
        memory_snapshots.append({
            "cycle": cycle,
            "memory_snapshot": copy.deepcopy(memory),
        })

        # ── 13. Terminate on error ───────────────────────────────────────
        if error is not None:
            termination_reason = "error"
            agent_is_done = False
            break

        if agent_is_done:
            termination_reason = "agent_complete"
            break

    # ── Post-loop: determine termination reason ───────────────────────────
    # The loop variable holds the last value used in the for loop,
    # but to be safe we compute explicitly:
    if agent_is_done:
        final_is_complete = True
        final_reason = "agent_complete"
        total_cycles_executed = len(cycle_records)
    elif termination_reason == "error":
        final_is_complete = False
        final_reason = "error"
        total_cycles_executed = len(cycle_records)
    else:
        final_is_complete = False
        final_reason = "max_cycles_exceeded"
        total_cycles_executed = max_cycles

    final_exec_state = AgentExecutionState(
        cycle=total_cycles_executed,
        subgoal_state=subgoal_exec,
        segment_state=segment_exec,
        is_complete=final_is_complete,
    )

    return AgentLoopResult(
        execution_state=final_exec_state,
        trace=AgentFullTrace(
            cycles=cycle_records,
            agent=agent_records,
            subgoals=subgoal_traces_all,
            segments=segment_traces_all,
            drift=drift_records,
            repairs=repair_records,
            reflections=reflection_records,
            memory=memory_snapshots,
            errors=error_records,
        ),
        is_complete=final_is_complete,
        termination_reason=final_reason,
        total_cycles=total_cycles_executed,
        error=last_error,
    )
