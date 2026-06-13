"""Stratum-4 transport boundary — Gateway, normalization, dev transports."""

from src.platform.transport.dev_smtp import DevSMTPConfig, DevSMTPTransport
from src.platform.transport.normalization import (
    ChannelMessage,
    cli_to_channel_message,
    gateway_to_channel_message,
)

__all__ = [
    "ChannelMessage",
    "DevSMTPConfig",
    "DevSMTPTransport",
    "cli_to_channel_message",
    "gateway_to_channel_message",
]
