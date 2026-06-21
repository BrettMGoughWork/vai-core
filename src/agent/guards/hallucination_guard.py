"""
Hallucination guard — detect LLM claims of side-effects without tool_calls.

If the LLM claims an action was performed (sent, deleted, drafted, etc.)
but the reply contains no ``/invoke-workflow`` directive, the claim is a
hallucination — return a safety message.
"""

from __future__ import annotations

import re

# ── Hallucination guard patterns ──────────────────────────────────────────
_ACTION_CLAIM_RE = re.compile(
    r"(?i)"
    r"(?:"
    # "I've sent", "I've replied", "I've deleted" etc.
    r"\bI'?ve\s+(?:sent|replied|deleted|forwarded|drafted|created|"
    r"cancelled|canceled|archived|moved|marked)"
    r"|"
    # "I sent your", "I replied to", etc.
    r"\bI\s+(?:sent|replied|deleted|forwarded|drafted|created)\s+"
    r"(?:your|the|this)"
    r"|"
    # "has been sent", "have been deleted", etc.
    r"\b(?:has been|have been)\s+(?:sent|deleted|forwarded|replied|"
    r"created|cancelled|canceled|archived)"
    r"|"
    # "sent your reply", "deleted the email", etc. — bare past-tense claim
    r"(?:sent|replied|deleted|forwarded|drafted)\s+(?:your|the|this)\s+"
    r"(?:reply|email|message|draft)"
    r")",
)


def apply_hallucination_guard(reply: str) -> str:
    """Detect and block LLM claims of side-effects without tool_calls.

    If the LLM claims an action was performed (sent, deleted, drafted, etc.)
    but the reply contains no ``/invoke-workflow`` directive, the claim is a
    hallucination — return a safety message.

    Returns the original *reply* when safe, or a guard message when a
    hallucination is detected.
    """
    if "/invoke-workflow" in reply:
        return reply  # directives present — legitimate execution path

    if _ACTION_CLAIM_RE.search(reply):
        return (
            "\u26a0\ufe0f **Safety guard triggered:** The assistant appeared to claim "
            "that an action was performed (e.g., sending, deleting, or "
            "forwarding) without issuing a tool_call or `/invoke-workflow` "
            "directive.\n\n"
            "**The action was NOT executed.**\n\n"
            "Please rephrase your request."
        )

    return reply
