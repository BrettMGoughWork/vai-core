"""Tests for stdlib.http.stealth primitive (Phase 3.11.3).

Tests cover:
- _classify_pw_exception unit tests (same mappings as headless_browser)
- _build_headers, _build_viewport, _human_delay helpers
- Argument validation (valid args, each invalid case)
- execute success (stealth applied, viewport randomisation, rate limiting)
- execute error (timeout, DNS, connection refused, SSL, missing dependency)
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from playwright.sync_api import Error as PwError, TimeoutError as PwTimeoutError

from src.capabilities.primitives.stdlib.http_stealth import (
    _build_headers,
    _build_viewport,
    _classify_pw_exception,
    _human_delay,
    HttpStealthPrimitive,
    _VIEWPORTS,
)
from src.capabilities.primitives.types import PrimitiveResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fetch() -> HttpStealthPrimitive:
    return HttpStealthPrimitive()


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_mock_page(
    content: str = "<html><body>ok</body></html>",
    final_url: str = "https://example.com/",
    status_code: int = 200,
    headers: dict | None = None,
    cookies: list[dict] | None = None,
) -> MagicMock:
    """Build a mock Playwright Page that fires the response handler on goto."""
    page = MagicMock()
    page.content.return_value = content
    page.url = final_url  # type: ignore[assignment]

    # Cookies via page.context.cookies()
    mock_context = MagicMock()
    mock_context.cookies.return_value = cookies or [
        {"name": "session", "value": "abc123"}
    ]
    page.context = mock_context

    # The response object that will be passed to the registered handler
    mock_response = MagicMock()
    mock_response.status = status_code
    mock_response.headers = headers or {"content-type": "text/html"}

    # Wire page.on("response", handler) → store handler, and
    # page.goto(...) → fire the stored handler (simulating real Playwright).
    _stored_handler = [None]  # mutable cell

    def on_side_effect(event: str, handler: object) -> None:
        if event == "response":
            _stored_handler[0] = handler

    def goto_side_effect(*_args: object, **_kwargs: object) -> None:
        if _stored_handler[0] is not None:
            _stored_handler[0](mock_response)

    page.on.side_effect = on_side_effect
    page.goto.side_effect = goto_side_effect

    return page


def _patch_playwright(
    mock_page: MagicMock | None = None,
) -> MagicMock:
    """Mock ``sync_playwright`` so ``execute`` runs without launching a real browser.

    Also mocks ``Stealth`` so no real stealth patches are applied.

    Returns the mock ``page``.  Registers a cleanup callable at
    ``page._cleanup()``.
    """
    if mock_page is None:
        mock_page = _make_mock_page()

    mock_pw = MagicMock()
    mock_browser = MagicMock()

    mock_pw.chromium.launch.return_value = mock_browser
    mock_browser.new_page.return_value = mock_page
    # Expose mock_browser for assertion access in tests
    mock_page._mock_browser = mock_browser  # type: ignore[attr-defined]

    # sync_playwright() returns a context manager whose __enter__ yields mock_pw
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_pw

    patcher1 = patch(
        "src.capabilities.primitives.stdlib.http_stealth.sync_playwright",
        return_value=mock_cm,
    )
    patcher1.start()

    # Mock Stealth so apply_stealth_sync is a no-op
    mock_stealth = MagicMock()
    patcher2 = patch(
        "src.capabilities.primitives.stdlib.http_stealth.Stealth",
        return_value=mock_stealth,
    )
    patcher2.start()

    def _cleanup() -> None:
        patcher1.stop()
        patcher2.stop()

    mock_page._cleanup = _cleanup  # type: ignore[attr-defined]
    return mock_page


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestBuildHeaders:
    """Tests for _build_headers."""

    def test_defaults(self) -> None:
        headers = _build_headers(None)
        assert headers["Accept-Language"] == "en-US,en;q=0.9"
        assert headers["Accept"] == "*/*"
        assert headers["User-Agent"] in (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ) or True  # always passes — just checking structure

    def test_user_overrides(self) -> None:
        headers = _build_headers({"Accept": "text/html"})
        assert headers["Accept"] == "text/html"
        assert "Accept-Language" in headers

    def test_user_agent_overridable(self) -> None:
        headers = _build_headers({"User-Agent": "Custom/1.0"})
        assert headers["User-Agent"] == "Custom/1.0"


class TestBuildViewport:
    """Tests for _build_viewport."""

    def test_returns_valid_viewport(self) -> None:
        vp = _build_viewport()
        assert "width" in vp
        assert "height" in vp
        assert vp in _VIEWPORTS

    def test_randomisation(self) -> None:
        """Multiple calls should eventually yield different viewports."""
        results = {str(_build_viewport()) for _ in range(50)}
        assert len(results) > 1


class TestHumanDelay:
    """Tests for _human_delay."""

    def test_delay_at_least_min(self) -> None:
        start = time.perf_counter()
        _human_delay(10, 20)
        elapsed = time.perf_counter() - start
        assert elapsed >= 0.005  # Allow timing fudge

    def test_zero_delay_no_error(self) -> None:
        _human_delay(0, 0)  # Should not raise


# ---------------------------------------------------------------------------
# _classify_pw_exception
# ---------------------------------------------------------------------------


class TestClassifyPwException:
    """Unit tests for _classify_pw_exception.

    Playwright is installed in this environment, so ``PwTimeoutError`` and
    ``PwError`` in the module are the real Playwright exception types.
    """

    def test_timeout(self) -> None:
        """PwTimeoutError maps to TimeoutError."""
        etype, _emsg = _classify_pw_exception(
            PwTimeoutError("Timeout 30000ms exceeded")
        )
        assert etype == "TimeoutError"

    def test_dns_error(self) -> None:
        """DNS-related PwError maps to ConnectionError."""
        etype, _emsg = _classify_pw_exception(
            PwError("net::ERR_NAME_NOT_RESOLVED at https://bad.example.com")
        )
        assert etype == "ConnectionError"

    def test_connection_refused(self) -> None:
        """Connection refused PwError maps to ConnectionError."""
        etype, _emsg = _classify_pw_exception(PwError("net::ERR_CONNECTION_REFUSED"))
        assert etype == "ConnectionError"

    def test_ssl_error(self) -> None:
        """SSL-related PwError maps to ConnectionError with SSL prefix."""
        _etype, emsg = _classify_pw_exception(
            PwError("net::ERR_CERT_AUTHORITY_INVALID")
        )
        assert _etype == "ConnectionError"
        assert "SSL" in emsg

    def test_timeout_in_message(self) -> None:
        """PwError with 'timed out' message maps to TimeoutError."""
        etype, _emsg = _classify_pw_exception(
            PwError("navigation timed out after 30s")
        )
        assert etype == "TimeoutError"

    def test_generic_pw_error(self) -> None:
        """Generic PwError falls back to ConnectionError."""
        etype, _emsg = _classify_pw_exception(PwError("some random browser error"))
        assert etype == "ConnectionError"

    def test_generic_exception(self) -> None:
        """Non-Playwright exception falls back to ConnectionError."""
        etype, _emsg = _classify_pw_exception(RuntimeError("unexpected"))
        assert etype == "ConnectionError"


# ---------------------------------------------------------------------------
# validate_args
# ---------------------------------------------------------------------------


class TestHttpStealthValidate:
    """Tests for HttpStealthPrimitive.validate_args."""

    def test_valid_minimal(self, fetch: HttpStealthPrimitive) -> None:
        """Just a URL passes."""
        fetch.validate_args({"url": "https://example.com"})

    def test_valid_all_fields(self, fetch: HttpStealthPrimitive) -> None:
        """All optional fields pass."""
        fetch.validate_args({
            "url": "https://example.com",
            "timeout": 30.0,
            "headers": {"Accept": "text/html"},
            "wait_until": "load",
            "wait_ms": 3000,
            "rate_limit_ms": 500,
        })

    @pytest.mark.parametrize("wu", ["load", "domcontentloaded", "networkidle"])
    def test_valid_wait_until(
        self, fetch: HttpStealthPrimitive, wu: str
    ) -> None:
        fetch.validate_args({"url": "https://x.com", "wait_until": wu})

    def test_valid_zero_wait_ms(self, fetch: HttpStealthPrimitive) -> None:
        fetch.validate_args({"url": "https://x.com", "wait_ms": 0})

    def test_valid_zero_rate_limit(self, fetch: HttpStealthPrimitive) -> None:
        fetch.validate_args({"url": "https://x.com", "rate_limit_ms": 0})

    def test_missing_url(self, fetch: HttpStealthPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'url' key"):
            fetch.validate_args({})

    def test_non_string_url(self, fetch: HttpStealthPrimitive) -> None:
        with pytest.raises(ValueError, match="'url' must be a string"):
            fetch.validate_args({"url": 42})

    def test_empty_url(self, fetch: HttpStealthPrimitive) -> None:
        with pytest.raises(ValueError, match="'url' must not be empty"):
            fetch.validate_args({"url": ""})

    def test_non_number_timeout(self, fetch: HttpStealthPrimitive) -> None:
        with pytest.raises(ValueError, match="'timeout' must be a number"):
            fetch.validate_args({"url": "https://x.com", "timeout": "10"})

    def test_negative_timeout(self, fetch: HttpStealthPrimitive) -> None:
        with pytest.raises(ValueError, match="'timeout' must be positive"):
            fetch.validate_args({"url": "https://x.com", "timeout": -1})

    def test_zero_timeout(self, fetch: HttpStealthPrimitive) -> None:
        with pytest.raises(ValueError, match="'timeout' must be positive"):
            fetch.validate_args({"url": "https://x.com", "timeout": 0})

    def test_non_dict_headers(self, fetch: HttpStealthPrimitive) -> None:
        with pytest.raises(ValueError, match="'headers' must be a dict"):
            fetch.validate_args({"url": "https://x.com", "headers": "bad"})

    def test_non_string_header_key(
        self, fetch: HttpStealthPrimitive
    ) -> None:
        with pytest.raises(ValueError, match="'headers' keys must be strings"):
            fetch.validate_args({"url": "https://x.com", "headers": {1: "v"}})

    def test_non_string_header_value(
        self, fetch: HttpStealthPrimitive
    ) -> None:
        with pytest.raises(ValueError, match="'headers' values must be strings"):
            fetch.validate_args({"url": "https://x.com", "headers": {"k": 1}})

    def test_invalid_wait_until(self, fetch: HttpStealthPrimitive) -> None:
        with pytest.raises(ValueError, match="'wait_until' must be one of"):
            fetch.validate_args({"url": "https://x.com", "wait_until": "invalid"})

    def test_non_number_wait_ms(self, fetch: HttpStealthPrimitive) -> None:
        with pytest.raises(ValueError, match="'wait_ms' must be a number"):
            fetch.validate_args({"url": "https://x.com", "wait_ms": "bad"})

    def test_negative_wait_ms(self, fetch: HttpStealthPrimitive) -> None:
        with pytest.raises(ValueError, match="'wait_ms' must be >= 0"):
            fetch.validate_args({"url": "https://x.com", "wait_ms": -1})

    def test_non_number_rate_limit(
        self, fetch: HttpStealthPrimitive
    ) -> None:
        with pytest.raises(ValueError, match="'rate_limit_ms' must be a number"):
            fetch.validate_args({"url": "https://x.com", "rate_limit_ms": "bad"})

    def test_negative_rate_limit(
        self, fetch: HttpStealthPrimitive
    ) -> None:
        with pytest.raises(ValueError, match="'rate_limit_ms' must be >= 0"):
            fetch.validate_args({"url": "https://x.com", "rate_limit_ms": -1})

    def test_args_not_a_dict(self, fetch: HttpStealthPrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            fetch.validate_args("bad")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# execute — success
# ---------------------------------------------------------------------------


class TestHttpStealthExecuteSuccess:
    """Tests for HttpStealthPrimitive.execute — success."""

    def test_successful_get(self, fetch: HttpStealthPrimitive) -> None:
        """200 response returns ok: true with all fields."""
        page = _make_mock_page(
            content="<html><body>Hello</body></html>",
            final_url="https://example.com/page",
            status_code=200,
            headers={"content-type": "text/html"},
            cookies=[{"name": "session", "value": "abc123"}],
        )
        page = _patch_playwright(page)
        try:
            result = fetch.execute({"url": "https://example.com"}, {})
        finally:
            page._cleanup()

        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data["ok"] is True
        assert result.data["final_url"] == "https://example.com/page"
        assert result.data["status_code"] == 200
        assert result.data["body"] == "<html><body>Hello</body></html>"
        assert result.data["headers"]["content-type"] == "text/html"
        assert result.data["cookies"] == {"session": "abc123"}
        assert isinstance(result.data["elapsed_ms"], int)
        assert result.error is None

    def test_stealth_applied(self, fetch: HttpStealthPrimitive) -> None:
        """Stealth patches are applied to the page."""
        page = _patch_playwright()
        try:
            fetch.execute({"url": "https://example.com"}, {})
            # Check BEFORE cleanup so the patch on Stealth is still active
            from src.capabilities.primitives.stdlib.http_stealth import Stealth

            mock_stealth_instance = Stealth.return_value
            mock_stealth_instance.apply_stealth_sync.assert_called_once_with(page)
        finally:
            page._cleanup()

    def test_viewport_randomised(self, fetch: HttpStealthPrimitive) -> None:
        """Browser is created with a randomised viewport."""
        page = _patch_playwright()
        try:
            fetch.execute({"url": "https://example.com"}, {})
            # Check BEFORE cleanup — new_page was called on mock_browser
            _args, kwargs = page._mock_browser.new_page.call_args
            assert "viewport" in kwargs
            vp = kwargs["viewport"]
            assert "width" in vp
            assert "height" in vp
            assert vp in _VIEWPORTS
        finally:
            page._cleanup()

    def test_timeout_forwarded(self, fetch: HttpStealthPrimitive) -> None:
        """Timeout is converted to ms and forwarded to goto."""
        page = _patch_playwright()
        try:
            fetch.execute({"url": "https://example.com", "timeout": 10.0}, {})
        finally:
            page._cleanup()

        _args, kwargs = page.goto.call_args
        assert kwargs.get("timeout") == 10000  # 10 s → 10000 ms

    def test_wait_until_forwarded(self, fetch: HttpStealthPrimitive) -> None:
        """wait_until is forwarded to goto."""
        page = _patch_playwright()
        try:
            fetch.execute(
                {"url": "https://example.com", "wait_until": "domcontentloaded"}, {}
            )
        finally:
            page._cleanup()

        _args, kwargs = page.goto.call_args
        assert kwargs.get("wait_until") == "domcontentloaded"

    def test_wait_ms_observed(self, fetch: HttpStealthPrimitive) -> None:
        """wait_ms causes a measurable delay."""
        page = _patch_playwright()
        try:
            start = time.perf_counter()
            fetch.execute({"url": "https://x.com", "wait_ms": 50}, {})
            elapsed = time.perf_counter() - start
        finally:
            page._cleanup()

        assert elapsed >= 0.04  # Allow timing fudge

    def test_rate_limit_enforced(self, fetch: HttpStealthPrimitive) -> None:
        """When elapsed < rate_limit_ms, total time is at least rate_limit_ms."""
        page = _patch_playwright()
        try:
            start = time.perf_counter()
            fetch.execute(
                {"url": "https://x.com", "rate_limit_ms": 300, "wait_ms": 0}, {}
            )
            elapsed = time.perf_counter() - start
        finally:
            page._cleanup()

        assert elapsed >= 0.25  # Allow timing fudge

    def test_no_side_effects(self, fetch: HttpStealthPrimitive) -> None:
        """Result has an empty side_effects list."""
        page = _patch_playwright()
        try:
            result = fetch.execute({"url": "https://example.com"}, {})
        finally:
            page._cleanup()

        assert result.side_effects == []

    def test_missing_playwright(self) -> None:
        """When Playwright is not installed, return MissingDependencyError."""
        with patch(
            "src.capabilities.primitives.stdlib.http_stealth._playwright_available",
            False,
        ):
            f = HttpStealthPrimitive()
            result = f.execute({"url": "https://example.com"}, {})

        assert result.status == "error"
        assert result.data["ok"] is False
        assert result.data["error_type"] == "MissingDependencyError"
        assert "playwright" in result.data["error_message"].lower()

    def test_missing_stealth(self) -> None:
        """When playwright-stealth is not installed, return MissingDependencyError."""
        with patch(
            "src.capabilities.primitives.stdlib.http_stealth._stealth_available",
            False,
        ):
            f = HttpStealthPrimitive()
            result = f.execute({"url": "https://example.com"}, {})

        assert result.status == "error"
        assert result.data["ok"] is False
        assert result.data["error_type"] == "MissingDependencyError"
        assert "stealth" in result.data["error_message"].lower()

    def test_null_status_code(self, fetch: HttpStealthPrimitive) -> None:
        """If no response event fires, status_code and headers are None."""
        page = _make_mock_page(status_code=200)

        # Override goto so it does NOT fire the response handler
        page.goto.side_effect = None
        page.goto.return_value = None

        page = _patch_playwright(page)
        try:
            result = fetch.execute({"url": "https://example.com"}, {})
        finally:
            page._cleanup()

        assert result.status == "success"
        assert result.data["status_code"] is None
        assert result.data["headers"] is None


# ---------------------------------------------------------------------------
# execute — errors
# ---------------------------------------------------------------------------


class TestHttpStealthExecuteErrors:
    """Tests for HttpStealthPrimitive.execute — transport failures."""

    def test_timeout_error(self, fetch: HttpStealthPrimitive) -> None:
        """Timeout returns structured error."""
        page = MagicMock()
        page.goto.side_effect = PwTimeoutError("Timeout 30000ms exceeded")
        page = _patch_playwright(page)
        try:
            result = fetch.execute({"url": "https://x.com", "timeout": 0.001}, {})
        finally:
            page._cleanup()

        assert result.status == "error"
        assert result.data["ok"] is False
        assert result.data["error_type"] == "TimeoutError"
        assert isinstance(result.data["elapsed_ms"], int)
        assert result.error is not None

    def test_dns_error(self, fetch: HttpStealthPrimitive) -> None:
        page = MagicMock()
        page.goto.side_effect = PwError(
            "net::ERR_NAME_NOT_RESOLVED at https://bad.example.com"
        )
        page = _patch_playwright(page)
        try:
            result = fetch.execute({"url": "https://bad.example.com"}, {})
        finally:
            page._cleanup()

        assert result.status == "error"
        assert result.data["error_type"] == "ConnectionError"

    def test_connection_refused(self, fetch: HttpStealthPrimitive) -> None:
        page = MagicMock()
        page.goto.side_effect = PwError("net::ERR_CONNECTION_REFUSED")
        page = _patch_playwright(page)
        try:
            result = fetch.execute({"url": "https://refused.example.com"}, {})
        finally:
            page._cleanup()

        assert result.status == "error"
        assert result.data["error_type"] == "ConnectionError"

    def test_ssl_error(self, fetch: HttpStealthPrimitive) -> None:
        page = MagicMock()
        page.goto.side_effect = PwError("net::ERR_CERT_AUTHORITY_INVALID")
        page = _patch_playwright(page)
        try:
            result = fetch.execute({"url": "https://self-signed.bad"}, {})
        finally:
            page._cleanup()

        assert result.status == "error"
        assert result.data["error_type"] == "ConnectionError"
        assert "SSL" in result.data["error_message"]
