"""WebSocket Channel — pure-logic WebSocket transport adapter for Stratum-4.

Converts structured WebSocket frames (as provided by any WebSocket server
library) into :class:`InboundChannelMessage` objects and converts outbound
S4 messages into WebSocket-friendly output structures.  This slice is pure
logic only: no WebSocket server, no event loop, no network IO.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from src.platform.runtime.channels.base import Channel, InboundChannelMessage
from src.platform.runtime.channels.registry import ChannelRegistry


class WebSocketChannel(Channel):
    """WebSocket transport adapter.

    Converts raw WebSocket frames (a ``dict`` with ``text``, optional
    ``sender``, and optional ``message_type`` fields) into canonical
    :class:`InboundChannelMessage` instances, normalises them into S4 job
    payloads, and converts outbound payloads back into WebSocket-friendly
    output dicts.

    Pure logic — no IO, no event loop, no WebSocket server.

    Args:
        clock: A no-arg callable returning the current Unix timestamp
            (defaults to :func:`time.time`).  Inject a deterministic
            clock in tests.
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock if clock is not None else time.time

    # ------------------------------------------------------------------
    # Channel protocol
    # ------------------------------------------------------------------

    def receive(self, raw_input: Any) -> InboundChannelMessage:
        """Convert a raw WebSocket frame into an :class:`InboundChannelMessage`.

        Args:
            raw_input: A ``dict`` with fields:
                - ``text`` (``str``): The message text.
                - ``sender`` (``str | None``, optional): The sender identity.
                - ``message_type`` (``str | None``, optional): Frame type
                  (``"text"``, ``"binary"``, …).  Defaults to ``"text"``.

        Returns:
            A canonical :class:`InboundChannelMessage` with
            ``channel="ws"``.

        Raises:
            TypeError: If *raw_input* is not a ``dict``.
            ValueError: If the ``text`` field is missing or not a string.
        """
        if not isinstance(raw_input, dict):
            raise TypeError(
                f"WebSocketChannel.receive requires a dict, "
                f"got {type(raw_input).__name__}"
            )

        text = raw_input.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(
                "WebSocketChannel.receive requires a 'text' field "
                "with a non-empty string"
            )

        sender: str | None = raw_input.get("sender", None)
        if sender is not None and not isinstance(sender, str):
            raise TypeError(
                f"WebSocketChannel.receive 'sender' must be a string or None, "
                f"got {type(sender).__name__}"
            )

        message_type: str | None = raw_input.get("message_type", None)
        if message_type is not None and not isinstance(message_type, str):
            raise TypeError(
                f"WebSocketChannel.receive 'message_type' must be a string "
                f"or None, got {type(message_type).__name__}"
            )

        return InboundChannelMessage(
            channel="ws",
            sender=sender,
            payload={
                "text": text,
                "message_type": message_type or "text",
            },
            timestamp=self._clock(),
        )

    def normalize(self, message: InboundChannelMessage) -> dict[str, Any]:
        """Normalise an :class:`InboundChannelMessage` into a canonical S4 job payload.

        Returns:
            A dict::

                {
                    "input": ...,       # the WebSocket message text
                    "metadata": {...},  # channel metadata
                }
        """
        return {
            "input": message.payload.get("text", ""),
            "metadata": {
                "channel": message.channel,
                "sender": message.sender,
                "message_type": message.payload.get("message_type", "text"),
            },
        }

    def send(self, message: dict[str, Any]) -> dict[str, Any]:
        """Convert an outbound S4 payload into a WebSocket-friendly output dict.

        Returns:
            A dict::

                {
                    "text": ...,           # the response text
                    "message_type": ...,   # frame type (default "text")
                    "metadata": {...},     # any additional metadata
                }
        """
        return {
            "text": message.get("output", ""),
            "message_type": "text",
            "metadata": message.get("metadata", {}),
        }


# ------------------------------------------------------------------
# Convenience — register the default WebSocket channel
# ------------------------------------------------------------------


def register_websocket_channel(
    registry: ChannelRegistry,
    clock: Callable[[], float] | None = None,
) -> None:
    """Register a :class:`WebSocketChannel` in *registry* under the name ``"ws"``.

    This is a convenience helper for the composition root.

    Args:
        registry: The :class:`ChannelRegistry` to register into.
        clock:    Optional deterministic clock (see :class:`WebSocketChannel`).
    """
    registry.register("ws", WebSocketChannel(clock=clock))
