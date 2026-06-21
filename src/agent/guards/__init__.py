"""
Agent safety guards — detect and block hallucination claims.

Guards are stateless, pure functions that operate on LLM reply text.
They do not depend on the supervisor, agent state, or runtime context.
"""

from src.agent.guards.hallucination_guard import apply_hallucination_guard

__all__ = ["apply_hallucination_guard"]
