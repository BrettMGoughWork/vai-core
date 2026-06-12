"""CLI Channel — pure-logic CLI transport adapter for Stratum-4.

Converts raw local CLI input into :class:`InboundChannelMessage` objects
and converts outbound S4 messages back into CLI-friendly output structures.
This slice is pure logic only: no argparse, no terminal IO, no TUI, no
curses.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from src.platform.runtime.channels.base import Channel, InboundChannelMessage
from src.platform.runtime.channels.registry import ChannelRegistry


class CLIChannel(Channel):
    """CLI transport adapter.

    Converts raw CLI input (a ``dict`` with ``text`` and optional
    ``sender`` fields) into canonical :class:`InboundChannelMessage`
    instances, normalises them into S4 job payloads, and converts
    outbound payloads back into CLI-friendly output dicts.

    Pure logic — no IO, no terminal access, no argparse.

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
        """Convert raw CLI input into an :class:`InboundChannelMessage`.

        Args:
            raw_input: A ``dict`` with fields:
                - ``text`` (``str``): The CLI command text.
                - ``sender`` (``str | None``, optional): The user identity.

        Returns:
            A canonical :class:`InboundChannelMessage` with
            ``channel="cli"``.

        Raises:
            TypeError: If *raw_input* is not a ``dict``.
            ValueError: If the ``text`` field is missing or not a string.
        """
        if not isinstance(raw_input, dict):
            raise TypeError(
                f"CLIChannel.receive requires a dict, got {type(raw_input).__name__}"
            )

        text = raw_input.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(
                "CLIChannel.receive requires a 'text' field with a non-empty string"
            )

        sender: str | None = raw_input.get("sender", None)
        if sender is not None and not isinstance(sender, str):
            raise TypeError(
                f"CLIChannel.receive 'sender' must be a string or None, "
                f"got {type(sender).__name__}"
            )

        return InboundChannelMessage(
            channel="cli",
            sender=sender,
            payload={"text": text},
            timestamp=self._clock(),
        )

    def normalize(self, message: InboundChannelMessage) -> dict[str, Any]:
        """Normalise an :class:`InboundChannelMessage` into a canonical S4 job payload.

        Returns:
            A dict::

                {
                    "input": ...,       # the CLI text
                    "metadata": {...},  # channel metadata
                }
        """
        return {
            "input": message.payload.get("text", ""),
            "metadata": {
                "channel": message.channel,
                "sender": message.sender,
                "received_at": message.timestamp,
            },
        }

    def send(self, message: dict[str, Any]) -> dict[str, Any]:
        """Convert an outbound S4 payload into a CLI-friendly output dict.

        Returns:
            A dict::

                {
                    "text": ...,       # human-readable output text
                    "metadata": {...},  # any additional metadata
                }
        """
        return {
            "text": message.get("output", ""),
            "metadata": message.get("metadata", {}),
        }


# ------------------------------------------------------------------
# TUI stub (pure logic placeholder)
# ------------------------------------------------------------------


class CLITUI:
    """Pure-logic placeholder for future TUI rendering.

    No IO, no curses.  The :meth:`render` method is a pure
    transformation that will be fleshed out in a follow-up prompt.
    """

    def render(self, message: dict[str, Any]) -> dict[str, Any]:
        """Pure-logic placeholder for TUI rendering.

        Args:
            message: The S4 payload to render.

        Returns:
            A dict indicating the message was "rendered"::

                {"rendered": True, "content": message}
        """
        return {"rendered": True, "content": message}


# ------------------------------------------------------------------
# Convenience — register the default CLI channel
# ------------------------------------------------------------------


def register_cli_channel(
    registry: ChannelRegistry,
    clock: Callable[[], float] | None = None,
) -> None:
    """Register a :class:`CLIChannel` in *registry* under the name ``"cli"``.

    This is a convenience helper for the composition root.

    Args:
        registry: The :class:`ChannelRegistry` to register into.
        clock:    Optional deterministic clock (see :class:`CLIChannel`).
    """
    registry.register("cli", CLIChannel(clock=clock))
