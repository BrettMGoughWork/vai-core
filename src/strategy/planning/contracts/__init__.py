"""
S2 Planning Contracts (Phase 2.15).

Frozen, versioned schemas for the S2 planning surface:
- AgentPlan: Complete plan with identity, segments, and metadata
- StepSpec: Deterministic step contract with inputs, outputs, and fallback
- ExecutionContract: Versioned S2↔S3 boundary contract wrappers
"""

from src.strategy.planning.contracts.agent_plan import AgentPlan
from src.strategy.planning.contracts.step_spec import StepSpec

__all__ = ["AgentPlan", "StepSpec"]
