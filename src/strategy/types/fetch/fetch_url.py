"""
fetch_url — Public-facing fetch skill (PHASE 3.12.6).

This is the ONLY fetch interface exposed to the LLM.  All internal logic —
heuristics, domain policy, signals, fallback, mode escalation, request
hydration, and search fallback — is hidden behind this single entry-point.

Usage::

    from src.strategy.types.fetch import fetch_url, FetchResult

    result = fetch_url("https://example.com", executor=my_executor)
    if result.ok:
        print(result.body)
    else:
        print(result.error_type, result.error_message)

The LLM sees ONLY ``fetch_url(url, ...)``.  Internal modes, signals, fallback
logic, domain policy, and request chaining are NEVER exposed.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.strategy.types.validation import deadcode_ignore

from .domain_policy import interpret_domain_policy
from .mode_selector import FetchMode, ModeHistory, select_initial_mode
from .request import FetchRequest
from .response import FetchResponse
from .signal_extraction import extract_signals
from .signal_fallback import choose_next_mode

# ---------------------------------------------------------------------------
# Safety cap — prevents infinite escalation loops
# ---------------------------------------------------------------------------

_MAX_ITERATIONS = 10

# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@deadcode_ignore(reason="Public-facing return type for fetch_url, used via type annotation by LLM-facing code")
@dataclass(frozen=True)
class FetchResult:
    """Public-facing fetch result returned to the LLM.

    On success the error fields are ``None``; on failure the response fields
    are omitted (empty / ``None``).  This matches the output schema for the
    public ``fetch_url`` contract.
    """

    ok: bool
    status_code: int | None = None
    final_url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    elapsed_ms: int = 0
    error_type: str | None = None
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_url(
    url: str,
    *,
    timeout: float | None = None,
    headers: dict[str, str] | None = None,
    domain_policy: dict[str, dict[str, Any]] | None = None,
    history: ModeHistory | None = None,
    executor: Callable[[str, FetchRequest], FetchResponse],
) -> FetchResult:
    """Fetch *url*, transparently handling mode selection, fallback, and retries.

    This is the public-facing entry-point for PHASE 3.12's unified http_fetch
    orchestrator.  The LLM calls this with a URL and (optionally) a timeout
    and headers.  Everything else — mode heuristics, domain policy enforcement,
    signal extraction, and the multi-mode fallback chain — runs internally and
    is never exposed.

    Parameters
    ----------
    url:
        The target URL to fetch.
    timeout:
        Optional per-request timeout in seconds.  Internal modes have their
        own timeouts; this value is passed through to the fetch primitives.
    headers:
        Optional HTTP headers for the initial request.
    domain_policy:
        Runtime-supplied domain policy dict (see :mod:`.domain_policy`).
        ``None`` uses the default permissive policy.
    history:
        Aggregated success/failure counts per mode for the domain.  ``None``
        uses a blank history.
    executor:
        **Required.**  A callable ``(mode: str, request: FetchRequest) ->
        FetchResponse`` that dispatches to the actual fetch primitive for the
        given mode.  The orchestrator itself NEVER performs network I/O.

    Returns
    -------
    FetchResult
        A public-facing result with either ``ok=True`` (success) or
        ``ok=False`` (failure).  Internal metadata is never leaked.
    """
    # 1. Build initial FetchRequest ------------------------------------------
    request = FetchRequest(
        url=url,
        timeout=timeout,
        headers=dict(headers or {}),
    )

    # 2. Apply domain policy -------------------------------------------------
    policy = interpret_domain_policy(url, domain_policy)

    # 3. Denied domains — immediate failure ----------------------------------
    if policy.deny:
        return FetchResult(
            ok=False,
            error_type="DomainDeniedError",
            error_message=f"domain {policy.domain} is denied by policy",
        )

    # 4. Select initial mode -------------------------------------------------
    hist = history or ModeHistory()

    if policy.preferred_mode and policy.preferred_mode not in policy.forbidden_modes:
        current_mode: str = policy.preferred_mode
    else:
        current_mode = select_initial_mode(request, hist).mode

    # 5. Pipeline loop -------------------------------------------------------
    total_elapsed_ms = 0
    current_request = request

    for _iteration in range(1, _MAX_ITERATIONS + 1):
        # --- Rate-limit throttle ---
        if policy.rate_limit_ms > 0:
            time.sleep(policy.rate_limit_ms / 1000.0)

        # --- Execute current mode ---
        response = executor(current_mode, current_request)
        total_elapsed_ms += response.elapsed_ms

        # --- Success ---
        if response.ok:
            return FetchResult(
                ok=True,
                status_code=response.status_code,
                final_url=response.url or current_request.url,
                headers=dict(response.headers),
                cookies=dict(response.cookies),
                body=response.body,
                elapsed_ms=total_elapsed_ms,
            )

        # --- Failure → extract signals ---
        # extract_signals expects FetchMode, but "search" is handled
        # gracefully (script_timeout only fires for headless/stealth).
        signals = extract_signals(
            current_request,
            response,
            current_mode,  # type: ignore[arg-type]
            policy,
        )

        # --- Choose next mode (signal-driven fallback) ---
        decision = choose_next_mode(
            current_mode,  # type: ignore[arg-type]
            current_request,
            response,
            signals,
            policy,
            hist,
        )

        # --- Give up ---
        if decision.should_give_up:
            return FetchResult(
                ok=False,
                error_type=response.error_type or "FetchFailedError",
                error_message=response.error_message or decision.reasoning,
                elapsed_ms=total_elapsed_ms,
            )

        # --- Advance to next mode ---
        current_mode = decision.next_mode
        current_request = decision.next_request

    # 6. Exhausted — safety net ----------------------------------------------
    return FetchResult(
        ok=False,
        error_type="FetchExhaustedError",
        error_message=(
            f"all fetch modes exhausted after {_MAX_ITERATIONS} attempts"
        ),
        elapsed_ms=total_elapsed_ms,
    )
