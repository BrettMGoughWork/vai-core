"""Tests for FetchRequest / FetchResponse dataclasses (Phase 3.10.5)."""

from __future__ import annotations

import pytest

from src.strategy.types.fetch import FetchRequest, FetchResponse
from src.strategy.types.fetch.response import _extract_cookies, _parse_set_cookie


# =====================================================================
# FetchRequest
# =====================================================================


class TestFetchRequestCreation:
    """Tests for FetchRequest construction."""

    def test_minimal_request(self) -> None:
        """A request with just a URL has sensible defaults."""
        req = FetchRequest(url="https://example.com")
        assert req.url == "https://example.com"
        assert req.method == "GET"
        assert req.headers == {}
        assert req.cookies == {}
        assert req.timeout is None
        assert req.body is None

    def test_full_request(self) -> None:
        """All fields can be set at construction."""
        req = FetchRequest(
            url="https://api.example.com/login",
            method="POST",
            headers={"Content-Type": "application/json"},
            cookies={"session": "abc123"},
            timeout=10.0,
            body='{"user": "me"}',
        )
        assert req.url == "https://api.example.com/login"
        assert req.method == "POST"
        assert req.headers == {"Content-Type": "application/json"}
        assert req.cookies == {"session": "abc123"}
        assert req.timeout == 10.0
        assert req.body == '{"user": "me"}'

    def test_frozen_immutable(self) -> None:
        """FetchRequest is frozen; attempting mutation raises FrozenInstanceError."""
        from dataclasses import FrozenInstanceError

        req = FetchRequest(url="https://example.com")
        with pytest.raises(FrozenInstanceError):
            req.url = "https://other.com"  # type: ignore[misc]

    def test_from_dict_round_trip(self) -> None:
        """from_dict(to_dict()) preserves all values."""
        original = FetchRequest(
            url="https://example.com/path",
            headers={"Accept": "*/*"},
            timeout=5.0,
        )
        d = original.to_dict()
        restored = FetchRequest.from_dict(d)
        assert restored == original

    def test_from_dict_unknown_keys_ignored(self) -> None:
        """from_dict silently ignores unknown keys."""
        req = FetchRequest.from_dict(
            {"url": "https://x.com", "unknown_field": "ignored"}
        )
        assert req.url == "https://x.com"
        assert req.headers == {}

    def test_from_dict_missing_url_raises(self) -> None:
        """from_dict requires 'url' key."""
        with pytest.raises(KeyError):
            FetchRequest.from_dict({})

    def test_from_dict_optional_defaults(self) -> None:
        """from_dict fills missing optional fields with defaults."""
        req = FetchRequest.from_dict({"url": "https://x.com"})
        assert req.method == "GET"
        assert req.headers == {}
        assert req.cookies == {}


class TestFetchRequestToArgs:
    """Tests for FetchRequest.to_args()."""

    def test_minimal_to_args(self) -> None:
        """A URL-only request produces the minimal args dict."""
        req = FetchRequest(url="https://example.com")
        args = req.to_args()
        assert args == {"url": "https://example.com"}

    def test_to_args_with_timeout(self) -> None:
        """Timeout is included when set."""
        req = FetchRequest(url="https://example.com", timeout=5.0)
        args = req.to_args()
        assert args["timeout"] == 5.0

    def test_to_args_with_headers(self) -> None:
        """Headers are included when set."""
        req = FetchRequest(url="https://x.com", headers={"Accept": "text/html"})
        args = req.to_args()
        assert args["headers"] == {"Accept": "text/html"}

    def test_to_args_with_cookies(self) -> None:
        """Cookies are serialised as a Cookie header."""
        req = FetchRequest(url="https://x.com", cookies={"session": "abc"})
        args = req.to_args()
        assert "headers" in args
        assert args["headers"]["Cookie"] == "session=abc"

    def test_to_args_cookies_do_not_clobber_explicit_header(self) -> None:
        """An explicit Cookie header takes precedence over cookies."""
        req = FetchRequest(
            url="https://x.com",
            headers={"Cookie": "explicit=yes"},
            cookies={"session": "abc"},
        )
        args = req.to_args()
        assert args["headers"]["Cookie"] == "explicit=yes"


