"""Channel base — re-exported from Gateway.

.. note::
   The canonical implementation now lives in ``src.gateway.channels.base``.
   This module re-exports symbols so existing Platform consumers continue
   to work during the transition period.
"""

from src.gateway.channels.base import (  # noqa: F401
    Channel,
    InboundChannelMessage,
)
