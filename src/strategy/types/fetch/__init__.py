"""
Fetch Types — Request/response shapes, error taxonomy, mode selection,
and fallback routing for the fetch subsystem.

These types represent all data crossing the S0/S1 fetch boundary. They are pure
data containers with no fetch logic, safe to extend in later phases (3.11 hardened
modes, 3.12 fallback chain).
"""

from .domain_policy import (
    DomainPolicy,
    interpret_domain_policy,
)
from .errors import (
    FetchError,
    TimeoutError,
    HTTPError,
    ParseError,
    ConnectionError,
    classify_exception,
)
from .fallback_router import (
    FallbackDestination,
    FallbackSelection,
    select_fallback,
)
from .mode_selector import (
    FetchMode,
    ModeHistory,
    ModeSelection,
    select_initial_mode,
)
from .request import FetchRequest
from .response import FetchResponse
from .signal_extraction import (
    FetchSignals,
    extract_signals,
)
from .fetch_url import (
    FetchResult,
    fetch_url,
)
from .sanitisation import sanitise_response
from .signal_fallback import (
    FallbackDecision,
    SignalFallbackDestination,
    choose_next_mode,
    hydrate_next_request,
)

__all__ = [
    "DomainPolicy",
    "interpret_domain_policy",
    "FetchError",
    "TimeoutError",
    "HTTPError",
    "ParseError",
    "ConnectionError",
    "classify_exception",
    "FallbackDestination",
    "FallbackSelection",
    "select_fallback",
    "FetchMode",
    "ModeHistory",
    "ModeSelection",
    "select_initial_mode",
    "FetchRequest",
    "FetchResponse",
    "FetchSignals",
    "extract_signals",
    "FallbackDecision",
    "SignalFallbackDestination",
    "choose_next_mode",
    "hydrate_next_request",
    "FetchResult",
    "fetch_url",
    "sanitise_response",
]