# =====================================================================
# FetchResponse
# =====================================================================


class TestFetchResponseCreation:
    """Tests for FetchResponse construction."""

    def test_success_response(self) -> None:
        """A successful response stores all fields."""
        resp = FetchResponse(
            ok=True,
            status_code=200,
            body="hello",
            headers={"content-type": "text/plain"},
            elapsed_ms=42,
            url="https://example.com",
        )
        assert resp.ok is True
        assert resp.status_code == 200
        assert resp.body == "hello"
        assert resp.headers == {"content-type": "text/plain"}
        assert resp.elapsed_ms == 42
        assert resp.url == "https://example.com"
        assert resp.error_type is None
        assert resp.error_message is None

    def test_error_response(self) -> None:
        """An error response stores error fields."""
        resp = FetchResponse(
            ok=False,
            elapsed_ms=1500,
            url="https://x.com",
            error_type="TimeoutError",
            error_message="timed out after 1.5s",
        )
        assert resp.ok is False
        assert resp.status_code is None
        assert resp.error_type == "TimeoutError"
        assert resp.error_message == "timed out after 1.5s"

    def test_frozen_immutable(self) -> None:
        """FetchResponse is frozen."""
        from dataclasses import FrozenInstanceError

        resp = FetchResponse(ok=True, url="https://x.com")
        with pytest.raises(FrozenInstanceError):
            resp.ok = False  # type: ignore[misc]

    def test_to_dict_omits_none(self) -> None:
        """to_dict() omits None-valued fields but keeps default-factory fields."""
        resp = FetchResponse(ok=True, status_code=200, elapsed_ms=10, url="https://x.com")
        d = resp.to_dict()
        assert "error_type" not in d
        assert "error_message" not in d
        assert "cookies" in d  # default_factory=dict means it's never None
        assert d["cookies"] == {}

    def test_to_dict_includes_cookies_when_present(self) -> None:
        """to_dict() includes cookies when non-empty."""
        resp = FetchResponse(
            ok=True, status_code=200, elapsed_ms=10, url="https://x.com",
            cookies={"session": "abc"},
        )
        d = resp.to_dict()
        assert d["cookies"] == {"session": "abc"}


