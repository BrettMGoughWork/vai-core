"""
custom.gmail.send — Send or draft Gmail messages from the LLM.

Designed so an LLM can:
- Reply to an existing thread (thread-aware, correct quoting)
- Send a new email (to, subject, body)
- Save a draft (instead of sending)

The caller must pass the authentication-scoped Gmail service.
"""

from __future__ import annotations

import base64
from typing import Any
from email.mime.text import MIMEText

from src.capabilities.primitives.base import PrimitiveBase, PrimitiveResult, PrimitiveType
from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class GmailSendPrimitive(PrimitiveBase):
    """Send, reply, or draft Gmail messages."""

    name = "custom.gmail.send"
    description = (
        "Send a new email or reply to an existing thread in Gmail. "
        "Use 'to' + 'subject' + 'body' for a new message, or "
        "'reply_to_email_id' + 'reply_body' to reply to an existing thread "
        "(the subject, to, and cc are automatically populated from the original). "
        "Set 'draft_only: true' to save a draft without sending."
    )
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "Recipient email address(es), comma-separated (not needed for replies)",
            },
            "subject": {
                "type": "string",
                "description": "Email subject line (not needed for replies — inherited from original)",
            },
            "body": {
                "type": "string",
                "description": "Plain-text body content of the email",
            },
            "cc": {
                "type": "string",
                "description": "CC recipient(s), comma-separated",
            },
            "reply_to_email_id": {
                "type": "string",
                "description": "If replying to an existing email, pass the email/message ID here; "
                "the to/subject/cc will be auto-populated from the original",
            },
            "reply_body": {
                "type": "string",
                "description": "Body content when replying to an existing email; if omitted, 'body' is used",
            },
            "draft_only": {
                "type": "boolean",
                "description": "If true, save as a draft instead of sending (default false)",
            },
        },
        "required": [],
    }

    def validate_args(self, args: dict) -> None:
        is_reply = bool(args.get("reply_to_email_id"))
        has_body = bool(args.get("body") or args.get("reply_body"))

        if is_reply:
            if not has_body:
                raise ValueError("A reply needs body content — use 'reply_body' or 'body'")
        else:
            if not args.get("to"):
                raise ValueError("'to' is required for new emails")
            if not args.get("subject"):
                raise ValueError("'subject' is required for new emails")
            if not has_body:
                raise ValueError("'body' is required")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        from src.capabilities.primitives.custom.gmail_client import gmail_client

        self.validate_args(args)

        try:
            service = gmail_client(context=context)
        except Exception as exc:
            return PrimitiveResult(
                status="error",
                data={"error": str(exc)},
                error=str(exc),
            )

        is_reply = bool(args.get("reply_to_email_id"))
        draft_only = bool(args.get("draft_only", False))
        action = "draft" if draft_only else "send"

        try:
            if is_reply:
                result = self._send_reply(service, args, draft_only)
            else:
                result = self._send_new(service, args, draft_only)
            return PrimitiveResult(status="success", data={"action": action, **result})
        except Exception as exc:
            return PrimitiveResult(
                status="error",
                data={"action": action, "error": str(exc)},
                error=str(exc),
            )

    # ── private helpers ──────────────────────────────────────────────────

    @staticmethod
    def _send_new(
        service: Any,
        args: dict,
        draft_only: bool,
    ) -> dict:
        """Compose and send/draft a brand-new email."""
        to = args["to"]
        subject = args.get("subject", "(no subject)")
        body = args.get("body", args.get("reply_body", ""))
        cc = args.get("cc", "")

        mime_msg = MIMEText(body, "plain")
        mime_msg["To"] = to
        mime_msg["Subject"] = subject
        if cc:
            mime_msg["Cc"] = cc

        raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")
        body_payload = {"raw": raw}

        return _execute_send(service, body_payload, draft_only)

    @staticmethod
    def _send_reply(
        service: Any,
        args: dict,
        draft_only: bool,
    ) -> dict:
        """Reply to an existing thread, inheriting subject/recipients."""
        email_id = args["reply_to_email_id"]

        # Fetch original message to get threading info
        original = (
            service.users()
            .messages()
            .get(userId="me", id=email_id, format="metadata")
            .execute()
        )

        headers: dict[str, str] = {}
        for hdr in original.get("payload", {}).get("headers", []):
            name = hdr.get("name", "")
            val = hdr.get("value", "")
            if name and val:
                headers[name] = val

        subject = headers.get("Subject", "(no subject)")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        to = headers.get("From", "")
        cc = args.get("cc", headers.get("Cc", ""))
        body = args.get("reply_body", args.get("body", ""))
        thread_id = original.get("threadId", email_id)

        mime_msg = MIMEText(body, "plain")
        mime_msg["To"] = to
        mime_msg["Subject"] = subject
        if cc:
            mime_msg["Cc"] = cc
        mime_msg["References"] = headers.get("Message-ID", "")
        mime_msg["In-Reply-To"] = headers.get("Message-ID", "")

        raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")
        body_payload = {"raw": raw, "threadId": thread_id}

        result = _execute_send(service, body_payload, draft_only)
        result["thread_id"] = thread_id
        result["reply_to"] = email_id
        return result


def _execute_send(service: Any, body_payload: dict, draft_only: bool) -> dict:
    """Execute the Gmail API send or draft call."""
    if draft_only:
        created = service.users().drafts().create(userId="me", body=body_payload).execute()
        return {"draft_id": created.get("id", ""), "status": "draft_saved"}
    else:
        sent = service.users().messages().send(userId="me", body=body_payload).execute()
        return {
            "message_id": sent.get("id", ""),
            "thread_id": sent.get("threadId", ""),
            "status": "sent",
        }
