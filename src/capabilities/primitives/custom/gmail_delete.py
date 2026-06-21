"""
custom.gmail.delete — Delete / trash Gmail messages.

Supports:
- Trashing a single message (default — reversible)
- Permanently deleting a single message
- Trashing an entire thread
"""

from __future__ import annotations

from typing import Any

from src.capabilities.primitives.base import PrimitiveBase, PrimitiveResult, PrimitiveType
from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class GmailDeletePrimitive(PrimitiveBase):
    """Delete or trash Gmail messages."""

    name = "custom.gmail.delete"
    description = (
        "Trash or permanently delete a Gmail message or thread. "
        "By default messages are trashed (reversible). "
        "Set 'permanent: true' to bypass the trash and delete forever."
    )
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "email_id": {
                "type": "string",
                "description": "The Gmail message ID to delete/trash (also accepts 'message_id' or 'id')",
            },
            "thread_id": {
                "type": "string",
                "description": "If provided, the entire thread is trashed/deleted",
            },
            "permanent": {
                "type": "boolean",
                "description": "If true, permanently delete instead of trashing (default false — trash is reversible)",
            },
        },
        "required": [],
        "description": "Either 'email_id' or 'thread_id' is required.",
    }

    def validate_args(self, args: dict) -> None:
        email_id = args.get("email_id") or args.get("message_id") or args.get("id")
        thread_id = args.get("thread_id")
        if not email_id and not thread_id:
            raise ValueError(
                "Either 'email_id' (or 'message_id'/'id') or 'thread_id' is required"
            )

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        from src.capabilities.primitives.custom.gmail_client import gmail_client

        self.validate_args(args)

        email_id = (args.get("email_id") or args.get("message_id") or args.get("id") or "").strip()
        thread_id = (args.get("thread_id") or "").strip()
        permanent = bool(args.get("permanent", False))

        try:
            service = gmail_client(context=context)
        except Exception as exc:
            return PrimitiveResult(
                status="error",
                data={"error": str(exc)},
                error=str(exc),
            )

        method = "permanently delete" if permanent else "trash"

        try:
            target = f"thread {thread_id}" if thread_id else f"message {email_id}"

            if permanent:
                if thread_id:
                    # Delete all messages in the thread
                    thread = (
                        service.users()
                        .threads()
                        .get(userId="me", id=thread_id)
                        .execute()
                    )
                    deleted_ids = []
                    for msg in thread.get("messages", []):
                        service.users().messages().delete(
                            userId="me", id=msg["id"]
                        ).execute()
                        deleted_ids.append(msg["id"])

                    return PrimitiveResult(
                        status="success",
                        data={
                            "action": "permanently_deleted",
                            "target": target,
                            "message_ids": deleted_ids,
                            "count": len(deleted_ids),
                        },
                    )
                else:
                    service.users().messages().delete(
                        userId="me", id=email_id
                    ).execute()
                    return PrimitiveResult(
                        status="success",
                        data={
                            "action": "permanently_deleted",
                            "target": target,
                            "message_id": email_id,
                        },
                    )
            else:
                if thread_id:
                    service.users().threads().trash(
                        userId="me", id=thread_id
                    ).execute()
                else:
                    service.users().messages().trash(
                        userId="me", id=email_id
                    ).execute()

                return PrimitiveResult(
                    status="success",
                    data={
                        "action": "trashed",
                        "target": target,
                    },
                )

        except Exception as exc:
            return PrimitiveResult(
                status="error",
                data={
                    "action": method,
                    "target": target,
                    "error": str(exc),
                },
                error=str(exc),
            )
