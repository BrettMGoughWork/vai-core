"""Web Channel adapter — pure-logic HTTP transport adapter for Stratum-4.

Converts structured HTTP request bodies (as provided by FastAPI or any web
framework) into :class:`InboundChannelMessage` objects and converts outbound
S4 messages into transport-agnostic HTTP response payloads.  This slice is
pure logic only: no FastAPI app, no routing, no network IO.

Moved from ``src/gateway/channels/web.py`` to ``web_simple/adapter.py`` as
part of the channel-package refactor (Sprint 13).
"""

from __future__ import annotations

import time
from typing import Any, Callable

from pydantic import BaseModel

from src.gateway.channels.base import Channel, InboundChannelMessage
from src.gateway.channels.registry import ChannelRegistry


# ------------------------------------------------------------------
# Pydantic request / response models (pure logic, no IO)
# ------------------------------------------------------------------


class WebRequest(BaseModel):
    """Canonical web request body.

    Attributes:
        input:    The user's input text.
        sender:   Optional sender identity (user, API key, …).
        metadata: Optional arbitrary JSON-compatible metadata.
    """

    input: str
    sender: str | None = None
    metadata: dict[str, Any] | None = None


class WebResponse(BaseModel):
    """Canonical web response body.

    Attributes:
        output:   The response output text.
        metadata: Optional arbitrary metadata attached by the runtime.
    """

    output: str
    metadata: dict[str, Any] | None = None


# ------------------------------------------------------------------
# Web Channel adapter
# ------------------------------------------------------------------


class WebChannel(Channel):
    """Web (HTTP) transport adapter.

    Converts structured HTTP JSON bodies (a ``dict`` with ``input``,
    optional ``sender``, and optional ``metadata`` fields) into canonical
    :class:`InboundChannelMessage` instances, normalises them into S4 job
    payloads, and converts outbound payloads back into HTTP-friendly
    output dicts.

    Pure logic — no IO, no FastAPI, no routing.

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
        """Convert raw HTTP request body into an :class:`InboundChannelMessage`.

        Args:
            raw_input: A ``dict`` with fields:
                - ``input`` (``str``): The user input text.
                - ``sender`` (``str | None``, optional): The user identity.
                - ``metadata`` (``dict | None``, optional): Extra metadata.

        Returns:
            A canonical :class:`InboundChannelMessage` with
            ``channel="web"``.

        Raises:
            TypeError: If *raw_input* is not a ``dict``.
            ValueError: If the ``input`` field is missing or not a string.
        """
        if not isinstance(raw_input, dict):
            raise TypeError(
                f"WebChannel.receive requires a dict, got {type(raw_input).__name__}"
            )

        input_text = raw_input.get("input")
        if not isinstance(input_text, str) or not input_text.strip():
            raise ValueError(
                "WebChannel.receive requires an 'input' field with a non-empty string"
            )

        sender: str | None = raw_input.get("sender", None)
        if sender is not None and not isinstance(sender, str):
            raise TypeError(
                f"WebChannel.receive 'sender' must be a string or None, "
                f"got {type(sender).__name__}"
            )

        metadata: dict[str, Any] | None = raw_input.get("metadata", None)
        if metadata is not None and not isinstance(metadata, dict):
            raise TypeError(
                f"WebChannel.receive 'metadata' must be a dict or None, "
                f"got {type(metadata).__name__}"
            )

        return InboundChannelMessage(
            channel="web",
            sender=sender,
            payload={"input": input_text, "metadata": metadata or {}},
            timestamp=self._clock(),
        )

    def normalize(self, message: InboundChannelMessage) -> dict[str, Any]:
        """Normalise an :class:`InboundChannelMessage` into a canonical S4 job payload.

        Returns:
            A dict::

                {
                    "input": ...,       # the web input text
                    "metadata": {...},  # channel metadata + user metadata
                }
        """
        return {
            "input": message.payload.get("input", ""),
            "metadata": {
                "channel": message.channel,
                "sender": message.sender,
                **message.payload.get("metadata", {}),
            },
        }

    def send(self, message: dict[str, Any]) -> dict[str, Any]:
        """Convert an outbound S4 payload into an HTTP-friendly output dict.

        Returns:
            A dict::

                {
                    "output": ...,       # the response output text
                    "metadata": {...},   # any additional metadata
                }
        """
        return {
            "output": message.get("output", ""),
            "metadata": message.get("metadata", {}),
        }


# ------------------------------------------------------------------
# Convenience — register the default Web channel
# ------------------------------------------------------------------


def register_web_channel(
    registry: ChannelRegistry,
    clock: Callable[[], float] | None = None,
) -> None:
    """Register a :class:`WebChannel` in *registry* under the name ``"web"``.

    This is a convenience helper for the composition root.

    Args:
        registry: The :class:`ChannelRegistry` to register into.
        clock:    Optional deterministic clock (see :class:`WebChannel`).
    """
    registry.register("web", WebChannel(clock=clock))
