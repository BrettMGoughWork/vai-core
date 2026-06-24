"""
Agent Deferral — hand-off work from one agent to another.

An agent can declare an optional list of peer agents it is allowed to
defer / hand off work to.  At registration time the full deferral graph
is validated for acyclicity.  At runtime the Supervisor orchestrates a
suspend → delegate → resume lifecycle.

.. code-block:: yaml

    agent_id: support-agent
    name: General Support
    defer_to:
      - billing-agent
      - technical-agent
"""

from __future__ import annotations

from src.agent.deferral.context_bridge import ContextBridge, build_delegate_prompt
from src.agent.deferral.depth_guard import DepthGuard, DeferralDepthError
from src.agent.deferral.resolver import (
    DelegateNotAllowedError,
    DelegateSelfReferentialError,
    DeferralResolver,
    resolve_delegate,
)
from src.agent.deferral.validator import (
    DeferralCycleError,
    DeferralGraphError,
    validate_deferral_graph,
)

__all__ = [
    "build_delegate_prompt",
    "ContextBridge",
    "DelegateNotAllowedError",
    "DelegateSelfReferentialError",
    "DeferralCycleError",
    "DeferralDepthError",
    "DeferralGraphError",
    "DeferralResolver",
    "DepthGuard",
    "resolve_delegate",
    "validate_deferral_graph",
]
