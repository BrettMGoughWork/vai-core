"""Webhook Channel — pure-logic webhook transport adapter for Stratum-4.

Accepts arbitrary inbound POST payloads from external systems (WhatsApp,
Telegram, GitHub, Stripe, Twilio, custom integrations) and normalises them
into :class:`InboundChannelMessage` objects.  Converts outbound S4 messages
into webhook-compatible response payloads.  This slice is pure logic only:
no FastAPI, no routing, no signature verification, no network IO.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from src.platform.runtime.channels.base import Channel, InboundChannelMessage
from src.platform.runtime.channels.registry import ChannelRegistry


@dataclass(frozen=True)
class WebhookEvent:
    """Canonical representation of an inbound webhook payload.

    Attributes:
        source:  The originating service (``"whatsapp"``, ``"github"``, …).
        payload: The raw webhook body as a JSON-compatible dict.
        sender:  Optional sender identity extracted by the gateway layer.
    """

    source: str
    payload: dict[str, Any]
    sender: str | None


class WebhookChannel(Channel):
    """Webhook transport adapter.

    Accepts arbitrary HTTP POST bodies from external systems, converts them
    into canonical :class:`InboundChannelMessage` instances, normalises them
    into S4 job payloads, and converts outbound payloads back into webhook-
    compatible response dicts.

    Pure logic — no IO, no FastAPI, no signature verification.

    Args:
        clock: A no-arg callable returning the current Unix timestamp
            (defaults to :func:`time.time`).  Inject a deterministic
            clock in tests.
    """

    VALID_SOURCES: tuple[str, ...] = (
        "whatsapp", "telegram", "github", "stripe", "twilio", "slack",
        "discord", "generic",
    )

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock if clock is not None else time.time

    # ------------------------------------------------------------------
    # Channel protocol
    # ------------------------------------------------------------------

    def receive(self, raw_input: Any) -> InboundChannelMessage:
        """Convert a raw webhook POST body into an :class:`InboundChannelMessage`.

        Args:
            raw_input: A ``dict`` with fields:
                - ``source`` (``str``): The originating service identifier
                  (e.g. ``"whatsapp"``, ``"github"``).
                - ``payload`` (``dict``): The raw webhook body.
                - ``sender`` (``str | None``, optional): Sender identity
                  extracted by the gateway.

        Returns:
            A canonical :class:`InboundChannelMessage` with
            ``channel="webhook"``.

        Raises:
            TypeError: If *raw_input* is not a ``dict``.
            ValueError: If ``source`` or ``payload`` are missing or invalid.
        """
        if not isinstance(raw_input, dict):
            raise TypeError(
                f"WebhookChannel.receive requires a dict, "
                f"got {type(raw_input).__name__}"
            )

        source = raw_input.get("source")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(
                "WebhookChannel.receive requires a 'source' field "
                "with a non-empty string"
            )

        payload = raw_input.get("payload")
        if not isinstance(payload, dict):
            raise ValueError(
                "WebhookChannel.receive requires a 'payload' field "
                "with a dict"
            )

        sender: str | None = raw_input.get("sender", None)
        if sender is not None and not isinstance(sender, str):
            raise TypeError(
                f"WebhookChannel.receive 'sender' must be a string or None, "
                f"got {type(sender).__name__}"
            )

        return InboundChannelMessage(
            channel="webhook",
            sender=sender,
            payload={
                "source": source,
                "payload": payload,
            },
            timestamp=self._clock(),
        )

    def normalize(self, message: InboundChannelMessage) -> dict[str, Any]:
        """Normalise an :class:`InboundChannelMessage` into a canonical S4 job payload.

        Returns:
            A dict::

                {
                    "input": ...,       # the raw webhook payload dict
                    "metadata": {...},  # channel metadata
                }
        """
        return {
            "input": message.payload.get("payload", {}),
            "metadata": {
                "channel": message.channel,
                "source": message.payload.get("source", ""),
                "sender": message.sender,
            },
        }

    def send(self, message: dict[str, Any]) -> dict[str, Any]:
        """Convert an outbound S4 payload into a webhook-compatible response dict.

        Returns:
            A dict::

                {
                    "status": "ok",
                    "response": ...,      # the response output
                    "metadata": {...},    # any additional metadata
                }
        """
        return {
            "status": "ok",
            "response": message.get("output", ""),
            "metadata": message.get("metadata", {}),
        }


# ------------------------------------------------------------------
# Convenience — register the default Webhook channel
# ------------------------------------------------------------------


def register_webhook_channel(
    registry: ChannelRegistry,
    clock: Callable[[], float] | None = None,
) -> None:
    """Register a :class:`WebhookChannel` in *registry* under the name ``"webhook"``.

    This is a convenience helper for the composition root.

    Args:
        registry: The :class:`ChannelRegistry` to register into.
        clock:    Optional deterministic clock (see :class:`WebhookChannel`).
    """
    registry.register("webhook", WebhookChannel(clock=clock))
