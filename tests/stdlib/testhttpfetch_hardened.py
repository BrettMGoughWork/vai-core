"""Tests for stdlib.http.hardened primitive (Phase 3.11.1)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from src.capabilities.primitives.stdlib._http_hardened import (
    _DEFAULT_HEADERS,
    HttpHardenedFetchPrimitive,
    _classify_curl_exception,
)
from src.capabilities.primitives.types import PrimitiveResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fetch() -> HttpHardenedFetchPrimitive:
    """Real HttpHardenedFetchPrimitive instance."""
    return HttpHardenedFetchPrimitive()


# ---------------------------------------------------------------------------
# Mock helper
# ---------------------------------------------------------------------------


def _make_mock_response(
    status_code: int = 200,
    text: str = "ok",
    headers: dict | None = None,
    cookies: dict | None = None,
) -> MagicMock:
    """Build a minimal mock curl_cffi Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.headers = headers or {"content-type": "text/plain"}
    mock_cookies = MagicMock()
    mock_cookies.items.return_value = (cookies or {}).items()
    resp.cookies = mock_cookies
    return resp


def _patch_session(
    mock_responses: MagicMock | list[MagicMock] | list[Exception],
) -> MagicMock:
    """Patch ``http_hardened.Session`` so ``.get()`` yields ``mock_responses``.

    Accepts a single mock response, a list of responses, or a list mixing
    responses and exceptions (for retry scenarios).
    Returns the mock session instance for additional assertions.
    """
    session_instance = MagicMock()

    if isinstance(mock_responses, list):
        session_instance.get.side_effect = mock_responses
    else:
        session_instance.get.return_value = mock_responses

    mock_session_cls = MagicMock(return_value=session_instance)

    patcher = patch(
        "src.capabilities.primitives.stdlib._http_hardened.Session",
        mock_session_cls,
    )
    patcher.start()

    def _cleanup() -> None:
        patcher.stop()

    session_instance._cleanup = _cleanup  # type: ignore[attr-defined]
    return session_instance


# ---------------------------------------------------------------------------
# _classify_curl_exception
# ---------------------------------------------------------------------------


class TestClassifyCurlException:
    """Unit tests for _classify_curl_exception."""

    def _make_exc(self, exc_cls: type, msg: str = "something went wrong"):
        return exc_cls(msg)

    def test_timeout(self) -> None:
        """Timeout maps to TimeoutError."""
        from curl_cffi.requests.exceptions import Timeout

        etype, emsg = _classify_curl_exception(self._make_exc(Timeout))
        assert etype == "TimeoutError"

    def test_connect_timeout(self) -> None:
        """ConnectTimeout maps to TimeoutError."""
        from curl_cffi.requests.exceptions import ConnectTimeout

        etype, emsg = _classify_curl_exception(self._make_exc(ConnectTimeout))
        assert etype == "TimeoutError"

    def test_read_timeout(self) -> None:
        """ReadTimeout maps to TimeoutError."""
        from curl_cffi.requests.exceptions import ReadTimeout

        etype, emsg = _classify_curl_exception(self._make_exc(ReadTimeout))
        assert etype == "TimeoutError"

    def test_connection_error(self) -> None:
        """ConnectionError maps to ConnectionError."""
        from curl_cffi.requests.exceptions import ConnectionError as CurlConnErr

        etype, emsg = _classify_curl_exception(self._make_exc(CurlConnErr))
        assert etype == "ConnectionError"

    def test_dns_error(self) -> None:
        """DNSError maps to ConnectionError."""
        from curl_cffi.requests.exceptions import DNSError

        etype, emsg = _classify_curl_exception(self._make_exc(DNSError))
        assert etype == "ConnectionError"

    def test_proxy_error(self) -> None:
        """ProxyError maps to ConnectionError."""
        from curl_cffi.requests.exceptions import ProxyError

        etype, emsg = _classify_curl_exception(self._make_exc(ProxyError))
        assert etype == "ConnectionError"

    def test_ssl_error(self) -> None:
        """SSLError maps to ConnectionError."""
        from curl_cffi.requests.exceptions import SSLError

        etype, emsg = _classify_curl_exception(self._make_exc(SSLError))
        assert etype == "ConnectionError"
        assert "SSL" in emsg or "connection" in emsg.lower()

    def test_invalid_url(self) -> None:
        """InvalidURL maps to ParseError."""
        from curl_cffi.requests.exceptions import InvalidURL

        etype, emsg = _classify_curl_exception(self._make_exc(InvalidURL))
        assert etype == "ParseError"

    def test_missing_schema(self) -> None:
        """MissingSchema maps to ParseError."""
        from curl_cffi.requests.exceptions import MissingSchema

        etype, emsg = _classify_curl_exception(self._make_exc(MissingSchema))
        assert etype == "ParseError"

    def test_http_error(self) -> None:
        """HTTPError maps to HTTPError."""
        from curl_cffi.requests.exceptions import HTTPError as CurlHTTPErr

        etype, emsg = _classify_curl_exception(self._make_exc(CurlHTTPErr))
        assert etype == "HTTPError"

    def test_generic_curl_error(self) -> None:
        """Generic RequestException falls back to ConnectionError."""
        from curl_cffi.requests.exceptions import RequestException

        etype, emsg = _classify_curl_exception(
            self._make_exc(RequestException, "weird error")
        )
        assert etype == "ConnectionError"
        assert "weird" in emsg


