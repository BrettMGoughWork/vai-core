"""
Strategy Stratum — Integration Interfaces
==========================================

Canonical re-exports of the Strategy stratum's contracts.

The Strategy stratum owns:
- Agent‑planner types consumed by other strata
- Core execution primitives (CoreStep)
- Conversation and signal types consumed by Agent stratum
"""

from __future__ import annotations

# ── S2 — Planning Interface ────────────────────────────────────────────────

from src.strategy.interfaces.planning import (
    PlanRequest as PlanRequest,
    PlanResult as PlanResult,
    StepNode as StepNode,
    Planner as Planner,
)

# ── Agent Planner ─────────────────────────────────────────────────────────

from src.strategy.planning.contracts.agent_plan import (
    AgentPlan as AgentPlan,
)

# ── Core execution primitives ─────────────────────────────────────────────

from src.strategy.types.core_step import (
    CoreStep as CoreStep,
)

# ── Signal types ──────────────────────────────────────────────────────────

from src.strategy.signals.model import (
    GovernedSignal as GovernedSignal,
    SignalSeverity as SignalSeverity,
)

# ── Conversation state ────────────────────────────────────────────────────

from src.strategy.state.state import (
    ConversationState as ConversationState,
)

__all__ = [
    # S2 — Planning Interface
    "PlanRequest",
    "PlanResult",
    "StepNode",
    "Planner",
    # Agent Planner
    "AgentPlan",
    # Core execution
    "CoreStep",
    # Signals
    "GovernedSignal",
    "SignalSeverity",
    # Conversation
    "ConversationState",
]
