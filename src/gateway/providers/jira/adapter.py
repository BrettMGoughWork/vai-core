"""Jira webhook adapter — pure-logic payload normaliser.

Transforms a raw Jira webhook payload into a canonical
:class:`~src.gateway.channels.webhook.WebhookEvent`.

Expected raw structure::

    {
        "timestamp": 1234567890,
        "webhookEvent": "jira:issue_created",
        "issue": {
            "id": "10000",
            "key": "PROJ-123",
            "fields": {
                "summary": "Something broke",
                "description": "...",
                ...
            }
        },
        "user": {
            "name": "admin",
            "displayName": "Admin User",
            ...
        }
    }

This adapter extracts the ``issue`` sub-object as the payload and surfaces
``user.name`` as the ``sender``.  Pure logic only — no IO, no SDKs.
"""

from __future__ import annotations

from typing import Any

from src.gateway.channels.webhook import WebhookEvent


def normalize_webhook(raw_input: dict[str, Any]) -> WebhookEvent:
    """Convert a raw Jira webhook payload into a :class:`WebhookEvent`.

    Args:
        raw_input: The full Jira webhook POST body as a JSON-parsed dict.

    Returns:
        A :class:`WebhookEvent` with:
            - ``source`` = ``"jira"``
            - ``payload`` = the ``issue`` sub-object (or ``{}``)
            - ``sender`` = ``user.name`` (or ``None``)
    """
    issue: dict[str, Any] = raw_input.get("issue") or {}
    user_obj: dict[str, Any] | None = raw_input.get("user")
    sender: str | None = user_obj.get("name") if isinstance(user_obj, dict) else None

    return WebhookEvent(
        source="jira",
        payload=issue,
        sender=sender,
    )
