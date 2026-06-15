"""Channel normalization — Stratum-4 transport boundary.

Re-exports from the canonical gateway normalization module.
This module exists for backward compatibility during the migration.

Pure transformation layer.  No business logic, no orchestration, no side effects.
All inbound payloads are normalized into ``ChannelMessage`` — the canonical
inbound message format for S4.
"""

from src.gateway.normalization import (  # noqa: F401
    ChannelMessage,
    cli_to_channel_message,
    gateway_to_channel_message,
)
