"""
Tests for Phase 2.5.6 — Agent Loop V2.

Covers:
  - run_agent_cycle
    - empty subgoals → terminal
    - SUCCESS subgoal treated as done (no closure)
    - SATISFIED / ABANDONED subgoals closed → CLOSED
    - FAILED with budget → retry (FAILED → RUNNING)
    - FAILED with no budget → closed → ERROR reason
    - active (RUNNING) subgoal → reflection runs
    - unrecognised state → SAFETY termination
    - post-reflection safety gate
    - error budget abort
    - cycle counter increments
    - memory snapshot captured at end
  - run_agent_loop
    - max_cycles reached → BUDGET
    - natural terminal → terminated=True
    - AgentRunTrace structure
  - per-subgoal isolation (runtime state scoped)
  - _classify_termination helper
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import List, Optional

import pytest

from src.core.memory.subgoal_memory import SubgoalMemory
from src.core.memory.segment_memory import SegmentMemory
from src.core.memory.plan_memory import PlanMemory
from src.core.memory.drift_memory import DriftMemory
from src.core.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.core.memory.governance.memory_governance import MemoryGovernance
from src.core.planning.agent_loop.agent_loop_types import (
    AgentLoopConfig,
    AgentCycleOutcome,
    AgentLoopError,
    AgentRunTrace,
    AgentState,
    SubgoalCycleResult,
    TerminationReason,
)
from src.core.planning.agent_loop.agent_loop_v2 import (
    AgentLoopV2,
    _classify_termination,
    _ACTIVE_STATES,
    _DONE_FOR_LOOP,
    _NEEDS_CLOSURE_STATES,
)
from src.core.types.subgoal import Subgoal, SubgoalLifecycleState


# ---------------------------------------------------------------------------
# Constants and helpers
# ---------------------------------------------------------------------------

NOW_MS = int(time.time() * 1000)
NOW_ISO = datetime.fromtimestamp(NOW_MS / 1000.0, tz=timezone.utc).isoformat()


def make_subgoal(
    subgoal_id: str,
    state: SubgoalLifecycleState = SubgoalLifecycleState.RUNNING,
    goal: str = "test goal",
) -> Subgoal:
    return Subgoal(
        subgoal_id=subgoal_id,
        goal=goal,
        context={},
        metadata={},
        state=state,
        created_at=NOW_MS,
    )


def fresh_stores() -> tuple:
    """Return (SubgoalMemory, SegmentMemory, PlanMemory, DriftMemory)."""
    return SubgoalMemory(), SegmentMemory(), PlanMemory(), DriftMemory()


def make_state(
    subgoals: Optional[List[Subgoal]] = None,
    config: Optional[AgentLoopConfig] = None,
) -> AgentState:
    """Create an AgentState, optionally pre-populated with subgoals."""
    sm, seg, pm, dm = fresh_stores()
    for sg in (subgoals or []):
        sm.put(sg)
    return AgentState(
        subgoal_memory=sm,
        segment_memory=seg,
        plan_memory=pm,
        drift_memory=dm,
        config=config or AgentLoopConfig(),
    )


def get_subgoal_state(state: AgentState, subgoal_id: str) -> Optional[str]:
    """Read current state value of a subgoal from memory."""
    sg = state.subgoal_memory.get(subgoal_id)
    return sg.state.value if sg else None


# ---------------------------------------------------------------------------
# _classify_termination
# ---------------------------------------------------------------------------

class TestClassifyTermination:

    def _make_record(self, subgoal_id: str, state: str) -> SubgoalMemoryRecord:
        return SubgoalMemoryRecord(
            subgoal_id=subgoal_id,
            parent_id=None,
            state=state,
            goal="g",
            context={},
            metadata={},
            created_at=NOW_MS,
        )

    def test_empty_records_is_terminal(self):
        from src.core.planning.agent_loop.agent_loop_types import SubgoalRuntimeState
        result = _classify_termination((), {}, AgentLoopConfig())
        assert result == TerminationReason.TERMINAL

    def test_active_subgoal_returns_none(self):
        for active_state in _ACTIVE_STATES:
            record = self._make_record("sg-1", active_state)
            result = _classify_termination((record,), {}, AgentLoopConfig())
            assert result is None, f"Expected None for active state {active_state!r}"

    def test_done_states_return_terminal(self):
        for done_state in _DONE_FOR_LOOP:
            record = self._make_record("sg-1", done_state)
            result = _classify_termination((record,), {}, AgentLoopConfig())
            assert result == TerminationReason.TERMINAL, (
                f"Expected TERMINAL for done state {done_state!r}"
            )

    def test_failed_with_budget_returns_none(self):
        from src.core.planning.agent_loop.agent_loop_types import SubgoalRuntimeState
        record = self._make_record("sg-1", "failed")
        config = AgentLoopConfig(repair_budget=5)
        runtime = {"sg-1": SubgoalRuntimeState(repair_attempts=2)}
        result = _classify_termination((record,), runtime, config)
        assert result is None

    def test_failed_budget_exhausted_returns_error(self):
        from src.core.planning.agent_loop.agent_loop_types import SubgoalRuntimeState
        record = self._make_record("sg-1", "failed")
        config = AgentLoopConfig(repair_budget=5)
        runtime = {"sg-1": SubgoalRuntimeState(repair_attempts=5)}
        result = _classify_termination((record,), runtime, config)
        assert result == TerminationReason.ERROR

    def test_mixed_done_and_failed_exhausted_returns_error(self):
        from src.core.planning.agent_loop.agent_loop_types import SubgoalRuntimeState
        records = (
            self._make_record("sg-1", "closed"),
            self._make_record("sg-2", "failed"),
        )
        config = AgentLoopConfig(repair_budget=3)
        runtime = {"sg-2": SubgoalRuntimeState(repair_attempts=3)}
        result = _classify_termination(records, runtime, config)
        assert result == TerminationReason.ERROR

    def test_failed_with_no_runtime_entry_has_zero_attempts(self):
        record = self._make_record("sg-1", "failed")
        config = AgentLoopConfig(repair_budget=3)
        result = _classify_termination((record,), {}, config)
        assert result is None  # 0 < 3, still has budget


# ---------------------------------------------------------------------------
# AgentCycleOutcome structure
# ---------------------------------------------------------------------------

class TestAgentCycleStructure:

    def test_empty_subgoals_is_terminal(self):
        loop = AgentLoopV2()
        state = make_state(subgoals=[])
        outcome = loop.run_agent_cycle(state)

        assert outcome.terminal is True
        assert outcome.termination_reason == TerminationReason.TERMINAL.value
        assert outcome.cycle == 1
        assert len(outcome.subgoal_results) == 0
        assert len(outcome.errors) == 0

    def test_cycle_counter_increments(self):
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.SUCCESS)
        ])
        assert state.cycle == 0
        o1 = loop.run_agent_cycle(state)
        assert o1.cycle == 1
        # State is mutated — add another subgoal to keep running.
        state.subgoal_memory.put(make_subgoal("sg-2", SubgoalLifecycleState.SUCCESS))
        o2 = loop.run_agent_cycle(state)
        assert o2.cycle == 2

    def test_memory_snapshot_captured(self):
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.SUCCESS)
        ])
        outcome = loop.run_agent_cycle(state)

        assert isinstance(outcome.memory_snapshot.snapshot_timestamp, str)
        assert len(outcome.memory_snapshot.subgoals) >= 1

    def test_timestamp_is_iso_string(self):
        loop = AgentLoopV2()
        state = make_state(subgoals=[])
        outcome = loop.run_agent_cycle(state)
        # Should be parseable ISO-8601
        datetime.fromisoformat(outcome.timestamp)


# ---------------------------------------------------------------------------
# SUCCESS subgoal handling
# ---------------------------------------------------------------------------

class TestSuccessSubgoal:

    def test_success_subgoal_is_terminal(self):
        """SUCCESS is a done-for-loop state; no closure needed."""
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.SUCCESS)
        ])
        outcome = loop.run_agent_cycle(state)

        assert outcome.terminal is True
        assert outcome.termination_reason == TerminationReason.TERMINAL.value

    def test_success_subgoal_not_closed(self):
        """SUCCESS has no direct transition to CLOSED — must stay as SUCCESS."""
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.SUCCESS)
        ])
        loop.run_agent_cycle(state)

        # State should still be SUCCESS (not CLOSED), or the record was not changed.
        sg = state.subgoal_memory.get("sg-1")
        assert sg is not None
        assert sg.state == SubgoalLifecycleState.SUCCESS

    def test_multiple_success_subgoals_terminal(self):
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.SUCCESS),
            make_subgoal("sg-2", SubgoalLifecycleState.SUCCESS),
        ])
        outcome = loop.run_agent_cycle(state)
        assert outcome.terminal is True
        assert outcome.termination_reason == TerminationReason.TERMINAL.value


# ---------------------------------------------------------------------------
# SATISFIED / ABANDONED closure
# ---------------------------------------------------------------------------

class TestEventTerminalClosure:

    @pytest.mark.parametrize("initial_state", [
        SubgoalLifecycleState.SATISFIED,
        SubgoalLifecycleState.ABANDONED,
    ])
    def test_satisfied_abandoned_closed_in_cycle(self, initial_state):
        """SATISFIED and ABANDONED subgoals must be closed to CLOSED in the cycle."""
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", initial_state)
        ])
        outcome = loop.run_agent_cycle(state)

        assert outcome.terminal is True
        assert outcome.termination_reason == TerminationReason.TERMINAL.value

        # Subgoal should now be CLOSED.
        sg = state.subgoal_memory.get("sg-1")
        assert sg is not None
        assert sg.state == SubgoalLifecycleState.CLOSED

    @pytest.mark.parametrize("initial_state", [
        SubgoalLifecycleState.SATISFIED,
        SubgoalLifecycleState.ABANDONED,
    ])
    def test_closure_recorded_in_result(self, initial_state):
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", initial_state)
        ])
        outcome = loop.run_agent_cycle(state)

        sg_result = next(r for r in outcome.subgoal_results if r.subgoal_id == "sg-1")
        assert sg_result.closed is True
        assert sg_result.skipped is True

    def test_closed_subgoal_stays_closed(self):
        """CLOSED subgoal requires no further action; loop should terminate."""
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.CLOSED)
        ])
        outcome = loop.run_agent_cycle(state)

        assert outcome.terminal is True
        sg = state.subgoal_memory.get("sg-1")
        assert sg.state == SubgoalLifecycleState.CLOSED


# ---------------------------------------------------------------------------
# FAILED subgoal handling
# ---------------------------------------------------------------------------

class TestFailedSubgoal:

    def test_failed_with_budget_retried_to_running(self):
        """FAILED subgoal with repair budget should be moved to RUNNING via RETRY+RESUME."""
        config = AgentLoopConfig(repair_budget=3)
        loop = AgentLoopV2(config)
        state = make_state(
            subgoals=[make_subgoal("sg-1", SubgoalLifecycleState.FAILED)],
            config=config,
        )
        outcome = loop.run_agent_cycle(state)

        sg_result = next(r for r in outcome.subgoal_results if r.subgoal_id == "sg-1")
        assert sg_result.retry_applied is True
        assert sg_result.skipped is True

        # Subgoal should now be RUNNING.
        sg = state.subgoal_memory.get("sg-1")
        assert sg is not None
        assert sg.state == SubgoalLifecycleState.RUNNING

    def test_failed_with_budget_does_not_terminate(self):
        """A retried subgoal leaves the loop non-terminal (it's now RUNNING)."""
        config = AgentLoopConfig(repair_budget=3)
        loop = AgentLoopV2(config)
        # After retry, subgoal goes to RUNNING — reflection then runs and marks it as
        # active work; the cycle should not be terminal.
        state = make_state(
            subgoals=[make_subgoal("sg-1", SubgoalLifecycleState.FAILED)],
            config=config,
        )
        outcome = loop.run_agent_cycle(state)
        # Cycle is not terminal because RUNNING subgoal was processed by reflection.
        assert outcome.terminal is False

    def test_failed_budget_exhausted_closed(self):
        """FAILED subgoal with exhausted repair budget → CLOSED, ERROR reason."""
        from src.core.planning.agent_loop.agent_loop_types import SubgoalRuntimeState
        config = AgentLoopConfig(repair_budget=2)
        loop = AgentLoopV2(config)
        state = make_state(
            subgoals=[make_subgoal("sg-1", SubgoalLifecycleState.FAILED)],
            config=config,
        )
        # Simulate exhausted budget.
        state.subgoal_runtime["sg-1"] = SubgoalRuntimeState(repair_attempts=2)

        outcome = loop.run_agent_cycle(state)

        assert outcome.terminal is True
        assert outcome.termination_reason == TerminationReason.ERROR.value

        sg = state.subgoal_memory.get("sg-1")
        assert sg is not None
        assert sg.state == SubgoalLifecycleState.CLOSED

    def test_failed_budget_exhausted_result_has_closed_true(self):
        from src.core.planning.agent_loop.agent_loop_types import SubgoalRuntimeState
        config = AgentLoopConfig(repair_budget=1)
        loop = AgentLoopV2(config)
        state = make_state(
            subgoals=[make_subgoal("sg-1", SubgoalLifecycleState.FAILED)],
            config=config,
        )
        state.subgoal_runtime["sg-1"] = SubgoalRuntimeState(repair_attempts=1)

        outcome = loop.run_agent_cycle(state)

        sg_result = next(r for r in outcome.subgoal_results if r.subgoal_id == "sg-1")
        assert sg_result.closed is True
        assert sg_result.retry_applied is False

    def test_repair_attempts_counter_increments_on_retry(self):
        """Each successful retry increments repair_attempts for that subgoal."""
        config = AgentLoopConfig(repair_budget=5)
        loop = AgentLoopV2(config)
        state = make_state(
            subgoals=[make_subgoal("sg-1", SubgoalLifecycleState.FAILED)],
            config=config,
        )
        assert state.subgoal_runtime == {}

        loop.run_agent_cycle(state)

        assert "sg-1" in state.subgoal_runtime
        assert state.subgoal_runtime["sg-1"].repair_attempts == 1


# ---------------------------------------------------------------------------
# RUNNING subgoal — reflection integration
# ---------------------------------------------------------------------------

class TestRunningSubgoal:

    def test_running_subgoal_triggers_reflection(self):
        """A RUNNING subgoal should produce a SubgoalCycleResult with reflection_outcome set."""
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.RUNNING)
        ])
        outcome = loop.run_agent_cycle(state)

        sg_result = next(r for r in outcome.subgoal_results if r.subgoal_id == "sg-1")
        assert sg_result.skipped is False
        assert sg_result.reflection_outcome is not None

    def test_running_subgoal_cycle_not_terminal(self):
        """RUNNING subgoal means there is still active work."""
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.RUNNING)
        ])
        outcome = loop.run_agent_cycle(state)
        assert outcome.terminal is False

    def test_running_subgoal_reflection_has_progress(self):
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.RUNNING)
        ])
        outcome = loop.run_agent_cycle(state)

        sg_result = next(r for r in outcome.subgoal_results if r.subgoal_id == "sg-1")
        assert sg_result.reflection_outcome is not None
        progress = sg_result.reflection_outcome.progress
        assert progress.subgoals_total == 1

    def test_prior_progress_updated_after_cycle(self):
        """state.last_cycle_progress should be set after a cycle with a RUNNING subgoal."""
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.RUNNING)
        ])
        assert state.last_cycle_progress is None
        loop.run_agent_cycle(state)
        assert state.last_cycle_progress is not None

    def test_created_subgoal_triggers_reflection(self):
        """Any _ACTIVE_STATES subgoal should trigger reflection."""
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.CREATED)
        ])
        outcome = loop.run_agent_cycle(state)
        sg_result = next(r for r in outcome.subgoal_results if r.subgoal_id == "sg-1")
        assert sg_result.skipped is False
        assert sg_result.reflection_outcome is not None


