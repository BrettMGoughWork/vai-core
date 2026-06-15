"""Stratum-4 Gateway — transport, ingress normalization, and external API surface.

Gateway owns:
- Transport layer (FastAPI)
- Channel normalizers (CLI, Slack, Web, WebSocket, etc.)
- External API surface (POST /run, GET /jobs/{job_id})
- Provider webhook adapters (WhatsApp, Slack, GitHub, Jira)

Gateway interfaces with Platform through the ``GatewayPlatformAdapter`` protocol.
It never imports Platform internals directly.
"""

from src.gateway.adapters.platform_adapter import (
    GatewayPlatformAdapter as GatewayPlatformAdapter,
    JobRequest as JobRequest,
    JobResult as JobResult,
    JobStatus as JobStatus,
)
from src.gateway.normalization import (
    ChannelMessage as ChannelMessage,
    cli_to_channel_message as cli_to_channel_message,
    gateway_to_channel_message as gateway_to_channel_message,
)

__all__ = [
    "ChannelMessage",
    "GatewayPlatformAdapter",
    "JobRequest",
    "JobResult",
    "JobStatus",
    "cli_to_channel_message",
    "gateway_to_channel_message",
]
