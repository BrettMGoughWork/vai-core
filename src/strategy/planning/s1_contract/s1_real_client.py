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
from pathlib import Path
from typing import Optional

import yaml

from src.strategy.planning.s1_contract.s1_prompt_builder import build_llm_prompt
from src.strategy.planning.s1_contract.types import PromptRequest


# ══════════════════════════════════════════════════════════════════════════════
# Kill‑switch — driven by config.yaml:enable_real_llm
# ══════════════════════════════════════════════════════════════════════════════

_ENABLE_REAL_LLM_BY_CONFIG: bool = False
"""Read ``enable_real_llm`` from ``config.yaml`` at module load time."""
try:
    _config_path = Path("config/config.yaml")
    if _config_path.exists():
        with open(_config_path) as _f:
            _raw = yaml.safe_load(_f)
        _ENABLE_REAL_LLM_BY_CONFIG = bool(_raw.get("enable_real_llm", False))
except Exception:
    _ENABLE_REAL_LLM_BY_CONFIG = False

ENABLE_REAL_LLM: bool = _ENABLE_REAL_LLM_BY_CONFIG
"""Master kill-switch.

Reads ``config.yaml:enable_real_llm`` at module load time (default ``False``).
Set to ``True`` only when all readiness checks pass (Phase 2.14.6).
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
    """Convert the structured prompt builder output into a string for the LLM.

    The prompt builder (s1_prompt_builder.build_llm_prompt) returns a dict
    with keys: system_instruction, response_schema, context, valid_examples,
    invalid_examples.  This function serialises that dict into a single
    plain-text prompt that the LLM transport can consume as a user message.
    """
    import json

    parts: list[str] = []

    # 1. System instruction (the rules the LLM must follow)
    system = prompt_payload.get("system_instruction", "")
    if system:
        parts.append(system)

    # 2. Response schema (what the LLM must output)
    schema = prompt_payload.get("response_schema", {})
    if schema:
        parts.append("JSON SCHEMA you MUST follow:\n" + json.dumps(schema, indent=2))

    # 3. Execution context (plan_context, memory, tool_context, instruction)
    context = prompt_payload.get("context", {})
    if context:
        parts.append("EXECUTION CONTEXT:\n" + json.dumps(context, indent=2))

    # 4. Valid examples (what a correct response looks like)
    valid_examples = prompt_payload.get("valid_examples", [])
    if valid_examples:
        lines = ["VALID RESPONSE EXAMPLES:"]
        for ex in valid_examples:
            label = ex.get("label", "Example")
            response = ex.get("response", {})
            lines.append(f"\n  [{label}]")
            lines.append(f"  {json.dumps(response, indent=2)}")
        parts.append("\n".join(lines))

    # 5. Invalid examples (what NOT to do)
    invalid_examples = prompt_payload.get("invalid_examples", [])
    if invalid_examples:
        lines = ["INVALID RESPONSE EXAMPLES (do NOT do this):"]
        for ex in invalid_examples:
            label = ex.get("label", "Example")
            why = ex.get("why_invalid", "")
            lines.append(f"\n  [{label}]")
            lines.append(f"  Why invalid: {why}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def _call_provider(prompt_text: str) -> str:
    """Send the prompt to the configured LLM provider and return raw text.

    Uses the existing LLM infrastructure from ``src.strategy.llm`` so all
    providers (OpenAI, Anthropic, Gemini, DeepSeek, Qwen, Mistral) are
    supported through a single code path.
    """
    from src.strategy.planning.s1_contract.s1_client import _get_llm_transport

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
