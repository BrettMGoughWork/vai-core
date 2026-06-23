"""
Initial Mode Selector — PHASE 3.12.1

Pure-logic component invoked at the start of the http_fetch pipeline.
Given a FetchRequest and a history of prior successes/failures, it selects
the single best initial fetch mode.  It does NOT:

- Perform any network I/O
- Inspect any response body
- Classify signals
- Trigger fallback or retry

Those behaviours belong to later stages of the orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

from src.domain._markers import deadcode_ignore

from .request import FetchRequest

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

FetchMode = Literal[
    "http_simple",
    "http_hardened",
    "http_headless_browser",
    "http_stealth",
]

ALL_MODES: tuple[FetchMode, ...] = (
    "http_simple",
    "http_hardened",
    "http_headless_browser",
    "http_stealth",
)

# Cost order (cheapest → most expensive)
_MODE_COST_RANK: dict[FetchMode, int] = {
    "http_simple": 0,
    "http_hardened": 1,
    "http_headless_browser": 2,
    "http_stealth": 3,
}


@dataclass(frozen=True)
class ModeHistory:
    """Aggregated success/failure counts for every fetch mode.

    Each key maps to a non-negative integer.  Absent keys are treated as 0.
    """

    successes: dict[FetchMode, int] = field(default_factory=dict)
    failures: dict[FetchMode, int] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> ModeHistory:
        """Construct from the "history" block in the orchestrator input schema."""
        return cls(
            successes=_normalise_mode_dict(d.get("successes", {})),
            failures=_normalise_mode_dict(d.get("failures", {})),
        )

    def success_rate(self, mode: FetchMode) -> float:
        """Return the success rate for *mode* as a float in [0.0, 1.0].

        A mode with no recorded attempts returns 0.5 (neutral prior).
        """
        s = self.successes.get(mode, 0)
        f = self.failures.get(mode, 0)
        total = s + f
        if total == 0:
            return 0.5  # neutral — no data
        return s / total

    def total_attempts(self, mode: FetchMode) -> int:
        return self.successes.get(mode, 0) + self.failures.get(mode, 0)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalise_mode_dict(raw: dict) -> dict[FetchMode, int]:
    """Filter *raw* to only contain valid fetch modes, coercing values to int."""
    result: dict[FetchMode, int] = {}
    for mode in ALL_MODES:
        v = raw.get(mode, 0)
        try:
            result[mode] = max(0, int(v))
        except (ValueError, TypeError):
            result[mode] = 0
    return result


# ---------------------------------------------------------------------------
# URL pattern analysis
# ---------------------------------------------------------------------------

# Path extensions strongly indicating static assets
_STATIC_EXTENSIONS: frozenset[str] = frozenset({
    ".css", ".js", ".mjs", ".cjs",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".7z",
    ".mp4", ".webm", ".mp3", ".wav",
})

# Path segments strongly indicating an API
_API_PATH_SEGMENTS: frozenset[str] = frozenset({
    "api", "v1", "v2", "v3", "v4", "graphql", "rest",
})

# Well-known low-risk domains (always safe for simple fetch)
_LOW_RISK_DOMAINS: frozenset[str] = frozenset({
    "example.com", "httpbin.org", "jsonplaceholder.typicode.com",
    "api.github.com", "postman-echo.com",
})

# Domains known to require hardened mode (WAF, rate-limiting, anti-bot)
_MEDIUM_RISK_DOMAINS: frozenset[str] = frozenset({
    "reddit.com", "old.reddit.com", "medium.com",
    "blog.cloudflare.com", "stackoverflow.com",
    "news.ycombinator.com",
})

# Domains that aggressively block non-browser traffic
_HIGH_RISK_DOMAINS: frozenset[str] = frozenset({
    "google.com", "www.google.com",
    "datadome.co",
})

# Patterns in URL or domain that signal a JS-heavy SPA
_SPA_SIGNALS: tuple[str, ...] = (
    "react", "vue", "angular", "nextjs", "nuxt", "svelte",
    "gatsby", "remix", "astro",
)

# Patterns that signal anti-bot countermeasures are likely
_ANTIBOT_SIGNALS: tuple[str, ...] = (
    "cloudflare", "datadome", "akamai", "imperva",
    "distil", "perimeterx", "recaptcha", "captcha",
)


def _extract_domain(url: str) -> str:
    """Return the lower-cased netloc from *url*, or empty string on failure."""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _url_basename(url: str) -> str:
    """Return the lower-cased final path component (including extension)."""
    try:
        path = urlparse(url).path or "/"
        return path.rstrip("/").rsplit("/", 1)[-1].lower()
    except Exception:
        return ""


def _has_path_segment(url: str, segment: str) -> bool:
    """True when *segment* appears as a path component in *url*."""
    try:
        parts = [p.lower() for p in urlparse(url).path.split("/") if p]
        return segment.lower() in parts
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------


_RISK_SCORES: dict[str, int] = {"low": 0, "medium": 1, "high": 3}


def _domain_risk(url: str) -> tuple[str, int]:
    """Return (label, score) for the domain risk tier of *url*."""
    domain = _extract_domain(url)
    # Exact match first
    if domain in _LOW_RISK_DOMAINS:
        return ("low", 0)
    if domain in _HIGH_RISK_DOMAINS:
        return ("high", 3)
    if domain in _MEDIUM_RISK_DOMAINS:
        return ("medium", 1)
    # Substring check for medium/high risk patterns
    for risk_domain in _HIGH_RISK_DOMAINS:
        if risk_domain in domain:
            return ("high", 3)
    for risk_domain in _MEDIUM_RISK_DOMAINS:
        if risk_domain in domain:
            return ("medium", 1)
    # Check anti-bot signals in full URL
    url_lower = url.lower()
    for signal in _ANTIBOT_SIGNALS:
        if signal in url_lower:
            return ("high", 3)
    # Default: low risk
    return ("low", 0)


def _url_pattern_score(url: str) -> dict[FetchMode, float]:
    """Score each mode based purely on URL structural analysis.

    Returns a dict mapping mode → score in [0.0, 1.0].  Higher = more likely
    the correct initial mode.
    """
    scores: dict[FetchMode, float] = {m: 0.0 for m in ALL_MODES}
    url_lower = url.lower()
    domain = _extract_domain(url)
    basename = _url_basename(url)

    # --- Static asset detection ---
    if any(basename.endswith(ext) for ext in _STATIC_EXTENSIONS):
        scores["http_simple"] = 1.0
        return scores

    # --- API endpoint detection ---
    is_api = (
        any(_has_path_segment(url, seg) for seg in _API_PATH_SEGMENTS)
        or basename.endswith(".json")
        or basename.endswith(".xml")
        or "/api." in url_lower  # e.g. api.example.com
    )
    if is_api:
        scores["http_simple"] = 0.9
        scores["http_hardened"] = 0.6
        return scores

    # --- Documentation / wiki ---
    is_docs = (
        domain.startswith("docs.")
        or "readthedocs" in domain
        or "/docs/" in url_lower
        or "/wiki/" in url_lower
        or "developer.mozilla.org" in domain
    )
    if is_docs:
        scores["http_simple"] = 0.95
        return scores

    # --- Blog / news / article ---
    is_blog = (
        domain.startswith("blog.")
        or "/blog/" in url_lower
        or "/news/" in url_lower
        or "/article/" in url_lower
        or "medium.com" in domain
        or "substack.com" in domain
    )
    if is_blog:
        scores["http_hardened"] = 0.8
        scores["http_simple"] = 0.3
        scores["http_headless_browser"] = 0.4
        return scores

    # --- SPA / JS-framework detection ---
    is_spa = any(signal in url_lower for signal in _SPA_SIGNALS)
    if is_spa:
        scores["http_headless_browser"] = 0.9
        scores["http_hardened"] = 0.3
        return scores

    # --- Anti-bot detection ---
    is_antibot = any(signal in url_lower for signal in _ANTIBOT_SIGNALS)
    if is_antibot:
        scores["http_stealth"] = 0.9
        scores["http_headless_browser"] = 0.4
        scores["http_hardened"] = 0.2
        return scores

    # --- Default: HTML page, unknown risk ---
    scores["http_simple"] = 0.6
    scores["http_hardened"] = 0.4
    return scores


def _content_type_hint_score(request: FetchRequest) -> dict[FetchMode, float]:
    """Score each mode based on content-type hints from URL or headers."""
    scores: dict[FetchMode, float] = {m: 0.0 for m in ALL_MODES}

    # Inspect Accept header
    accept = (request.headers or {}).get("Accept", "").lower()
    content_type = (request.headers or {}).get("Content-Type", "").lower()

    # URL-extension-based content-type hints
    basename = _url_basename(request.url)

    # JSON
    if "application/json" in accept or basename.endswith(".json"):
        scores["http_simple"] = max(scores["http_simple"], 0.95)
        return scores

    # Plain text / markdown
    if "text/plain" in accept or basename.endswith((".txt", ".md", ".rst")):
        scores["http_simple"] = max(scores["http_simple"], 0.95)
        return scores

    # XML / RSS / Atom
    if any(t in accept for t in ("application/xml", "text/xml", "application/rss", "application/atom")) or basename.endswith((".xml", ".rss", ".atom")):
        scores["http_simple"] = max(scores["http_simple"], 0.9)
        return scores

    # HTML with JS render hint from URL
    if basename.endswith(".html") or basename.endswith(".htm"):
        scores["http_simple"] = 0.7
        scores["http_hardened"] = 0.3
        return scores

    # No strong content-type signal — neutral
    return scores


def _history_score(history: ModeHistory) -> dict[FetchMode, float]:
    """Up-rank modes with prior success; down-rank modes with prior failure.

    Modes with no history get a neutral 0.5 baseline.
    Modes with ≥3 successes and zero failures get a strong boost.
    Modes with ≥3 failures and zero successes get heavily down-ranked.
    """
    scores: dict[FetchMode, float] = {}
    for mode in ALL_MODES:
        s = history.successes.get(mode, 0)
        f = history.failures.get(mode, 0)
        total = s + f
        if total == 0:
            scores[mode] = 0.5  # neutral
        elif total >= 3 and f == 0:
            scores[mode] = 1.0  # strong success pattern
        elif total >= 3 and s == 0:
            scores[mode] = 0.05  # strong failure pattern
        else:
            # Weighted: successes count 2× more than failures for moderate history
            scores[mode] = (s * 2 + f * 0.5) / (total * 2.5) if total > 0 else 0.5
    return scores


def _cost_penalty(mode: FetchMode) -> float:
    """Return a penalty factor for more expensive modes.

    Cheaper modes get no penalty; the most expensive mode gets the highest penalty.
    """
    rank = _MODE_COST_RANK[mode]
    max_rank = len(ALL_MODES) - 1
    if max_rank == 0:
        return 1.0
    return 1.0 - (rank / max_rank) * 0.3  # max 30% penalty for stealth


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@deadcode_ignore(reason="Return type for select_initial_mode, used via type annotation in fetch orchestrator")
@dataclass(frozen=True)
class ModeSelection:
    """The result of running the initial mode selector."""

    mode: FetchMode
    reasoning: str


def select_initial_mode(
    request: FetchRequest,
    history: ModeHistory | None = None,
) -> ModeSelection:
    """Choose the best initial fetch mode for *request*.

    Parameters
    ----------
    request:
        The fetch request to analyse.  URL and headers are the primary inputs;
        method, body, cookies, and timeout are ignored by the selector.
    history:
        Optional aggregated history of prior successes and failures per mode.
        When omitted a neutral (empty) history is assumed.

    Returns
    -------
    ModeSelection
        The single recommended mode with a short human-readable reasoning.
    """
    if history is None:
        history = ModeHistory()

    # 1. URL pattern score
    url_scores = _url_pattern_score(request.url)

    # 2. Content-type hint score (layered on top)
    ct_scores = _content_type_hint_score(request)

    # 3. Domain risk adjustment
    risk_label, risk_score = _domain_risk(request.url)

    # 4. History score
    hist_scores = _history_score(history)

    # --- Composite scoring ---
    # Weights: URL pattern 40%, history 30%, domain risk 20%, content-type 10%
    composite: dict[FetchMode, float] = {}
    for mode in ALL_MODES:
        composite[mode] = (
            url_scores[mode] * 0.40
            + hist_scores[mode] * 0.30
            + (1.0 - risk_score / 3.0) * 0.20  # invert: high risk → low score
            + ct_scores[mode] * 0.10
        ) * _cost_penalty(mode)

    # --- Domain risk override ---
    # High-risk domains can never start with http_simple and get a stealth boost
    if risk_label == "high":
        composite["http_simple"] = -1.0
        composite["http_stealth"] = max(composite["http_stealth"], composite["http_hardened"] + 0.15)

    # Medium-risk domains can never start with http_simple unless history
    # strongly supports it (≥3 successes, 0 failures)
    if risk_label == "medium":
        s = history.successes.get("http_simple", 0)
        f = history.failures.get("http_simple", 0)
        if not (s >= 3 and f == 0):
            composite["http_simple"] = -1.0

    # --- Select winner ---
    best_mode: FetchMode = "http_simple"
    best_score = -999.0
    for mode in ALL_MODES:
        if composite[mode] > best_score:
            best_score = composite[mode]
            best_mode = mode

    # --- Build reasoning ---
    reasoning_parts: list[str] = []

    # Domain risk
    reasoning_parts.append(f"domain risk={risk_label}")

    # Top URL signal
    top_url_mode = max(url_scores, key=lambda m: url_scores[m])
    if url_scores[top_url_mode] > 0.5:
        reasoning_parts.append(f"URL pattern→{top_url_mode} ({url_scores[top_url_mode]:.0%})")

    # Content-type
    top_ct_mode = max(ct_scores, key=lambda m: ct_scores[m])
    if ct_scores[top_ct_mode] > 0.5:
        reasoning_parts.append(f"content-type→{top_ct_mode}")

    # History
    for mode in ALL_MODES:
        total = history.total_attempts(mode)
        if total >= 3:
            rate = history.success_rate(mode)
            reasoning_parts.append(f"history {mode}={rate:.0%} ({total} attempts)")

    # Cost
    reasoning_parts.append(f"cost rank={_MODE_COST_RANK[best_mode]}/3")

    reasoning = "; ".join(reasoning_parts)
    return ModeSelection(mode=best_mode, reasoning=reasoning)
