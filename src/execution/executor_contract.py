from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from src.core.planning.plan import Plan


@dataclass
class ExecutionResult:
    status: str
    output: Any | None
    error: Any | None
    skill_id: str
    raw_response: Any | None


class Executor(ABC):
    @abstractmethod
    def execute(self, plan: Plan) -> ExecutionResult:
        pass
