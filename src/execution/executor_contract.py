from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from src.core.planning.models.plan import Plan


@dataclass
class ExecutionResult:
    status: str
    output: Any | None
    error: Any | None
    skill_id: str
    raw_response: Any | None


class ExecutorContract(ABC):
    """Abstract contract for plan-based executors. Will be revisited in Stratum 3."""
    @abstractmethod
    def execute(self, plan: Plan) -> ExecutionResult:
        pass
