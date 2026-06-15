"""Provider-specific webhook adapters for Stratum-4.

Each provider sub-package exports a ``normalize_webhook`` pure function
that transforms a raw provider POST payload into a
:class:`~src.gateway.channels.webhook.WebhookEvent`.

These adapters sit **outside** the generic Webhook Channel and are
responsible for isolating provider-specific quirks (field names, nesting,
metadata).  They are pure logic only — no IO, no FastAPI, no provider SDKs.
"""

from __future__ import annotations
