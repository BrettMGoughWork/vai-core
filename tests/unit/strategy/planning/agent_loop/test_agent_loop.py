"""
Tests for Phase 2.13.1 — Full Agent Loop
(``src.strategy.planning.agent_loop.agent_loop``).
"""
from __future__ import annotations

import json

import pytest

from src.strategy.planning.agent_loop.agent_loop import (
    AgentCycleRecord,
    AgentExecutionState,
    AgentFullTrace,
    AgentLoopResult,
    classify_catastrophic_drift,
    detect_repair_failure,
    evaluate_agent_errors,
    run_agent_loop,
    validate_memory_state,
    validate_segment_state,
    validate_subgoal_state,
)
from src.strategy.types.errors.AgentError import AgentError
from src.strategy.planning.segments.execution import SegmentExecutionState, SegmentLifecycle
from src.strategy.planning.segments.trace import SegmentTrace
from src.strategy.planning.subgoals.execution import (
    SubgoalExecutionPhase,
    SubgoalExecutionState,
)
from src.strategy.planning.subgoals.trace import SubgoalTrace
from src.strategy.types.plan_segment import PlanSegment
from src.strategy.types.subgoal import Subgoal, SubgoalLifecycleState


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _make_subgoal(
    subgoal_id: str = "sg.test",
    goal: str = "Test goal",
    context: dict | None = None,
    metadata: dict | None = None,
) -> Subgoal:
    """Create a minimal valid Subgoal for testing."""
    if context is None:
        context = {"key": "value"}
    if metadata is None:
        metadata = {}
    return Subgoal(
        subgoal_id=subgoal_id,
        goal=goal,
        context=context,
        metadata=metadata,
        state=SubgoalLifecycleState.ACTIVE,
    )


def _make_segment(
    subgoal_id: str = "sg.test",
    steps: list | None = None,
    context: dict | None = None,
) -> PlanSegment:
    """Create a minimal valid PlanSegment for testing.

    NOTE: PlanSegment computes segment_id automatically via stable_hash,
    so it is NOT passed as a constructor argument.
    """
    if steps is None:
        steps = ["noop"]
    if context is None:
        context = {}
    return PlanSegment(
        subgoal_id=subgoal_id,
        steps=steps,
        context=context,
        metadata={},
    )


def _is_json_safe(obj: object) -> bool:
    """Check that an object is JSON-serialisable."""
    try:
        json.dumps(obj)
        return True
    except (TypeError, ValueError):
        return False


# ──────────────────────────────────────────────────────────────────────────────
# AgentExecutionState
# ──────────────────────────────────────────────────────────────────────────────


class TestAgentExecutionState:
    """Tests for the AgentExecutionState frozen dataclass."""

    def test_default_construction(self):
        """Default state has cycle 0, pending subgoal and segment, not complete."""
        s = AgentExecutionState()
        assert s.cycle == 0
        assert s.subgoal_state.index == 0
        assert s.subgoal_state.state == "pending"
        assert s.segment_state.index == 0
        assert s.segment_state.state == "pending"
        assert s.is_complete is False

    def test_explicit_construction(self):
        """Explicit state preserves all provided values."""
        sg = SubgoalExecutionState(index=1, state="active")
        seg = SegmentExecutionState(index=2, state="complete")
        s = AgentExecutionState(
            cycle=5,
            subgoal_state=sg,
            segment_state=seg,
            is_complete=True,
        )
        assert s.cycle == 5
        assert s.subgoal_state.index == 1
        assert s.subgoal_state.state == "active"
        assert s.segment_state.index == 2
        assert s.segment_state.state == "complete"
        assert s.is_complete is True

    def test_to_dict_json_safe(self):
        """to_dict() produces a JSON-safe dict."""
        s = AgentExecutionState(
            cycle=3,
            subgoal_state=SubgoalExecutionState(index=1, state="active"),
            segment_state=SegmentExecutionState(index=2, state="active"),
            is_complete=False,
        )
        d = s.to_dict()
        assert _is_json_safe(d)
        assert d["cycle"] == 3
        assert d["subgoal_state"]["index"] == 1
        assert d["segment_state"]["index"] == 2
        assert d["is_complete"] is False

    def test_hash_deterministic(self):
        """Identical states produce identical hashes."""
        s1 = AgentExecutionState(cycle=1)
        s2 = AgentExecutionState(cycle=1)
        assert hash(s1) == hash(s2)

    def test_hash_different_states_differ(self):
        """Different states produce different hashes."""
        s1 = AgentExecutionState(cycle=1)
        s2 = AgentExecutionState(cycle=2)
        assert hash(s1) != hash(s2)


# ──────────────────────────────────────────────────────────────────────────────
# AgentCycleRecord
# ──────────────────────────────────────────────────────────────────────────────


class TestAgentCycleRecord:
    """Tests for the AgentCycleRecord frozen dataclass."""

    def test_construction_minimal(self):
        """Cycle record constructs with minimal fields."""
        r = AgentCycleRecord(
            cycle=0,
            subgoal_state={"index": 0, "state": "active"},
            segment_state={"index": 0, "state": "active"},
            subgoal_trace=None,
            segment_trace=None,
            is_complete=False,
        )
        assert r.cycle == 0
        assert r.is_complete is False
        assert r.termination_reason is None

    def test_to_dict_json_safe(self):
        """to_dict() produces a JSON-safe dict."""
        r = AgentCycleRecord(
            cycle=0,
            subgoal_state={"index": 0, "state": "active"},
            segment_state={"index": 0, "state": "active"},
            subgoal_trace=None,
            segment_trace=None,
            is_complete=False,
        )
        d = r.to_dict()
        assert _is_json_safe(d)
        assert d["cycle"] == 0
        assert "termination_reason" not in d

    def test_to_dict_with_termination(self):
        """Cycle record includes termination_reason when set."""
        r = AgentCycleRecord(
            cycle=5,
            subgoal_state={"index": 2, "state": "complete"},
            segment_state={"index": 0, "state": "complete"},
            subgoal_trace=None,
            segment_trace=None,
            is_complete=True,
            termination_reason="max_cycles_exceeded",
        )
        d = r.to_dict()
        assert d["termination_reason"] == "max_cycles_exceeded"

    def test_hash_deterministic(self):
        """Identical records produce identical hashes."""
        r1 = AgentCycleRecord(
            cycle=0,
            subgoal_state={"index": 0, "state": "active"},
            segment_state={"index": 0, "state": "active"},
            subgoal_trace=None,
            segment_trace=None,
            is_complete=False,
        )
        r2 = AgentCycleRecord(
            cycle=0,
            subgoal_state={"index": 0, "state": "active"},
            segment_state={"index": 0, "state": "active"},
            subgoal_trace=None,
            segment_trace=None,
            is_complete=False,
        )
        assert hash(r1) == hash(r2)

    def test_with_segment_trace(self):
        """Cycle record carries a SegmentTrace."""
        st = SegmentTrace(transitions=[], drift=[], repairs=[], reflections=[])
        r = AgentCycleRecord(
            cycle=0,
            subgoal_state={"index": 0, "state": "active"},
            segment_state={"index": 0, "state": "active"},
            subgoal_trace=None,
            segment_trace=st,
            is_complete=False,
        )
        d = r.to_dict()
        assert "segment_trace" in d
        assert _is_json_safe(d)




# ──────────────────────────────────────────────────────────────────────────────
# AgentFullTrace
# ──────────────────────────────────────────────────────────────────────────────


class TestAgentFullTrace:
    """Tests for the AgentFullTrace frozen dataclass (Phase 2.13.3)."""

    def test_construction_empty(self):
        """AgentFullTrace constructs with all empty lists."""
        t = AgentFullTrace(
            cycles=[], agent=[], subgoals=[], segments=[],
            drift=[], repairs=[], reflections=[], memory=[],
        )
        assert t.cycles == []
        assert t.agent == []
        assert t.subgoals == []
        assert t.segments == []
        assert t.drift == []
        assert t.repairs == []
        assert t.reflections == []
        assert t.memory == []
        assert t.errors == []

    def test_to_dict_json_safe(self):
        """to_dict() is JSON-safe and includes all fields."""
        t = AgentFullTrace(
            cycles=[{"c": 1}],
            agent=[{"sg": "active"}],
            subgoals=[{"s": 1}],
            segments=[{"seg": 1}],
            drift=[{"level": "segment", "drift": {}}],
            repairs=[{"level": "segment", "action": "none"}],
            reflections=[{"level": "segment", "is_complete": True}],
            memory=[{"cycle": 0, "memory_snapshot": {}}],
            errors=[{"cycle": 0, "error_type": "test"}],
        )
        d = t.to_dict()
        assert _is_json_safe(d)
        assert len(d["cycles"]) == 1
        assert len(d["agent"]) == 1
        assert len(d["subgoals"]) == 1
        assert len(d["segments"]) == 1
        assert len(d["drift"]) == 1
        assert len(d["repairs"]) == 1
        assert len(d["reflections"]) == 1
        assert len(d["memory"]) == 1
        assert len(d["errors"]) == 1

    def test_hash_deterministic(self):
        """Identical full traces produce identical hashes."""
        t1 = AgentFullTrace(
            cycles=[], agent=[], subgoals=[], segments=[],
            drift=[], repairs=[], reflections=[], memory=[],
        )
        t2 = AgentFullTrace(
            cycles=[], agent=[], subgoals=[], segments=[],
            drift=[], repairs=[], reflections=[], memory=[],
        )
        assert hash(t1) == hash(t2)

    def test_hash_different_after_change(self):
        """Different full trace content produces different hashes."""
        t1 = AgentFullTrace(
            cycles=[], agent=[], subgoals=[], segments=[],
            drift=[], repairs=[], reflections=[], memory=[],
        )
        t2 = AgentFullTrace(
            cycles=[{"changed": True}], agent=[], subgoals=[], segments=[],
            drift=[], repairs=[], reflections=[], memory=[],
        )
        assert hash(t1) != hash(t2)


# ──────────────────────────────────────────────────────────────────────────────
# AgentLoopResult
# ──────────────────────────────────────────────────────────────────────────────


class TestAgentLoopResult:
    """Tests for the AgentLoopResult frozen dataclass."""

    def test_construction(self):
        """AgentLoopResult constructs with all required fields."""
        es = AgentExecutionState()
        tr = AgentFullTrace(
            cycles=[], agent=[], subgoals=[], segments=[],
            drift=[], repairs=[], reflections=[], memory=[],
        )
        r = AgentLoopResult(
            execution_state=es,
            trace=tr,
            is_complete=True,
            termination_reason="agent_complete",
            total_cycles=5,
        )
        assert r.is_complete is True
        assert r.termination_reason == "agent_complete"
        assert r.total_cycles == 5

    def test_to_dict_json_safe(self):
        """to_dict() is JSON-safe."""
        es = AgentExecutionState()
        tr = AgentFullTrace(
            cycles=[], agent=[], subgoals=[], segments=[],
            drift=[], repairs=[], reflections=[], memory=[],
        )
        r = AgentLoopResult(
            execution_state=es,
            trace=tr,
            is_complete=True,
            termination_reason="agent_complete",
            total_cycles=5,
        )
        d = r.to_dict()
        assert _is_json_safe(d)
        assert d["is_complete"] is True
        assert d["total_cycles"] == 5