# ---------------------------------------------------------------------------
# Safety: unrecognised state
# ---------------------------------------------------------------------------

class TestSafetyUnrecognisedState:

    def test_unrecognised_state_triggers_safety_termination(self):
        """A subgoal with an unrecognised state string should halt immediately."""
        sm, seg, pm, dm = fresh_stores()
        # Write a bad record directly, bypassing governance.
        bad_record = SubgoalMemoryRecord(
            subgoal_id="sg-bad",
            parent_id=None,
            state="totally_invalid_state",
            goal="bad subgoal",
            context={},
            metadata={},
            created_at=NOW_MS,
        )
        sm.load_snapshot(
            sm.snapshot().__class__(records=(bad_record,))
        )
        state = AgentState(
            subgoal_memory=sm,
            segment_memory=seg,
            plan_memory=pm,
            drift_memory=dm,
        )

        loop = AgentLoopV2()
        outcome = loop.run_agent_cycle(state)

        assert outcome.terminal is True
        assert outcome.termination_reason == TerminationReason.SAFETY.value
        assert any(e.error_type == "safety" for e in outcome.errors)

    def test_unrecognised_state_produces_safety_blocked_result(self):
        sm, seg, pm, dm = fresh_stores()
        bad_record = SubgoalMemoryRecord(
            subgoal_id="sg-bad",
            parent_id=None,
            state="not_a_real_state",
            goal="bad",
            context={},
            metadata={},
            created_at=NOW_MS,
        )
        from src.core.memory.subgoal_memory_types import SubgoalMemorySnapshot
        sm.load_snapshot(SubgoalMemorySnapshot(records=(bad_record,)))
        state = AgentState(
            subgoal_memory=sm,
            segment_memory=seg,
            plan_memory=pm,
            drift_memory=dm,
        )
        loop = AgentLoopV2()
        outcome = loop.run_agent_cycle(state)

        sg_result = next(r for r in outcome.subgoal_results if r.subgoal_id == "sg-bad")
        assert sg_result.safety_blocked is True
        assert len(sg_result.safety_errors) > 0


