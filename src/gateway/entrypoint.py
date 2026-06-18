"""Gateway entrypoint — normalises channel input and hands off to S5.

This module provides the channel abstraction pipeline::

    # Pure channel logic (returns a dict — use for testing/validation)
    payload = process_channel_input(registry, channel_name, raw_input)

    # Wired through to S5 via a GatewayAgentAdapter (use in apps)
    result = submit_channel_input(registry, channel_name, raw_input, adapter)

It also provides convenience wrappers for each transport channel (web,
WebSocket, webhook) and a :func:`handle_provider_webhook` function that
chains a provider-specific adapter → webhook channel → canonical payload.

No networking or framework code lives here.
"""

from __future__ import annotations

from typing import Any

from src.gateway.adapters.agent_adapter import (
    AgentRequest,
    GatewayAgentAdapter,
)
from src.gateway.channels.base import InboundChannelMessage
from src.gateway.channels.registry import ChannelRegistry
from src.gateway.channels.webhook import WebhookEvent
from src.gateway.providers.whatsapp.adapter import (
    normalize_webhook as whatsapp_norm,
)
from src.gateway.providers.slack.adapter import (
    normalize_webhook as slack_norm,
)
from src.gateway.providers.github.adapter import (
    normalize_webhook as github_norm,
)
from src.gateway.providers.jira.adapter import (
    normalize_webhook as jira_norm,
)


# ------------------------------------------------------------------
# Provider adapter map
# ------------------------------------------------------------------

PROVIDER_MAP: dict[str, Any] = {
    "whatsapp": whatsapp_norm,
    "slack": slack_norm,
    "github": github_norm,
    "jira": jira_norm,
}


def process_channel_input(
    registry: ChannelRegistry,
    channel_name: str,
    raw_input: Any,
) -> dict[str, Any] | None:
    """Convert *raw_input* from a named channel into a canonical S4 payload.

    Args:
        registry:     The :class:`ChannelRegistry` with registered adapters.
        channel_name: The channel identifier (e.g. ``"cli"``).
        raw_input:    The raw input from the transport layer.

    Returns:
        A canonical S4 job payload (``dict``) or ``None`` if the channel
        does not exist in the registry.
    """
    try:
        channel = registry.get(channel_name)
    except KeyError:
        return None

    msg: InboundChannelMessage = channel.receive(raw_input)
    normalized: dict[str, Any] = channel.normalize(msg)
    return normalized


def handle_web_request(
    registry: ChannelRegistry,
    body: dict[str, Any],
) -> dict[str, Any] | None:
    """Convert an HTTP JSON body into a canonical S4 job payload via the Web channel.

    This is a convenience wrapper around :func:`process_channel_input` that
    hard-codes the channel name to ``"web"`` for use in FastAPI route
    handlers and similar HTTP entrypoints.

    Args:
        registry: The :class:`ChannelRegistry` with a registered Web channel.
        body:     The HTTP JSON body as a ``dict`` with ``input``,
                  optional ``sender``, and optional ``metadata`` fields.

    Returns:
        A canonical S4 job payload (``dict``) or ``None`` if the Web
        channel is not registered.
    """
    return process_channel_input(registry, "web", body)


def handle_ws_message(
    registry: ChannelRegistry,
    body: dict[str, Any],
) -> dict[str, Any] | None:
    """Convert a WebSocket frame body into a canonical S4 job payload via the WS channel.

    This is a convenience wrapper around :func:`process_channel_input` that
    hard-codes the channel name to ``"ws"`` for use in WebSocket server
    handlers and similar real-time entrypoints.

    Args:
        registry: The :class:`ChannelRegistry` with a registered WebSocket channel.
        body:     The frame body as a ``dict`` with ``text``,
                  optional ``sender``, and optional ``message_type`` fields.

    Returns:
        A canonical S4 job payload (``dict``) or ``None`` if the WebSocket
        channel is not registered.
    """
    return process_channel_input(registry, "ws", body)


def handle_slack_event(
    registry: ChannelRegistry,
    body: dict[str, Any],
) -> dict[str, Any] | None:
    """Convert a Slack Events API body into a canonical S4 job payload via the Slack channel.

    This is a convenience wrapper around :func:`process_channel_input` that
    hard-codes the channel name to ``"slack"``.

    Args:
        registry: The :class:`ChannelRegistry` with a registered Slack channel.
        body:     The Slack event body as a ``dict`` with ``text``,
                  optional ``sender``, ``channel``, and ``team`` fields.

    Returns:
        A canonical S4 job payload (``dict``) or ``None`` if the Slack
        channel is not registered.
    """
    return process_channel_input(registry, "slack", body)


