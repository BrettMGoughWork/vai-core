"""Channel registry — re-exported from Gateway.

.. note::
   The canonical implementation now lives in ``src.gateway.channels.registry``.
   This module re-exports symbols so existing Platform consumers continue
   to work during the transition period.
"""

from src.gateway.channels.registry import ChannelRegistry  # noqa: F401
