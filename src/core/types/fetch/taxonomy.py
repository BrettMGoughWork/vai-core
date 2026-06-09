"""URL taxonomy classifier (PHASE 3.13.5).

Lightweight, deterministic, provider-agnostic content-type classifier.
Uses ONLY URL pattern matching — no network calls, no LLM, no content
inspection.  Used by the fetch fallback router to choose the best fetch
mode for a URL.

Taxonomy labels → FetchMode mapping:

    article        → http_simple
    documentation  → http_hardened
    blog           → http_headless_browser
    unknown        → http_stealth
"""

from __future__ import annotations

from urllib.parse import urlparse, unquote

from src.core.types.fetch.mode_selector import FetchMode

# ── Taxonomy labels ─────────────────────────────────────────────────────

_TAXONOMY_ARTICLE = "article"
_TAXONOMY_DOCUMENTATION = "documentation"
_TAXONOMY_BLOG = "blog"
_TAXONOMY_UNKNOWN = "unknown"

# ── Pattern collections ─────────────────────────────────────────────────

_ARTICLE_PATH_SEGMENTS: tuple[str, ...] = (
    "/news/",
    "/article/",
    "/articles/",
    "/stories/",
    "/story/",
    "/press/",
    "/releases/",
)

_ARTICLE_EXTENSIONS: tuple[str, ...] = (
    ".html",
    ".htm",
)

_DOCUMENTATION_PATH_SEGMENTS: tuple[str, ...] = (
    "/docs/",
    "/documentation/",
    "/api/",
    "/reference/",
    "/guide/",
    "/guides/",
    "/tutorial/",
    "/tutorials/",
    "/manual/",
    "/wiki/",
)

_BLOG_PATH_SEGMENTS: tuple[str, ...] = (
    "/blog/",
    "/blogs/",
    "/posts/",
    "/post/",
    "/writing/",
    "/writings/",
    "/essays/",
    "/essay/",
    "/journal/",
    "/diary/",
    "/notes/",
    "/thoughts/",
    "/musings/",
)

# ── Subdomain signals ───────────────────────────────────────────────────

_DOCUMENTATION_SUBDOMAIN_PREFIXES: tuple[str, ...] = (
    "docs.",
    "documentation.",
    "api.",
    "reference.",
    "developer.",
    "developers.",
)

_BLOG_SUBDOMAIN_PREFIXES: tuple[str, ...] = (
    "blog.",
    "blogs.",
    "journal.",
)

_ARTICLE_SUBDOMAIN_PREFIXES: tuple[str, ...] = (
    "news.",
)

# ── FetchMode → taxonomy mapping ────────────────────────────────────────

_TAXONOMY_TO_FETCH_MODE: dict[str, FetchMode] = {
    _TAXONOMY_ARTICLE: "http_simple",
    _TAXONOMY_DOCUMENTATION: "http_hardened",
    _TAXONOMY_BLOG: "http_headless_browser",
    _TAXONOMY_UNKNOWN: "http_stealth",
}

# ── Public API ──────────────────────────────────────────────────────────


def classify_url(url: str) -> str:
    """Classify a URL into a taxonomy label.

    Args:
        url: A fully-qualified URL string.

    Returns:
        One of ``"article"``, ``"documentation"``, ``"blog"``, or ``"unknown"``.

    This function is **deterministic** — the same URL always produces the
    same label.  It never makes network calls, inspects content, or uses
    heuristics beyond simple path-segment and subdomain matching.
    """
    if not url:
        return _TAXONOMY_UNKNOWN

    parsed = urlparse(url)
    path = unquote(parsed.path).lower().rstrip("/") + "/"
    hostname = unquote(parsed.hostname or "").lower()

    # 1. Check path-segment patterns (ordered by specificity)
    for segment in _DOCUMENTATION_PATH_SEGMENTS:
        if segment in path:
            return _TAXONOMY_DOCUMENTATION

    for segment in _BLOG_PATH_SEGMENTS:
        if segment in path:
            return _TAXONOMY_BLOG

    for segment in _ARTICLE_PATH_SEGMENTS:
        if segment in path:
            return _TAXONOMY_ARTICLE

    # 2. Check subdomain signals
    for prefix in _DOCUMENTATION_SUBDOMAIN_PREFIXES:
        if hostname.startswith(prefix):
            return _TAXONOMY_DOCUMENTATION

    for prefix in _BLOG_SUBDOMAIN_PREFIXES:
        if hostname.startswith(prefix):
            return _TAXONOMY_BLOG

    for prefix in _ARTICLE_SUBDOMAIN_PREFIXES:
        if hostname.startswith(prefix):
            return _TAXONOMY_ARTICLE

    # 3. Check file extensions
    if path.endswith(tuple(e + "/" for e in _ARTICLE_EXTENSIONS)):
        return _TAXONOMY_ARTICLE

    return _TAXONOMY_UNKNOWN


def choose_fetch_mode(url_or_taxonomy: str) -> FetchMode:
    """Map a URL or taxonomy label to the best fetch mode.

    Args:
        url_or_taxonomy: Either a URL string (will be classified) or one
            of the four taxonomy labels (``"article"``, ``"documentation"``,
            ``"blog"``, ``"unknown"``).

    Returns:
        The corresponding ``FetchMode`` literal.

    Examples:
        >>> choose_fetch_mode("https://example.com/docs/api")
        'http_hardened'
        >>> choose_fetch_mode("blog")
        'http_headless_browser'
    """
    # If the input is already a taxonomy label, use it directly
    if url_or_taxonomy in _TAXONOMY_TO_FETCH_MODE:
        return _TAXONOMY_TO_FETCH_MODE[url_or_taxonomy]

    # Otherwise classify the URL first
    taxonomy = classify_url(url_or_taxonomy)
    return _TAXONOMY_TO_FETCH_MODE[taxonomy]
