"""
custom.gmail_search — Search Gmail messages with LLM-friendly parameters.

Designed so an LLM can intuitively navigate an inbox:
- Free-form ``query`` supports full Gmail search syntax
- Convenience shortcuts ``subject``, ``from_``, ``to_`` build the query for you
- ``max_results`` controls how many results to return (default 10, max 50)
- ``sort_by`` controls ordering (default newest-first)
- Results include both sender name and envelope email address
"""

from __future__ import annotations

from typing import Any

from src.capabilities.primitives.base import PrimitiveBase, PrimitiveResult, PrimitiveType
from src.domain._markers import deadcode_ignore

# Gmail client is imported lazily inside execute() so the module
# loads even when the Google SDK is not installed.


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class GmailSearchPrimitive(PrimitiveBase):
    """Search Gmail messages and return a summary of each result."""

    name = "custom.gmail.search"
    description = (
        "Search Gmail messages by sender, subject, content, or date. "
        "Returns a list of message summaries with sender name, email address, "
        "subject, date, and a content snippet so you can decide which message(s) "
        "to read in full or act on."
    )
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Full Gmail search syntax query (e.g. 'has:attachment after:2024/01/01')",
            },
            "subject": {
                "type": "string",
                "description": "Search by subject line keywords",
            },
            "from_": {
                "type": "string",
                "description": "Sender email address or display name",
            },
            "to_": {
                "type": "string",
                "description": "Recipient email address or display name",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (1-50, default 10). "
                "Infer from the user's request: 'most recent email' → 1, "
                "'last few/recent emails' → 5, 'recent emails/inbox' → 10.",
            },
            "sort_by": {
                "type": "string",
                "enum": ["date_desc", "date_asc"],
                "description": "Sort order — newest first or oldest first (default date_desc)",
            },
            "include_snippets": {
                "type": "boolean",
                "description": "Include a content snippet for each result (default true)",
            },
        },
        "required": ["query"],
    }

    def evaluate_args(self, args: dict) -> dict:
        """Normalise & fill defaults so the LLM gets back a predictable schema."""
        return {
            "query": args.get("query", ""),
            "subject": args.get("subject", ""),
            "from_": args.get("from_", args.get("from", "")),
            "to_": args.get("to_", args.get("to", "")),
            "max_results": min(int(args.get("max_results", 10)), 50),
            "sort_by": args.get("sort_by", "date_desc"),
            "include_snippets": bool(args.get("include_snippets", True)),
        }

    def validate_args(self, args: dict) -> None:
        normalized = self.evaluate_args(args)
        if normalized["max_results"] < 1:
            raise ValueError("'max_results' must be >= 1")
        if normalized["sort_by"] not in ("date_desc", "date_asc"):
            raise ValueError(f"'sort_by' must be 'date_desc' or 'date_asc', got {normalized['sort_by']!r}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        from src.capabilities.primitives.custom.gmail_client import gmail_client

        self.validate_args(args)
        normalized = self.evaluate_args(args)

        try:
            service = gmail_client(context=context)
        except Exception as exc:
            return PrimitiveResult(
                status="error",
                data={"messages": [], "error": str(exc)},
                error=str(exc),
            )

        # Build Gmail search query
        query_parts = []
        if normalized["query"]:
            query_parts.append(normalized["query"])
        if normalized["subject"]:
            query_parts.append(f"subject:({normalized['subject']})")
        if normalized["from_"]:
            query_parts.append(f"from:({normalized['from_']})")
        if normalized["to_"]:
            query_parts.append(f"to:({normalized['to_']})")

        query_string = " ".join(query_parts)
        sort_order = normalized["sort_by"]
        max_results = normalized["max_results"]
        include_snippets = normalized["include_snippets"]

        try:
            # Fetch message list
            resp = (
                service.users()
                .messages()
                .list(
                    userId="me",
                    q=query_string,
                    maxResults=max_results,
                )
                .execute()
            )

            messages_raw = resp.get("messages", [])
            if not messages_raw:
                return PrimitiveResult(
                    status="success",
                    data={
                        "messages": [],
                        "total_estimate": 0,
                        "query": query_string or "(all inbox)",
                    },
                )

            # Fetch details for each message
            messages = []
            for msg in messages_raw[:max_results]:
                details = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg["id"], format="metadata")
                    .execute()
                )

                headers = _headers_dict(details)
                msg_id = details["id"]
                thread_id = details.get("threadId", msg_id)

                entry = {
                    "id": msg_id,
                    "thread_id": thread_id,
                    "from": headers.get("From", ""),
                    "from_email": _extract_email(headers.get("From", "")),
                    "to": headers.get("To", ""),
                    "subject": headers.get("Subject", "(no subject)"),
                    "date": headers.get("Date", ""),
                    "labels": details.get("labelIds", []),
                }

                if include_snippets:
                    entry["snippet"] = details.get("snippet", "")

                messages.append(entry)

            return PrimitiveResult(
                status="success",
                data={
                    "messages": messages,
                    "total_estimate": resp.get("resultSizeEstimate", len(messages)),
                    "query": query_string or "(all inbox)",
                },
            )

        except Exception as exc:
            return PrimitiveResult(
                status="error",
                data={"messages": [], "query": query_string, "error": str(exc)},
                error=str(exc),
            )


# ── helpers ───────────────────────────────────────────────────────────────


def _headers_dict(msg: dict) -> dict[str, str]:
    """Extract ``headers`` from a Gmail API message into a flat dict."""
    result: dict[str, str] = {}
    for hdr in msg.get("payload", {}).get("headers", []):
        name = hdr.get("name", "")
        value = hdr.get("value", "")
        if name and value:
            result[name] = value
    return result


def _extract_email(from_header: str) -> str:
    """Extract the email address from a ``"Name <email>"`` header value."""
    if "<" in from_header and ">" in from_header:
        start = from_header.index("<") + 1
        end = from_header.index(">")
        return from_header[start:end]
    return from_header.strip()
