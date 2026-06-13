"""Slack Channel — pure-logic Slack Events API transport adapter for Stratum-4.

Accepts inbound Slack Events API payloads (message events) and normalises
them into :class:`InboundChannelMessage` objects.  Converts outbound S4
messages into Slack-compatible webhook POST payloads.  This slice is pure
logic only: no Slack SDK, no WebSocket RTM, no HTTP, no network IO.

Integration testing requires a real Slack workspace and a configured
Slack app with Event Subscriptions enabled.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from src.platform.runtime.channels.base import Channel, InboundChannelMessage
from src.platform.runtime.channels.registry import ChannelRegistry


class SlackChannel(Channel):
    """Slack Events API transport adapter.

    Accepts Slack message-event payloads, converts them into canonical
    :class:`InboundChannelMessage` instances, normalises them into S4
    job payloads, and converts outbound payloads back into Slack-compatible
    response dicts.

    Pure logic — no IO, no Slack SDK, no HTTP.

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
        """Convert a raw Slack Events API payload into an :class:`InboundChannelMessage`.

        The expected input shape mirrors the Slack Events API schema::

            {
                "text": "deploy now",       # the message text (required)
                "sender": "U12345",         # Slack user ID (optional)
                "channel": "C67890",        # Slack channel ID (optional)
                "team": "T11111",           # team/workspace ID (optional)
            }

        Args:
            raw_input: A ``dict`` with Slack message fields.

        Returns:
            A canonical :class:`InboundChannelMessage` with
            ``channel="slack"``.

        Raises:
            TypeError: If *raw_input* is not a ``dict``.
            ValueError: If ``text`` is missing or empty.
        """
        if not isinstance(raw_input, dict):
            raise TypeError(
                f"SlackChannel.receive requires a dict, "
                f"got {type(raw_input).__name__}"
            )

        text = raw_input.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(
                "SlackChannel.receive requires a 'text' field "
                "with a non-empty string"
            )

        sender: str | None = raw_input.get("sender")
        if sender is not None and not isinstance(sender, str):
            raise TypeError(
                f"SlackChannel.receive 'sender' must be a string or None, "
                f"got {type(sender).__name__}"
            )

        channel_id: str | None = raw_input.get("channel")
        if channel_id is not None and not isinstance(channel_id, str):
            raise TypeError(
                f"SlackChannel.receive 'channel' must be a string or None, "
                f"got {type(channel_id).__name__}"
            )

        team: str | None = raw_input.get("team")
        if team is not None and not isinstance(team, str):
            raise TypeError(
                f"SlackChannel.receive 'team' must be a string or None, "
                f"got {type(team).__name__}"
            )

        payload: dict[str, Any] = {"text": text}
        if channel_id is not None:
            payload["channel"] = channel_id
        if team is not None:
            payload["team"] = team

        return InboundChannelMessage(
            channel="slack",
            sender=sender,
            payload=payload,
            timestamp=self._clock(),
        )

    def normalize(self, message: InboundChannelMessage) -> dict[str, Any]:
        """Normalise an :class:`InboundChannelMessage` into a canonical S4 job payload.

        Returns:
            A dict::

                {
                    "input": ...,       # the Slack message text
                    "metadata": {...},  # channel metadata
                }
        """
        metadata: dict[str, Any] = {
            "channel": message.channel,
            "sender": message.sender,
        }
        if "channel" in message.payload:
            metadata["slack_channel"] = message.payload["channel"]
        if "team" in message.payload:
            metadata["slack_team"] = message.payload["team"]

        return {
            "input": message.payload.get("text", ""),
            "metadata": metadata,
        }

    def send(self, message: dict[str, Any]) -> dict[str, Any]:
        """Convert an outbound S4 payload into a Slack-compatible webhook POST body.

        Returns:
            A dict::

                {
                    "text": ...,             # the response text
                    "channel": ...,          # optional Slack channel override
                    "attachments": [...],    # optional Slack attachments
                    "metadata": {...},       # any additional metadata
                }
        """
        result: dict[str, Any] = {
            "text": message.get("output", ""),
            "metadata": message.get("metadata", {}),
        }
        # Pass through Slack-specific fields if present in metadata
        meta = message.get("metadata", {})
        if isinstance(meta, dict):
            if "slack_channel" in meta:
                result["channel"] = meta["slack_channel"]
        return result


# ------------------------------------------------------------------
# Convenience — register the default Slack channel
# ------------------------------------------------------------------


def register_slack_channel(
    registry: ChannelRegistry,
    clock: Callable[[], float] | None = None,
) -> None:
    """Register a :class:`SlackChannel` in *registry* under the name ``"slack"``.

    This is a convenience helper for the composition root.

    Args:
        registry: The :class:`ChannelRegistry` to register into.
        clock:    Optional deterministic clock (see :class:`SlackChannel`).
    """
    registry.register("slack", SlackChannel(clock=clock))
