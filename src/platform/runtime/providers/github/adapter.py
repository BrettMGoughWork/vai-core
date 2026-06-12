"""GitHub webhook adapter — pure-logic payload normaliser.

Transforms a raw GitHub webhook payload into a canonical
:class:`~src.platform.runtime.channels.webhook.WebhookEvent`.

Expected raw structure::

    {
        "action": "opened",
        "issue": {...},
        "pull_request": {...},
        "sender": {"login": "octocat", ...},
        "repository": {...}
    }

GitHub webhooks can represent many event types (push, pull_request, issues,
etc.).  This adapter passes the full payload through as-is and extracts the
``sender.login`` as the ``sender``.  Pure logic only — no IO, no SDKs.
"""

from __future__ import annotations

from typing import Any

from src.platform.runtime.channels.webhook import WebhookEvent


def normalize_webhook(raw_input: dict[str, Any]) -> WebhookEvent:
    """Convert a raw GitHub webhook payload into a :class:`WebhookEvent`.

    Args:
        raw_input: The full GitHub webhook POST body as a JSON-parsed dict.

    Returns:
        A :class:`WebhookEvent` with:
            - ``source`` = ``"github"``
            - ``payload`` = the full raw payload (preserved for downstream
              processing)
            - ``sender`` = ``sender.login`` (or ``None``)
    """
    sender_obj: dict[str, Any] | None = raw_input.get("sender")
    sender: str | None = sender_obj.get("login") if isinstance(sender_obj, dict) else None

    return WebhookEvent(
        source="github",
        payload=raw_input,
        sender=sender,
    )