# ---------------------------------------------------------------------------
# validate_args
# ---------------------------------------------------------------------------


class TestHttpHardenedValidate:
    """Tests for HttpHardenedFetchPrimitive.validate_args."""

    def test_valid_minimal_args(self, fetch: HttpHardenedFetchPrimitive) -> None:
        """Just a URL passes validation."""
        fetch.validate_args({"url": "https://example.com"})

    def test_valid_with_all_args(self, fetch: HttpHardenedFetchPrimitive) -> None:
        """All optional fields pass validation."""
        fetch.validate_args({
            "url": "https://example.com",
            "timeout": 10.0,
            "headers": {"Accept": "application/json"},
            "max_retries": 5,
            "backoff_base_ms": 500,
        })

    def test_valid_zero_retries(self, fetch: HttpHardenedFetchPrimitive) -> None:
        """max_retries=0 is valid (no retries)."""
        fetch.validate_args({"url": "https://example.com", "max_retries": 0})

    def test_missing_url_raises(self, fetch: HttpHardenedFetchPrimitive) -> None:
        """Missing 'url' key raises ValueError."""
        with pytest.raises(ValueError, match="must contain 'url' key"):
            fetch.validate_args({})

    def test_non_string_url_raises(self, fetch: HttpHardenedFetchPrimitive) -> None:
        """Non-string url raises ValueError."""
        with pytest.raises(ValueError, match="'url' must be a string"):
            fetch.validate_args({"url": 42})

    def test_empty_url_raises(self, fetch: HttpHardenedFetchPrimitive) -> None:
        """Empty url raises ValueError."""
        with pytest.raises(ValueError, match="'url' must not be empty"):
            fetch.validate_args({"url": ""})

    def test_non_number_timeout_raises(
        self, fetch: HttpHardenedFetchPrimitive
    ) -> None:
        """Non-number timeout raises ValueError."""
        with pytest.raises(ValueError, match="'timeout' must be a number"):
            fetch.validate_args({"url": "https://x.com", "timeout": "10"})

    def test_negative_timeout_raises(
        self, fetch: HttpHardenedFetchPrimitive
    ) -> None:
        """Non-positive timeout raises ValueError."""
        with pytest.raises(ValueError, match="'timeout' must be positive"):
            fetch.validate_args({"url": "https://x.com", "timeout": -1})

    def test_zero_timeout_raises(self, fetch: HttpHardenedFetchPrimitive) -> None:
        """Zero timeout raises ValueError."""
        with pytest.raises(ValueError, match="'timeout' must be positive"):
            fetch.validate_args({"url": "https://x.com", "timeout": 0})

    def test_non_dict_headers_raises(
        self, fetch: HttpHardenedFetchPrimitive
    ) -> None:
        """Non-dict headers raises ValueError."""
        with pytest.raises(ValueError, match="'headers' must be a dict"):
            fetch.validate_args({"url": "https://x.com", "headers": "bad"})

    def test_non_string_header_key_raises(
        self, fetch: HttpHardenedFetchPrimitive
    ) -> None:
        """Non-string header key raises ValueError."""
        with pytest.raises(ValueError, match="'headers' keys must be strings"):
            fetch.validate_args({"url": "https://x.com", "headers": {1: "v"}})

    def test_non_string_header_value_raises(
        self, fetch: HttpHardenedFetchPrimitive
    ) -> None:
        """Non-string header value raises ValueError."""
        with pytest.raises(ValueError, match="'headers' values must be strings"):
            fetch.validate_args({"url": "https://x.com", "headers": {"k": 1}})

    def test_non_int_max_retries_raises(
        self, fetch: HttpHardenedFetchPrimitive
    ) -> None:
        """Non-int max_retries raises ValueError."""
        with pytest.raises(ValueError, match="'max_retries' must be an integer"):
            fetch.validate_args({"url": "https://x.com", "max_retries": 1.5})

    def test_negative_max_retries_raises(
        self, fetch: HttpHardenedFetchPrimitive
    ) -> None:
        """Negative max_retries raises ValueError."""
        with pytest.raises(ValueError, match="'max_retries' must be >= 0"):
            fetch.validate_args({"url": "https://x.com", "max_retries": -1})

    def test_non_number_backoff_raises(
        self, fetch: HttpHardenedFetchPrimitive
    ) -> None:
        """Non-number backoff_base_ms raises ValueError."""
        with pytest.raises(
            ValueError, match="'backoff_base_ms' must be a number"
        ):
            fetch.validate_args({"url": "https://x.com", "backoff_base_ms": "bad"})

    def test_zero_backoff_raises(
        self, fetch: HttpHardenedFetchPrimitive
    ) -> None:
        """Zero backoff_base_ms raises ValueError."""
        with pytest.raises(
            ValueError, match="'backoff_base_ms' must be positive"
        ):
            fetch.validate_args({"url": "https://x.com", "backoff_base_ms": 0})

    def test_negative_backoff_raises(
        self, fetch: HttpHardenedFetchPrimitive
    ) -> None:
        """Negative backoff_base_ms raises ValueError."""
        with pytest.raises(
            ValueError, match="'backoff_base_ms' must be positive"
        ):
            fetch.validate_args({"url": "https://x.com", "backoff_base_ms": -100})

    def test_args_not_a_dict_raises(
        self, fetch: HttpHardenedFetchPrimitive
    ) -> None:
        """Non-dict args raises ValueError."""
        with pytest.raises(ValueError, match="args must be a dict"):
            fetch.validate_args("bad")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# execute — success cases
