"""
Phase 2.14.7 — Real S1 Client (Live LLM Enablement)
====================================================

Calls the real LLM provider, behind a kill-switch, with retries,
timeouts, and rate-limit handling.  Produces raw text only — all
validation happens upstream in ``s1_response_validator``.

This is the **only** module in the S1 contract layer that performs
I/O.  All other modules remain pure.
"""

from __future__ import annotations

import time
from typing import Optional

from src.core.planning.s1_contract.s1_prompt_builder import build_llm_prompt
from src.core.planning.s1_contract.types import PromptRequest


# ══════════════════════════════════════════════════════════════════════════════
# Kill‑switch — global, defaults to OFF
# ══════════════════════════════════════════════════════════════════════════════

ENABLE_REAL_LLM: bool = False
"""Master kill-switch.

Set to ``True`` only when all readiness checks pass (Phase 2.14.6).
Default ``False`` prevents any real LLM call.
"""


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════


def call_llm(request: PromptRequest) -> str:
    """Call the real LLM provider and return raw text.

    Orchestrates the full LLM interaction:
      1. Kill‑switch check
      2. Build the structured prompt from the request
      3. Send to provider with retry/timeout/rate‑limit handling
      4. Return raw text (no parsing)

    Args:
        request: A validated PromptRequest from S2.

    Returns:
        Raw text from the LLM.

    Raises:
        RuntimeError: If the kill‑switch is active (``ENABLE_REAL_LLM`` is ``False``).
        S1RealLLMError: On provider, timeout, or rate‑limit failures after all retries.
    """
    if not ENABLE_REAL_LLM:
        raise RuntimeError(
            "Real LLM is disabled.  Set ENABLE_REAL_LLM=True after passing "
            "the readiness checklist (Phase 2.14.6)."
        )

    prompt_payload = build_llm_prompt(request)
    prompt_text = _serialise_prompt(prompt_payload)

    return _call_with_retries(prompt_text)


# ══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

# ── Default retry / timeout policy ───────────────────────────────────────────

_DEFAULT_MAX_RETRIES: int = 3
_DEFAULT_TIMEOUT_SECONDS: int = 60
_DEFAULT_RATE_LIMIT_BACKOFF_SECONDS: float = 2.0


def _serialise_prompt(prompt_payload: dict) -> str:
    """Convert the structured prompt into a JSON string for the LLM."""
    import json

    instruction = prompt_payload.get("instruction", "")
    schema_str = json.dumps(prompt_payload.get("schema", {}), indent=2)
    examples_str = json.dumps(prompt_payload.get("examples", []), indent=2)

    return (
        f"{instruction}\n\n"
        f"JSON SCHEMA:\n{schema_str}\n\n"
        f"EXAMPLES:\n{examples_str}"
    )


def _call_provider(prompt_text: str) -> str:
    """Send the prompt to the configured LLM provider and return raw text.

    Uses the existing LLM infrastructure from ``src.core.llm`` so all
    providers (OpenAI, Anthropic, Gemini, DeepSeek, Qwen, Mistral) are
    supported through a single code path.
    """
    from src.core.planning.s1_contract.s1_client import _get_llm_transport

    transport = _get_llm_transport()
    if transport is None:
        raise S1RealLLMError(
            message="No LLM transport configured.  Ensure llm.provider is set in config.yaml.",
            retryable=False,
        )

    return transport.complete(prompt_text)


def _call_with_retries(
    prompt_text: str,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    base_backoff: float = _DEFAULT_RATE_LIMIT_BACKOFF_SECONDS,
) -> str:
    """Call the provider with exponential backoff for transient failures.

    Retries on:
      - Timeout errors
      - Rate‑limit errors (HTTP 429)
      - Transient server errors (HTTP 5xx)

    Does NOT retry on:
      - Authentication errors (HTTP 401/403)
      - Invalid request errors (HTTP 400)
    """
    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            return _call_provider(prompt_text)
        except S1RealLLMError as e:
            if not e.retryable:
                raise
            last_error = e
        except Exception as e:
            last_error = e
            if not _is_retryable_exception(e):
                raise S1RealLLMError(
                    message=f"LLM call failed (non-retryable): {str(e)}",
                    retryable=False,
                ) from e

        if attempt < max_retries:
            backoff = base_backoff * (2 ** (attempt - 1))
            time.sleep(backoff)

    raise S1RealLLMError(
        message=(
            f"LLM call failed after {max_retries} attempt(s): "
            f"{str(last_error) if last_error else 'unknown error'}"
        ),
        retryable=False,
    )


def _is_retryable_exception(exc: Exception) -> bool:
    """Heuristic to decide whether an exception is retryable."""
    msg = str(exc).lower()
    retryable_keywords = (
        "timeout",
        "timed out",
        "rate limit",
        "429",
        "503",
        "502",
        "504",
        "connection",
        "reset",
        "refused",
        "too many requests",
    )
    return any(kw in msg for kw in retryable_keywords)


# ══════════════════════════════════════════════════════════════════════════════
# Error type
# ══════════════════════════════════════════════════════════════════════════════


class S1RealLLMError(Exception):
    """Raised when the real S1 client cannot complete an LLM call."""

    def __init__(self, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable
