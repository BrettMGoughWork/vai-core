"""Unit tests for FetchError taxonomy (Phase 3.10.1)."""

from __future__ import annotations

import json
from dataclasses import asdict

import httpx
import pytest

from src.capabilities.primitives.fetch.errors import (
    ConnectionError,
    FetchError,
    HTTPError,
    ParseError,
    TimeoutError,
    classify_exception,
)


# ---------------------------------------------------------------------------
# Construction tests
# ---------------------------------------------------------------------------


class TestTimeoutError:
    def test_construction(self) -> None:
        err = TimeoutError(url="https://example.com", timeout=30.0, elapsed=15.5)
        assert err.url == "https://example.com"
        assert err.timeout == 30.0
        assert err.elapsed == 15.5
        assert err.kind == "timeout"

    def test_is_fetch_error(self) -> None:
        err = TimeoutError(url="https://x.com", timeout=10.0, elapsed=10.0)
        assert isinstance(err, FetchError)
        assert isinstance(err, Exception)

    def test_str_contains_url_and_timings(self) -> None:
        err = TimeoutError(url="https://a.com", timeout=5.0, elapsed=4.2)
        s = str(err)
        assert "https://a.com" in s
        assert "timeout" in s.lower()


class TestHTTPError:
    def test_construction_minimal(self) -> None:
        err = HTTPError(url="https://example.com", status_code=404)
        assert err.url == "https://example.com"
        assert err.status_code == 404
        assert err.body is None
        assert err.headers is None
        assert err.kind == "http"

    def test_construction_full(self) -> None:
        err = HTTPError(
            url="https://example.com",
            status_code=500,
            body="Internal Server Error",
            headers={"content-type": "text/plain"},
        )
        assert err.body == "Internal Server Error"
        assert err.headers == {"content-type": "text/plain"}

    def test_is_fetch_error(self) -> None:
        err = HTTPError(url="https://x.com", status_code=403)
        assert isinstance(err, FetchError)

    def test_str_contains_status(self) -> None:
        err = HTTPError(url="https://a.com", status_code=503, body="down")
        s = str(err)
        assert "503" in s
        assert "https://a.com" in s


class TestParseError:
    def test_construction(self) -> None:
        err = ParseError(url="https://example.com", message="invalid JSON")
        assert err.url == "https://example.com"
        assert err.message == "invalid JSON"
        assert err.body is None
        assert err.kind == "parse"

    def test_construction_with_body(self) -> None:
        err = ParseError(url="https://x.com", message="bad syntax", body="not json")
        assert err.body == "not json"

    def test_is_fetch_error(self) -> None:
        err = ParseError(url="https://x.com", message="oops")
        assert isinstance(err, FetchError)

    def test_str_contains_message(self) -> None:
        err = ParseError(url="https://a.com", message="unexpected token")
        assert "unexpected token" in str(err)


class TestConnectionError:
    def test_construction(self) -> None:
        err = ConnectionError(url="https://example.com", message="refused")
        assert err.url == "https://example.com"
        assert err.message == "refused"
        assert err.kind == "connection"

    def test_is_fetch_error(self) -> None:
        err = ConnectionError(url="https://x.com", message="timeout")
        assert isinstance(err, FetchError)

    def test_str_contains_message(self) -> None:
        err = ConnectionError(url="https://a.com", message="no route to host")
        assert "no route to host" in str(err)


class TestFetchErrorBase:
    def test_to_dict_includes_all_fields(self) -> None:
        err = TimeoutError(url="https://x.com", timeout=10.0, elapsed=5.0)
        d = err.to_dict()
        assert d == {"url": "https://x.com", "timeout": 10.0, "elapsed": 5.0, "kind": "timeout"}

    def test_base_kind_is_fetch(self) -> None:
        # The base class is abstract-ish, but constructible for testing.
        pass  # kind is init=False with default "fetch"


# ---------------------------------------------------------------------------
# JSON serialization tests
# ---------------------------------------------------------------------------


