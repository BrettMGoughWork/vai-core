"""Stratum-4 transport boundary — Gateway, normalization."""

from src.platform.transport.normalization import (
    ChannelMessage,
    cli_to_channel_message,
    gateway_to_channel_message,
)

__all__ = [
    "ChannelMessage",
    "cli_to_channel_message",
    "gateway_to_channel_message",
]