class TestFetchResponseFromPrimitiveResult:
    """Tests for FetchResponse.from_primitive_result()."""

    def test_success_primitive(self) -> None:
        """A primitive success dict creates a valid FetchResponse."""
        data = {
            "ok": True,
            "status_code": 200,
            "body": '{"ok": true}',
            "headers": {"content-type": "application/json"},
            "elapsed_ms": 42,
        }
        resp = FetchResponse.from_primitive_result(data, url="https://example.com")
        assert resp.ok is True
        assert resp.status_code == 200
        assert resp.body == '{"ok": true}'
        assert resp.headers == {"content-type": "application/json"}
        assert resp.elapsed_ms == 42
        assert resp.url == "https://example.com"
        assert resp.error_type is None
        assert resp.error_message is None

    def test_error_primitive(self) -> None:
        """A primitive error dict creates a valid error FetchResponse."""
        data = {
            "ok": False,
            "error_type": "TimeoutError",
            "error_message": "timed out",
            "elapsed_ms": 5000,
        }
        resp = FetchResponse.from_primitive_result(data, url="https://slow.com")
        assert resp.ok is False
        assert resp.status_code is None
        assert resp.body is None
        assert resp.error_type == "TimeoutError"
        assert resp.error_message == "timed out"
        assert resp.elapsed_ms == 5000
        assert resp.url == "https://slow.com"

    def test_success_4xx_primitive(self) -> None:
        """A 4xx primitive result maps to ok=True."""
        data = {
            "ok": True,
            "status_code": 404,
            "body": "Not Found",
            "headers": {},
            "elapsed_ms": 50,
        }
        resp = FetchResponse.from_primitive_result(data, url="https://x.com/404")
        assert resp.ok is True
        assert resp.status_code == 404
        assert resp.body == "Not Found"

    def test_success_5xx_primitive(self) -> None:
        """A 5xx primitive result maps to ok=True."""
        data = {
            "ok": True,
            "status_code": 500,
            "body": "Server Error",
            "headers": {},
            "elapsed_ms": 100,
        }
        resp = FetchResponse.from_primitive_result(data, url="https://x.com/500")
        assert resp.ok is True
        assert resp.status_code == 500

    def test_from_primitive_parses_cookies(self) -> None:
        """Set-Cookie headers are parsed into the cookies field."""
        data = {
            "ok": True,
            "status_code": 200,
            "body": "ok",
            "headers": {"set-cookie": "session=abc123; Path=/; HttpOnly"},
            "elapsed_ms": 30,
        }
        resp = FetchResponse.from_primitive_result(data, url="https://x.com")
        assert resp.cookies == {"session": "abc123"}

    def test_from_primitive_no_cookies(self) -> None:
        """Absent Set-Cookie results in empty cookies."""
        data = {
            "ok": True,
            "status_code": 200,
            "body": "ok",
            "headers": {"content-type": "text/plain"},
            "elapsed_ms": 10,
        }
        resp = FetchResponse.from_primitive_result(data, url="https://x.com")
        assert resp.cookies == {}

    def test_from_primitive_uses_direct_cookies_key(self) -> None:
        """The data['cookies'] key is included (headless/hardened primitives)."""
        data = {
            "ok": True,
            "status_code": 200,
            "body": "ok",
            "headers": {"content-type": "text/plain"},
            "cookies": {"session": "abc123"},
            "elapsed_ms": 10,
        }
        resp = FetchResponse.from_primitive_result(data, url="https://x.com")
        assert resp.cookies == {"session": "abc123"}

    def test_from_primitive_merges_direct_and_header_cookies(self) -> None:
        """Direct cookies merge with Set-Cookie; direct wins on conflict."""
        data = {
            "ok": True,
            "status_code": 200,
            "body": "ok",
            "headers": {"set-cookie": "tracker=xyz; Path=/"},
            "cookies": {"session": "abc123"},
            "elapsed_ms": 10,
        }
        resp = FetchResponse.from_primitive_result(data, url="https://x.com")
        assert resp.cookies == {"tracker": "xyz", "session": "abc123"}


# =====================================================================
# Cookie parsing
# =====================================================================


class TestParseSetCookie:
    """Tests for low-level Set-Cookie parsing."""

    def test_simple_cookie(self) -> None:
        """A simple name=value pair is parsed."""
        assert _parse_set_cookie("session=abc123") == {"session": "abc123"}

    def test_cookie_with_attributes(self) -> None:
        """Attributes after ';' are discarded."""
        result = _parse_set_cookie("session=abc123; Path=/; HttpOnly; Secure")
        assert result == {"session": "abc123"}

    def test_multiple_cookies_in_one_header(self) -> None:
        """Multiple name=value pairs before ';' are all captured."""
        result = _parse_set_cookie("a=1; Path=/; b=2; Domain=.x.com; c=3")
        assert result == {"a": "1", "b": "2", "c": "3"}

    def test_valueless_cookie(self) -> None:
        """A valueless cookie flag produces an empty-string value."""
        result = _parse_set_cookie("debug; Path=/")
        assert result == {"debug": ""}

    def test_empty_string(self) -> None:
        """Empty string produces empty dict."""
        assert _parse_set_cookie("") == {}

    def test_only_attributes(self) -> None:
        """Only attributes produces empty dict."""
        result = _parse_set_cookie("Path=/; HttpOnly")
        assert result == {}

    def test_expires_contains_equals(self) -> None:
        """Expires with = inside date is not treated as a cookie."""
        result = _parse_set_cookie(
            "session=abc; Expires=Wed, 21 Oct 2025 07:28:00 GMT; Path=/"
        )
        assert result == {"session": "abc"}

    def test_multiple_set_cookie_headers(self) -> None:
        """Multiple Set-Cookie entries are merged (last write wins).

        Note: a Python ``dict`` literal with duplicate keys keeps only the
        last value, so ``_extract_cookies`` sees a single ``set-cookie``
        entry.  In real HTTP the primitive flattens ``httpx.Headers`` the
        same way via ``dict(response.headers)``; proper multi-value support
        would require changing the primitive's output shape.
        """
        headers = {
            "set-cookie": "session=abc; Path=/",
            "set-cookie": "theme=dark; Path=/",
        }
        # dict with duplicate keys keeps only the last value
        cookies = _extract_cookies(headers)
        assert cookies == {"theme": "dark"}

    def test_extract_cookies_empty(self) -> None:
        """No Set-Cookie headers yields empty dict."""
        assert _extract_cookies({"content-type": "text/plain"}) == {}

    def test_extract_cookies_case_insensitive(self) -> None:
        """Set-Cookie header matching is case-insensitive."""
        headers = {"Set-Cookie": "x=1"}
        assert _extract_cookies(headers) == {"x": "1"}