# ---------------------------------------------------------------------------
# Error budget abort
# ---------------------------------------------------------------------------

class TestErrorBudget:

    def test_error_budget_abort_on_accumulated_errors(self):
        """When accumulated_errors reaches max_errors_before_abort, halt with ERROR."""
        config = AgentLoopConfig(max_errors_before_abort=2)
        loop = AgentLoopV2(config)
        state = make_state(
            subgoals=[make_subgoal("sg-1", SubgoalLifecycleState.RUNNING)],
            config=config,
        )
        # Pre-populate accumulated errors.
        pre_errors = [
            AgentLoopError(cycle=0, error_type="reflection", message="old error", subgoal_id="sg-1"),
            AgentLoopError(cycle=0, error_type="reflection", message="old error 2", subgoal_id="sg-1"),
        ]
        state.accumulated_errors.extend(pre_errors)

        outcome = loop.run_agent_cycle(state)

        assert outcome.terminal is True
        assert outcome.termination_reason == TerminationReason.ERROR.value

    def test_below_error_budget_does_not_abort(self):
        config = AgentLoopConfig(max_errors_before_abort=10)
        loop = AgentLoopV2(config)
        state = make_state(
            subgoals=[make_subgoal("sg-1", SubgoalLifecycleState.RUNNING)],
            config=config,
        )
        # Only one pre-existing error — below threshold.
        state.accumulated_errors.append(
            AgentLoopError(cycle=0, error_type="reflection", message="one error", subgoal_id="sg-1")
        )
        outcome = loop.run_agent_cycle(state)
        # Should not abort due to budget.
        assert outcome.termination_reason != TerminationReason.ERROR.value


