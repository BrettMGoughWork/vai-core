from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any
from src.strategy.planning.models.plan import Plan

class PlanStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"
    COMPLETED = "completed"
    NEEDS_REPAIR = "needs_repair"


@dataclass(frozen=True)
class PlanState:
    plan_id: str
    steps: List[Dict[str, Any]] # raw plan steps (single-step for now)
    current_step_index: int
    status: PlanStatus
    last_result: Optional[Dict[str, Any]]
    trace: List[Dict[str, Any]]
    created_at: int
    updated_at: int

    @staticmethod
    def initial(plan: 'Plan') -> 'PlanState':
        return PlanState(
            plan_id=getattr(plan, 'plan_id', 'unknown'),
            steps=[],
            current_step_index=0,
            status=PlanStatus.PENDING,
            last_result=None,
            trace=[],
            created_at=0,
            updated_at=0,
        )