# =====================================================================
# Chaining — hydrate_next_request
# =====================================================================


class TestHydrateNextRequest:
    """Tests for FetchResponse.hydrate_next_request()."""

    def test_hydrate_with_cookies(self) -> None:
        """Cookies from response are propagated to new request."""
        resp = FetchResponse(
            ok=True,
            status_code=200,
            body="ok",
            headers={"set-cookie": "session=abc123"},
            elapsed_ms=30,
            url="https://x.com/login",
            cookies={"session": "abc123"},
        )
        next_req = resp.hydrate_next_request("https://x.com/dashboard")
        assert next_req.url == "https://x.com/dashboard"
        assert next_req.cookies == {"session": "abc123"}
        assert "Cookie" in next_req.headers
        assert next_req.headers["Cookie"] == "session=abc123"

    def test_hydrate_without_cookies(self) -> None:
        """No cookies results in no Cookie header."""
        resp = FetchResponse(
            ok=True, status_code=200, body="ok", elapsed_ms=10, url="https://x.com"
        )
        next_req = resp.hydrate_next_request("https://x.com/other")
        assert next_req.url == "https://x.com/other"
        assert next_req.cookies == {}
        assert "Cookie" not in next_req.headers

    def test_hydrate_with_extra_headers(self) -> None:
        """Extra headers are merged into the new request."""
        resp = FetchResponse(
            ok=True,
            status_code=200,
            body="ok",
            headers={"set-cookie": "tok=x"},
            elapsed_ms=10,
            url="https://x.com/login",
            cookies={"tok": "x"},
        )
        next_req = resp.hydrate_next_request(
            "https://x.com/data", headers={"Accept": "application/json"}
        )
        assert next_req.headers["Accept"] == "application/json"
        assert next_req.headers["Cookie"] == "tok=x"

    def test_hydrate_with_timeout(self) -> None:
        """Timeout is forwarded."""
        resp = FetchResponse(
            ok=True, status_code=200, body="ok", elapsed_ms=10, url="https://x.com"
        )
        next_req = resp.hydrate_next_request("https://x.com/slow", timeout=30.0)
        assert next_req.timeout == 30.0

    def test_hydrate_round_trip_to_args(self) -> None:
        """A hydrated request produces valid primitive args."""
        resp = FetchResponse(
            ok=True,
            status_code=200,
            body='{"token": "abc"}',
            headers={"set-cookie": "session=s1; Path=/; HttpOnly"},
            elapsed_ms=50,
            url="https://api.example.com/login",
            cookies={"session": "s1"},
        )
        next_req = resp.hydrate_next_request(
            "https://api.example.com/data",
            headers={"Authorization": "Bearer abc"},
            timeout=5.0,
        )
        args = next_req.to_args()
        assert args["url"] == "https://api.example.com/data"
        assert args["timeout"] == 5.0
        assert args["headers"]["Authorization"] == "Bearer abc"
        assert args["headers"]["Cookie"] == "session=s1"

    def test_hydrate_returns_fetch_request(self) -> None:
        """Return type is FetchRequest."""
        resp = FetchResponse(ok=True, status_code=200, body="ok", elapsed_ms=0, url="https://x.com")
        result = resp.hydrate_next_request("https://x.com/next")
        assert isinstance(result, FetchRequest)
