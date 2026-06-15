"""Webhook Channel — re-exported from Gateway.

.. note::
   The canonical implementation now lives in ``src.gateway.channels.webhook``.
   This module re-exports symbols so existing Platform consumers continue
   to work during the transition period.
"""

from src.gateway.channels.webhook import (  # noqa: F401
    WebhookChannel,
    WebhookEvent,
    register_webhook_channel,
)
