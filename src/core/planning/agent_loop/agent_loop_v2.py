"""
Phase 2.5.6 — Agent Loop V2: orchestration class.

AgentLoopV2 wires all Stratum-2 substrate components into a single deterministic
agent loop.  One instance per agent run (stateful: holds per-subgoal drift detectors
via the embedded ReflectionLoop).

Lifecycle within a single cycle:
  1. Safety pre-check — reject records with unrecognised states immediately.
  2. Close event-terminal subgoals (SATISFIED / ABANDONED → CLOSED).
  3. Handle FAILED subgoals — retry (FAILED → RETRYING → RUNNING) or close if budget
     is exhausted.
  4. Refresh memory snapshot — pick up state changes from steps 2-3.
  4.5 Seed plans — if a SubgoalPlanner is injected, call it for any active subgoal
     that has no plan in PlanMemory.  Errors are captured but do not abort the cycle.
  5. Run one ReflectionLoop cycle per active subgoal (sorted deterministically).
  6. Post-reflection safety gate — check SafetyValidationResult from each outcome.
  7. Classify termination — detect when all work is done.

All orchestration is deterministic and table-driven.
No LLM calls in the base loop.  The optional SubgoalPlanner extension point
allows injectable plan generation (e.g. MockLLM for testing, live provider for production).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from src.core.memory.governance.memory_governance import MemoryGovernance
from src.core.memory.governance.governance_errors import MemoryGovernanceError
from src.core.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.core.planning.generator.subgoal_planner import SubgoalPlanner
from src.core.planning.reflection.reflection_loop import ReflectionLoop
from src.core.planning.reflection.reflection_types import (
    ReflectionOutcome,
    ReflectionState,
)
from src.core.planning.subgoals.transition_rules import SubgoalEvent
from src.core.planning.transitions.full_transition_rules import FullTransitionRules
from src.core.planning.validation.full_validation_engine import FullValidationEngine
from src.core.types.subgoal import Subgoal, SubgoalLifecycleState
from src.core.planning.drift.behavioural_drift import evaluate_behavioural_drift

from .agent_loop_types import (
    AgentLoopConfig,
    AgentCycleOutcome,
    AgentLoopError,
    AgentRunTrace,
    AgentState,
    SubgoalCycleResult,
    SubgoalRuntimeState,
    TerminationReason,
)


# ---------------------------------------------------------------------------
# State classification sets
# ---------------------------------------------------------------------------

# Subgoal is still actively working — reflection should run.
_ACTIVE_STATES: frozenset = frozenset({
    "created", "validated", "ready", "running", "blocked", "retrying",
})

# Event-terminal states that can direct-transition to CLOSED.
# ("success" has no outgoing direct transitions and is treated as done for the loop.)
_NEEDS_CLOSURE_STATES: frozenset = frozenset({"satisfied", "abandoned"})

# All states where the agent loop considers the subgoal's work complete
# (no further reflection or repair is needed).
_DONE_FOR_LOOP: frozenset = frozenset({"success", "satisfied", "abandoned", "closed"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _classify_termination(
    subgoal_records: Tuple[SubgoalMemoryRecord, ...],
    subgoal_runtime: Dict[str, SubgoalRuntimeState],
    config: AgentLoopConfig,
) -> Optional[TerminationReason]:
    """
    Determine whether the agent loop should terminate and why.

    Returns None if any active work remains.
    Returns TERMINAL if all subgoals are in done states.
    Returns ERROR if any subgoal is failed with no remaining repair budget.
    """
    has_failed_exhausted = False

    for record in subgoal_records:
        state = record.state
        if state in _ACTIVE_STATES:
            return None  # still has work to do
        if state == "failed":
            sg_rt = subgoal_runtime.get(record.subgoal_id)
            used = sg_rt.repair_attempts if sg_rt else 0
            if used < config.repair_budget:
                return None  # repair budget remaining — active
            has_failed_exhausted = True
        # _DONE_FOR_LOOP states contribute to termination

    return TerminationReason.ERROR if has_failed_exhausted else TerminationReason.TERMINAL

# ---------------------------------------------------------------------------
# AgentLoopV2
# ---------------------------------------------------------------------------

class AgentLoopV2:
    """
    Full agent-level control loop for Stratum-2.

    Orchestrates all substrate components into one deterministic run.
    Stateful: one instance per agent run.  Do not reuse across independent runs.

    Components wired:
      - ReflectionLoop (2.5.5):       drift detection, validation, transitions, repair
      - FullTransitionRules (2.5.2):  lifecycle transition table
      - FullValidationEngine (2.5.4): safety gate
      - MemoryGovernance (2.4.5):     all governed writes
      - SubgoalPlanner (optional):    plan generation via injectable ChatProvider
                                      (pass planner=SubgoalPlanner(llm=MockLLM()) for tests;
                                       replace MockLLM with any ChatProvider for production)
    """

    def __init__(self, config: AgentLoopConfig = AgentLoopConfig(), *, planner: Optional[SubgoalPlanner] = None) -> None:
        self._config = config
        self._planner = planner
        self._reflection_loop = ReflectionLoop(
            confirmation_cycles=config.confirmation_cycles,
            cooldown_cycles=config.cooldown_cycles,
            repair_budget=config.repair_budget,
            repair_retry_limit=config.repair_retry_limit,
            stall_repair_threshold=config.stall_repair_threshold,
        )
        self._transition_rules = FullTransitionRules()
        self._validation_engine = FullValidationEngine()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_agent_cycle(self, state: AgentState) -> AgentCycleOutcome:
        """
        Execute one agent cycle across all subgoals.

        Increments state.cycle.  Updates state.subgoal_runtime, state.last_cycle_progress,
        state.last_reflection_trace, state.last_error, and state.accumulated_errors in-place.

        Returns a fully deterministic AgentCycleOutcome.
        """
        now_ms = int(time.time() * 1000)
        now_iso = _ms_to_iso(now_ms)
        state.cycle += 1

        subgoal_results: List[SubgoalCycleResult] = []
        cycle_errors: List[AgentLoopError] = []
        terminal = False
        termination_reason: Optional[str] = None
        # Set to True if any FAILED subgoal was closed due to exhausted repair budget.
        # Used to distinguish TERMINAL (clean) from ERROR (some subgoals permanently failed).
        _had_budget_exhaustion = False

        # Capture prior_progress once at cycle start — stable baseline for all subgoals.
        prior_progress = state.last_cycle_progress

        governance = MemoryGovernance(
            state.subgoal_memory,
            state.segment_memory,
            state.plan_memory,
            state.drift_memory,
        )

        # ── 0. Load all subgoals sorted deterministically ───────────────────
        all_records = sorted(
            state.subgoal_memory.snapshot().records,
            key=lambda r: (r.created_at, r.subgoal_id),
        )

        if not all_records:
            snapshot = state.to_snapshot(now_iso)
            return AgentCycleOutcome(
                cycle=state.cycle,
                timestamp=now_iso,
                subgoal_results=(),
                memory_snapshot=snapshot,
                errors=(),
                terminal=True,
                termination_reason=TerminationReason.TERMINAL.value,
            )

        # ── 1. Safety pre-check: reject records with unrecognised states ────
        valid_records: List[SubgoalMemoryRecord] = []
        for record in all_records:
            try:
                SubgoalLifecycleState(record.state)
                valid_records.append(record)
            except ValueError:
                err = AgentLoopError(
                    cycle=state.cycle,
                    error_type="safety",
                    message=(
                        f"Subgoal {record.subgoal_id!r} has unrecognised state "
                        f"{record.state!r} — halting"
                    ),
                    subgoal_id=record.subgoal_id,
                )
                cycle_errors.append(err)
                state.accumulated_errors.append(err)
                state.last_error = err
                terminal = True
                termination_reason = TerminationReason.SAFETY.value
                subgoal_results.append(SubgoalCycleResult(
                    subgoal_id=record.subgoal_id,
                    reflection_outcome=None,
                    skipped=True,
                    skip_reason=f"unrecognised state: {record.state!r}",
                    safety_blocked=True,
                    safety_errors=(f"Unrecognised state: {record.state!r}",),
                    closed=False,
                    retry_applied=False,
                ))

        if terminal:
            snapshot = state.to_snapshot(now_iso)
            return AgentCycleOutcome(
                cycle=state.cycle,
                timestamp=now_iso,
                subgoal_results=tuple(subgoal_results),
                memory_snapshot=snapshot,
                errors=tuple(cycle_errors),
                terminal=True,
                termination_reason=termination_reason,
            )

        # ── 2. Close SATISFIED / ABANDONED → CLOSED ─────────────────────────
        for record in valid_records:
            if record.state in _NEEDS_CLOSURE_STATES:
                closed = self._close_subgoal(
                    subgoal_id=record.subgoal_id,
                    governance=governance,
                    state=state,
                    cycle_errors=cycle_errors,
                )
                subgoal_results.append(SubgoalCycleResult(
                    subgoal_id=record.subgoal_id,
                    reflection_outcome=None,
                    skipped=True,
                    skip_reason="event-terminal: applied direct CLOSED transition",
                    safety_blocked=False,
                    safety_errors=(),
                    closed=closed,
                    retry_applied=False,
                ))

        # ── 3. Handle FAILED subgoals ────────────────────────────────────────
        for record in valid_records:
            if record.state != "failed":
                continue
            sg_rt = self._get_subgoal_runtime(state, record.subgoal_id)
            if sg_rt.repair_attempts < state.config.repair_budget:
                retry_ok = self._retry_subgoal(
                    subgoal_id=record.subgoal_id,
                    governance=governance,
                    state=state,
                    cycle_errors=cycle_errors,
                )
                sg_rt.repair_attempts += 1
                sg_rt.failed_consecutive += 1
                subgoal_results.append(SubgoalCycleResult(
                    subgoal_id=record.subgoal_id,
                    reflection_outcome=None,
                    skipped=True,
                    skip_reason="failed: applied RETRY + RESUME transition",
                    safety_blocked=False,
                    safety_errors=(),
                    closed=False,
                    retry_applied=retry_ok,
                ))
            else:
                # Repair budget exhausted — close the failed subgoal.
                closed = self._close_failed_subgoal(
                    subgoal_id=record.subgoal_id,
                    governance=governance,
                    state=state,
                    cycle_errors=cycle_errors,
                )
                sg_rt.failed_consecutive += 1
                _had_budget_exhaustion = True  # remember this for termination reason
                subgoal_results.append(SubgoalCycleResult(
                    subgoal_id=record.subgoal_id,
                    reflection_outcome=None,
                    skipped=True,
                    skip_reason="failed: repair budget exhausted — applied direct CLOSED transition",
                    safety_blocked=False,
                    safety_errors=(),
                    closed=closed,
                    retry_applied=False,
                ))

        # ── 4. Refresh records (closures / retries may have changed states) ─
        refreshed_records = sorted(
            state.subgoal_memory.snapshot().records,
            key=lambda r: (r.created_at, r.subgoal_id),
        )
        active_records = [r for r in refreshed_records if r.state in _ACTIVE_STATES]

        # ── 4.5. Seed plans for active subgoals that have no plan ────────────
        if self._planner is not None:
            for record in active_records:
                sg_id = record.subgoal_id
                if state.plan_memory.get_latest_for_subgoal(sg_id) is not None:
                    continue  # plan already exists — skip
                try:
                    self._planner.plan_for_subgoal(
                        subgoal_id=sg_id,
                        goal=record.goal,
                        governance=governance,
                        timestamp=now_iso,
                    )
                except Exception as exc:  # noqa: BLE001
                    err = AgentLoopError(
                        cycle=state.cycle,
                        error_type="planning",
                        message=f"Plan seeding failed for {sg_id!r}: {exc}",
                        subgoal_id=sg_id,
                    )
                    cycle_errors.append(err)
                    state.accumulated_errors.append(err)
                    state.last_error = err

        # ── 5. Run ReflectionLoop for each active subgoal ───────────────────
        handled_ids = {r.subgoal_id for r in subgoal_results}

        for record in active_records:
            sg_id = record.subgoal_id
            if sg_id in handled_ids:
                continue  # already handled (defensive guard)

            sg_rt = self._get_subgoal_runtime(state, sg_id)
            latest_plan = state.plan_memory.get_latest_for_subgoal(sg_id)
            plan_id = latest_plan.plan_id if latest_plan else None

            reflection_state = ReflectionState(
                cycle=state.cycle,
                timestamp=now_ms,
                subgoal_id=sg_id,
                subgoal_memory=state.subgoal_memory,
                segment_memory=state.segment_memory,
                plan_memory=state.plan_memory,
                drift_memory=state.drift_memory,
                plan_id=plan_id,
                repair_attempts=sg_rt.repair_attempts,
                fallback_count=sg_rt.fallback_count,
                transition_failures=[],
                prior_progress=prior_progress,
            )

            try:
                reflection_outcome: ReflectionOutcome = (
                    self._reflection_loop.run_reflection_cycle(reflection_state)
                )
            except Exception as exc:  # noqa: BLE001
                err = AgentLoopError(
                    cycle=state.cycle,
                    error_type="unknown",
                    message=f"Reflection cycle crashed for {sg_id!r}: {exc}",
                    subgoal_id=sg_id,
                )
                cycle_errors.append(err)
                state.accumulated_errors.append(err)
                state.last_error = err
                sg_rt.fallback_count += 1
                subgoal_results.append(SubgoalCycleResult(
                    subgoal_id=sg_id,
                    reflection_outcome=None,
                    skipped=True,
                    skip_reason=f"reflection crashed: {exc}",
                    safety_blocked=False,
                    safety_errors=(),
                    closed=False,
                    retry_applied=False,
                ))
                continue

            # ── 6. Post-reflection safety gate ──────────────────────────────
            safety_blocked = False
            safety_error_msgs: Tuple[str, ...] = ()

            safety_result = (
                reflection_outcome.validation_result.safety
                if reflection_outcome.validation_result is not None
                else None
            )
            if safety_result is not None and safety_result.forbidden_state:
                safety_blocked = True
                safety_error_msgs = tuple(e.message for e in safety_result.errors)
                err = AgentLoopError(
                    cycle=state.cycle,
                    error_type="safety",
                    message=(
                        f"Subgoal {sg_id!r} is in a forbidden state "
                        "after reflection — halting"
                    ),
                    subgoal_id=sg_id,
                )
                cycle_errors.append(err)
                state.accumulated_errors.append(err)
                state.last_error = err
                terminal = True
                termination_reason = TerminationReason.SAFETY.value

            # Collect non-fatal reflection errors.
            for msg in reflection_outcome.errors:
                err = AgentLoopError(
                    cycle=state.cycle,
                    error_type="reflection",
                    message=msg,
                    subgoal_id=sg_id,
                )
                cycle_errors.append(err)
                state.accumulated_errors.append(err)

            # Update per-subgoal runtime from reflection.
            if (
                reflection_outcome.plan_adjustment is not None
                and reflection_outcome.plan_adjustment.repair_succeeded
            ):
                sg_rt.repair_attempts += 1

            # Update cycle-level progress from the last processed subgoal.
            state.last_cycle_progress = reflection_outcome.progress
            state.last_reflection_trace = reflection_outcome.trace

            subgoal_results.append(SubgoalCycleResult(
                subgoal_id=sg_id,
                reflection_outcome=reflection_outcome,
                skipped=False,
                skip_reason=None,
                safety_blocked=safety_blocked,
                safety_errors=safety_error_msgs,
                closed=False,
                retry_applied=False,
            ))

        # ── 6. Add skipped results for subgoals not yet handled ─────────────
        # Covers SUCCESS and CLOSED states which have no active work but must appear
        # in subgoal_results (one result per subgoal per cycle).
        handled_ids_final = {r.subgoal_id for r in subgoal_results}
        for record in valid_records:
            if record.subgoal_id not in handled_ids_final:
                subgoal_results.append(SubgoalCycleResult(
                    subgoal_id=record.subgoal_id,
                    reflection_outcome=None,
                    skipped=True,
                    skip_reason=f"no action required: state={record.state!r}",
                    safety_blocked=False,
                    safety_errors=(),
                    closed=False,
                    retry_applied=False,
                ))

        # ── 7. Check accumulated error budget ────────────────────────────────
        if (
            not terminal
            and len(state.accumulated_errors) >= state.config.max_errors_before_abort
        ):
            terminal = True
            termination_reason = TerminationReason.ERROR.value

        # ── 8. Classify termination from final state ─────────────────────────
        if not terminal:
            final_records = state.subgoal_memory.snapshot().records
            reason = _classify_termination(
                final_records, state.subgoal_runtime, state.config
            )
            if reason is not None:
                terminal = True
                # If budget exhaustion was recorded this cycle, the final reason is ERROR
                # even though the subgoals were successfully closed to CLOSED.
                if _had_budget_exhaustion and reason == TerminationReason.TERMINAL:
                    termination_reason = TerminationReason.ERROR.value
                else:
                    termination_reason = reason.value

        if cycle_errors:
            state.last_error = cycle_errors[-1]

        snapshot = state.to_snapshot(now_iso)

        return AgentCycleOutcome(
            cycle=state.cycle,
            timestamp=now_iso,
            subgoal_results=tuple(subgoal_results),
            memory_snapshot=snapshot,
            errors=tuple(cycle_errors),
            terminal=terminal,
            termination_reason=termination_reason,
        )

    def run_agent_loop(
        self,
        initial_state: AgentState,
        *,
        max_cycles: int,
    ) -> AgentRunTrace:
        """
        Run the agent loop until terminal or max_cycles is exhausted.

        Each iteration calls run_agent_cycle() on initial_state (mutated in place).
        Returns an AgentRunTrace with the full append-only cycle history.
        """
        cycles: List[AgentCycleOutcome] = []
        terminated = False
        termination_reason = TerminationReason.BUDGET.value

        for _ in range(max_cycles):
            outcome = self.run_agent_cycle(initial_state)
            cycles.append(outcome)

            if outcome.terminal:
                terminated = True
                termination_reason = (
                    outcome.termination_reason or TerminationReason.TERMINAL.value
                )
                break

        return AgentRunTrace(
            cycles=tuple(cycles),
            terminated=terminated,
            termination_reason=termination_reason,
            total_cycles=len(cycles),
            total_errors=len(initial_state.accumulated_errors),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _observe_executor_output(
        self,
        *,
        state: AgentState,
        subgoal_id: str,
        segment_id: str,
        step_id: str,
        tool_spec,
        output,
    ):
        """
        2.6.x — Behavioural observation hook.
        Called by ReflectionLoop after a capability executes.
        """
        evaluate_behavioural_drift(
            drift_memory=state.drift_memory,
            subgoal_id=subgoal_id,
            segment_id=segment_id,
            step_id=step_id,
            expected_schema=getattr(tool_spec, "expected_output_schema", None),
            actual_output=output,
        )

    def _get_subgoal_runtime(
        self, state: AgentState, subgoal_id: str
    ) -> SubgoalRuntimeState:
        """Get or lazily create the per-subgoal runtime state."""
        if subgoal_id not in state.subgoal_runtime:
            state.subgoal_runtime[subgoal_id] = SubgoalRuntimeState()
        return state.subgoal_runtime[subgoal_id]

    def _close_subgoal(
        self,
        subgoal_id: str,
        governance: MemoryGovernance,
        state: AgentState,
        cycle_errors: List[AgentLoopError],
    ) -> bool:
        """
        Apply a direct CLOSED transition from SATISFIED or ABANDONED.

        Returns True on success, False if the transition or governance write fails.
        """
        subgoal: Optional[Subgoal] = state.subgoal_memory.get(subgoal_id)
        if subgoal is None:
            cycle_errors.append(AgentLoopError(
                cycle=state.cycle,
                error_type="governance",
                message=f"Cannot close subgoal {subgoal_id!r}: not found in memory",
                subgoal_id=subgoal_id,
            ))
            return False

        result = self._transition_rules.apply_direct_transition(
            subgoal.state, SubgoalLifecycleState.CLOSED
        )
        if not result.success:
            cycle_errors.append(AgentLoopError(
                cycle=state.cycle,
                error_type="transition",
                message=(
                    f"Direct CLOSED transition rejected for {subgoal_id!r} "
                    f"from {subgoal.state.value!r}: "
                    f"{result.error.reason if result.error else 'unknown reason'}"
                ),
                subgoal_id=subgoal_id,
            ))
            return False

        updated = subgoal.with_state(SubgoalLifecycleState.CLOSED)
        try:
            governance.put_subgoal(updated)
            return True
        except MemoryGovernanceError as exc:
            cycle_errors.append(AgentLoopError(
                cycle=state.cycle,
                error_type="governance",
                message=f"Governance rejected CLOSED write for {subgoal_id!r}: {exc}",
                subgoal_id=subgoal_id,
            ))
            return False

    def _close_failed_subgoal(
        self,
        subgoal_id: str,
        governance: MemoryGovernance,
        state: AgentState,
        cycle_errors: List[AgentLoopError],
    ) -> bool:
        """
        Apply a direct CLOSED transition from FAILED (repair budget exhausted).

        Returns True on success.
        """
        subgoal: Optional[Subgoal] = state.subgoal_memory.get(subgoal_id)
        if subgoal is None:
            cycle_errors.append(AgentLoopError(
                cycle=state.cycle,
                error_type="governance",
                message=f"Cannot close failed subgoal {subgoal_id!r}: not found in memory",
                subgoal_id=subgoal_id,
            ))
            return False

        result = self._transition_rules.apply_direct_transition(
            subgoal.state, SubgoalLifecycleState.CLOSED
        )
        if not result.success:
            cycle_errors.append(AgentLoopError(
                cycle=state.cycle,
                error_type="transition",
                message=(
                    f"Direct CLOSED transition rejected for failed subgoal {subgoal_id!r} "
                    f"from {subgoal.state.value!r}: "
                    f"{result.error.reason if result.error else 'unknown reason'}"
                ),
                subgoal_id=subgoal_id,
            ))
            return False

        updated = subgoal.with_state(SubgoalLifecycleState.CLOSED)
        try:
            governance.put_subgoal(updated)
            return True
        except MemoryGovernanceError as exc:
            cycle_errors.append(AgentLoopError(
                cycle=state.cycle,
                error_type="governance",
                message=(
                    f"Governance rejected CLOSED write for failed subgoal "
                    f"{subgoal_id!r}: {exc}"
                ),
                subgoal_id=subgoal_id,
            ))
            return False

    def _retry_subgoal(
        self,
        subgoal_id: str,
        governance: MemoryGovernance,
        state: AgentState,
        cycle_errors: List[AgentLoopError],
    ) -> bool:
        """
        Apply RETRY (FAILED → RETRYING) then RESUME (RETRYING → RUNNING).

        Both transitions are written through governance in sequence.
        Returns True only if both succeed; False on the first failure.
        """
        subgoal: Optional[Subgoal] = state.subgoal_memory.get(subgoal_id)
        if subgoal is None:
            cycle_errors.append(AgentLoopError(
                cycle=state.cycle,
                error_type="governance",
                message=f"Cannot retry subgoal {subgoal_id!r}: not found in memory",
                subgoal_id=subgoal_id,
            ))
            return False

        # Step 1: FAILED → RETRYING
        retry_result = self._transition_rules.apply_subgoal_transition(
            subgoal.state, SubgoalEvent.RETRY
        )
        if not retry_result.success:
            cycle_errors.append(AgentLoopError(
                cycle=state.cycle,
                error_type="transition",
                message=(
                    f"RETRY event rejected for {subgoal_id!r} "
                    f"from {subgoal.state.value!r}: "
                    f"{retry_result.error.reason if retry_result.error else 'unknown'}"
                ),
                subgoal_id=subgoal_id,
            ))
            return False

        retrying = subgoal.with_state(SubgoalLifecycleState.RETRYING)
        try:
            governance.put_subgoal(retrying)
        except MemoryGovernanceError as exc:
            cycle_errors.append(AgentLoopError(
                cycle=state.cycle,
                error_type="governance",
                message=f"Governance rejected RETRYING write for {subgoal_id!r}: {exc}",
                subgoal_id=subgoal_id,
            ))
            return False

        # Step 2: RETRYING → RUNNING
        resume_result = self._transition_rules.apply_subgoal_transition(
            retrying.state, SubgoalEvent.RESUME
        )
        if not resume_result.success:
            cycle_errors.append(AgentLoopError(
                cycle=state.cycle,
                error_type="transition",
                message=(
                    f"RESUME event rejected for {subgoal_id!r} "
                    f"from {retrying.state.value!r}: "
                    f"{resume_result.error.reason if resume_result.error else 'unknown'}"
                ),
                subgoal_id=subgoal_id,
            ))
            return False

        running = retrying.with_state(SubgoalLifecycleState.RUNNING)
        try:
            governance.put_subgoal(running)
            return True
        except MemoryGovernanceError as exc:
            cycle_errors.append(AgentLoopError(
                cycle=state.cycle,
                error_type="governance",
                message=f"Governance rejected RUNNING write for {subgoal_id!r}: {exc}",
                subgoal_id=subgoal_id,
            ))
            return False
