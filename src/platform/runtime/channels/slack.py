"""Slack Channel — re-exported from Gateway.

.. note::
   The canonical implementation now lives in ``src.gateway.channels.slack``.
   This module re-exports symbols so existing Platform consumers continue
   to work during the transition period.
"""

from src.gateway.channels.slack import (  # noqa: F401
    SlackChannel,
    register_slack_channel,
)
