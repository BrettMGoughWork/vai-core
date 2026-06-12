"""Channel base — pure-logic transport adapter protocol.

Defines the :class:`ChannelMessage` dataclass and the :class:`Channel`
protocol that all transport adapters must implement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class InboundChannelMessage:
    """Canonical inbound message produced by a transport channel.

    Attributes:
        channel:   Channel identifier (``"cli"``, ``"http"``, ``"ws"``, …).
        sender:    Optional sender identity (user, API key, …).
        payload:   The raw user payload as an arbitrary JSON-compatible dict.
        timestamp: Unix timestamp (seconds) when the message was received.
    """

    channel: str
    sender: str | None
    payload: dict[str, Any]
    timestamp: float


@runtime_checkable
class Channel(Protocol):
    """Protocol that every transport channel adapter must implement.

    Methods
    -------
    receive(raw_input)
        Convert raw transport input into a :class:`ChannelMessage`.

    normalize(message)
        Normalise a :class:`ChannelMessage` into a canonical S4 job payload
        (a plain ``dict``).

    send(message)
        Convert an outbound S4 payload (``dict``) into the transport-specific
        output format.
    """

    def receive(self, raw_input: Any) -> InboundChannelMessage:
        """Convert raw transport input → InboundChannelMessage.

        Args:
            raw_input: The raw input received from the transport layer.

        Returns:
            A canonical :class:`InboundChannelMessage`.
        """
        ...

    def normalize(self, message: InboundChannelMessage) -> dict[str, Any]:
        """Normalise InboundChannelMessage → canonical S4 job payload.

        The returned dict is the canonical payload that Stratum-4 uses
        internally.  Implementations strip transport-specific metadata and
        preserve only the user's intent.

        Args:
            message: The :class:`InboundChannelMessage` to normalise.

        Returns:
            A plain ``dict`` suitable for job creation.
        """
        ...

    def send(self, message: dict[str, Any]) -> dict[str, Any]:
        """Convert outbound S4 payload → transport-specific output.

        Args:
            message: The outbound S4 payload (a ``dict``).

        Returns:
            A transport-specific output ``dict`` (the caller serialises
            as appropriate for the channel).
        """
        ...
