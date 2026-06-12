"""Channel abstraction — transport adapters for Stratum-4.

All ingress transports (CLI, Web, WebSocket, Webhooks) implement the
:class:`Channel` protocol to convert external events into
:class:`InboundChannelMessage` objects and convert outbound messages back
to the transport format.  This slice is pure logic only: no networking, no
FastAPI, no WebSocket server, no webhook handlers.
"""

from src.platform.runtime.channels.base import Channel, InboundChannelMessage
from src.platform.runtime.channels.cli import CLIChannel, CLITUI, register_cli_channel
from src.platform.runtime.channels.registry import ChannelRegistry
from src.platform.runtime.channels.tui import (
    TUIChannel,
    TUIPanel,
    TUIScreen,
    TUIStatusBar,
    register_tui_channel,
)
from src.platform.runtime.channels.web import (
    WebChannel,
    WebRequest,
    WebResponse,
    register_web_channel,
)
from src.platform.runtime.channels.webhook import (
    WebhookChannel,
    WebhookEvent,
    register_webhook_channel,
)
from src.platform.runtime.channels.ws import (
    WebSocketChannel,
    register_websocket_channel,
)

__all__ = [
    "Channel",
    "CLIChannel",
    "CLITUI",
    "ChannelRegistry",
    "InboundChannelMessage",
    "TUIChannel",
    "TUIPanel",
    "TUIScreen",
    "TUIStatusBar",
    "WebChannel",
    "WebRequest",
    "WebResponse",
    "WebhookChannel",
    "WebhookEvent",
    "WebSocketChannel",
    "register_cli_channel",
    "register_tui_channel",
    "register_web_channel",
    "register_webhook_channel",
    "register_websocket_channel",
]
