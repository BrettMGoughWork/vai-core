from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any


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