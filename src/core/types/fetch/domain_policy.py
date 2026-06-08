"""
Domain Policy Interpreter — PHASE 3.12.3

Pure-logic component invoked BEFORE heuristics and BEFORE the fallback
chain.  Given a URL and a domain-policy dictionary, it returns the
effective policy for that domain.

It does NOT:
- Perform any network I/O
- Choose a fetch mode
- Inspect response bodies
- Classify signals
- Trigger fallback or retry
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .mode_selector import FetchMode

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DomainPolicy:
    """Effective policy for a single domain.

    This is the output of :func:`interpret_domain_policy` and tells the
    orchestrator how to treat a specific domain — whether it is allowed,
    which modes are preferred or forbidden, and whether rate-limiting
    should be applied.

    Attributes:
        domain: The normalised domain extracted from the URL.
        allow: ``False`` when the domain is denied (either explicitly via
               ``deny=true`` or implicitly via ``allow=false``).
        deny: ``True`` when the domain is explicitly denied.
        rate_limit_ms: Minimum delay between successive requests to this
                       domain.  ``0`` means no rate limit.
        preferred_mode: A hint to the mode selector.  ``None`` means no
                        preference.
        forbidden_modes: Modes the orchestrator must never attempt for
                         this domain.
        reasoning: A short human-readable explanation.
    """

    domain: str
    allow: bool = True
    deny: bool = False
    rate_limit_ms: int = 0
    preferred_mode: FetchMode | None = None
    forbidden_modes: tuple[str, ...] = field(default_factory=tuple)
    reasoning: str = ""

    @property
    def is_denied(self) -> bool:
        """True when the domain is blocked and no fetch should be attempted."""
        return not self.allow

    @property
    def has_preference(self) -> bool:
        """True when a preferred_mode is specified."""
        return self.preferred_mode is not None

    @property
    def has_forbidden(self) -> bool:
        """True when at least one mode is forbidden."""
        return len(self.forbidden_modes) > 0

    @property
    def is_rate_limited(self) -> bool:
        """True when rate_limit_ms > 0."""
        return self.rate_limit_ms > 0


# ---------------------------------------------------------------------------
# Default policy (returned for domains not present in the policy file)
# ---------------------------------------------------------------------------

_DEFAULT_POLICY = {
    "allow": True,
    "deny": False,
    "rate_limit_ms": 0,
    "preferred_mode": None,
    "forbidden_modes": [],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def interpret_domain_policy(
    url: str,
    domain_policy: dict[str, dict[str, Any]] | None = None,
) -> DomainPolicy:
    """Resolve the effective domain policy for a URL.

    Parameters
    ----------
    url:
        The full request URL.  Only the hostname component is used;
        path, query, and fragment are ignored.

    domain_policy:
        A dictionary mapping domain names to policy entries.  Each entry
        may contain any subset of ``allow``, ``deny``, ``rate_limit_ms``,
        ``preferred_mode``, ``forbidden_modes``, and ``notes``.
        Pass ``None`` or an empty dict to get defaults for every domain.

    Returns
    -------
    DomainPolicy
        The effective policy.  Never ``None``.

    Notes
    -----
    Domain matching is **exact** — ``foo.example.com`` does NOT match a
    policy entry for ``example.com``.  Subdomain / wildcard handling is
    not part of PHASE 3.12.3.
    """
    domain = _extract_domain(url)

    # If no policy file supplied, return defaults
    if not domain_policy:
        return DomainPolicy(
            domain=domain,
            reasoning=f"no domain policy configured → defaults for {domain}",
        )

    # Look up the domain
    entry = domain_policy.get(domain)

    if entry is None:
        return DomainPolicy(
            domain=domain,
            reasoning=f"no policy entry for {domain} → defaults",
        )

    # Merge with defaults
    merged: dict[str, Any] = {**_DEFAULT_POLICY}
    merged.update({k: v for k, v in entry.items() if v is not None})

    # Normalise rate_limit_ms to int early
    rate_limit = _normalise_rate_limit(merged.get("rate_limit_ms", 0))
    merged["rate_limit_ms"] = rate_limit

    # Validate allowed modes
    preferred = _normalise_preferred_mode(merged.get("preferred_mode"))
    forbidden = _normalise_forbidden_modes(merged.get("forbidden_modes", []))

    # Build reasoning
    deny_flag = bool(merged.get("deny", False))
    allow_flag = bool(merged.get("allow", True))

    if deny_flag or not allow_flag:
        reasoning = f"domain {domain} is denied"
    else:
        parts = [f"policy matched for {domain}"]
        if preferred:
            parts.append(f"preferred={preferred}")
        if forbidden:
            parts.append(f"forbidden={forbidden}")
        if rate_limit > 0:
            parts.append(f"rate_limit={rate_limit}ms")
        reasoning = "; ".join(parts)

    return DomainPolicy(
        domain=domain,
        allow=allow_flag and not deny_flag,
        deny=deny_flag or not allow_flag,
        rate_limit_ms=rate_limit,
        preferred_mode=preferred,
        forbidden_modes=forbidden,
        reasoning=reasoning,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_VALID_MODES: set[str] = {
    "http_simple",
    "http_hardened",
    "http_headless_browser",
    "http_stealth",
}


def _extract_domain(url: str) -> str:
    """Extract the hostname component from *url*.

    Returns the empty string when the URL cannot be parsed (missing
    scheme, invalid syntax, non-HTTP schemes that have no meaningful
    host like ``mailto:``, etc.).  The orchestrator should treat an
    empty domain as "no policy applies".
    """
    if not url or not isinstance(url, str):
        return ""

    # Non-HTTP schemes that carry no routable hostname
    if "://" in url:
        scheme = url.split("://", 1)[0].lower()
        if scheme in ("mailto", "tel", "data", "javascript", "about"):
            return ""
    elif ":" in url:
        # Handle schemes like "mailto:" without "://"
        scheme = url.split(":", 1)[0].lower()
        if scheme in ("mailto", "tel", "data", "javascript", "about"):
            return ""

    # urlparse requires a scheme — add one if missing
    if "://" not in url:
        url = "http://" + url

    try:
        parsed = urlparse(url)
    except Exception:
        return ""

    hostname = parsed.hostname or ""
    # Strip brackets from IPv6 addresses
    if hostname.startswith("[") and hostname.endswith("]"):
        hostname = hostname[1:-1]

    return hostname.lower()


def _normalise_rate_limit(raw: Any) -> int:
    """Coerce *raw* to int, returning 0 for anything unparseable."""
    try:
        return int(raw)
    except (ValueError, TypeError):
        return 0


def _normalise_preferred_mode(raw: Any) -> FetchMode | None:
    """Validate and normalise a preferred_mode value.

    Returns ``None`` for anything that isn't a recognised fetch mode.
    """
    if isinstance(raw, str) and raw in _VALID_MODES:
        return raw  # type: ignore[return-value]
    return None


def _normalise_forbidden_modes(raw: Any) -> tuple[str, ...]:
    """Filter a list of candidate modes down to only valid ones."""
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(m for m in raw if isinstance(m, str) and m in _VALID_MODES)