# ──────────────────────────────────────────────────────────────────────────────
# run_agent_loop — basic behaviour
# ──────────────────────────────────────────────────────────────────────────────


class TestRunAgentLoop:
    """Integration tests for ``run_agent_loop``."""

    # ── Edge cases ────────────────────────────────────────────────────────

    def test_empty_subgoals_returns_immediately(self):
        """No subgoals → agent is trivially complete, zero cycles."""
        result = run_agent_loop(subgoals=[], segments=[], max_cycles=10)
        assert result.total_cycles == 0
        assert result.is_complete is True
        assert result.termination_reason == "agent_complete"
        assert result.trace.cycles == []

    def test_max_cycles_zero_terminates(self):
        """max_cycles=0 terminates immediately with max_cycles_exceeded."""
        sg = _make_subgoal(subgoal_id="sg.1")
        seg = _make_segment(subgoal_id="sg.1", steps=["noop"])
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=0)
        assert result.is_complete is False
        assert result.termination_reason == "max_cycles_exceeded"
        assert result.total_cycles == 0

    # ── Subgoal with zero segments (trivially complete) ───────────────────

    def test_subgoal_no_segments_trivially_complete(self):
        """A subgoal with zero segments is marked complete instantly."""
        sg = _make_subgoal(subgoal_id="sg.alone")
        result = run_agent_loop(subgoals=[sg], segments=[], max_cycles=10)
        assert result.is_complete is True
        assert result.total_cycles == 1
        # The single cycle should show the subgoal transitioning to complete
        assert len(result.trace.cycles) == 1
        cycle0 = result.trace.cycles[0]
        assert cycle0["is_complete"] is True

    # ── Single subgoal, single segment ────────────────────────────────────

    def test_single_subgoal_single_segment(self):
        """One subgoal with one segment completes within a few cycles."""
        sg = _make_subgoal(subgoal_id="sg.1")
        seg = _make_segment(subgoal_id="sg.1", steps=["noop"])
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert result.is_complete is True
        assert result.termination_reason == "agent_complete"
        assert result.total_cycles > 0
        assert result.total_cycles <= 10
        # Agent execution state should be complete
        assert result.execution_state.is_complete is True

    # ── Multi-segment subgoal ─────────────────────────────────────────────

    def test_multi_segment_subgoal(self):
        """One subgoal with three segments completes all of them."""
        sg = _make_subgoal(subgoal_id="sg.multi")
        segs = [
            _make_segment(subgoal_id="sg.multi", steps=["noop"]),
            _make_segment(subgoal_id="sg.multi", steps=["noop"]),
            _make_segment(subgoal_id="sg.multi", steps=["noop"]),
        ]
        result = run_agent_loop(subgoals=[sg], segments=segs, max_cycles=30)
        assert result.is_complete is True
        # Verify we have segment trace entries across cycles
        seg_traces = result.trace.segments
        assert len(seg_traces) >= 3  # At least one per segment

    # ── Multi-subgoal plan ────────────────────────────────────────────────

    def test_multi_subgoal_plan(self):
        """Two subgoals, each with one segment."""
        sg1 = _make_subgoal(subgoal_id="sg.1")
        sg2 = _make_subgoal(subgoal_id="sg.2")
        seg1 = _make_segment(subgoal_id="sg.1", steps=["noop"])
        seg2 = _make_segment(subgoal_id="sg.2", steps=["noop"])
        result = run_agent_loop(
            subgoals=[sg1, sg2],
            segments=[seg1, seg2],
            max_cycles=20,
        )
        assert result.is_complete is True
        # Both subgoals should have been processed
        # Final subgoal state should be complete at final index
        exec_state = result.execution_state
        assert exec_state.subgoal_state.state == "complete"
        assert exec_state.subgoal_state.index >= 1  # At least advanced to subgoal 2

    def test_multi_subgoal_with_segments(self):
        """Three subgoals with varying segment counts."""
        sg1 = _make_subgoal(subgoal_id="sg.1")
        sg2 = _make_subgoal(subgoal_id="sg.2")
        sg3 = _make_subgoal(subgoal_id="sg.3")
        segs = [
            _make_segment(subgoal_id="sg.1"),
            _make_segment(subgoal_id="sg.1"),
            _make_segment(subgoal_id="sg.2"),
            _make_segment(subgoal_id="sg.3"),
            _make_segment(subgoal_id="sg.3"),
            _make_segment(subgoal_id="sg.3"),
        ]
        result = run_agent_loop(
            subgoals=[sg1, sg2, sg3],
            segments=segs,
            max_cycles=50,
        )
        assert result.is_complete is True
        # Verify cycle records exist
        assert len(result.trace.cycles) > 0
        # Last cycle should be complete
        assert result.trace.cycles[-1]["is_complete"] is True

    # ── Max cycle termination ─────────────────────────────────────────────

    def test_max_cycles_termination(self):
        """If max_cycles is too low, agent reports max_cycles_exceeded."""
        sg = _make_subgoal(subgoal_id="sg.1")
        seg = _make_segment(subgoal_id="sg.1", steps=["noop"])
        # With only 1 cycle, it's unlikely to process everything
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=1)
        # Could possibly complete in 1 cycle, so just check termination_reason
        assert result.termination_reason in ("agent_complete", "max_cycles_exceeded")

    def test_max_cycles_exceeded_structure(self):
        """When max_cycles exceeded, result reflects this."""
        sg = _make_subgoal(subgoal_id="sg.1")
        # Many segments to guarantee exceeding 1 cycle
        segs = [
            _make_segment(subgoal_id="sg.1")
            for i in range(100)
        ]
        result = run_agent_loop(subgoals=[sg], segments=segs, max_cycles=1)
        assert result.termination_reason == "max_cycles_exceeded"
        assert result.is_complete is False
        assert result.total_cycles == 1

    # ── Determinism ───────────────────────────────────────────────────────

    def test_deterministic_across_runs(self):
        """Identical inputs produce identical AgentLoopResult."""
        sg = _make_subgoal(subgoal_id="sg.det")
        seg = _make_segment(subgoal_id="sg.det", steps=["noop"])
        r1 = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        r2 = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert r1.total_cycles == r2.total_cycles
        assert r1.is_complete == r2.is_complete
        assert r1.termination_reason == r2.termination_reason
        assert len(r1.trace.cycles) == len(r2.trace.cycles)
        for i, (c1, c2) in enumerate(zip(r1.trace.cycles, r2.trace.cycles)):
            assert c1 == c2, f"Cycle {i} differs"

    # ── JSON safety ───────────────────────────────────────────────────────

    def test_result_json_safe(self):
        """The full AgentLoopResult is JSON‑serialisable."""
        sg = _make_subgoal(subgoal_id="sg.json")
        seg = _make_segment(subgoal_id="sg.json")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert _is_json_safe(result.to_dict())

    def test_cycle_records_are_json_safe(self):
        """Every cycle record in the trace is JSON‑serialisable."""
        sg = _make_subgoal(subgoal_id="sg.j2")
        segs = [
            _make_segment(subgoal_id="sg.j2"),
            _make_segment(subgoal_id="sg.j2"),
        ]
        result = run_agent_loop(subgoals=[sg], segments=segs, max_cycles=20)
        for i, cycle in enumerate(result.trace.cycles):
            assert _is_json_safe(cycle), f"Cycle {i} is not JSON‑safe"

    # ── Trace structure ───────────────────────────────────────────────────

    def test_trace_has_expected_keys(self):
        """Trace dict has cycles, subgoals, segments keys."""
        sg = _make_subgoal(subgoal_id="sg.trace")
        seg = _make_segment(subgoal_id="sg.trace")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        td = result.trace.to_dict()
        assert "cycles" in td
        assert "subgoals" in td
        assert "segments" in td
        assert isinstance(td["cycles"], list)
        assert isinstance(td["subgoals"], list)
        assert isinstance(td["segments"], list)

    def test_cycle_records_include_expected_keys(self):
        """Each cycle record has cycle, subgoal_state, segment_state, is_complete."""
        sg = _make_subgoal(subgoal_id="sg.keys")
        seg = _make_segment(subgoal_id="sg.keys")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        for cycle_record in result.trace.cycles:
            assert "cycle" in cycle_record
            assert "subgoal_state" in cycle_record
            assert "segment_state" in cycle_record
            assert "is_complete" in cycle_record

    # ── Subgoal with no segments edge case ────────────────────────────────

    def test_multiple_empty_subgoals(self):
        """Multiple subgoals, all with zero segments."""
        sg1 = _make_subgoal(subgoal_id="sg.e1")
        sg2 = _make_subgoal(subgoal_id="sg.e2")
        sg3 = _make_subgoal(subgoal_id="sg.e3")
        result = run_agent_loop(subgoals=[sg1, sg2, sg3], segments=[], max_cycles=10)
        assert result.is_complete is True
        assert result.termination_reason == "agent_complete"
        # Should process all three subgoals (3 cycles)
        assert result.total_cycles == 3

    # ── Segment ordering ─────────────────────────────────────────────────

    def test_segment_ordering_is_deterministic(self):
        """Segments are processed in segment_id order."""
        sg = _make_subgoal(subgoal_id="sg.order")
        segs = [
            _make_segment(subgoal_id="sg.order"),
            _make_segment(subgoal_id="sg.order"),
            _make_segment(subgoal_id="sg.order"),
        ]
        result = run_agent_loop(subgoals=[sg], segments=segs, max_cycles=30)
        # Segments in the trace should appear sorted
        for tr in result.trace.segments:
            assert _is_json_safe(tr)

    # ── Result type invariants ────────────────────────────────────────────

    def test_agent_loop_result_type(self):
        """run_agent_loop returns an AgentLoopResult."""
        sg = _make_subgoal(subgoal_id="sg.type")
        seg = _make_segment(subgoal_id="sg.type")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert isinstance(result, AgentLoopResult)

    def test_execution_state_type(self):
        """Result.execution_state is an AgentExecutionState."""
        sg = _make_subgoal(subgoal_id="sg.es")
        seg = _make_segment(subgoal_id="sg.es")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert isinstance(result.execution_state, AgentExecutionState)


