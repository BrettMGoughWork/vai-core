"""Mail Channel — pure-logic email transport adapter for Stratum-4.

Accepts inbound parsed email payloads and normalises them into
:class:`InboundChannelMessage` objects.  Converts outbound S4 messages
into SMTP-compatible send payloads.  This slice is pure logic only: no
SMTP client, no IMAP, no MIME parsing, no network IO.

Integration testing requires an SMTP server (or a mock like ``smtpd``/
``aiosmtpd``) and an IMAP inbox for end-to-end receive tests.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from src.platform.runtime.channels.base import Channel, InboundChannelMessage
from src.platform.runtime.channels.registry import ChannelRegistry


class MailChannel(Channel):
    """Email transport adapter.

    Accepts parsed email payloads, converts them into canonical
    :class:`InboundChannelMessage` instances, normalises them into S4
    job payloads, and converts outbound payloads back into SMTP-compatible
    send dicts.

    Pure logic — no IO, no SMTP, no IMAP, no MIME parsing.

    Args:
        clock: A no-arg callable returning the current Unix timestamp
            (defaults to :func:`time.time`).  Inject a deterministic
            clock in tests.
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock if clock is not None else time.time

    # ------------------------------------------------------------------
    # Channel protocol
    # ------------------------------------------------------------------

    def receive(self, raw_input: Any) -> InboundChannelMessage:
        """Convert a parsed email payload into an :class:`InboundChannelMessage`.

        The expected input shape::

            {
                "from": "alice@example.com",     # sender email (required)
                "to": "bot@vai.example",         # recipient email (optional)
                "subject": "Deploy request",      # email subject (required)
                "body": "Please deploy staging",  # email body (required)
            }

        Args:
            raw_input: A ``dict`` with email fields.

        Returns:
            A canonical :class:`InboundChannelMessage` with
            ``channel="mail"``.

        Raises:
            TypeError: If *raw_input* is not a ``dict``.
            ValueError: If required fields are missing or invalid.
        """
        if not isinstance(raw_input, dict):
            raise TypeError(
                f"MailChannel.receive requires a dict, "
                f"got {type(raw_input).__name__}"
            )

        sender = raw_input.get("from")
        if not isinstance(sender, str) or not sender.strip():
            raise ValueError(
                "MailChannel.receive requires a 'from' field "
                "with a non-empty string"
            )

        subject = raw_input.get("subject")
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError(
                "MailChannel.receive requires a 'subject' field "
                "with a non-empty string"
            )

        body = raw_input.get("body")
        if not isinstance(body, str) or not body.strip():
            raise ValueError(
                "MailChannel.receive requires a 'body' field "
                "with a non-empty string"
            )

        to: str | None = raw_input.get("to")
        if to is not None and not isinstance(to, str):
            raise TypeError(
                f"MailChannel.receive 'to' must be a string or None, "
                f"got {type(to).__name__}"
            )

        payload: dict[str, Any] = {
            "from": sender,
            "to": to or "",
            "subject": subject,
            "body": body,
        }

        return InboundChannelMessage(
            channel="mail",
            sender=sender,
            payload=payload,
            timestamp=self._clock(),
        )

    def normalize(self, message: InboundChannelMessage) -> dict[str, Any]:
        """Normalise an :class:`InboundChannelMessage` into a canonical S4 job payload.

        Combines the email subject and body into the ``input`` field,
        preserving the original values in metadata.

        Returns:
            A dict::

                {
                    "input": ...,       # "subject: body" combined text
                    "metadata": {...},  # channel metadata
                }
        """
        subject = message.payload.get("subject", "")
        body = message.payload.get("body", "")
        raw_from = message.payload.get("from", "")
        raw_to = message.payload.get("to", "")

        # Use the full subject + body as the semantic input
        combined = f"{subject}: {body}" if subject else body

        return {
            "input": combined,
            "metadata": {
                "channel": message.channel,
                "sender": message.sender,
                "to": raw_to,
                "subject": subject,
            },
        }

    def send(self, message: dict[str, Any]) -> dict[str, Any]:
        """Convert an outbound S4 payload into an SMTP-compatible send dict.

        Returns:
            A dict::

                {
                    "to": ...,           # recipient email (from metadata or empty)
                    "subject": ...,      # response subject line
                    "body": ...,         # the response output
                    "metadata": {...},   # any additional metadata
                }
        """
        meta = message.get("metadata", {}) or {}
        to = meta.get("to", "") if isinstance(meta, dict) else ""
        subject = meta.get("subject", "Re: Your request") if isinstance(meta, dict) else "Re: Your request"

        return {
            "to": to,
            "subject": subject,
            "body": message.get("output", ""),
            "metadata": message.get("metadata", {}),
        }


# ------------------------------------------------------------------
# Convenience — register the default Mail channel
# ------------------------------------------------------------------


def register_mail_channel(
    registry: ChannelRegistry,
    clock: Callable[[], float] | None = None,
) -> None:
    """Register a :class:`MailChannel` in *registry* under the name ``"mail"``.

    This is a convenience helper for the composition root.

    Args:
        registry: The :class:`ChannelRegistry` to register into.
        clock:    Optional deterministic clock (see :class:`MailChannel`).
    """
    registry.register("mail", MailChannel(clock=clock))
