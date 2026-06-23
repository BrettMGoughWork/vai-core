"""
Signal-Driven Fallback Router — PHASE 3.12.5

Pure-logic component invoked AFTER signal extraction (PHASE 3.12.4) and
BEFORE the next fetch attempt.  Given the failed attempt's mode, request,
response, signals, domain policy, and history, it chooses the NEXT mode
using a signal-driven decision model.

It does NOT:
- Perform any network I/O
- Extract signals
- Modify the response
- Perform the actual fetch

Those behaviours belong to other phases of the orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.domain._markers import deadcode_ignore

from .domain_policy import DomainPolicy
from .mode_selector import FetchMode, ModeHistory
from .request import FetchRequest
from .response import FetchResponse
from .signal_extraction import FetchSignals

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

SignalFallbackDestination = Literal[
    "http_simple",
    "http_hardened",
    "http_headless_browser",
    "http_stealth",
    "search",
    "give_up",
]

# ---------------------------------------------------------------------------
# Mode escalation chain (strict order, used when no signal-specific rule fires)
# ---------------------------------------------------------------------------

_ESCALATION_CHAIN: dict[
    FetchMode | Literal["search"], SignalFallbackDestination
] = {
    "http_simple": "http_hardened",
    "http_hardened": "http_headless_browser",
    "http_headless_browser": "http_stealth",
    "http_stealth": "search",
    "search": "give_up",
}

# ---------------------------------------------------------------------------
# Mode-specific timeouts (in seconds)
# ---------------------------------------------------------------------------

_MODE_TIMEOUTS: dict[SignalFallbackDestination, int] = {
    "http_simple": 10,
    "http_hardened": 15,
    "http_headless_browser": 30,
    "http_stealth": 45,
    "search": 10,
    "give_up": 0,
}

_HARD_FAILURE_ERROR_TYPES: frozenset[str] = frozenset({
    "NetworkError",
    "TimeoutError",
    "DNSFailure",
})

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@deadcode_ignore(reason="Return type for choose_next_mode, used via type annotation in fetch orchestrator")
@dataclass(frozen=True)
class FallbackDecision:
    """The result of running the signal-driven fallback router.

    Attributes:
        next_mode: The next mode to attempt, ``"search"``, or ``"give_up"``.
        timeout_seconds: The timeout to use for the next attempt.
        next_request: The hydrated request ready for the next attempt.
        reasoning: A short human-readable explanation of the decision.
    """

    next_mode: SignalFallbackDestination
    timeout_seconds: int
    next_request: FetchRequest
    reasoning: str

    @property
    def should_give_up(self) -> bool:
        """True when no further attempts should be made."""
        return self.next_mode == "give_up"

    @property
    def should_retry(self) -> bool:
        """True when there is a next mode to try."""
        return self.next_mode not in ("give_up",)


def choose_next_mode(
    current_mode: FetchMode | Literal["search"],
    request: FetchRequest,
    response: FetchResponse,
    signals: FetchSignals,
    domain_policy: DomainPolicy,
    history: ModeHistory,
) -> FallbackDecision:
    """Choose the next fetch mode after *current_mode* failed.

    Uses the signal-driven decision model (PHASE 3.12.5) which considers
    domain policy overrides, hard failures, JS/rendering signals, anti-bot
    signals, content-type signals, and the base escalation chain — in that
    order.

    Parameters
    ----------
    current_mode:
        The mode that just failed.
    request:
        The original (or previous-hop) fetch request.
    response:
        The failed response containing status, body, headers, and error info.
    signals:
        Structured signals extracted from *response* by PHASE 3.12.4.
    domain_policy:
        The effective domain policy resolved by PHASE 3.12.3.
    history:
        Aggregated success/failure counts per mode for the domain.

    Returns
    -------
    FallbackDecision
        The next mode, its timeout, a hydrated request, and reasoning.
    """
    # --- Rule 1: Domain policy overrides ---
    # Denied domains → give_up immediately
    if domain_policy.deny:
        return _give_up(request, f"domain {domain_policy.domain} is denied by policy")

    # --- Rule 2: Hard failures (always escalate) ---
    if _is_hard_failure(signals, response):
        return _escalate_hard(current_mode, request, response, domain_policy, signals)

    # --- Rule 3: JavaScript / rendering signals → headless ---
    if signals.has_js_signal and "http_headless_browser" not in domain_policy.forbidden_modes:
        return _jump_to(
            "http_headless_browser",
            request,
            response,
            reasoning=f"JS/rendering signals detected → jumping to http_headless_browser",
        )

    # --- Rule 4: Anti-bot signals → stealth ---
    if signals.has_anti_bot_signal and "http_stealth" not in domain_policy.forbidden_modes:
        return _jump_to(
            "http_stealth",
            request,
            response,
            reasoning=f"anti-bot signals detected → jumping to http_stealth",
        )

    # --- Rule 5: Content-type signals ---
    if signals.json_endpoint_detected:
        # Retry with simple — JSON APIs rarely need browser rendering
        if "http_simple" not in domain_policy.forbidden_modes:
            return _jump_to(
                "http_simple",
                request,
                response,
                reasoning="JSON endpoint detected → retrying with http_simple",
            )

    if signals.static_asset:
        if "http_simple" not in domain_policy.forbidden_modes:
            return _jump_to(
                "http_simple",
                request,
                response,
                reasoning="static asset detected → retrying with http_simple",
            )

    # --- Rule 6: Standard escalation with forbidden mode skipping ---
    next_mode = _escalate_skipping_forbidden(current_mode, domain_policy.forbidden_modes)

    if next_mode is None:
        return _give_up(request, f"all modes exhausted or forbidden from {current_mode}")

    # --- Build next request ---
    next_req = hydrate_next_request(request, response, next_mode)

    timeout = _MODE_TIMEOUTS.get(next_mode, 10)
    reasoning = _build_escalation_reasoning(current_mode, next_mode, signals, domain_policy)

    return FallbackDecision(
        next_mode=next_mode,
        timeout_seconds=timeout,
        next_request=next_req,
        reasoning=reasoning,
    )


# ---------------------------------------------------------------------------
# Request hydration
# ---------------------------------------------------------------------------


def hydrate_next_request(
    request: FetchRequest,
    response: FetchResponse,
    next_mode: SignalFallbackDestination,
) -> FetchRequest:
    """Create the next :class:`FetchRequest` preserving cookies, headers, and URL.

    Cookies accumulated from prior responses (via ``Set-Cookie``) are carried
    forward.  The response URL (if different due to redirects) is preferred
    over the original request URL.

    Parameters
    ----------
    request:
        The original or previous-hop fetch request.
    response:
        The response from the failed attempt (may carry cookies and a final URL).
    next_mode:
        The mode the orchestrator will use next.  Currently informational only;
        does not affect request shape.

    Returns
    -------
    FetchRequest
        A new request hydrated with accumulated state.
    """
    # Merge cookies: response cookies override request cookies
    merged_cookies = dict(request.cookies)
    if response.cookies:
        merged_cookies.update(response.cookies)

    # Merge headers: preserve original headers, add cookie header
    merged_headers = dict(request.headers)
    if merged_cookies and "Cookie" not in merged_headers:
        merged_headers["Cookie"] = "; ".join(
            f"{k}={v}" for k, v in merged_cookies.items()
        )

    # Use the response's final URL if available (handles redirects)
    # FetchResponse does not have final_url, so use url attribute
    url = response.url or request.url

    return FetchRequest(
        url=url,
        method=request.method,
        headers=merged_headers,
        cookies=merged_cookies,
        timeout=request.timeout,
        body=request.body,
    )


# ---------------------------------------------------------------------------
# Internal helpers — decision logic
# ---------------------------------------------------------------------------


def _is_hard_failure(signals: FetchSignals, response: FetchResponse) -> bool:
    """True when the failure is a hard infrastructure/network error."""
    if signals.redirect_loop or signals.ssl_error or signals.connection_reset:
        return True
    if response.error_type and response.error_type in _HARD_FAILURE_ERROR_TYPES:
        return True
    return False


def _escalate_hard(
    current_mode: FetchMode | Literal["search"],
    request: FetchRequest,
    response: FetchResponse,
    domain_policy: DomainPolicy,
    signals: FetchSignals,
) -> FallbackDecision:
    """Escalate due to a hard failure, skipping forbidden modes."""
    hard_reason = _describe_hard_failure(signals, response)
    next_mode = _escalate_skipping_forbidden(current_mode, domain_policy.forbidden_modes)

    if next_mode is None:
        return _give_up(request, f"hard failure ({hard_reason}) — all modes exhausted")

    next_req = hydrate_next_request(request, response, next_mode)
    timeout = _MODE_TIMEOUTS.get(next_mode, 10)

    return FallbackDecision(
        next_mode=next_mode,
        timeout_seconds=timeout,
        next_request=next_req,
        reasoning=f"hard failure: {hard_reason} → escalating to {next_mode}",
    )


def _describe_hard_failure(signals: FetchSignals, response: FetchResponse) -> str:
    """Return a short description of the hard failure reason."""
    if signals.redirect_loop:
        return "redirect_loop"
    if signals.ssl_error:
        return "ssl_error"
    if signals.connection_reset:
        return "connection_reset"
    return response.error_type or "unknown hard failure"


def _jump_to(
    target_mode: SignalFallbackDestination,
    request: FetchRequest,
    response: FetchResponse,
    *,
    reasoning: str,
) -> FallbackDecision:
    """Jump directly to *target_mode*, bypassing the linear chain."""
    next_req = hydrate_next_request(request, response, target_mode)
    timeout = _MODE_TIMEOUTS.get(target_mode, 10)
    return FallbackDecision(
        next_mode=target_mode,
        timeout_seconds=timeout,
        next_request=next_req,
        reasoning=reasoning,
    )


def _escalate_skipping_forbidden(
    current_mode: FetchMode | Literal["search"],
    forbidden_modes: tuple[str, ...],
) -> SignalFallbackDestination | None:
    """Walk the escalation chain from *current_mode*, skipping forbidden modes.

    Returns ``None`` if all reachable modes are exhausted or forbidden.
    """
    mode: SignalFallbackDestination | Literal["search"] | None = current_mode
    visited: set[str] = set()

    while mode is not None:
        if mode in visited:
            # Cycle guard — shouldn't happen with the linear chain, but safe
            return None
        visited.add(mode)

        next_mode = _ESCALATION_CHAIN.get(mode)
        if next_mode is None:
            return None  # current_mode not in chain

        if next_mode == "give_up":
            return None  # exhausted

        if next_mode not in forbidden_modes:
            return next_mode

        # Skip forbidden mode → continue walking
        mode = next_mode

    return None


def _build_escalation_reasoning(
    current_mode: FetchMode | Literal["search"],
    next_mode: SignalFallbackDestination,
    signals: FetchSignals,
    domain_policy: DomainPolicy,
) -> str:
    """Build a concise reasoning string for the escalation."""
    parts: list[str] = []

    # What failed
    parts.append(f"{current_mode} failed")

    # What signals were detected
    detected = _list_detected_signals(signals)
    if detected:
        parts.append(f"signals=[{', '.join(detected)}]")

    # Any policy constraint
    if domain_policy.preferred_mode:
        parts.append(f"preferred={domain_policy.preferred_mode}")
    if domain_policy.forbidden_modes:
        parts.append(f"forbidden={list(domain_policy.forbidden_modes)}")

    # Outcome
    timeout = _MODE_TIMEOUTS.get(next_mode, 10)
    parts.append(f"→ {next_mode} (timeout={timeout}s)")

    return "; ".join(parts)


def _list_detected_signals(signals: FetchSignals) -> list[str]:
    """Return the names of all raised signal fields."""
    names: list[str] = []
    _SIGNAL_FIELDS: tuple[tuple[str, str], ...] = (
        ("js_required", "js_required"),
        ("blank_html", "blank_html"),
        ("hydration_error", "hydration_error"),
        ("script_timeout", "script_timeout"),
        ("cloudflare_challenge", "cloudflare_challenge"),
        ("datadome_block", "datadome_block"),
        ("perimeterx_block", "perimeterx_block"),
        ("akamai_bot_detected", "akamai_bot_detected"),
        ("captcha_present", "captcha_present"),
        ("json_endpoint_detected", "json_endpoint_detected"),
        ("xml_feed", "xml_feed"),
        ("static_asset", "static_asset"),
        ("redirect_loop", "redirect_loop"),
        ("ssl_error", "ssl_error"),
        ("connection_reset", "connection_reset"),
        ("malformed_html", "malformed_html"),
        ("empty_body", "empty_body"),
        ("suspicious_meta_refresh", "suspicious_meta_refresh"),
    )
    for attr, label in _SIGNAL_FIELDS:
        if getattr(signals, attr, False):
            names.append(label)
    return names


def _give_up(
    request: FetchRequest,
    reason: str,
) -> FallbackDecision:
    """Return a ``give_up`` decision with an empty next request."""
    return FallbackDecision(
        next_mode="give_up",
        timeout_seconds=0,
        next_request=FetchRequest(url=request.url),
        reasoning=reason,
    )