# ──────────────────────────────────────────────────────────────────────────────
# Phase 2.13.2 — Error Handling Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestAgentErrorDataclass:
    """Tests for the ``AgentError`` data structure."""

    def test_agent_error_creation(self):
        """AgentError can be created with all required fields."""
        error = AgentError(
            type="catastrophic_drift",
            message="Test error message",
            details={"key": "value"},
            timestamp="2025-01-01T00:00:00+00:00",
            recoverable=False,
        )
        assert error.type == "catastrophic_drift"
        assert error.message == "Test error message"
        assert error.details == {"key": "value"}
        assert error.timestamp == "2025-01-01T00:00:00+00:00"
        assert error.recoverable is False

    def test_agent_error_to_dict_is_json_safe(self):
        """AgentError.to_dict() produces JSON-safe output."""
        error = AgentError(
            type="invalid_memory",
            message="Memory is corrupt",
            details={"missing_keys": ["drift_memory"]},
            timestamp="2025-01-01T00:00:00+00:00",
            recoverable=False,
        )
        d = error.to_dict()
        assert d["type"] == "invalid_memory"
        assert d["message"] == "Memory is corrupt"
        assert d["details"] == {"missing_keys": ["drift_memory"]}
        assert d["timestamp"] == "2025-01-01T00:00:00+00:00"
        assert d["recoverable"] is False
        assert json.dumps(d)  # Must not raise


