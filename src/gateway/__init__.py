"""Stratum-4 Gateway — transport, ingress normalization, and external API surface.

Gateway owns:
- Transport layer (FastAPI)
- Channel normalizers (CLI, Slack, Web, WebSocket, etc.)
- External API surface (POST /run, GET /jobs/{job_id})
- Provider webhook adapters (WhatsApp, Slack, GitHub, Jira)

Gateway interfaces with S5 through the ``GatewayAgentAdapter`` protocol.
It never imports Supervisor internals directly.
"""

from src.gateway.adapters.agent_adapter import (
    AgentRequest as AgentRequest,
    GatewayAgentAdapter as GatewayAgentAdapter,
)

__all__ = [
    "AgentRequest",
    "GatewayAgentAdapter",
]
