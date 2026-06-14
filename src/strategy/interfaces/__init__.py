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
    "AgentPlan",
    "CoreStep",
    "GovernedSignal",
    "SignalSeverity",
    "ConversationState",
]
