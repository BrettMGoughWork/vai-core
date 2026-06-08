"""Tests for stdlib.http.fetch primitive (Phase 3.10.2)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.capabilities.primitives.stdlib.http_fetch import HttpFetchPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def fetch() -> HttpFetchPrimitive:
    """Real HttpFetchPrimitive instance."""
    return HttpFetchPrimitive()


@pytest.fixture
def mock_client() -> MagicMock:
    """Return a MagicMock that replaces httpx.Client.

    Usage in tests::

        client = mock_client
        client.get.return_value = httpx.Response(200, text="ok")

        with patch("httpx.Client", return_value=client.__enter__.return_value.__enter__()):
            pass
    """
    return MagicMock()


def _patch_client(mock_responses: list[httpx.Response] | httpx.Response) -> MagicMock:
    """Patch ``httpx.Client`` so its ``.get()`` yields ``mock_responses``.

    Accepts either a single response or a list (for sequential calls).
    Returns the mock client instance for additional assertions.
    """
    client_instance = MagicMock()
    if isinstance(mock_responses, list):
        client_instance.get.side_effect = mock_responses
    else:
        client_instance.get.return_value = mock_responses

    cm = MagicMock()
    cm.__enter__.return_value = client_instance

    patcher = patch("httpx.Client", return_value=cm)
    patcher.start()

    def _cleanup() -> None:
        patcher.stop()

    # Store cleanup so tests can call it manually if needed
    client_instance._cleanup = _cleanup  # type: ignore[attr-defined]
    return client_instance


# ---------------------------------------------------------------------------
# validate_args
# ---------------------------------------------------------------------------


class TestHttpFetchValidate:
    """Tests for HttpFetchPrimitive.validate_args."""

    def test_valid_minimal_args(self, fetch: HttpFetchPrimitive) -> None:
        """Just a URL passes validation."""
        fetch.validate_args({"url": "https://example.com"})

    def test_valid_with_all_args(self, fetch: HttpFetchPrimitive) -> None:
        """URL + timeout + headers passes validation."""
        fetch.validate_args({
            "url": "https://example.com",
            "timeout": 10.0,
            "headers": {"Accept": "application/json"},
        })

    def test_valid_timeout_as_int(self, fetch: HttpFetchPrimitive) -> None:
        """Integer timeout is valid."""
        fetch.validate_args({"url": "https://example.com", "timeout": 5})

    def test_missing_url_raises(self, fetch: HttpFetchPrimitive) -> None:
        """Missing 'url' key raises ValueError."""
        with pytest.raises(ValueError, match="must contain 'url' key"):
            fetch.validate_args({})

    def test_non_string_url_raises(self, fetch: HttpFetchPrimitive) -> None:
        """Non-string url raises ValueError."""
        with pytest.raises(ValueError, match="'url' must be a string"):
            fetch.validate_args({"url": 42})

    def test_empty_url_raises(self, fetch: HttpFetchPrimitive) -> None:
        """Empty url raises ValueError."""
        with pytest.raises(ValueError, match="'url' must not be empty"):
            fetch.validate_args({"url": ""})

    def test_non_number_timeout_raises(self, fetch: HttpFetchPrimitive) -> None:
        """Non-number timeout raises ValueError."""
        with pytest.raises(ValueError, match="'timeout' must be a number"):
            fetch.validate_args({"url": "https://x.com", "timeout": "10"})

    def test_negative_timeout_raises(self, fetch: HttpFetchPrimitive) -> None:
        """Non-positive timeout raises ValueError."""
        with pytest.raises(ValueError, match="'timeout' must be positive"):
            fetch.validate_args({"url": "https://x.com", "timeout": -1})

    def test_zero_timeout_raises(self, fetch: HttpFetchPrimitive) -> None:
        """Zero timeout raises ValueError."""
        with pytest.raises(ValueError, match="'timeout' must be positive"):
            fetch.validate_args({"url": "https://x.com", "timeout": 0})

    def test_non_dict_headers_raises(self, fetch: HttpFetchPrimitive) -> None:
        """Non-dict headers raises ValueError."""
        with pytest.raises(ValueError, match="'headers' must be a dict"):
            fetch.validate_args({"url": "https://x.com", "headers": "bad"})

    def test_header_non_string_key_raises(self, fetch: HttpFetchPrimitive) -> None:
        """Non-string header key raises ValueError."""
        with pytest.raises(ValueError, match="'headers' keys must be strings"):
            fetch.validate_args({"url": "https://x.com", "headers": {1: "v"}})

    def test_header_non_string_value_raises(self, fetch: HttpFetchPrimitive) -> None:
        """Non-string header value raises ValueError."""
        with pytest.raises(ValueError, match="'headers' values must be strings"):
            fetch.validate_args({"url": "https://x.com", "headers": {"k": 1}})

    def test_args_not_a_dict_raises(self, fetch: HttpFetchPrimitive) -> None:
        """Non-dict args raises ValueError."""
        with pytest.raises(ValueError, match="args must be a dict"):
            fetch.validate_args("bad")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# execute — success cases
# ---------------------------------------------------------------------------


class TestHttpFetchExecuteSuccess:
    """Tests for HttpFetchPrimitive.execute — successful responses."""

    def test_successful_get(self, fetch: HttpFetchPrimitive) -> None:
        """A 200 response returns ok: true with body and headers."""
        response = httpx.Response(
            200,
            text='{"hello": "world"}',
            headers={"content-type": "application/json"},
        )
        client = _patch_client(response)

        try:
            result = fetch.execute({"url": "https://api.example.com/data"}, {})
        finally:
            client._cleanup()

        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data["ok"] is True
        assert result.data["status_code"] == 200
        assert result.data["body"] == '{"hello": "world"}'
        assert result.data["headers"]["content-type"] == "application/json"
        assert isinstance(result.data["elapsed_ms"], int)
        assert result.data["elapsed_ms"] >= 0
        assert result.error is None

    def test_custom_headers_forwarded(self, fetch: HttpFetchPrimitive) -> None:
        """Custom headers are forwarded to the httpx call."""
        response = httpx.Response(200, text="ok")
        client = _patch_client(response)

        try:
            fetch.execute(
                {"url": "https://x.com", "headers": {"Authorization": "Bearer tok"}},
                {},
            )
        finally:
            client._cleanup()

        call_kwargs = client.get.call_args
        assert call_kwargs is not None
        _args, kwargs = call_kwargs
        assert kwargs.get("headers") == {"Authorization": "Bearer tok"}

    def test_timeout_forwarded(self, fetch: HttpFetchPrimitive) -> None:
        """Timeout is forwarded to the httpx call."""
        response = httpx.Response(200, text="ok")
        client = _patch_client(response)

        try:
            fetch.execute({"url": "https://x.com", "timeout": 5.0}, {})
        finally:
            client._cleanup()

        call_kwargs = client.get.call_args
        assert call_kwargs is not None
        _args, kwargs = call_kwargs
        assert kwargs.get("timeout") == 5.0

    def test_timeout_not_forwarded_when_omitted(self, fetch: HttpFetchPrimitive) -> None:
        """Omitting timeout passes None to httpx (default)."""
        response = httpx.Response(200, text="ok")
        client = _patch_client(response)

        try:
            fetch.execute({"url": "https://x.com"}, {})
        finally:
            client._cleanup()

        call_kwargs = client.get.call_args
        assert call_kwargs is not None
        _args, kwargs = call_kwargs
        assert kwargs.get("timeout") is None

    def test_404_returns_success_with_status(self, fetch: HttpFetchPrimitive) -> None:
        """A 404 is returned as a success (HTTP transaction completed)."""
        response = httpx.Response(
            404,
            text="Not Found",
            headers={"content-type": "text/plain"},
        )
        client = _patch_client(response)

        try:
            result = fetch.execute({"url": "https://x.com/notfound"}, {})
        finally:
            client._cleanup()

        assert result.status == "success"
        assert result.data["ok"] is True
        assert result.data["status_code"] == 404
        assert "Not Found" in result.data["body"]

    def test_500_returns_success_with_status(self, fetch: HttpFetchPrimitive) -> None:
        """A 500 is returned as a success (HTTP transaction completed)."""
        response = httpx.Response(500, text="Internal Server Error")
        client = _patch_client(response)

        try:
            result = fetch.execute({"url": "https://x.com/error"}, {})
        finally:
            client._cleanup()

        assert result.status == "success"
        assert result.data["ok"] is True
        assert result.data["status_code"] == 500

    def test_elapsed_ms_is_positive(self, fetch: HttpFetchPrimitive) -> None:
        """elapsed_ms reflects real wall-clock time."""
        response = httpx.Response(200, text="ok")
        client = _patch_client(response)

        try:
            result = fetch.execute({"url": "https://x.com"}, {})
        finally:
            client._cleanup()

        assert result.data["elapsed_ms"] >= 0

    def test_no_side_effects(self, fetch: HttpFetchPrimitive) -> None:
        """Result has an empty side_effects list."""
        response = httpx.Response(200, text="ok")
        client = _patch_client(response)

        try:
            result = fetch.execute({"url": "https://x.com"}, {})
        finally:
            client._cleanup()

        assert result.side_effects == []


# ---------------------------------------------------------------------------
# execute — error cases
# ---------------------------------------------------------------------------


class TestHttpFetchExecuteErrors:
    """Tests for HttpFetchPrimitive.execute — transport failures."""

    def test_timeout_error(self, fetch: HttpFetchPrimitive) -> None:
        """TimeoutException returns structured error."""
        client_instance = MagicMock()
        client_instance.get.side_effect = httpx.TimeoutException(
            "timed out", request=httpx.Request("GET", "https://x.com")
        )
        cm = MagicMock()
        cm.__enter__.return_value = client_instance

        with patch("httpx.Client", return_value=cm):
            result = fetch.execute({"url": "https://x.com", "timeout": 0.001}, {})

        assert isinstance(result, PrimitiveResult)
        assert result.status == "error"
        assert result.data["ok"] is False
        assert result.data["error_type"] == "TimeoutError"
        assert result.data["error_message"] is not None
        assert isinstance(result.data["elapsed_ms"], int)
        assert result.error is not None
        assert "timeout" in result.error.lower() or "Timeout" in result.error

    def test_connection_error(self, fetch: HttpFetchPrimitive) -> None:
        """ConnectionError returns structured error."""
        client_instance = MagicMock()
        client_instance.get.side_effect = httpx.ConnectError(
            "connection refused"
        )
        cm = MagicMock()
        cm.__enter__.return_value = client_instance

        with patch("httpx.Client", return_value=cm):
            result = fetch.execute({"url": "https://x.com"}, {})

        assert result.status == "error"
        assert result.data["ok"] is False
        assert result.data["error_type"] == "ConnectionError"
        assert result.data["error_message"] is not None
        assert isinstance(result.data["elapsed_ms"], int)

    def test_invalid_url(self, fetch: HttpFetchPrimitive) -> None:
        """An unparseable URL triggers ConnectionError via httpx."""
        client_instance = MagicMock()
        client_instance.get.side_effect = httpx.ConnectError(
            "unable to resolve"
        )
        cm = MagicMock()
        cm.__enter__.return_value = client_instance

        with patch("httpx.Client", return_value=cm):
            result = fetch.execute({"url": "not-a-valid-url"}, {})

        assert result.status == "error"
        assert result.data["ok"] is False


# ---------------------------------------------------------------------------
# execute — context handling
# ---------------------------------------------------------------------------


class TestHttpFetchContext:
    """Tests that context dict is accepted but does not affect behaviour."""

    def test_context_ignored(self, fetch: HttpFetchPrimitive) -> None:
        """The context dict is read but not used."""
        response = httpx.Response(200, text="ok")
        client = _patch_client(response)

        try:
            result = fetch.execute(
                {"url": "https://x.com"},
                {"trace_id": "abc", "user_id": "42"},
            )
        finally:
            client._cleanup()

        assert result.status == "success"
        assert result.data["ok"] is True
