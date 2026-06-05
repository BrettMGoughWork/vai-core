"""
Phase 2.5.6 — Agent Loop V2: package exports.

Wires all Stratum-2 substrate components into a single deterministic agent loop:
  - ReflectionLoop (2.5.5)
  - FullTransitionRules (2.5.2)
  - FullValidationEngine (2.5.4)
  - MemoryGovernance (2.4.5)
  - All memory stores (2.4.x)

No LLM calls, no inference, no side effects beyond governed memory writes.
"""
from src.core.planning.agent_loop.agent_loop_types import (
    AgentLoopConfig,
    AgentCycleOutcome,
    AgentLoopError,
    AgentRunTrace,
    AgentState,
    MemorySnapshot,
    SubgoalCycleResult,
    SubgoalRuntimeState,
    TerminationReason,
)
from src.core.planning.agent_loop.agent_loop_v2 import AgentLoopV2
from src.core.planning.agent_loop.agent_loop_v3 import (
    AgentCycleRecord,
    AgentExecutionState,
    AgentLoopResult,
    AgentTrace,
    run_agent_loop,
)

__all__ = [
    "AgentCycleRecord",
    "AgentExecutionState",
    "AgentLoopConfig",
    "AgentLoopResult",
    "AgentCycleOutcome",
    "AgentLoopError",
    "AgentLoopV2",
    "AgentRunTrace",
    "AgentState",
    "AgentTrace",
    "MemorySnapshot",
    "SubgoalCycleResult",
    "SubgoalRuntimeState",
    "TerminationReason",
    "run_agent_loop",
]