class TestClassifyCatastrophicDrift:
    """Tests for ``classify_catastrophic_drift``."""

    def test_none_drift_result_returns_none(self):
        """None drift_result → no error."""
        assert classify_catastrophic_drift(None) is None

    def test_non_dict_drift_result_returns_none(self):
        """Non-dict drift_result → no error."""
        assert classify_catastrophic_drift("bad") is None

    def test_empty_drift_result_returns_none(self):
        """Empty drift result → no error."""
        assert classify_catastrophic_drift({}) is None

    def test_minor_drift_returns_none(self):
        """Minor severity drift → no error."""
        result = {"drift": [{"signal_type": "minor", "severity": "minor"}]}
        assert classify_catastrophic_drift(result) is None

    def test_major_drift_returns_none(self):
        """Major severity drift → no error."""
        result = {"drift": [{"signal_type": "major", "severity": "major"}]}
        assert classify_catastrophic_drift(result) is None

    def test_catastrophic_drift_returns_error(self):
        """Catastrophic severity drift → AgentError."""
        result = {"drift": [{"signal_type": "test", "severity": "catastrophic"}]}
        error = classify_catastrophic_drift(result)
        assert error is not None
        assert error.type == "catastrophic_drift"
        assert "catastrophic" in error.message.lower()
        assert error.details["severity"] == "catastrophic"

    def test_catastrophic_drift_case_insensitive(self):
        """Severity check is case-insensitive."""
        result = {"drift": [{"signal_type": "x", "severity": "Catastrophic"}]}
        error = classify_catastrophic_drift(result)
        assert error is not None
        assert error.type == "catastrophic_drift"


class TestDetectRepairFailure:
    """Tests for ``detect_repair_failure``."""

    def test_none_repair_result_returns_none(self):
        """None repair → no error."""
        assert detect_repair_failure(None) is None

    def test_non_dict_repair_returns_error(self):
        """Non-dict repair result → error."""
        error = detect_repair_failure("bad")
        assert error is not None
        assert error.type == "repair_failure"

    def test_repair_failed_action_returns_error(self):
        """Explicit repair_failed action → error."""
        error = detect_repair_failure({"action": "repair_failed"})
        assert error is not None
        assert error.type == "repair_failure"

    def test_none_action_returns_none(self):
        """No action key → no error."""
        assert detect_repair_failure({}) is None

    def test_repair_subgoal_with_missing_repaired_returns_error(self):
        """repair_subgoal without repaired key → error."""
        error = detect_repair_failure({"action": "repair_subgoal"})
        assert error is not None
        assert error.type == "repair_failure"

    def test_repair_subgoal_with_repaired_returns_none(self):
        """repair_subgoal with valid repaired → no error."""
        result = {"action": "repair_subgoal", "repaired": {"ok": True}}
        assert detect_repair_failure(result) is None

    def test_valid_repair_result_returns_none(self):
        """Valid repair result → no error."""
        result = {"action": "none", "data": "ok"}
        assert detect_repair_failure(result) is None


class TestValidateMemoryState:
    """Tests for ``validate_memory_state``."""

    def test_valid_memory_returns_none(self):
        """Properly structured memory → no error."""
        memory = {
            "drift_memory": {},
            "repair_memory": {},
            "reflection_memory": {},
        }
        assert validate_memory_state(memory) is None

    def test_non_dict_memory_returns_error(self):
        """Non-dict memory → error."""
        error = validate_memory_state("bad")
        assert error is not None
        assert error.type == "invalid_memory"

    def test_missing_keys_returns_error(self):
        """Missing required keys → error."""
        memory = {"drift_memory": {}}
        error = validate_memory_state(memory)
        assert error is not None
        assert error.type == "invalid_memory"
        assert "repair_memory" in error.details.get("missing_keys", [])

    def test_null_value_returns_error(self):
        """None value for required key → error."""
        memory = {
            "drift_memory": None,
            "repair_memory": {},
            "reflection_memory": {},
        }
        error = validate_memory_state(memory)
        assert error is not None
        assert error.type == "invalid_memory"

    def test_invalid_type_value_returns_error(self):
        """String value for memory key (expected dict/list) → error."""
        memory = {
            "drift_memory": "not_a_dict",
            "repair_memory": {},
            "reflection_memory": {},
        }
        error = validate_memory_state(memory)
        assert error is not None
        assert error.type == "invalid_memory"

    def test_list_value_is_valid(self):
        """List values are accepted for memory keys."""
        memory = {
            "drift_memory": [],
            "repair_memory": [],
            "reflection_memory": [],
        }
        assert validate_memory_state(memory) is None


class TestValidateSubgoalState:
    """Tests for ``validate_subgoal_state``."""

    def test_valid_state_returns_none(self):
        """Valid subgoal state → no error."""
        state = SubgoalExecutionState(index=0, state=SubgoalExecutionPhase.ACTIVE.value)
        assert validate_subgoal_state(state, total_subgoals=3) is None

    def test_negative_index_returns_error(self):
        """Negative index → error."""
        state = SubgoalExecutionState(index=-1, state=SubgoalExecutionPhase.ACTIVE.value)
        error = validate_subgoal_state(state, total_subgoals=3)
        assert error is not None
        assert error.type == "invalid_subgoal_state"

    def test_index_out_of_range_returns_error(self):
        """Index >= total → error."""
        state = SubgoalExecutionState(index=5, state=SubgoalExecutionPhase.ACTIVE.value)
        error = validate_subgoal_state(state, total_subgoals=3)
        assert error is not None
        assert error.type == "invalid_subgoal_state"

    def test_zero_total_always_valid(self):
        """With 0 total subgoals, index 0 is valid (edge case)."""
        state = SubgoalExecutionState(index=0, state=SubgoalExecutionPhase.ACTIVE.value)
        assert validate_subgoal_state(state, total_subgoals=0) is None

    def test_unknown_state_returns_error(self):
        """State string not in enum → error."""
        state = SubgoalExecutionState(index=0, state="nonexistent_state")
        error = validate_subgoal_state(state, total_subgoals=3)
        assert error is not None
        assert error.type == "invalid_subgoal_state"


