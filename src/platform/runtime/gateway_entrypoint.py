"""Gateway entrypoint — converts external input to S4 Jobs and enqueues them.

This module provides the channel abstraction pipeline::

    # Pure channel logic (returns a dict — use for testing/validation)
    payload = process_channel_input(registry, channel_name, raw_input)

    # Wired through to a real Job (creates Job, pushes to queue — use in apps)
    result = submit_channel_input(registry, channel_name, raw_input, queue)

It also provides convenience wrappers for each transport channel (web,
WebSocket, webhook) and a :func:`handle_provider_webhook` function that
chains a provider-specific adapter → webhook channel → canonical payload.

No networking or framework code lives here.
"""

from __future__ import annotations

from typing import Any

from src.platform.runtime.channels.base import InboundChannelMessage
from src.platform.runtime.channels.registry import ChannelRegistry
from src.platform.runtime.channels.webhook import WebhookEvent
from src.platform.runtime.providers.whatsapp.adapter import (
    normalize_webhook as whatsapp_norm,
)
from src.platform.runtime.providers.slack.adapter import (
    normalize_webhook as slack_norm,
)
from src.platform.runtime.providers.github.adapter import (
    normalize_webhook as github_norm,
)
from src.platform.runtime.providers.jira.adapter import (
    normalize_webhook as jira_norm,
)
from src.platform.queue.queue import Queue


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
    queue: Queue,
    control_plane: Any | None = None,
) -> dict[str, Any]:
    """Channel input → create Job → push to queue → return job info.

    This is the **wired** version of :func:`process_channel_input`.  Instead
    of returning a plain dict, it creates an S4 ``Job``, registers it with
    the control plane, and pushes it onto the queue so a worker can pick it
    up.  Use this in application entry points (CLI, Web, WebSocket, …)::

        result = submit_channel_input(registry, "cli", {"text": "hello"}, queue)
        # result == {"job_id": "…", "state": "pending", "channel": "cli"}

    Args:
        registry:      The :class:`ChannelRegistry` with registered adapters.
        channel_name:  Channel identifier (e.g. ``"cli"``, ``"web"``).
        raw_input:     Raw input from the transport layer.
        queue:         Queue backend to push the job onto.
        control_plane: Optional :class:`ControlPlane`.  Uses the module-level
                       singleton if not given.

    Returns:
        A dict with ``job_id``, ``state``, and ``channel`` on success, or
        an error dict if the channel is not registered.

    Raises:
        ValueError: If the normalized payload cannot be converted to a
                    ``ChannelMessage``.
    """
    from src.platform.observability.logging import log_job_created
    from src.platform.runtime import create_job
    from src.platform.runtime.control_plane import (
        control_plane as _default_cp,
    )
    from src.platform.transport.normalization import ChannelMessage

    cp = control_plane or _default_cp

    payload = process_channel_input(registry, channel_name, raw_input)
    if payload is None:
        return {"error": f"Channel '{channel_name}' not available"}

    msg = ChannelMessage(input=payload, metadata={}, channel=channel_name)
    job = create_job(msg)
    cp.register_job(job)
    log_job_created(job)
    queue.push(job)

    return {
        "job_id": job.job_id,
        "state": job.state.value,
        "channel": channel_name,
    }
