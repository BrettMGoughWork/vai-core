"""Web Channel — backward-compatibility re-export shim.

All logic has moved to ``src/gateway/channels/web_simple/adapter.py``.
This module re-exports everything so existing imports don't break::

    from src.gateway.channels.web import WebChannel  # still works
"""

from __future__ import annotations

from src.gateway.channels.web_simple import (
    WebChannel,
    WebRequest,
    WebResponse,
    register_web_channel,
)

__all__ = [
    "WebChannel",
    "WebRequest",
    "WebResponse",
    "register_web_channel",
]