class TestJSONSerialization:
    @pytest.mark.parametrize(
        "error_instance, expected_keys",
        [
            (
                TimeoutError(url="https://a.com", timeout=10.0, elapsed=3.0),
                {"url", "timeout", "elapsed", "kind"},
            ),
            (
                HTTPError(url="https://b.com", status_code=404, body="gone", headers={"x": "y"}),
                {"url", "status_code", "body", "headers", "kind"},
            ),
            (
                ParseError(url="https://c.com", message="bad", body="raw"),
                {"url", "message", "body", "kind"},
            ),
            (
                ConnectionError(url="https://d.com", message="refused"),
                {"url", "message", "kind"},
            ),
        ],
    )
    def test_serializes_to_json(self, error_instance: FetchError, expected_keys: set[str]) -> None:
        d = asdict(error_instance)
        assert set(d.keys()) == expected_keys
        # Round-trip through JSON
        payload = json.dumps(d)
        restored = json.loads(payload)
        assert restored == d


# ---------------------------------------------------------------------------
# classify_exception tests
# ---------------------------------------------------------------------------


class TestClassifyTimeout:
    def test_timeout_exception(self) -> None:
        exc = httpx.TimeoutException("timed out", request=httpx.Request("GET", "https://x.com"))
        result = classify_exception(exc, url="https://x.com")
        assert isinstance(result, TimeoutError)
        assert result.kind == "timeout"
        assert result.url == "https://x.com"

    def test_connect_timeout_is_timeout(self) -> None:
        # ConnectTimeout is a subclass of TimeoutException
        exc = httpx.ConnectTimeout("connect timed out")
        result = classify_exception(exc, url="https://x.com")
        assert isinstance(result, TimeoutError)


class TestClassifyConnection:
    def test_connect_error(self) -> None:
        exc = httpx.ConnectError("connection refused")
        result = classify_exception(exc, url="https://x.com")
        assert isinstance(result, ConnectionError)
        assert result.kind == "connection"
        assert "connection refused" in result.message

    def test_read_error(self) -> None:
        exc = httpx.ReadError("read failed")
        result = classify_exception(exc, url="https://x.com")
        assert isinstance(result, ConnectionError)
        assert result.kind == "connection"
        assert "read failed" in result.message

    def test_remote_protocol_error_is_connection(self) -> None:
        # RemoteProtocolError is a subclass of ConnectError in httpx
        exc = httpx.RemoteProtocolError("protocol error")
        result = classify_exception(exc, url="https://x.com")
        assert isinstance(result, ConnectionError)


class TestClassifyHTTP:
    def test_http_status_error(self) -> None:
        response = httpx.Response(status_code=404, request=httpx.Request("GET", "https://x.com"))
        exc = httpx.HTTPStatusError("not found", request=httpx.Request("GET", "https://x.com"), response=response)
        result = classify_exception(exc, url="https://x.com")
        assert isinstance(result, HTTPError)
        assert result.kind == "http"
        assert result.status_code == 404

    def test_http_status_error_with_headers(self) -> None:
        response = httpx.Response(
            status_code=500,
            headers={"content-type": "application/json"},
            request=httpx.Request("GET", "https://x.com"),
        )
        exc = httpx.HTTPStatusError("server error", request=httpx.Request("GET", "https://x.com"), response=response)
        result = classify_exception(exc, url="https://x.com")
        assert isinstance(result, HTTPError)
        assert result.headers is not None
        assert "content-type" in result.headers


class TestClassifyParse:
    def test_value_error(self) -> None:
        exc = ValueError("invalid literal")
        result = classify_exception(exc, url="https://x.com")
        assert isinstance(result, ParseError)
        assert result.kind == "parse"
        assert "invalid literal" in result.message

    def test_json_decode_error(self) -> None:
        try:
            json.loads("{bad json}")
        except json.JSONDecodeError as exc:
            result = classify_exception(exc, url="https://x.com")
        assert isinstance(result, ParseError)
        assert result.kind == "parse"
        assert result.body == "{bad json}"


class TestClassifyFallback:
    def test_unknown_exception_defaults_to_connection(self) -> None:
        exc = RuntimeError("something unexpected")
        result = classify_exception(exc, url="https://x.com")
        assert isinstance(result, ConnectionError)
        assert result.kind == "connection"

    def test_empty_message_uses_type_name(self) -> None:
        class WeirdError(Exception):
            pass

        exc = WeirdError()
        result = classify_exception(exc, url="https://x.com")
        assert isinstance(result, ConnectionError)
        assert "WeirdError" in result.message