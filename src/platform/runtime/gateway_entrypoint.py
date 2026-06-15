"""Gateway entrypoint — re-exported from Gateway.

.. note::
   The canonical implementation now lives in ``src.gateway.entrypoint``.
   This module re-exports symbols so existing Platform consumers continue
   to work during the transition period.
"""

from src.gateway.entrypoint import (  # noqa: F401
    PROVIDER_MAP,
    handle_mail_message,
    handle_provider_webhook,
    handle_slack_event,
    handle_web_request,
    handle_webhook_post,
    handle_ws_message,
    process_channel_input,
    submit_channel_input,
)
