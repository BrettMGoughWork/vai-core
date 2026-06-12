"""WhatsApp webhook adapter — pure-logic payload normaliser.

Transforms a raw WhatsApp Cloud API inbound message webhook into a
canonical :class:`~src.platform.runtime.channels.webhook.WebhookEvent`.

Expected raw structure (Cloud API)::

    {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{"from": "<wa-id>", "text": {"body": "..."}}],
                    "contacts": [{"wa_id": "<wa-id>"}]
                }
            }]
        }]
    }

This adapter extracts the first message from each entry and surfaces the
WhatsApp ID as the ``sender``.  Pure logic only — no IO, no SDKs.
"""

from __future__ import annotations

from typing import Any

from src.platform.runtime.channels.webhook import WebhookEvent


def normalize_webhook(raw_input: dict[str, Any]) -> WebhookEvent:
    """Convert a raw WhatsApp Cloud API payload into a :class:`WebhookEvent`.

    Args:
        raw_input: The full WhatsApp webhook POST body as a JSON-parsed dict.

    Returns:
        A :class:`WebhookEvent` with:
            - ``source`` = ``"whatsapp"``
            - ``payload`` = the first message dict (or ``{}``)
            - ``sender`` = the ``wa_id`` of the first contact (or ``None``)
    """
    entry = (raw_input.get("entry") or [{}])[0]
    changes = (entry.get("changes") or [{}])[0]
    value = changes.get("value") or {}

    messages = value.get("messages") or []
    message: dict[str, Any] = messages[0] if messages else {}

    contacts = value.get("contacts") or []
    contact: dict[str, Any] = contacts[0] if contacts else {}
    sender: str | None = contact.get("wa_id")

    return WebhookEvent(
        source="whatsapp",
        payload=message,
        sender=sender,
    )
