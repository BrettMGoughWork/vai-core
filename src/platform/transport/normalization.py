"""Channel normalization — Stratum-4 transport boundary.

Pure transformation layer.  No business logic, no orchestration, no side effects.
All inbound payloads are normalized into ``ChannelMessage`` — the canonical
inbound message format for S4.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChannelMessage(BaseModel):
    """Canonical inbound message format for Stratum-4.

    Fields:
        input:    The raw user payload (arbitrary JSON dict).
        metadata: Channel-level metadata (source, timestamp, etc.).
        channel:  Channel identifier, e.g. ``"cli"``, ``"http"``.

    Validation:
        - ``input`` must be a ``dict``.
        - ``metadata`` must be a ``dict``.
    """

    input: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)
    channel: str = "cli"


def cli_to_channel_message(raw: dict[str, Any]) -> ChannelMessage:
    """Convert raw CLI input to a ``ChannelMessage``.

    Args:
        raw: The raw payload received from the CLI channel.

    Returns:
        A ``ChannelMessage`` with ``channel="cli"`` and empty metadata.
    """
    return ChannelMessage(input=raw, metadata={}, channel="cli")


def gateway_to_channel_message(raw: dict[str, Any]) -> ChannelMessage:
    """Convert raw gateway input to a ``ChannelMessage``.

    Args:
        raw: The raw payload received from the HTTP gateway.

    Returns:
        A ``ChannelMessage`` with ``channel="cli"`` and ``source`` set in metadata.
    """
    return ChannelMessage(
        input=raw,
        metadata={"source": "gateway"},
        channel="cli",
    )