def handle_mail_message(
    registry: ChannelRegistry,
    body: dict[str, Any],
) -> dict[str, Any] | None:
    """Convert a parsed email body into a canonical S4 job payload via the Mail channel.

    This is a convenience wrapper around :func:`process_channel_input` that
    hard-codes the channel name to ``"mail"``.

    Args:
        registry: The :class:`ChannelRegistry` with a registered Mail channel.
        body:     The email body as a ``dict`` with ``from``, ``subject``,
                  ``body``, and optional ``to`` fields.

    Returns:
        A canonical S4 job payload (``dict``) or ``None`` if the Mail
        channel is not registered.
    """
    return process_channel_input(registry, "mail", body)


def handle_webhook_post(
    registry: ChannelRegistry,
    body: dict[str, Any],
) -> dict[str, Any] | None:
    """Convert a webhook POST body into a canonical S4 job payload via the Webhook channel.

    This is a convenience wrapper around :func:`process_channel_input` that
    hard-codes the channel name to ``"webhook"`` for use in FastAPI route
    handlers and similar HTTP entrypoints.

    Args:
        registry: The :class:`ChannelRegistry` with a registered Webhook channel.
        body:     The POST body as a ``dict`` with ``source``, ``payload``,
                  and optional ``sender`` fields.

    Returns:
        A canonical S4 job payload (``dict``) or ``None`` if the Webhook
        channel is not registered.
    """
    return process_channel_input(registry, "webhook", body)


def handle_provider_webhook(
    registry: ChannelRegistry,
    provider: str,
    body: dict[str, Any],
) -> dict[str, Any] | None:
    """Convert a provider-specific webhook payload through its adapter.

    Chains the provider adapter → Webhook Channel → canonical S4 payload::

        event = whatsapp_norm(body)           # WebhookEvent
        msg   = webhook_channel.receive(...)  # InboundChannelMessage
        norm  = webhook_channel.normalize(…)  # S4 job payload

    Args:
        registry: The :class:`ChannelRegistry` with a registered Webhook
                  channel.
        provider: One of ``"whatsapp"``, ``"slack"``, ``"github"``,
                  ``"jira"``.
        body:     The raw provider webhook POST body as a JSON-parsed dict.

    Returns:
        A canonical S4 job payload (``dict``) or ``None`` if the provider
        is unknown or the Webhook channel is not registered.

    Raises:
        KeyError: If *provider* is not in :data:`PROVIDER_MAP`.
    """
    if provider not in PROVIDER_MAP:
        raise KeyError(
            f"Unknown webhook provider '{provider}'. "
            f"Available: {list(PROVIDER_MAP)}"
        )

    try:
        channel = registry.get("webhook")
    except KeyError:
        return None

    event: WebhookEvent = PROVIDER_MAP[provider](body)
    msg: InboundChannelMessage = channel.receive({
        "source": event.source,
        "payload": event.payload,
        "sender": event.sender,
    })
    return channel.normalize(msg)


def submit_channel_input(
    registry: ChannelRegistry,
    channel_name: str,
    raw_input: Any,
    adapter: GatewayAgentAdapter | None = None,
    *,
    queue: Any = None,
    control_plane: Any = None,
) -> dict[str, Any]:
    """Channel input → normalise → hand off to S5 → return result.

    This is the **wired** version of :func:`process_channel_input`.  Instead
    of returning a plain dict, it normalises the input and hands off to S5
    via the provided ``GatewayAgentAdapter``.  Use this in application entry
    points (CLI, Web, WebSocket, …)::

        result = submit_channel_input(registry, "cli", {"text": "hello"}, adapter)
        # result == {"reply": "…", "metadata": {…}}

    Args:
        registry:      The :class:`ChannelRegistry` with registered adapters.
        channel_name:  Channel identifier (e.g. ``"cli"``, ``"web"``).
        raw_input:     Raw input from the transport layer.
        adapter:       The :class:`GatewayAgentAdapter` to hand off to S5.
                       If ``None``, returns the normalised payload dict only
                       (useful for testing/validation).
        queue:         **Deprecated** — kept for backward compatibility.
        control_plane: **Deprecated** — kept for backward compatibility.

    Returns:
        A dict with the S5 response (``reply``, ``metadata``) on success, or
        an error dict if the channel is not registered or the handoff fails.
    """
    payload = process_channel_input(registry, channel_name, raw_input)
    if payload is None:
        return {"error": f"Channel '{channel_name}' not available"}

    if adapter is None:
        return {"payload": payload, "channel": channel_name}

    # Build an AgentRequest from the normalised payload
    text = ""
    if isinstance(payload, dict):
        # Try common payload text keys
        text = str(
            payload.get("text")
            or payload.get("input")
            or payload.get("message")
            or payload.get("content", str(payload))
        )

    msg_metadata: dict[str, Any] = (
        payload.get("metadata", {}) if isinstance(payload, dict) else {}
    )

    request = AgentRequest(
        channel=channel_name,
        message_text=text,
        user_id=(
            msg_metadata.pop("user_id", None)
            or (payload.get("sender") if isinstance(payload, dict) else None)
            or msg_metadata.get("sender")  # CLI channel puts sender in metadata
        ),
        metadata=msg_metadata,
    )

    return adapter.ingest(request)