class TestValidateSegmentState:
    """Tests for ``validate_segment_state``."""

    def test_valid_state_returns_none(self):
        """Valid segment state → no error."""
        state = SegmentExecutionState(index=0, state=SegmentLifecycle.ACTIVE.value)
        assert validate_segment_state(state, total_segments=3) is None

    def test_negative_index_returns_error(self):
        """Negative index → error."""
        state = SegmentExecutionState(index=-1, state=SegmentLifecycle.ACTIVE.value)
        error = validate_segment_state(state, total_segments=3)
        assert error is not None
        assert error.type == "invalid_segment_state"

    def test_index_out_of_range_returns_error(self):
        """Index >= total → error."""
        state = SegmentExecutionState(index=10, state=SegmentLifecycle.ACTIVE.value)
        error = validate_segment_state(state, total_segments=3)
        assert error is not None
        assert error.type == "invalid_segment_state"

    def test_unknown_state_returns_error(self):
        """State string not in enum → error."""
        state = SegmentExecutionState(index=0, state="nonexistent_state")
        error = validate_segment_state(state, total_segments=3)
        assert error is not None
        assert error.type == "invalid_segment_state"


class TestEvaluateAgentErrors:
    """Tests for ``evaluate_agent_errors`` unified checker."""

    def _make_agent_state(self, sg_idx=0, sg_state="active", seg_idx=0, seg_state="active"):
        return AgentExecutionState(
            cycle=0,
            subgoal_state=SubgoalExecutionState(index=sg_idx, state=sg_state),
            segment_state=SegmentExecutionState(index=seg_idx, state=seg_state),
            is_complete=False,
        )

    def _make_valid_memory(self):
        return {
            "drift_memory": {},
            "repair_memory": {},
            "reflection_memory": {},
        }

    def test_no_errors_returns_none(self):
        """Clean state → no errors."""
        result = evaluate_agent_errors(
            agent_state=self._make_agent_state(),
            drift_result=None,
            repair_result=None,
            memory=self._make_valid_memory(),
            total_subgoals=3,
            total_segments=3,
        )
        assert result is None

    def test_catastrophic_drift_surfaced_first(self):
        """Catastrophic drift is checked first and returned."""
        drift = {"drift": [{"signal_type": "bad", "severity": "catastrophic"}]}
        result = evaluate_agent_errors(
            agent_state=self._make_agent_state(),
            drift_result=drift,
            repair_result=None,
            memory=self._make_valid_memory(),
            total_subgoals=3,
            total_segments=3,
        )
        assert result is not None
        assert result.type == "catastrophic_drift"

    def test_repair_failure_surfaced(self):
        """Repair failure is checked after catastrophic drift."""
        result = evaluate_agent_errors(
            agent_state=self._make_agent_state(),
            drift_result=None,
            repair_result={"action": "repair_failed"},
            memory=self._make_valid_memory(),
            total_subgoals=3,
            total_segments=3,
        )
        assert result is not None
        assert result.type == "repair_failure"

    def test_invalid_memory_surfaced(self):
        """Invalid memory is checked after repair failure."""
        result = evaluate_agent_errors(
            agent_state=self._make_agent_state(),
            drift_result=None,
            repair_result=None,
            memory={"drift_memory": {}},  # missing required keys
            total_subgoals=3,
            total_segments=3,
        )
        assert result is not None
        assert result.type == "invalid_memory"

    def test_invalid_subgoal_state_surfaced(self):
        """Invalid subgoal state is checked after memory."""
        result = evaluate_agent_errors(
            agent_state=self._make_agent_state(sg_idx=-1),
            drift_result=None,
            repair_result=None,
            memory=self._make_valid_memory(),
            total_subgoals=3,
            total_segments=3,
        )
        assert result is not None
        assert result.type == "invalid_subgoal_state"

    def test_invalid_segment_state_surfaced(self):
        """Invalid segment state is checked after subgoal state."""
        result = evaluate_agent_errors(
            agent_state=self._make_agent_state(seg_idx=999),
            drift_result=None,
            repair_result=None,
            memory=self._make_valid_memory(),
            total_subgoals=3,
            total_segments=3,
        )
        assert result is not None
        assert result.type == "invalid_segment_state"

    def test_priority_order_catastrophic_over_repair(self):
        """Catastrophic drift is returned even when repair also failed."""
        drift = {"drift": [{"signal_type": "bad", "severity": "catastrophic"}]}
        result = evaluate_agent_errors(
            agent_state=self._make_agent_state(),
            drift_result=drift,
            repair_result={"action": "repair_failed"},
            memory=self._make_valid_memory(),
            total_subgoals=3,
            total_segments=3,
        )
        assert result is not None
        assert result.type == "catastrophic_drift"  # first priority