# ---------------------------------------------------------------------------


class TestHttpHardenedExecuteSuccess:
    """Tests for HttpHardenedFetchPrimitive.execute — successful responses."""

    def test_successful_get(self, fetch: HttpHardenedFetchPrimitive) -> None:
        """A 200 response returns ok: true with body, headers, cookies."""
        mock_resp = _make_mock_response(
            status_code=200,
            text='{"hello": "world"}',
            headers={"content-type": "application/json"},
            cookies={"session": "abc123"},
        )
        session = _patch_session(mock_resp)
        try:
            result = fetch.execute({"url": "https://api.example.com/data"}, {})
        finally:
            session._cleanup()

        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data["ok"] is True
        assert result.data["status_code"] == 200
        assert result.data["body"] == '{"hello": "world"}'
        assert result.data["headers"]["content-type"] == "application/json"
        assert result.data["cookies"] == {"session": "abc123"}
        assert isinstance(result.data["elapsed_ms"], int)
        assert result.data["elapsed_ms"] >= 0
        assert result.error is None

    def test_anti_bot_headers_applied(self, fetch: HttpHardenedFetchPrimitive) -> None:
        """Default anti-bot headers are sent with the request."""
        mock_resp = _make_mock_response()
        session = _patch_session(mock_resp)
        try:
            fetch.execute({"url": "https://x.com"}, {})
        finally:
            session._cleanup()

        call_kwargs = session.get.call_args
        assert call_kwargs is not None
        _args, kwargs = call_kwargs
        headers: dict = kwargs.get("headers", {})
        # Default anti-bot headers should be present
        for key, value in _DEFAULT_HEADERS.items():
            assert headers.get(key) == value
        # User-Agent should be set and start like a browser UA
        ua = headers.get("User-Agent", "")
        assert ua.startswith("Mozilla/5.0"), f"UA does not look like a browser: {ua!r}"

    def test_custom_headers_merged(
        self, fetch: HttpHardenedFetchPrimitive
    ) -> None:
        """Custom headers override defaults and are included."""
        mock_resp = _make_mock_response()
        session = _patch_session(mock_resp)
        try:
            fetch.execute(
                {
                    "url": "https://x.com",
                    "headers": {"Authorization": "Bearer tok", "Accept": "text/html"},
                },
                {},
            )
        finally:
            session._cleanup()

        call_kwargs = session.get.call_args
        assert call_kwargs is not None
        _args, kwargs = call_kwargs
        headers: dict = kwargs.get("headers", {})
        # User's Accept should override the default
        assert headers.get("Accept") == "text/html"
        # Authorization should be present
        assert headers.get("Authorization") == "Bearer tok"
        # Language default should still be there
        assert headers.get("Accept-Language") == "en-US,en;q=0.9"

    def test_timeout_forwarded(self, fetch: HttpHardenedFetchPrimitive) -> None:
        """Timeout is forwarded to the curl_cffi call."""
        mock_resp = _make_mock_response()
        session = _patch_session(mock_resp)
        try:
            fetch.execute({"url": "https://x.com", "timeout": 5.0}, {})
        finally:
            session._cleanup()

        call_kwargs = session.get.call_args
        assert call_kwargs is not None
        _args, kwargs = call_kwargs
        assert kwargs.get("timeout") == 5.0

    def test_impersonate_used(self, fetch: HttpHardenedFetchPrimitive) -> None:
        """The impersonate parameter is passed to curl_cffi."""
        mock_resp = _make_mock_response()
        session = _patch_session(mock_resp)
        try:
            fetch.execute({"url": "https://x.com"}, {})
        finally:
            session._cleanup()

        call_kwargs = session.get.call_args
        assert call_kwargs is not None
        _args, kwargs = call_kwargs
        assert kwargs.get("impersonate") == "chrome120"

    def test_404_returns_success_with_status(
        self, fetch: HttpHardenedFetchPrimitive
    ) -> None:
        """A 404 is returned as a success (HTTP transaction completed)."""
        mock_resp = _make_mock_response(404, text="Not Found")
        session = _patch_session(mock_resp)
        try:
            result = fetch.execute({"url": "https://x.com/notfound"}, {})
        finally:
            session._cleanup()

        assert result.status == "success"
        assert result.data["ok"] is True
        assert result.data["status_code"] == 404

    def test_no_side_effects(self, fetch: HttpHardenedFetchPrimitive) -> None:
        """Result has an empty side_effects list."""
        mock_resp = _make_mock_response()
        session = _patch_session(mock_resp)
        try:
            result = fetch.execute({"url": "https://x.com"}, {})
        finally:
            session._cleanup()

        assert result.side_effects == []


