"""WebSocket Channel — re-exported from Gateway.

.. note::
   The canonical implementation now lives in ``src.gateway.channels.ws``.
   This module re-exports symbols so existing Platform consumers continue
   to work during the transition period.
"""

from src.gateway.channels.ws import (  # noqa: F401
    WebSocketChannel,
    register_websocket_channel,
)
