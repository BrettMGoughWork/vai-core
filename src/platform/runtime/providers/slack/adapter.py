"""Slack webhook adapter — pure-logic payload normaliser.

Transforms a raw Slack Events API payload into a canonical
:class:`~src.gateway.channels.webhook.WebhookEvent`.

Expected raw structure (Events API)::

    {
        "token": "...",
        "team_id": "T...",
        "api_app_id": "A...",
        "event": {
            "type": "message",
            "user": "U...",
            "text": "Hello",
            "channel": "C...",
            ...
        }
    }

This adapter extracts the ``event`` sub-object and surfaces the ``user``
field as the ``sender``.  Pure logic only — no IO, no SDKs.
"""

from __future__ import annotations

from typing import Any

from src.gateway.channels.webhook import WebhookEvent


def normalize_webhook(raw_input: dict[str, Any]) -> WebhookEvent:
    """Convert a raw Slack Events API payload into a :class:`WebhookEvent`.

    Args:
        raw_input: The full Slack webhook POST body as a JSON-parsed dict.

    Returns:
        A :class:`WebhookEvent` with:
            - ``source`` = ``"slack"``
            - ``payload`` = the ``event`` sub-object (or ``{}``)
            - ``sender`` = the ``user`` field from the event (or ``None``)
    """
    event: dict[str, Any] = raw_input.get("event") or {}
    sender: str | None = event.get("user")

    return WebhookEvent(
        source="slack",
        payload=event,
        sender=sender,
    )
