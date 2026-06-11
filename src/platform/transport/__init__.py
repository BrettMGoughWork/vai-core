"""Stratum-4 transport boundary — Gateway, normalization."""

from src.platform.transport.app import app, job_queue
from src.platform.transport.normalization import (
    ChannelMessage,
    cli_to_channel_message,
    gateway_to_channel_message,
)

__all__ = [
    "ChannelMessage",
    "app",
    "cli_to_channel_message",
    "gateway_to_channel_message",
    "job_queue",
]