# ---------------------------------------------------------------------------
# Multi-subgoal scenarios
# ---------------------------------------------------------------------------

class TestMultiSubgoal:

    def test_mixed_success_and_satisfied_all_close(self):
        """SUCCESS stays, SATISFIED is closed; both count as done → terminal."""
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.SUCCESS),
            make_subgoal("sg-2", SubgoalLifecycleState.SATISFIED),
        ])
        outcome = loop.run_agent_cycle(state)

        assert outcome.terminal is True
        assert outcome.termination_reason == TerminationReason.TERMINAL.value

        sg2 = state.subgoal_memory.get("sg-2")
        assert sg2.state == SubgoalLifecycleState.CLOSED

    def test_one_active_prevents_terminal(self):
        """If any subgoal is in an active state, the cycle must not be terminal."""
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.SUCCESS),
            make_subgoal("sg-2", SubgoalLifecycleState.RUNNING),
        ])
        outcome = loop.run_agent_cycle(state)

        # sg-2 is RUNNING → reflection runs, still active → not terminal.
        assert outcome.terminal is False

    def test_all_closed_is_terminal(self):
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.CLOSED),
            make_subgoal("sg-2", SubgoalLifecycleState.CLOSED),
        ])
        outcome = loop.run_agent_cycle(state)
        assert outcome.terminal is True
        assert outcome.termination_reason == TerminationReason.TERMINAL.value

    def test_subgoal_results_one_per_subgoal(self):
        """Every subgoal in memory must produce exactly one SubgoalCycleResult."""
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.SUCCESS),
            make_subgoal("sg-2", SubgoalLifecycleState.SATISFIED),
            make_subgoal("sg-3", SubgoalLifecycleState.RUNNING),
        ])
        outcome = loop.run_agent_cycle(state)

        result_ids = {r.subgoal_id for r in outcome.subgoal_results}
        assert "sg-1" in result_ids
        assert "sg-2" in result_ids
        assert "sg-3" in result_ids

    def test_per_subgoal_runtime_state_isolated(self):
        """repair_attempts on sg-1 must not affect sg-2's runtime state."""
        from src.core.planning.agent_loop.agent_loop_types import SubgoalRuntimeState
        config = AgentLoopConfig(repair_budget=5)
        loop = AgentLoopV2(config)
        state = make_state(
            subgoals=[
                make_subgoal("sg-1", SubgoalLifecycleState.FAILED),
                make_subgoal("sg-2", SubgoalLifecycleState.RUNNING),
            ],
            config=config,
        )
        loop.run_agent_cycle(state)

        sg1_rt = state.subgoal_runtime.get("sg-1")
        sg2_rt = state.subgoal_runtime.get("sg-2")

        assert sg1_rt is not None
        assert sg1_rt.repair_attempts == 1  # from retry

        # sg-2 had no repair — its repair_attempts should be 0
        if sg2_rt is not None:
            assert sg2_rt.repair_attempts == 0


