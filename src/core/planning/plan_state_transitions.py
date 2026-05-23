from src.core.planning.plan_state import PlanState, PlanStatus

def mark_running(state: PlanState, timestamp: int) -> PlanState:
    return PlanState(
        plan_id=state.plan_id,
        steps=state.steps,
        current_step_index=state.current_step_index,
        status=PlanStatus.RUNNING,
        last_result=state.last_result,
        trace=state.trace,
        created_at=state.created_at,
        updated_at=timestamp,
    )


def mark_completed(state: PlanState, result: dict, timestamp: int) -> PlanState:
    return PlanState(
        plan_id=state.plan_id,
        steps=state.steps,
        current_step_index=state.current_step_index,
        status=PlanStatus.COMPLETED,
        last_result=result,
        trace=state.trace,
        created_at=state.created_at,
        updated_at=timestamp,
    )


def mark_failed(state: PlanState, error: dict, timestamp: int) -> PlanState:
    return PlanState(
        plan_id=state.plan_id,
        steps=state.steps,
        current_step_index=state.current_step_index,
        status=PlanStatus.FAILED,
        last_result=error,
        trace=state.trace,
        created_at=state.created_at,
        updated_at=timestamp,
    )


def mark_needs_repair(state: PlanState, error: dict, timestamp: int) -> PlanState:
    return PlanState(
        plan_id=state.plan_id,
        steps=state.steps,
        current_step_index=state.current_step_index,
        status=PlanStatus.NEEDS_REPAIR,
        last_result=error,
        trace=state.trace,
        created_at=state.created_at,
        updated_at=timestamp,
    )