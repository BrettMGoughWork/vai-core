"""Web Channel — re-exported from Gateway.

.. note::
   The canonical implementation now lives in ``src.gateway.channels.web``.
   This module re-exports symbols so existing Platform consumers continue
   to work during the transition period.
"""

from src.gateway.channels.web import (  # noqa: F401
    WebChannel,
    WebRequest,
    WebResponse,
    register_web_channel,
)