# ---------------------------------------------------------------------------
# run_agent_loop
# ---------------------------------------------------------------------------

class TestRunAgentLoop:

    def test_max_cycles_respected(self):
        """Loop must not exceed max_cycles even if never terminal."""
        loop = AgentLoopV2()
        # RUNNING subgoal never terminates on its own → loop exhausts budget.
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.RUNNING)
        ])
        trace = loop.run_agent_loop(state, max_cycles=3)

        assert len(trace.cycles) == 3
        assert trace.total_cycles == 3
        assert trace.terminated is False
        assert trace.termination_reason == TerminationReason.BUDGET.value

    def test_natural_terminal_stops_early(self):
        """Loop stops as soon as all subgoals are in done states."""
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.SUCCESS)
        ])
        trace = loop.run_agent_loop(state, max_cycles=10)

        assert trace.total_cycles == 1  # stops after first cycle
        assert trace.terminated is True
        assert trace.termination_reason == TerminationReason.TERMINAL.value

    def test_satisfied_closed_and_terminal(self):
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.SATISFIED)
        ])
        trace = loop.run_agent_loop(state, max_cycles=5)

        assert trace.terminated is True
        assert trace.termination_reason == TerminationReason.TERMINAL.value
        sg = state.subgoal_memory.get("sg-1")
        assert sg.state == SubgoalLifecycleState.CLOSED

    def test_run_trace_structure(self):
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.SUCCESS)
        ])
        trace = loop.run_agent_loop(state, max_cycles=5)

        assert isinstance(trace, AgentRunTrace)
        assert isinstance(trace.cycles, tuple)
        assert all(isinstance(c, AgentCycleOutcome) for c in trace.cycles)
        assert trace.total_errors == len(state.accumulated_errors)

    def test_zero_max_cycles_returns_empty_trace(self):
        """max_cycles=0 should produce an empty trace with BUDGET reason."""
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.SUCCESS)
        ])
        trace = loop.run_agent_loop(state, max_cycles=0)

        assert len(trace.cycles) == 0
        assert trace.total_cycles == 0
        assert trace.terminated is False
        assert trace.termination_reason == TerminationReason.BUDGET.value

    def test_failed_exhausted_terminates_with_error(self):
        from src.core.planning.agent_loop.agent_loop_types import SubgoalRuntimeState
        config = AgentLoopConfig(repair_budget=0)  # no retries allowed
        loop = AgentLoopV2(config)
        state = make_state(
            subgoals=[make_subgoal("sg-1", SubgoalLifecycleState.FAILED)],
            config=config,
        )
        trace = loop.run_agent_loop(state, max_cycles=5)

        assert trace.terminated is True
        assert trace.termination_reason == TerminationReason.ERROR.value

    def test_total_errors_accumulates_across_cycles(self):
        """total_errors should count all errors from all cycles."""
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.SUCCESS)
        ])
        trace = loop.run_agent_loop(state, max_cycles=5)
        assert trace.total_errors == len(state.accumulated_errors)

    def test_detector_state_persists_across_cycles(self):
        """The ReflectionLoop (with its per-subgoal detectors) must persist across cycles."""
        loop = AgentLoopV2()
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.RUNNING)
        ])
        # Run two cycles — the same loop instance should use the same detector for sg-1.
        trace = loop.run_agent_loop(state, max_cycles=2)

        # Two cycles ran (RUNNING never goes terminal on its own in pure state).
        assert trace.total_cycles == 2
        # Both cycles produced reflection outcomes for sg-1.
        for cycle_outcome in trace.cycles:
            sg_result = next(
                (r for r in cycle_outcome.subgoal_results if r.subgoal_id == "sg-1"),
                None,
            )
            assert sg_result is not None
            # Should not be skipped (it's an active subgoal).
            assert sg_result.skipped is False