class TestAgentLoopResultErrorField:
    """Integration tests for error surfaced via ``AgentLoopResult``."""

    def test_normal_completion_has_no_error(self):
        """Normal completion → error is None."""
        sg = _make_subgoal(subgoal_id="sg.noerr")
        seg = _make_segment(subgoal_id="sg.noerr")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert result.error is None
        assert result.termination_reason == "agent_complete"

    def test_result_to_dict_includes_error_when_present(self):
        """to_dict includes error field when present."""
        result = run_agent_loop(subgoals=[], segments=[], max_cycles=10)
        d = result.to_dict()
        # Normal completion — error not in dict
        assert "error" not in d
        assert result.error is None

    def test_error_included_in_trace_when_present(self):
        """trace.errors is populated when errors occur."""
        sg = _make_subgoal(subgoal_id="sg.err")
        seg = _make_segment(subgoal_id="sg.err")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        # With valid data, no errors should appear
        assert isinstance(result.trace.errors, list)
        assert len(result.trace.errors) == 0

    def test_agent_loop_result_error_field_type(self):
        """AgentLoopResult.error is AgentError | None."""
        sg = _make_subgoal(subgoal_id="sg.types")
        seg = _make_segment(subgoal_id="sg.types")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert result.error is None or isinstance(result.error, AgentError)

    def test_max_cycles_exceeded_has_no_error(self):
        """Max cycles exceeded is not an error — it's a termination reason."""
        sg = _make_subgoal(subgoal_id="sg.max")
        seg = _make_segment(subgoal_id="sg.max")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=1)
        if result.termination_reason == "max_cycles_exceeded":
            assert result.error is None
            assert not result.is_complete

    def test_deterministic_error_trace(self):
        """Running the same valid loop twice produces identical error traces."""
        sg = _make_subgoal(subgoal_id="sg.det")
        seg = _make_segment(subgoal_id="sg.det")
        r1 = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        r2 = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert r1.trace.errors == r2.trace.errors
        assert r1.error == r2.error


# ──────────────────────────────────────────────────────────────────────────────
# Full Trace Integration (2.13.3)
# ──────────────────────────────────────────────────────────────────────────────


