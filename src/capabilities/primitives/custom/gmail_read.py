"""
custom.gmail_read — Read full email content from Gmail.

Returns the complete email including body text, HTML, headers, and
attachment metadata.  Designed so an LLM can easily extract quoted
reply context and decide on next actions.
"""

from __future__ import annotations

import base64
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase, PrimitiveResult, PrimitiveType
from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class GmailReadPrimitive(PrimitiveBase):
    """Read the full content of a Gmail message by ID."""

    name = "custom.gmail.read"
    description = (
        "Read the full content of a Gmail message by its message ID. "
        "Returns the sender, recipients, subject, date, body text, "
        "and any attachment metadata so you can process or reply to it."
    )
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "email_id": {
                "type": "string",
                "description": "The Gmail message ID to read (also accepts 'message_id' or 'id')",
            },
            "format": {
                "type": "string",
                "enum": ["full", "metadata", "minimal"],
                "description": "Format to read — 'full' (default) includes body text, 'metadata' just headers, 'minimal' raw",
            },
        },
        "required": ["email_id"],
    }

    def validate_args(self, args: dict) -> None:
        email_id = args.get("email_id") or args.get("message_id") or args.get("id")
        if not email_id or not isinstance(email_id, str) or not email_id.strip():
            raise ValueError(
                "A message identifier is required — pass 'email_id' (the Gmail message ID)"
            )

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        from src.capabilities.primitives.custom.gmail_client import gmail_client

        self.validate_args(args)

        email_id = (args.get("email_id") or args.get("message_id") or args.get("id")).strip()
        fmt = args.get("format", "full")  # 'full' | 'metadata' | 'minimal'

        try:
            service = gmail_client(context=context)
        except Exception as exc:
            return PrimitiveResult(
                status="error",
                data={"error": str(exc)},
                error=str(exc),
            )

        try:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=email_id, format=fmt)
                .execute()
            )

            headers = _headers_dict(msg)
            body_text, body_html = _extract_body(msg)

            result: dict[str, Any] = {
                "id": msg["id"],
                "thread_id": msg.get("threadId", msg["id"]),
                "from": headers.get("From", ""),
                "from_email": _extract_email(headers.get("From", "")),
                "to": headers.get("To", ""),
                "cc": headers.get("Cc", ""),
                "subject": headers.get("Subject", "(no subject)"),
                "date": headers.get("Date", ""),
                "labels": msg.get("labelIds", []),
                "body_text": body_text,
            }

            if body_html:
                result["body_html"] = body_html[:50000]  # cap to avoid token explosion

            # Attachment metadata
            attachments = _extract_attachments(msg, service, email_id)
            if attachments:
                result["attachments"] = attachments

            # Key reply headers for threading
            result["message_id_header"] = headers.get("Message-ID", "")
            result["references"] = headers.get("References", "")
            result["in_reply_to"] = headers.get("In-Reply-To", "")

            # Internal date timestamp (milliseconds since epoch)
            result["internal_date"] = msg.get("internalDate", "")

            return PrimitiveResult(status="success", data=result)

        except Exception as exc:
            return PrimitiveResult(
                status="error",
                data={"error": str(exc), "email_id": email_id},
                error=str(exc),
            )


# ── helpers ───────────────────────────────────────────────────────────────


def _headers_dict(msg: dict) -> dict[str, str]:
    """Extract headers from a Gmail API message."""
    result: dict[str, str] = {}
    for hdr in msg.get("payload", {}).get("headers", []):
        name = hdr.get("name", "")
        value = hdr.get("value", "")
        if name and value:
            result[name] = value
    return result


def _extract_email(from_header: str) -> str:
    if "<" in from_header and ">" in from_header:
        start = from_header.index("<") + 1
        end = from_header.index(">")
        return from_header[start:end]
    return from_header.strip()


def _extract_body(msg: dict) -> tuple[str, str]:
    """Recursively extract plain-text and HTML body from a Gmail message."""
    body_text = ""
    body_html = ""
    payload = msg.get("payload", {})

    # Check top-level body first
    _extract_from_part(payload, body_text_store := [], body_html_store := [])

    body_text = " ".join(body_text_store)
    body_html = " ".join(body_html_store)

    return body_text, body_html


def _extract_from_part(
    part: dict,
    text_store: list[str],
    html_store: list[str],
) -> None:
    """Recursively walk MIME parts extracting body content."""
    mime_type = part.get("mimeType", "")

    if mime_type == "text/plain":
        data = part.get("body", {}).get("data", "")
        if data:
            text_store.append(_decode_base64(data))
    elif mime_type == "text/html":
        data = part.get("body", {}).get("data", "")
        if data:
            html_store.append(_decode_base64(data))

    # Recurse into nested parts
    for subpart in part.get("parts", []):
        _extract_from_part(subpart, text_store, html_store)


def _decode_base64(data: str) -> str:
    """Decode a base64url-encoded string."""
    try:
        padded = data + "=" * (4 - len(data) % 4)
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_attachments(
    msg: dict,
    service: Any,
    msg_id: str,
) -> list[dict]:
    """Extract attachment metadata from a message."""
    attachments: list[dict] = []

    def _walk(part: dict) -> None:
        if part.get("filename") and part.get("body", {}).get("attachmentId"):
            attachments.append({
                "filename": part["filename"],
                "mime_type": part.get("mimeType", ""),
                "size_bytes": part.get("body", {}).get("size", 0),
                "attachment_id": part["body"]["attachmentId"],
                # Download endpoint: users.messages.attachments().get()
            })
        for sub in part.get("parts", []):
            _walk(sub)

    _walk(msg.get("payload", {}))
    return attachments
