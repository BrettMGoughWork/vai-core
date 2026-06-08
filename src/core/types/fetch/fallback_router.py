"""
Fallback Router — PHASE 3.12.2

Pure-logic component invoked AFTER an initial fetch attempt fails.
Given the current fetch mode and the FetchError it produced, this
router selects the next mode in a prescriptive, linear fallback chain.

It does NOT:
- Use heuristics or signals
- Inspect response bodies
- Skip ahead in the chain
- Classify errors beyond what the FetchError already provides

The fallback chain is FIXED:
    http_simple → http_hardened → http_headless_browser → http_stealth → search → give_up
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .errors import FetchError
from .mode_selector import FetchMode

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

FallbackDestination = Literal[
    "http_simple",
    "http_hardened",
    "http_headless_browser",
    "http_stealth",
    "search",
    "give_up",
]

# ---------------------------------------------------------------------------
# Fallback chain (strict order)
# ---------------------------------------------------------------------------

_FALLBACK_CHAIN: dict[FetchMode | Literal["search"], FallbackDestination] = {
    "http_simple": "http_hardened",
    "http_hardened": "http_headless_browser",
    "http_headless_browser": "http_stealth",
    "http_stealth": "search",
    "search": "give_up",
}

# ---------------------------------------------------------------------------
# Mode-specific timeouts (in seconds)
# ---------------------------------------------------------------------------

_MODE_TIMEOUTS: dict[FallbackDestination, int] = {
    "http_simple": 10,
    "http_hardened": 15,
    "http_headless_browser": 30,
    "http_stealth": 45,
    "search": 10,
    "give_up": 0,
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FallbackSelection:
    """The result of running the fallback router.

    Attributes:
        next_mode: The next mode to attempt, or ``"give_up"`` if no further
                   modes remain in the chain.
        timeout_seconds: The timeout to use for the next attempt.
        reasoning: A short human-readable explanation of the transition.
    """

    next_mode: FallbackDestination
    timeout_seconds: int
    reasoning: str

    @property
    def should_give_up(self) -> bool:
        """True when the chain is exhausted and no further attempts should be made."""
        return self.next_mode == "give_up"

    @property
    def should_retry(self) -> bool:
        """True when there is a next mode to try."""
        return self.next_mode != "give_up"


def select_fallback(
    current_mode: FetchMode | Literal["search"],
    error: FetchError | None = None,
) -> FallbackSelection:
    """Choose the next fetch mode after *current_mode* failed.

    Parameters
    ----------
    current_mode:
        The mode that just failed.  Must be one of the four fetch modes
        (``"http_simple"``, ``"http_hardened"``, ``"http_headless_browser"``,
        ``"http_stealth"``) or ``"search"``.

    error:
        The FetchError that triggered the failure.  Used only for the
        reasoning message; the fallback chain does NOT branch on error type.
        When ``None``, a generic error reference is used.

    Returns
    -------
    FallbackSelection
        The next mode, its timeout, and a short reasoning string.

    Raises
    ------
    ValueError
        If *current_mode* is not a recognised mode in the chain.
    """
    if current_mode not in _FALLBACK_CHAIN:
        raise ValueError(
            f"Unknown current_mode: {current_mode!r}. "
            f"Expected one of: {list(_FALLBACK_CHAIN)}"
        )

    next_mode = _FALLBACK_CHAIN[current_mode]
    timeout = _MODE_TIMEOUTS[next_mode]

    # Build reasoning
    error_type = type(error).__name__ if error is not None else "UnknownError"
    error_kind = getattr(error, "kind", "unknown") if error is not None else "unknown"
    reasoning = f"{current_mode} failed with [{error_kind}] {error_type} → escalating to {next_mode} (timeout={timeout}s)"

    return FallbackSelection(
        next_mode=next_mode,
        timeout_seconds=timeout,
        reasoning=reasoning,
    )