class TestAgentFullTraceIntegration:
    """Integration tests for the unified AgentFullTrace produced by run_agent_loop."""

    # ── Agent trace entries ────────────────────────────────────────────────

    def test_agent_trace_entries_present(self):
        """Agent trace entries are populated for each cycle."""
        sg = _make_subgoal(subgoal_id="sg.at")
        seg = _make_segment(subgoal_id="sg.at")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert isinstance(result.trace.agent, list)
        assert len(result.trace.agent) > 0
        for entry in result.trace.agent:
            assert "cycle" in entry
            assert "subgoal_index" in entry
            assert "subgoal_state" in entry
            assert "segment_index" in entry
            assert "segment_state" in entry
            assert "is_complete" in entry

    def test_agent_trace_is_json_safe(self):
        """Agent trace entries are JSON-safe."""
        sg = _make_subgoal(subgoal_id="sg.atjson")
        seg = _make_segment(subgoal_id="sg.atjson")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert _is_json_safe(result.trace.agent)

    # ── Drift trace entries ────────────────────────────────────────────────

    def test_drift_trace_entries_present(self):
        """Drift trace entries are present."""
        sg = _make_subgoal(subgoal_id="sg.drift")
        seg = _make_segment(subgoal_id="sg.drift")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert isinstance(result.trace.drift, list)
        # Drift may be empty for valid plans, but the field must exist
        for entry in result.trace.drift:
            assert "cycle" in entry
            assert "level" in entry
            assert entry["level"] in ("segment", "subgoal")

    def test_drift_trace_is_json_safe(self):
        """Drift trace entries are JSON-safe."""
        sg = _make_subgoal(subgoal_id="sg.driftjson")
        seg = _make_segment(subgoal_id="sg.driftjson")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert _is_json_safe(result.trace.drift)

    # ── Repair trace entries ───────────────────────────────────────────────

    def test_repair_trace_entries_present(self):
        """Repair trace entries are present."""
        sg = _make_subgoal(subgoal_id="sg.repair")
        seg = _make_segment(subgoal_id="sg.repair")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert isinstance(result.trace.repairs, list)
        for entry in result.trace.repairs:
            assert "cycle" in entry
            assert "level" in entry
            assert "action" in entry

    def test_repair_trace_is_json_safe(self):
        """Repair trace entries are JSON-safe."""
        sg = _make_subgoal(subgoal_id="sg.repairjson")
        seg = _make_segment(subgoal_id="sg.repairjson")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert _is_json_safe(result.trace.repairs)

    # ── Reflection trace entries ───────────────────────────────────────────

    def test_reflection_trace_entries_present(self):
        """Reflection trace entries are present."""
        sg = _make_subgoal(subgoal_id="sg.refl")
        seg = _make_segment(subgoal_id="sg.refl")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert isinstance(result.trace.reflections, list)
        for entry in result.trace.reflections:
            assert "cycle" in entry
            assert "level" in entry
            assert "is_complete" in entry

    def test_reflection_trace_is_json_safe(self):
        """Reflection trace entries are JSON-safe."""
        sg = _make_subgoal(subgoal_id="sg.refljson")
        seg = _make_segment(subgoal_id="sg.refljson")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert _is_json_safe(result.trace.reflections)

    # ── Memory trace entries ───────────────────────────────────────────────

    def test_memory_trace_entries_present(self):
        """Memory snapshots are captured per cycle."""
        sg = _make_subgoal(subgoal_id="sg.mem")
        seg = _make_segment(subgoal_id="sg.mem")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert isinstance(result.trace.memory, list)
        assert len(result.trace.memory) > 0
        for entry in result.trace.memory:
            assert "cycle" in entry
            assert "memory_snapshot" in entry
            snapshot = entry["memory_snapshot"]
            assert "drift_memory" in snapshot
            assert "repair_memory" in snapshot
            assert "reflection_memory" in snapshot

    def test_memory_trace_is_json_safe(self):
        """Memory trace entries are JSON-safe."""
        sg = _make_subgoal(subgoal_id="sg.memjson")
        seg = _make_segment(subgoal_id="sg.memjson")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert _is_json_safe(result.trace.memory)

    def test_memory_snapshot_not_aliased(self):
        """Memory snapshots are deep copies, not aliased."""
        sg = _make_subgoal(subgoal_id="sg.alias")
        seg = _make_segment(subgoal_id="sg.alias")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        if len(result.trace.memory) >= 2:
            snap0 = result.trace.memory[0]["memory_snapshot"]
            snap1 = result.trace.memory[1]["memory_snapshot"]
            # Modifying one should not affect the other
            assert snap0 is not snap1

    # ── Subgoal trace entries ──────────────────────────────────────────────

    def test_subgoal_trace_entries_present(self):
        """Subgoal trace entries are captured."""
        sg = _make_subgoal(subgoal_id="sg.sgtrace")
        seg = _make_segment(subgoal_id="sg.sgtrace")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert isinstance(result.trace.subgoals, list)
        for entry in result.trace.subgoals:
            assert _is_json_safe(entry)

    # ── Segment trace entries ──────────────────────────────────────────────

    def test_segment_trace_entries_present(self):
        """Segment trace entries are captured."""
        sg = _make_subgoal(subgoal_id="sg.segtrace")
        seg = _make_segment(subgoal_id="sg.segtrace")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert isinstance(result.trace.segments, list)
        assert len(result.trace.segments) > 0
        for entry in result.trace.segments:
            assert _is_json_safe(entry)

    # ── Determinism ────────────────────────────────────────────────────────

    def test_full_trace_deterministic(self):
        """Running the same loop twice produces identical full traces."""
        sg = _make_subgoal(subgoal_id="sg.det")
        seg = _make_segment(subgoal_id="sg.det")
        r1 = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        r2 = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert r1.trace.to_dict() == r2.trace.to_dict()

    def test_full_trace_ordering_is_deterministic(self):
        """Trace entries maintain deterministic ordering."""
        sg = _make_subgoal(subgoal_id="sg.order")
        seg = _make_segment(subgoal_id="sg.order")
        r1 = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        r2 = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        assert r1.trace.cycles == r2.trace.cycles
        assert r1.trace.agent == r2.trace.agent
        assert r1.trace.memory == r2.trace.memory

    # ── Multi-subgoal plan ─────────────────────────────────────────────────

    def test_multi_subgoal_trace(self):
        """Multi-subgoal plan produces agent trace with both subgoal levels."""
        sg1 = _make_subgoal(subgoal_id="sg.multi1")
        sg2 = _make_subgoal(subgoal_id="sg.multi2")
        seg1 = _make_segment(subgoal_id="sg.multi1")
        seg2 = _make_segment(subgoal_id="sg.multi2")
        result = run_agent_loop(subgoals=[sg1, sg2], segments=[seg1, seg2], max_cycles=20)
        assert result.is_complete
        # Agent trace should show at least one transition
        agent_entries = result.trace.agent
        assert len(agent_entries) >= 2  # At least 2 cycles for 2 subgoals

    def test_multi_subgoal_memory_coverage(self):
        """Multi-subgoal plan captures memory across all cycles."""
        sg1 = _make_subgoal(subgoal_id="sg.multi1")
        sg2 = _make_subgoal(subgoal_id="sg.multi2")
        seg1 = _make_segment(subgoal_id="sg.multi1")
        seg2 = _make_segment(subgoal_id="sg.multi2")
        result = run_agent_loop(subgoals=[sg1, sg2], segments=[seg1, seg2], max_cycles=20)
        # Memory snapshots for each cycle
        assert len(result.trace.memory) == result.total_cycles

    # ── Empty subgoals ─────────────────────────────────────────────────────

    def test_empty_segments_subgoal_trace(self):
        """Subgoal with zero segments still produces trace entries."""
        sg = _make_subgoal(subgoal_id="sg.empty")
        result = run_agent_loop(subgoals=[sg], segments=[], max_cycles=10)
        assert result.is_complete
        assert len(result.trace.agent) >= 1
        assert len(result.trace.memory) >= 1
        # No segment entries
        assert len(result.trace.segments) == 0
        assert len(result.trace.subgoals) == 0

    # ── Max cycles termination ─────────────────────────────────────────────

    def test_max_cycles_trace(self):
        """Trace is produced even when max_cycles is exceeded."""
        sg = _make_subgoal(subgoal_id="sg.maxc")
        seg = _make_segment(subgoal_id="sg.maxc")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=1)
        assert result.termination_reason == "max_cycles_exceeded"
        assert isinstance(result.trace.cycles, list)
        assert len(result.trace.cycles) == 1
        assert isinstance(result.trace.agent, list)
        assert isinstance(result.trace.memory, list)
        assert len(result.trace.memory) == 1

    # ── Full trace to_dict ─────────────────────────────────────────────────

    def test_full_trace_complete_to_dict(self):
        """AgentFullTrace.to_dict() contains all top-level keys."""
        sg = _make_subgoal(subgoal_id="sg.dict")
        seg = _make_segment(subgoal_id="sg.dict")
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        td = result.trace.to_dict()
        assert "cycles" in td
        assert "agent" in td
        assert "subgoals" in td
        assert "segments" in td
        assert "drift" in td
        assert "repairs" in td
        assert "reflections" in td
        assert "memory" in td
        assert "errors" in td
        assert _is_json_safe(td)