"""Channel abstraction — transport adapters for the Gateway.

All ingress transports (CLI, Web, WebSocket, Webhooks) implement the
:class:`Channel` protocol to convert external events into
:class:`InboundChannelMessage` objects and convert outbound messages back
to the transport format. This slice is pure logic only: no networking, no
FastAPI, no WebSocket server, no webhook handlers.
"""

from src.gateway.channels.base import Channel, InboundChannelMessage
from src.gateway.channels.cli import CLIChannel, CLITUI, register_cli_channel
from src.gateway.channels.registry import ChannelRegistry
from src.gateway.channels.tui import (
    TUIChannel,
    TUIPanel,
    TUIScreen,
    TUIStatusBar,
    register_tui_channel,
)
from src.gateway.channels.web_simple import (
    WebChannel,
    WebRequest,
    WebResponse,
    register_web_channel,
)
from src.gateway.channels.webhook import (
    WebhookChannel,
    WebhookEvent,
    register_webhook_channel,
)
from src.gateway.channels.ws import (
    WebSocketChannel,
    register_websocket_channel,
)
from src.gateway.channels.slack import (
    SlackChannel,
    register_slack_channel,
)
from src.gateway.channels.mail import (
    MailChannel,
    register_mail_channel,
)

__all__ = [
    "Channel",
    "CLIChannel",
    "CLITUI",
    "ChannelRegistry",
    "InboundChannelMessage",
    "MailChannel",
    "SlackChannel",
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
    "register_mail_channel",
    "register_slack_channel",
    "register_tui_channel",
    "register_web_channel",
    "register_webhook_channel",
    "register_websocket_channel",
]
