"""Channel registry — maps channel names to their adapter instances.

The :class:`ChannelRegistry` is a pure-logic container that associates
channel identifiers (``"cli"``, ``"http"``, …) with their :class:`Channel`
implementations.
"""

from __future__ import annotations

from src.gateway.channels.base import Channel


class ChannelRegistry:
    """Maps channel names to :class:`Channel` adapter instances.

    Usage::

        registry = ChannelRegistry()
        registry.register("cli", CliChannel())
        channel = registry.get("cli")
        msg = channel.receive(raw_input)
    """

    def __init__(self) -> None:
        self._channels: dict[str, Channel] = {}

    def register(self, name: str, channel: Channel) -> None:
        """Register a *channel* adapter under *name*.

        Args:
            name:     Channel identifier (e.g. ``"cli"``, ``"http"``).
            channel:  A :class:`Channel`-conforming adapter instance.
        """
        self._channels[name] = channel

    def get(self, name: str) -> Channel:
        """Retrieve the channel adapter registered under *name*.

        Args:
            name: The channel identifier.

        Returns:
            The :class:`Channel` adapter instance.

        Raises:
            KeyError: If *name* has not been registered.
        """
        return self._channels[name]

    @property
    def names(self) -> tuple[str, ...]:
        """Return the names of all registered channels."""
        return tuple(self._channels.keys())
