"""
Signal Extraction Engine — PHASE 3.12.4

Pure-logic component invoked AFTER a fetch attempt and BEFORE the fallback
router.  Given a FetchResponse, it analyses the response and produces a
structured FetchSignals object describing what happened during the fetch.

It does NOT:
- Choose the next mode
- Perform fallback or retry
- Modify the request or response
- Perform any network I/O

Those behaviours belong to PHASE 3.12.5 (signal-driven fallback).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .domain_policy import DomainPolicy
from .mode_selector import FetchMode
from .request import FetchRequest
from .response import FetchResponse

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

# Content-type constants used for signal detection
_TEXT_HTML = "text/html"
_APPLICATION_JSON = "application/json"
_APPLICATION_XML = "application/xml"
_TEXT_XML = "text/xml"


@dataclass(frozen=True)
class FetchSignals:
    """Structured signals extracted from a fetch response.

    Every field is a boolean indicating whether the corresponding condition
    was detected in the response.  ``False`` means "no evidence found" — the
    signal extractor never infers or speculates.

    Attributes:
        js_required: React/Vue/Next.js/Angular markers or blank body with JS tags.
        blank_html: Body shorter than 200 chars or containing only skeleton markup.
        hydration_error: Known hydration error strings in the body.
        script_timeout: Browser-mode JS timeout or ``ScriptTimeoutError``.

        cloudflare_challenge: CF challenge HTML/JS or ``cf-chl-bypass`` header.
        datadome_block: Datadome block markers in the body.
        perimeterx_block: PerimeterX fingerprinting markers.
        akamai_bot_detected: Akamai bot detection markers.
        captcha_present: Captcha forms, tokens, or challenge markup.

        json_endpoint_detected: Content-type is JSON or body parses as valid JSON.
        xml_feed: Content-type is XML or body begins with XML declaration.
        static_asset: Content-type indicates image, video, PDF, CSS, JS, font, etc.

        redirect_loop: Metadata shows >5 redirects or ``RedirectLoopError``.
        ssl_error: Error type is ``SSLError``.
        connection_reset: Error type is ``ConnectionResetError``.

        malformed_html: HTML parse errors detected in metadata.
        empty_body: Body length is exactly 0.
        suspicious_meta_refresh: HTML contains ``<meta http-equiv="refresh">``.

        reasoning: Short human-readable explanation of what was detected.
    """

    # -- JavaScript / rendering signals -----------------------------------
    js_required: bool = False
    blank_html: bool = False
    hydration_error: bool = False
    script_timeout: bool = False

    # -- Anti-bot / security signals --------------------------------------
    cloudflare_challenge: bool = False
    datadome_block: bool = False
    perimeterx_block: bool = False
    akamai_bot_detected: bool = False
    captcha_present: bool = False

    # -- Content-type signals ---------------------------------------------
    json_endpoint_detected: bool = False
    xml_feed: bool = False
    static_asset: bool = False

    # -- Network / protocol signals ---------------------------------------
    redirect_loop: bool = False
    ssl_error: bool = False
    connection_reset: bool = False

    # -- Quality / structure signals --------------------------------------
    malformed_html: bool = False
    empty_body: bool = False
    suspicious_meta_refresh: bool = False

    reasoning: str = ""

    @property
    def has_any_signal(self) -> bool:
        """``True`` if at least one signal flag is raised."""
        return any((
            self.js_required, self.blank_html, self.hydration_error,
            self.script_timeout, self.cloudflare_challenge, self.datadome_block,
            self.perimeterx_block, self.akamai_bot_detected, self.captcha_present,
            self.json_endpoint_detected, self.xml_feed, self.static_asset,
            self.redirect_loop, self.ssl_error, self.connection_reset,
            self.malformed_html, self.empty_body, self.suspicious_meta_refresh,
        ))

    @property
    def has_anti_bot_signal(self) -> bool:
        """``True`` if any anti-bot / security signal is raised."""
        return any((
            self.cloudflare_challenge, self.datadome_block,
            self.perimeterx_block, self.akamai_bot_detected,
            self.captcha_present,
        ))

    @property
    def has_js_signal(self) -> bool:
        """``True`` if any JavaScript / rendering signal is raised."""
        return any((
            self.js_required, self.blank_html, self.hydration_error,
            self.script_timeout,
        ))

    @property
    def raised_signals(self) -> tuple[str, ...]:
        """Return the names of all signals currently raised (value is ``True``)."""
        names: list[str] = []
        for attr in (
            "js_required", "blank_html", "hydration_error", "script_timeout",
            "cloudflare_challenge", "datadome_block", "perimeterx_block",
            "akamai_bot_detected", "captcha_present",
            "json_endpoint_detected", "xml_feed", "static_asset",
            "redirect_loop", "ssl_error", "connection_reset",
            "malformed_html", "empty_body", "suspicious_meta_refresh",
        ):
            if getattr(self, attr):
                names.append(attr)
        return tuple(names)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_signals(
    request: FetchRequest,
    response: FetchResponse,
    current_mode: FetchMode,
    domain_policy: DomainPolicy | None = None,
) -> FetchSignals:
    """Analyse a :class:`FetchResponse` and produce a :class:`FetchSignals` object.

    Parameters
    ----------
    request:
        The original fetch request (used for URL-based content-type hints).
    response:
        The response produced by the current fetch attempt.
    current_mode:
        The fetch mode that produced *response*.  Used to contextualise
        browser-mode signals (e.g. script_timeout only makes sense for
        headless/stealth).
    domain_policy:
        Optional domain policy — currently reserved for future use but
        accepted so the orchestrator can pass it through uniformly.

    Returns
    -------
    FetchSignals
        All signals set based on explicit evidence in *response*.  Never ``None``.

    Notes
    -----
    The extractor never inspects the request/response for anything beyond the
    documented signal rules.  If a signal's required evidence is absent, the
    signal remains ``False``.
    """
    body = response.body or ""
    headers = response.headers or {}
    error_type = response.error_type or ""
    error_message = response.error_message or ""
    content_type = _get_content_type(headers, body)
    metadata: dict = getattr(response, "metadata", {}) or {}

    signals = FetchSignals(
        # JavaScript / rendering
        js_required=_detect_js_required(body, content_type),
        blank_html=_detect_blank_html(body, content_type),
        hydration_error=_detect_hydration_error(body),
        script_timeout=_detect_script_timeout(error_type, error_message, metadata, current_mode),

        # Anti-bot / security
        cloudflare_challenge=_detect_cloudflare(body, headers),
        datadome_block=_detect_datadome(body),
        perimeterx_block=_detect_perimeterx(body),
        akamai_bot_detected=_detect_akamai(body),
        captcha_present=_detect_captcha(body),

        # Content-type
        json_endpoint_detected=_detect_json(content_type, body),
        xml_feed=_detect_xml(content_type, body),
        static_asset=_detect_static_asset(content_type, request.url),

        # Network / protocol
        redirect_loop=_detect_redirect_loop(error_type, metadata),
        ssl_error=_detect_ssl_error(error_type),
        connection_reset=_detect_connection_reset(error_type, error_message),

        # Quality / structure
        malformed_html=_detect_malformed_html(metadata),
        empty_body=_detect_empty_body(body),
        suspicious_meta_refresh=_detect_meta_refresh(body),

        reasoning="",
    )

    # Build reasoning string
    raised = signals.raised_signals
    if raised:
        signals = _with_reasoning(signals, f"detected: {', '.join(raised)}")
    else:
        signals = _with_reasoning(signals, "no unusual signals detected")
    return signals


# ---------------------------------------------------------------------------
# Helper: dataclass field replacement (frozen)
# ---------------------------------------------------------------------------


def _with_reasoning(signals: FetchSignals, reasoning: str) -> FetchSignals:
    """Return a copy of *signals* with *reasoning* set."""
    return FetchSignals(
        js_required=signals.js_required,
        blank_html=signals.blank_html,
        hydration_error=signals.hydration_error,
        script_timeout=signals.script_timeout,
        cloudflare_challenge=signals.cloudflare_challenge,
        datadome_block=signals.datadome_block,
        perimeterx_block=signals.perimeterx_block,
        akamai_bot_detected=signals.akamai_bot_detected,
        captcha_present=signals.captcha_present,
        json_endpoint_detected=signals.json_endpoint_detected,
        xml_feed=signals.xml_feed,
        static_asset=signals.static_asset,
        redirect_loop=signals.redirect_loop,
        ssl_error=signals.ssl_error,
        connection_reset=signals.connection_reset,
        malformed_html=signals.malformed_html,
        empty_body=signals.empty_body,
        suspicious_meta_refresh=signals.suspicious_meta_refresh,
        reasoning=reasoning,
    )


# ---------------------------------------------------------------------------
# Content-type extraction
# ---------------------------------------------------------------------------


def _get_content_type(headers: dict[str, str], body: str) -> str:
    """Extract the content-type from headers (case-insensitive), falling back to inference."""
    for key, value in headers.items():
        if key.lower() == "content-type":
            # Strip charset and other parameters
            return value.split(";")[0].strip().lower()
    # Fallback: sniff from body
    if body and body.strip():
        return _sniff_content_type(body)
    return ""


def _sniff_content_type(body: str) -> str:
    """Infer content-type from body contents when no header is present."""
    stripped = body.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return _APPLICATION_JSON
    if stripped.startswith("<"):
        if stripped.startswith("<?xml"):
            return _APPLICATION_XML
        return _TEXT_HTML
    return ""


# ---------------------------------------------------------------------------
# 1. JavaScript / rendering signals
# ---------------------------------------------------------------------------

# Markers indicating a JS framework that likely requires a browser to render
_JS_FRAMEWORK_MARKERS: tuple[re.Pattern, ...] = (
    re.compile(r'<div\s[^>]*\bid\s*=\s*["\'](?:app|root|__next|__nuxt|react-root)', re.I),
    re.compile(r'<script[^>]*\bsrc\s*=\s*["\'][^"\']*(?:react|vue|angular|next|nuxt)', re.I),
    re.compile(r'__NEXT_DATA__', re.I),
    re.compile(r'window\.__NUXT__', re.I),
    re.compile(r'ng-version\s*=', re.I),
    re.compile(r'data-reactroot', re.I),
    re.compile(r'<div\s[^>]*\bdata-v-', re.I),  # Vue scoped styles
)

# Known hydration error strings
_HYDRATION_ERRORS: tuple[str, ...] = (
    "Hydration failed",
    "Expected server HTML",
    "did not match",
    "Hydration completed but",
    "A tree hydrated but some",
    "Text content does not match",
    "An error occurred during hydration",
    "Minified React error #418",  # hydration mismatch
    "Minified React error #419",  # hydration mismatch
    "Minified React error #422",  # hydration mismatch
    "Minified React error #423",  # hydration mismatch
    "Minified React error #425",  # hydration mismatch
)


def _detect_js_required(body: str, content_type: str) -> bool:
    """True if the response requires JS to render meaningful content."""
    # Only relevant for HTML responses
    if content_type and content_type != _TEXT_HTML:
        return False
    if not body:
        return False
    for pattern in _JS_FRAMEWORK_MARKERS:
        if pattern.search(body):
            return True
    # Blank body with script tags
    if len(body.strip()) < 200:
        if "<script" in body.lower():
            return True
    return False


def _detect_blank_html(body: str, content_type: str) -> bool:
    """True if the body is too short to be meaningful HTML."""
    if content_type and content_type != _TEXT_HTML:
        return False
    stripped = body.strip()
    if len(stripped) < 200:
        return True
    # Skeleton-only: just html/head/body tags with no real content
    skeleton_patterns = (
        re.compile(r'^<!DOCTYPE\s+html>\s*<html[^>]*>\s*<head[^>]*>\s*</head>\s*<body[^>]*>\s*</body>\s*</html>\s*$', re.I),
    )
    for pattern in skeleton_patterns:
        if pattern.match(stripped):
            return True
    return False


def _detect_hydration_error(body: str) -> bool:
    """True if the body contains known hydration error strings."""
    if not body:
        return False
    for marker in _HYDRATION_ERRORS:
        if marker.lower() in body.lower():
            return True
    return False


def _detect_script_timeout(
    error_type: str,
    error_message: str,
    metadata: dict,
    current_mode: FetchMode,
) -> bool:
    """True if a browser-mode JS timeout occurred."""
    if error_type.lower() == "scripttimeouterror":
        return True
    if error_message and "script timeout" in error_message.lower():
        return True
    # Browser-mode metadata may carry js_timeout flag
    if metadata.get("js_timeout") or metadata.get("script_timeout"):
        return True
    # Only relevant for browser modes
    if current_mode in ("http_headless_browser", "http_stealth"):
        error_lower = (error_type + " " + error_message).lower()
        if "timeout" in error_lower and "script" in error_lower:
            return True
    return False


# ---------------------------------------------------------------------------
# 2. Anti-bot / security signals
# ---------------------------------------------------------------------------


def _detect_cloudflare(body: str, headers: dict[str, str]) -> bool:
    """True if Cloudflare challenge is detected."""
    # Check headers
    for key, value in headers.items():
        if key.lower() == "cf-chl-bypass":
            return True
    # Check body for CF challenge markers
    cf_markers = (
        "cf-challenge",
        "cf-browser-verification",
        "challenge-platform",
        "cf_clearance",
        'id="cf-chl',
        "cf-spinner",
        "/cdn-cgi/challenge-platform",
        "Checking your browser before accessing",
        "Please turn JavaScript on and reload the page",
        "cf-browser-check",
        "jschl-answer",
        "jschl_vc",
        "cf_chl_",
        "cloudflarechl",
    )
    body_lower = body.lower()
    for marker in cf_markers:
        if marker.lower() in body_lower:
            return True
    return False


def _detect_datadome(body: str) -> bool:
    """True if Datadome block is detected."""
    dd_markers = (
        "datadome",
        "dd-browser-check",
        "Please prove you are not a robot",
        "datadome-client",
    )
    body_lower = body.lower()
    for marker in dd_markers:
        if marker.lower() in body_lower:
            return True
    return False


def _detect_perimeterx(body: str) -> bool:
    """True if PerimeterX block is detected."""
    px_markers = (
        "perimeterx",
        "_pxCaptcha",
        "PX",  # too short — only match with surrounding fingerprint markers
        "window._pxAppId",
        "px-captcha",
        "human security",
    )
    body_lower = body.lower()
    # PX alone is too ambiguous; require co-occurrence
    px_found = False
    for marker in px_markers:
        if marker.lower() in body_lower:
            if marker.lower() == "px" and not px_found:
                # Require at least one other PX marker
                continue
            px_found = True
    return px_found


def _detect_akamai(body: str) -> bool:
    """True if Akamai bot detection is detected."""
    akamai_markers = (
        "akamai",
        "ak_bmsc",
        "bmpixel",
        "akamai-bot",
        "botdetect",
        "reference number",
        "akamai-edge",
    )
    body_lower = body.lower()
    for marker in akamai_markers:
        if marker.lower() in body_lower:
            return True
    return False


def _detect_captcha(body: str) -> bool:
    """True if captcha is present in the response."""
    captcha_markers = (
        "g-recaptcha",
        "h-captcha",
        "hcaptcha",
        "recaptcha",
        "cf-turnstile",
        "funCaptcha",
        "arkose",
        "are you a robot",
        "captcha",
        "challenge-form",
        "verify you are human",
        "not a robot",
    )
    body_lower = body.lower()
    for marker in captcha_markers:
        if marker.lower() in body_lower:
            return True
    return False


# ---------------------------------------------------------------------------
# 3. Content-type signals
# ---------------------------------------------------------------------------


def _detect_json(content_type: str, body: str) -> bool:
    """True if the response is JSON."""
    if content_type == _APPLICATION_JSON:
        return True
    if content_type and "+json" in content_type:
        return True
    # Try to parse body as JSON
    if body and body.strip():
        try:
            json.loads(body)
            return True
        except (json.JSONDecodeError, ValueError):
            pass
    return False


def _detect_xml(content_type: str, body: str) -> bool:
    """True if the response is XML."""
    if content_type in (_APPLICATION_XML, _TEXT_XML):
        return True
    if content_type and "+xml" in content_type:
        return True
    # Sniff body
    if body and body.strip().startswith("<?xml"):
        return True
    return False


def _detect_static_asset(content_type: str, url: str) -> bool:
    """True if the response is a static asset (image, video, font, CSS, JS, PDF, etc.)."""
    if not content_type:
        # Try URL-based detection
        url_lower = url.lower()
        static_extensions = (
            ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg",
            ".ico", ".woff", ".woff2", ".ttf", ".eot", ".otf",
            ".mp4", ".webm", ".ogg", ".mp3", ".wav",
            ".pdf", ".zip", ".tar", ".gz", ".bz2",
            ".webp", ".avif",
        )
        for ext in static_extensions:
            if url_lower.endswith(ext) or f"{ext}?" in url_lower or f"{ext}#" in url_lower:
                return True
        return False

    static_ct_prefixes = (
        "image/", "video/", "audio/",
        "application/pdf",
        "application/zip",
        "application/gzip",
        "application/x-tar",
        "application/x-font",
        "font/",
        "text/css",
        "application/javascript",
        "text/javascript",
        "application/x-javascript",
    )
    for prefix in static_ct_prefixes:
        if content_type.startswith(prefix):
            return True
    return False


# ---------------------------------------------------------------------------
# 4. Network / protocol signals
# ---------------------------------------------------------------------------


def _detect_redirect_loop(error_type: str, metadata: dict) -> bool:
    """True if a redirect loop is detected."""
    if error_type.lower() in ("redirectlooperror", "toomanyredirects"):
        return True
    redirect_count = metadata.get("redirect_count", 0)
    if isinstance(redirect_count, (int, float)) and redirect_count > 5:
        return True
    return False


def _detect_ssl_error(error_type: str) -> bool:
    """True if an SSL/TLS error occurred."""
    return error_type.lower() in (
        "sslerror",
        "tlserror",
        "certificateerror",
        "sslcertverificationerror",
    )


def _detect_connection_reset(error_type: str, error_message: str) -> bool:
    """True if the connection was reset."""
    if error_type.lower() in ("connectionreseterror", "connectionreset"):
        return True
    combined = (error_type + " " + error_message).lower()
    reset_markers = ("connection reset", "connection refused", "econnreset", "econnrefused")
    for marker in reset_markers:
        if marker in combined:
            return True
    return False


# ---------------------------------------------------------------------------
# 5. Quality / structure signals
# ---------------------------------------------------------------------------


def _detect_malformed_html(metadata: dict) -> bool:
    """True if metadata indicates HTML parse errors."""
    return bool(metadata.get("html_parse_errors") or metadata.get("parse_errors"))


def _detect_empty_body(body: str) -> bool:
    """True if the response body is completely empty."""
    return len(body or "") == 0


def _detect_meta_refresh(body: str) -> bool:
    """True if the HTML contains a meta refresh tag."""
    if not body:
        return False
    return bool(re.search(
        r'<meta[^>]*\bhttp-equiv\s*=\s*["\']refresh["\']',
        body,
        re.IGNORECASE,
    ))
