"""DevSMTPTransport — pluggable SMTP-based email transport for local SMTP test services.

Sends email alerts to MailHog (``localhost:1025``), smtp4dev (``localhost:25``)
or any SMTP server via a configurable host/port.

This is a *development-only* transport. It bypasses DKIM, SPF, DMARC — no real
SMTP configuration is required. Point it at a running test SMTP service and go.
"""

from __future__ import annotations

import smtplib
import time
from dataclasses import dataclass
from email.mime.text import MIMEText
from typing import Any, Callable


@dataclass
class DevSMTPConfig:
    """Configuration for DevSMTPTransport.

    Attributes:
        host: SMTP server hostname (default ``localhost`` — MailHog default).
        port: SMTP server port (default ``1025`` — MailHog default).
        sender: Default ``From`` address for all alerts.
        timeout: SMTP connection timeout in seconds.
    """

    host: str = "localhost"
    port: int = 1025
    sender: str = "alerts@vai-core.local"
    timeout: float = 5.0


class DevSMTPTransport:
    """Pluggable transport that sends email alerts via a local SMTP test service.

    Typical usage::

        config = DevSMTPConfig(host="localhost", port=1025)
        transport = DevSMTPTransport(config)

        result = transport.send(
            to="admin@example.com",
            subject="System alert: disk 90% full",
            body="The /dev/sda1 partition is at 90% capacity.",
        )

    ``result`` is a dict with keys ``success``, ``status_code`` (or ``None``),
    ``recipient``, ``subject``, ``body_len``, and ``error`` (on failure).
    """

    def __init__(
        self,
        config: DevSMTPConfig,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._config = config
        self._clock = clock or time.time

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        sender: str | None = None,
    ) -> dict[str, Any]:
        """Deliver an email alert through the configured SMTP test service.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Plain-text email body.
            sender: Override the default ``From`` address.

        Returns:
            A result dict::

                {
                    "success": True,
                    "status_code": 250,
                    "recipient": "admin@example.com",
                    "subject": "...",
                    "body_len": 42,
                }
        """
        timestamp = self._clock()
        try:
            resolved_sender = sender or self._config.sender
            msg = MIMEText(body, _charset="utf-8")
            msg["From"] = resolved_sender
            msg["To"] = to
            msg["Subject"] = subject

            with smtplib.SMTP(
                host=self._config.host,
                port=self._config.port,
                timeout=self._config.timeout,
            ) as smtp:
                smtp.send_message(msg)

            return {
                "success": True,
                "status_code": 250,
                "recipient": to,
                "subject": subject,
                "body_len": len(body),
                "sent_at": timestamp,
            }
        except (smtplib.SMTPException, OSError) as exc:
            return {
                "success": False,
                "status_code": None,
                "recipient": to,
                "subject": subject,
                "body_len": len(body),
                "error": f"{type(exc).__name__}: {exc}",
                "sent_at": timestamp,
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def config(self) -> DevSMTPConfig:
        """Expose the underlying config for introspection."""
        return self._config
