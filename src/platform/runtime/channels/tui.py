"""TUI Channel — re-exported from Gateway.

.. note::
   The canonical implementation now lives in ``src.gateway.channels.tui``.
   This module re-exports symbols so existing Platform consumers continue
   to work during the transition period.
"""

from src.gateway.channels.tui import (  # noqa: F401
    TUIChannel,
    TUIPanel,
    TUIScreen,
    TUIStatusBar,
    register_tui_channel,
)