# ---------------------------------------------------------------------------
# execute — error cases
# ---------------------------------------------------------------------------


class TestHttpHardenedExecuteErrors:
    """Tests for HttpHardenedFetchPrimitive.execute — transport failures."""

    def test_timeout_error(self, fetch: HttpHardenedFetchPrimitive) -> None:
        """Timeout returns structured error."""
        from curl_cffi.requests.exceptions import Timeout

        mock_err = Timeout("timed out")
        session = _patch_session([mock_err])
        try:
            result = fetch.execute(
                {"url": "https://x.com", "timeout": 0.001, "max_retries": 0},
                {},
            )
        finally:
            session._cleanup()

        assert isinstance(result, PrimitiveResult)
        assert result.status == "error"
        assert result.data["ok"] is False
        assert result.data["error_type"] == "TimeoutError"
        assert result.data["error_message"] is not None
        assert isinstance(result.data["elapsed_ms"], int)
        assert result.error is not None

    def test_connection_error(self, fetch: HttpHardenedFetchPrimitive) -> None:
        """ConnectionError returns structured error."""
        from curl_cffi.requests.exceptions import ConnectionError as CurlConnErr

        mock_err = CurlConnErr("connection refused")
        session = _patch_session([mock_err])
        try:
            result = fetch.execute(
                {"url": "https://x.com", "max_retries": 0}, {}
            )
        finally:
            session._cleanup()

        assert result.status == "error"
        assert result.data["ok"] is False
        assert result.data["error_type"] == "ConnectionError"
        assert result.data["error_message"] is not None
        assert isinstance(result.data["elapsed_ms"], int)

    def test_dns_error(self, fetch: HttpHardenedFetchPrimitive) -> None:
        """DNSError returns structured error."""
        from curl_cffi.requests.exceptions import DNSError

        mock_err = DNSError("Could not resolve host")
        session = _patch_session([mock_err])
        try:
            result = fetch.execute(
                {"url": "https://bad.example.com", "max_retries": 0}, {}
            )
        finally:
            session._cleanup()

        assert result.status == "error"
        assert result.data["ok"] is False
        assert result.data["error_type"] == "ConnectionError"

    def test_ssl_error(self, fetch: HttpHardenedFetchPrimitive) -> None:
        """SSLError returns structured error."""
        from curl_cffi.requests.exceptions import SSLError

        mock_err = SSLError("certificate verify failed")
        session = _patch_session([mock_err])
        try:
            result = fetch.execute(
                {"url": "https://self-signed.bad", "max_retries": 0}, {}
            )
        finally:
            session._cleanup()

        assert result.status == "error"
        assert result.data["ok"] is False
        assert result.data["error_type"] == "ConnectionError"
        assert "SSL" in result.data["error_message"]


