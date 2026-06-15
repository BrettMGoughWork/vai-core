"""CLI Channel — re-exported from Gateway.

.. note::
   The canonical implementation now lives in ``src.gateway.channels.cli``.
   This module re-exports symbols so existing Platform consumers continue
   to work during the transition period.
"""

from src.gateway.channels.cli import (  # noqa: F401
    CLIChannel,
    CLITUI,
    register_cli_channel,
)
