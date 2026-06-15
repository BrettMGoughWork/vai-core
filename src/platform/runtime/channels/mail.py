"""Mail Channel — re-exported from Gateway.

.. note::
   The canonical implementation now lives in ``src.gateway.channels.mail``.
   This module re-exports symbols so existing Platform consumers continue
   to work during the transition period.
"""

from src.gateway.channels.mail import (  # noqa: F401
    MailChannel,
    register_mail_channel,
)