# ---------------------------------------------------------------------------
# execute — retry behaviour
# ---------------------------------------------------------------------------


class TestHttpHardenedRetries:
    """Tests for retry logic."""

    def test_transient_failure_succeeds_on_retry(
        self, fetch: HttpHardenedFetchPrimitive
    ) -> None:
        """Transient error followed by success succeeds."""
        from curl_cffi.requests.exceptions import ConnectionError as CurlConnErr

        mock_err = CurlConnErr("connection reset")
        mock_ok = _make_mock_response(200, text="success after retry")
        # Two failures then success
        session = _patch_session([mock_err, mock_err, mock_ok])
        try:
            result = fetch.execute(
                {"url": "https://x.com", "max_retries": 3}, {}
            )
        finally:
            session._cleanup()

        assert result.status == "success"
        assert result.data["ok"] is True
        assert result.data["body"] == "success after retry"

    def test_all_retries_fail(self, fetch: HttpHardenedFetchPrimitive) -> None:
        """All retries exhausted returns last error."""
        from curl_cffi.requests.exceptions import Timeout

        mock_err = Timeout("timed out")
        # max_retries=2 means 3 attempts total: 1 original + 2 retries
        session = _patch_session([mock_err, mock_err, mock_err])
        try:
            result = fetch.execute(
                {"url": "https://x.com", "timeout": 0.001, "max_retries": 2}, {}
            )
        finally:
            session._cleanup()

        assert result.status == "error"
        assert result.data["ok"] is False
        assert result.data["error_type"] == "TimeoutError"

    def test_zero_retries_no_retry(self, fetch: HttpHardenedFetchPrimitive) -> None:
        """max_retries=0 means no retry attempt."""
        from curl_cffi.requests.exceptions import ConnectionError as CurlConnErr

        mock_err = CurlConnErr("connection refused")
        session = _patch_session([mock_err])
        try:
            result = fetch.execute(
                {"url": "https://x.com", "max_retries": 0}, {}
            )
        finally:
            session._cleanup()

        assert result.status == "error"
        assert result.data["error_type"] == "ConnectionError"
        # Should have only been called once
        assert session.get.call_count == 1

    def test_retry_backoff_delay_observed(
        self, fetch: HttpHardenedFetchPrimitive
    ) -> None:
        """Retries delay with exponential backoff (approximate check)."""
        from curl_cffi.requests.exceptions import ConnectionError as CurlConnErr

        mock_err = CurlConnErr("connection reset")
        mock_ok = _make_mock_response(200, text="ok")

        # max_retries=2, backoff_base_ms=10 (small for fast test)
        # Delays: ~10ms, ~20ms (with ±25% jitter) → ~30ms expected
        session = _patch_session([mock_err, mock_err, mock_ok])
        try:
            start = time.perf_counter()
            result = fetch.execute(
                {
                    "url": "https://x.com",
                    "max_retries": 2,
                    "backoff_base_ms": 10,
                },
                {},
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
        finally:
            session._cleanup()

        assert result.status == "success"
        # With 10ms base and 2 retry delays, should take at least ~10ms
        # (the first delay may be as low as ~7.5ms with jitter)
        assert elapsed_ms >= 5, f"elapsed={elapsed_ms}ms too low for backoff"


# ---------------------------------------------------------------------------
# execute — context handling
# ---------------------------------------------------------------------------


class TestHttpHardenedContext:
    """Tests that context dict is accepted but does not affect behaviour."""

    def test_context_ignored(self, fetch: HttpHardenedFetchPrimitive) -> None:
        """The context dict is read but not used."""
        mock_resp = _make_mock_response()
        session = _patch_session(mock_resp)
        try:
            result = fetch.execute(
                {"url": "https://x.com"},
                {"trace_id": "abc", "user_id": "42"},
            )
        finally:
            session._cleanup()

        assert result.status == "success"
        assert result.data["ok"] is True