# ---------------------------------------------------------------------------
# AgentState helpers
# ---------------------------------------------------------------------------

class TestAgentState:

    def test_to_snapshot_contains_all_stores(self):
        state = make_state(subgoals=[
            make_subgoal("sg-1", SubgoalLifecycleState.RUNNING)
        ])
        snapshot = state.to_snapshot(NOW_ISO)

        assert len(snapshot.subgoals) == 1
        assert snapshot.subgoals[0].subgoal_id == "sg-1"
        assert isinstance(snapshot.segments, tuple)
        assert isinstance(snapshot.plans, tuple)
        assert isinstance(snapshot.drift_events, tuple)
        assert snapshot.snapshot_timestamp == NOW_ISO

    def test_initial_cycle_is_zero(self):
        state = make_state()
        assert state.cycle == 0

    def test_subgoal_runtime_starts_empty(self):
        state = make_state()
        assert state.subgoal_runtime == {}

    def test_accumulated_errors_starts_empty(self):
        state = make_state()
        assert state.accumulated_errors == []


# ---------------------------------------------------------------------------
# SubgoalPlanner injection (step 4.5)
# ---------------------------------------------------------------------------

class TestSubgoalPlannerInjection:

    def _make_created_state(self, sg_id: str = "sg-planner") -> AgentState:
        return make_state(subgoals=[make_subgoal(sg_id, SubgoalLifecycleState.CREATED)])

    def _make_planner(self) -> "SubgoalPlanner":
        from src.core.llm.mock_llm import MockLLM
        from src.core.planning.generator.subgoal_planner import SubgoalPlanner
        return SubgoalPlanner(llm=MockLLM())

    def test_planner_seeds_plan_for_active_subgoal(self):
        """An active subgoal with no plan should have a plan after one cycle."""
        state = self._make_created_state()
        loop = AgentLoopV2(planner=self._make_planner())
        loop.run_agent_cycle(state)
        record = state.plan_memory.get_latest_for_subgoal("sg-planner")
        assert record is not None

    def test_planner_seeds_segments_for_active_subgoal(self):
        """Segments should be written to SegmentMemory during plan seeding."""
        state = self._make_created_state()
        loop = AgentLoopV2(planner=self._make_planner())
        loop.run_agent_cycle(state)
        snap = state.segment_memory.snapshot()
        # All LLM steps are grouped into one PlanSegment
        assert len(snap.records) == 1

    def test_plan_content_matches_mock_response(self):
        """Golden plan path: plan content must match MOCK_PLAN_RESPONSE."""
        from src.core.llm.mock_llm import MOCK_PLAN_RESPONSE
        state = self._make_created_state()
        loop = AgentLoopV2(planner=self._make_planner())
        loop.run_agent_cycle(state)
        record = state.plan_memory.get_latest_for_subgoal("sg-planner")
        assert record.intent == MOCK_PLAN_RESPONSE["plan"]["subgoal"]
        assert record.targetskillid == MOCK_PLAN_RESPONSE["plan"]["steps"][0]["capability"]

    def test_planner_not_called_when_plan_already_exists(self):
        """If a plan already exists for the subgoal, the planner must not re-seed."""
        state = self._make_created_state()
        loop = AgentLoopV2(planner=self._make_planner())
        loop.run_agent_cycle(state)
        # Capture segment count after first cycle.
        count_after_first = len(state.segment_memory.snapshot().records)
        # Second cycle: plan already exists — planner must not add more segments.
        loop.run_agent_cycle(state)
        count_after_second = len(state.segment_memory.snapshot().records)
        assert count_after_first == count_after_second

    def test_loop_without_planner_leaves_plan_memory_empty(self):
        """AgentLoopV2() with no planner must not write any plans (backward-compat)."""
        state = self._make_created_state()
        loop = AgentLoopV2()
        loop.run_agent_cycle(state)
        snap = state.plan_memory.snapshot()
        assert len(snap.records) == 0

    def test_agentloopv2_constructor_backward_compatible(self):
        """AgentLoopV2() and AgentLoopV2(config) must still work without planner arg."""
        loop1 = AgentLoopV2()
        loop2 = AgentLoopV2(AgentLoopConfig())
        assert loop1 is not None
        assert loop2 is not None

    def test_plan_appears_in_cycle_outcome_memory_snapshot(self):
        """The memory snapshot inside AgentCycleOutcome must include the seeded plan."""
        state = self._make_created_state()
        loop = AgentLoopV2(planner=self._make_planner())
        outcome = loop.run_agent_cycle(state)
        plan_ids = {p.plan_id for p in outcome.memory_snapshot.plans}
        assert len(plan_ids) >= 1
