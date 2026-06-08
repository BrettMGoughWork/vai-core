from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any, Dict, Optional, TYPE_CHECKING

from src.core.planning.dispatch.safe_step_dispatcher import SafeStepDispatcher
from src.core.planning.models.plan_state import PlanState
from src.core.types.errors.plan_errors import PlanDispatchError, PlanValidationError, PlanExecutionError
from src.core.planning.models.step_state import StepState
from src.core.types.step_result import StepResult
from src.core.types.cognitive_step_outcome import CognitiveStepOutcome
from src.core.planning.models.plan import Plan
from src.core.planning.safety.purity_enforcer import enforce_cognitive_purity
from src.core.planning.behavioural_delta import compute_behavioural_delta
from src.stratum2.s3_adapter import S3Adapter, S2SkillCallRequest

if TYPE_CHECKING:
    from src.core.memory.segment_memory import SegmentMemory
    from src.core.memory.segment_memory_types import SegmentMemoryRecord

@dataclass(frozen=True)
class PlanExecutorMetrics:
    duration: int
    termination_reason: str

class PlanExecutor:
    """
    Executes a validated plan and returns:
    - final StepState
    - final StepResult
    - PlanExecutorMetrics

    Phase 3.8.8: Integrates S3 skill results into S2 state via segment memory.
    """

    def __init__(
        self,
        dispatcher: SafeStepDispatcher,
        s3_adapter: Optional[S3Adapter] = None,
        segment_memory: Optional[SegmentMemory] = None,
    ):
        self.dispatcher = dispatcher
        self._s3_adapter = s3_adapter
        self._segment_memory = segment_memory

    def execute(
        self, 
        plan: Plan,
        plan_state: PlanState | None = None
    ) -> tuple[StepState, StepResult, PlanExecutorMetrics]:
        
        start = int(time() * 1000)

        # The skill to call is the first in the segment's skills list
        # (stored as plan.targetskillid by the planner — segment.skills[0]).
        selected_skill = plan.targetskillid

        state = PlanState.initial(plan)
        try:
            state, result = self.dispatcher.dispatch(plan, plan_state=plan_state)
        except Exception as exc:
            # catastrophic substrate error
            import traceback
            print("[PlanExecutorInternalError] Exception type:", type(exc).__name__)
            print("[PlanExecutorInternalError] Exception message:", exc)
            print("[PlanExecutorInternalError] Traceback:")
            traceback.print_exc()
            result = StepResult.failure(
                reason=str(exc),
                payload={"error_type": "PlanExecutorInternalError"},
                trace=[],
            )
            metrics = PlanExecutorMetrics(
                duration=0,
                termination_reason="internal_error",
            )
            return state, result, metrics

        # --- 3.8.8: Write skill result into S2 state via S3 adapter ---
        record = self._write_skill_result_to_state(plan, result)

        # --- 3.8.8: Halt on failure ---
        if record is not None and record.state == "error":
            error = PlanExecutionError(
                f"Skill execution failed: {record.error}"
            )
            failure_result = StepResult.failure(
                reason=str(error),
                payload={"error_type": type(error).__name__},
                trace=result.trace,
            )
            metrics = PlanExecutorMetrics(
                duration=int(time() * 1000) - start,
                termination_reason="failure",
            )
            return state, failure_result, metrics

        # Map unexpected outcomes to plan-level errors
        if result.outcome != CognitiveStepOutcome.SUCCESS:
            error = self._map_step_error(result)
            failure_result = StepResult.failure(
                reason=str(error),
                payload={"error_type": type(error).__name__},
                trace=result.trace,
            )
            metrics = PlanExecutorMetrics(
                duration=state.created_at,
                termination_reason="failure",
            )
            return state, failure_result, metrics

        # Success
        # Enforce purity only on capability outputs (result.payload if dict)
        if isinstance(result.payload, dict):
            enforce_cognitive_purity(result.payload)
        metrics = PlanExecutorMetrics(
            duration=state.created_at,
            termination_reason="success",
        )
        # Mark plan as complete
        from src.core.planning.models.plan_state import PlanStatus
        completed_state = state.__class__(
            plan_id=state.plan_id,
            steps=state.steps,
            current_step_index=state.current_step_index,
            status=PlanStatus.COMPLETED,
            last_result=state.last_result,
            trace=state.trace,
            created_at=state.created_at,
            updated_at=state.updated_at,
        )
        return completed_state, result, metrics

    # ── 3.8.8: Skill result → S2 state integration ─────────────────────

    def _write_skill_result_to_state(
        self,
        plan: Plan,
        result: StepResult,
    ) -> Optional["SegmentMemoryRecord"]:
        """Write the S3 skill execution result into S2 segment memory.

        Performs:
        1. Calls S3Adapter.call_skill() with the plan's target skill
        2. Retrieves the previous segment memory record (if any)
        3. Computes a behavioural delta between previous and new output
        4. Creates a new SegmentMemoryRecord and writes it into segment_memory

        Returns:
            The new SegmentMemoryRecord, or None if segment_memory is unavailable.
        """
        if self._s3_adapter is None or self._segment_memory is None:
            return None

        # Lazy import to avoid circular dependency (memory ↔ planning)
        from src.core.memory.segment_memory_types import SegmentMemoryRecord

        # 1. Call the skill through S3 adapter
        request = S2SkillCallRequest(
            skill_name=plan.targetskillid,
            arguments=dict(plan.arguments),
            request_id=getattr(plan, "plan_id", plan.targetskillid),
        )
        s2_result = self._s3_adapter.call_skill(request)

        # 2. Retrieve previous memory record
        segment_id = plan.targetskillid
        prev_record = self._segment_memory.get_record(segment_id)

        # 3. Compute behavioural delta
        if prev_record is not None:
            prev_output = prev_record.last_output
            delta = compute_behavioural_delta(prev_output, s2_result.output)
        else:
            delta = None

        # 4. Create SegmentMemoryRecord
        record = SegmentMemoryRecord(
            segment_id=segment_id,
            parent_id=None,
            subgoal_id=getattr(plan, "intent", ""),
            state="success" if s2_result.success else "error",
            content=list(plan.arguments.keys()),
            created_at=str(int(time())),
            context=dict(plan.arguments),
            metadata={},
            skills=[plan.targetskillid],
            last_output=s2_result.output,
            previous_output=prev_record.last_output if prev_record else None,
            behavioural_delta=delta,
            error=s2_result.error,
        )

        # 5. Write into segment memory
        self._segment_memory.put_record(record)
        return record

    def _map_step_error(self, result: StepResult) -> PlanValidationError:
        if result.outcome == CognitiveStepOutcome.FAILURE:
            return PlanExecutionError(result.reason)

        if result.outcome in (CognitiveStepOutcome.CONTINUE, CognitiveStepOutcome.TOOL_NEEDED):
            return PlanDispatchError(
                f"Unexpected step outcome during plan execution: {result.outcome}"
            )

        return PlanDispatchError("Unknown execution error")