"""Unit tests for fetch_url orchestrator (Phase 3.12.6)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.fetch.domain_policy import DomainPolicy
from src.capabilities.primitives.fetch.fetch_url import FetchResult, fetch_url
from src.capabilities.primitives.fetch.mode_selector import FetchMode, ModeHistory
from src.capabilities.primitives.fetch.request import FetchRequest
from src.capabilities.primitives.fetch.response import FetchResponse
from src.capabilities.primitives.fetch.signal_extraction import FetchSignals
from src.capabilities.primitives.fetch.signal_fallback import FallbackDecision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _req(
    url: str = "https://example.com",
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    method: str = "GET",
    timeout: float | None = None,
) -> FetchRequest:
    return FetchRequest(
        url=url,
        method=method,
        headers=headers or {},
        cookies=cookies or {},
        timeout=timeout,
    )


def _resp(
    ok: bool = False,
    status_code: int | None = 200,
    body: str | None = None,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    url: str = "https://example.com",
    elapsed_ms: int = 100,
) -> FetchResponse:
    return FetchResponse(
        ok=ok,
        status_code=status_code,
        body=body or "",
        headers=headers or {},
        cookies=cookies or {},
        elapsed_ms=elapsed_ms,
        url=url,
        error_type=error_type,
        error_message=error_message,
    )


def _success(body: str = "<html>hello</html>", **kwargs) -> FetchResponse:
    """Return an ok=True response."""
    return _resp(ok=True, body=body, **kwargs)


def _failure(
    error_type: str = "HTTPError",
    error_message: str = "failed",
    body: str = "",
    **kwargs,
) -> FetchResponse:
    """Return an ok=False response (failure trigger)."""
    return _resp(ok=False, error_type=error_type, error_message=error_message, body=body, **kwargs)


def _exec(*responses: FetchResponse):
    """Create an executor that returns responses in order, then repeats the last."""
    call_count = [0]

    def exec_fn(mode: str, request: FetchRequest) -> FetchResponse:
        idx = min(call_count[0], len(responses) - 1)
        call_count[0] += 1
        return responses[idx]

    return exec_fn


def _immediate_success(body: str = "<html>hello</html>") -> callable:
    """Executor that always succeeds."""
    return _exec(_success(body=body))


def _never_succeed() -> callable:
    """Executor that always fails."""
    return _exec(_failure())


# ---------------------------------------------------------------------------
# Success on first attempt
# ---------------------------------------------------------------------------


class TestSuccessFirstTry:
    def test_returns_ok_true(self):
        result = fetch_url("https://example.com", executor=_immediate_success())
        assert result.ok is True

    def test_returns_status_code(self):
        result = fetch_url("https://example.com", executor=_exec(_success(status_code=201)))
        assert result.status_code == 201

    def test_returns_body(self):
        result = fetch_url("https://example.com", executor=_exec(_success(body="<p>hi</p>")))
        assert result.body == "<p>hi</p>"

    def test_returns_final_url(self):
        result = fetch_url(
            "https://example.com",
            executor=_exec(_success(url="https://example.com/redirected")),
        )
        assert result.final_url == "https://example.com/redirected"

    def test_returns_headers(self):
        result = fetch_url(
            "https://example.com",
            executor=_exec(_success(headers={"content-type": "text/html"})),
        )
        assert result.headers["content-type"] == "text/html"

    def test_returns_cookies(self):
        result = fetch_url(
            "https://example.com",
            executor=_exec(_success(cookies={"session": "abc"})),
        )
        assert result.cookies["session"] == "abc"

    def test_tracks_elapsed(self):
        result = fetch_url("https://example.com", executor=_exec(_success(elapsed_ms=250)))
        assert result.elapsed_ms == 250

    def test_error_fields_are_none_on_success(self):
        result = fetch_url("https://example.com", executor=_immediate_success())
        assert result.error_type is None
        assert result.error_message is None


# ---------------------------------------------------------------------------
# Success after fallback
# ---------------------------------------------------------------------------


class TestSuccessAfterFallback:
    def test_escalates_simple_to_hardened(self):
        failures = [
            _failure(error_type="HTTPError"),
            _success(body="finally got it"),
        ]
        result = fetch_url("https://example.com", executor=_exec(*failures))
        assert result.ok is True
        assert result.body == "finally got it"

    def test_escalates_through_chain(self):
        # simple fails, hardened fails, headless succeeds
        responses = [
            _failure(error_type="HTTPError"),
            _failure(error_type="TimeoutError"),
            _success(body="rendered page", url="https://example.com/final"),
        ]
        result = fetch_url("https://example.com", executor=_exec(*responses))
        assert result.ok is True
        assert result.final_url == "https://example.com/final"

    def test_preserves_cookies_across_attempts(self):
        captured_requests: list[FetchRequest] = []

        def tracking_exec(mode: str, req: FetchRequest) -> FetchResponse:
            captured_requests.append(req)
            if mode == "http_simple":
                return _resp(
                    ok=False,
                    error_type="HTTPError",
                    cookies={"tracking": "x123"},
                )
            return _success()

        result = fetch_url("https://example.com", executor=tracking_exec)
        assert result.ok is True
        # The second request should forward cookies from the first response
        assert len(captured_requests) >= 2
        second_req = captured_requests[1]
        assert second_req.cookies.get("tracking") == "x123"


# ---------------------------------------------------------------------------
# Domain denied
# ---------------------------------------------------------------------------


class TestDomainDenied:
    def test_denied_policy_fails_immediately(self):
        result = fetch_url(
            "https://blocked.example.com",
            domain_policy={"blocked.example.com": {"deny": True}},
            executor=_immediate_success(),
        )
        assert result.ok is False
        assert result.error_type == "DomainDeniedError"

    def test_denied_never_calls_executor(self):
        called = [False]

        def exec_fn(mode: str, req: FetchRequest) -> FetchResponse:
            called[0] = True
            return _success()

        result = fetch_url(
            "https://evil.com",
            domain_policy={"evil.com": {"deny": True}},
            executor=exec_fn,
        )
        assert result.ok is False
        assert not called[0]

    def test_allow_false_treated_as_deny(self):
        result = fetch_url(
            "https://restricted.example.com",
            domain_policy={"restricted.example.com": {"allow": False}},
            executor=_immediate_success(),
        )
        assert result.ok is False
        assert result.error_type == "DomainDeniedError"


# ---------------------------------------------------------------------------
# Preferred mode
# ---------------------------------------------------------------------------


class TestPreferredMode:
    def test_uses_preferred_mode_directly(self):
        modes_used: list[str] = []

        def exec_fn(mode: str, req: FetchRequest) -> FetchResponse:
            modes_used.append(mode)
            return _success()

        result = fetch_url(
            "https://example.com",
            domain_policy={"example.com": {"preferred_mode": "http_stealth"}},
            executor=exec_fn,
        )
        assert result.ok is True
        assert modes_used == ["http_stealth"]

    def test_preferred_mode_ignored_if_forbidden(self):
        modes_used: list[str] = []

        def exec_fn(mode: str, req: FetchRequest) -> FetchResponse:
            modes_used.append(mode)
            return _success()

        result = fetch_url(
            "https://example.com",
            domain_policy={
                "example.com": {
                    "preferred_mode": "http_stealth",
                    "forbidden_modes": ["http_stealth"],
                }
            },
            executor=exec_fn,
        )
        assert result.ok is True
        assert modes_used[0] != "http_stealth"


# ---------------------------------------------------------------------------
# Forbidden modes escalation
# ---------------------------------------------------------------------------


class TestForbiddenModes:
    def test_skips_forbidden_mode_during_escalation(self):
        # simple fails, hardened is forbidden → should skip to headless
        modes_used: list[str] = []

        def exec_fn(mode: str, req: FetchRequest) -> FetchResponse:
            modes_used.append(mode)
            if mode == "http_headless_browser":
                return _success()
            return _failure()

        result = fetch_url(
            "https://example.com",
            domain_policy={
                "example.com": {"forbidden_modes": ["http_hardened"]}
            },
            executor=exec_fn,
        )
        assert result.ok is True
        assert "http_hardened" not in modes_used
        assert "http_headless_browser" in modes_used


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    def test_sleeps_when_rate_limited(self, monkeypatch):
        sleeps: list[float] = []

        def fake_sleep(seconds: float):
            sleeps.append(seconds)

        monkeypatch.setattr("time.sleep", fake_sleep)

        executor = _exec(_failure(error_type="HTTPError"), _success())
        result = fetch_url(
            "https://example.com",
            domain_policy={"example.com": {"rate_limit_ms": 500}},
            executor=executor,
        )
        assert result.ok is True
        # Should have slept at least once (before the retry)
        assert len(sleeps) >= 1
        assert sleeps[0] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Exhaustion / give up
# ---------------------------------------------------------------------------


class TestExhaustion:
    def test_returns_failure_when_all_modes_fail(self):
        result = fetch_url("https://example.com", executor=_never_succeed())
        assert result.ok is False
        assert result.error_type is not None

    def test_elapsed_accumulated_across_attempts(self):
        result = fetch_url(
            "https://example.com",
            executor=_exec(
                _failure(elapsed_ms=100),
                _failure(elapsed_ms=200),
                _failure(elapsed_ms=50),
                _failure(elapsed_ms=150),
                _failure(elapsed_ms=300),
                _failure(elapsed_ms=80),
                _failure(elapsed_ms=60),
                _failure(elapsed_ms=90),
                _failure(elapsed_ms=120),
                _failure(elapsed_ms=200),
            ),
        )
        assert result.ok is False
        assert result.elapsed_ms > 0


class TestGiveUpFromFallback:
    def test_propagates_last_error_on_give_up(self):
        """When signal_fallback returns give_up, the result carries
        the response's error info."""
        result = fetch_url(
            "https://example.com",
            domain_policy={"example.com": {"deny": False}},  # allow but...
            executor=_never_succeed(),
        )
        assert result.ok is False
        assert result.error_type is not None
        assert result.error_message is not None


# ---------------------------------------------------------------------------
# History propagation
# ---------------------------------------------------------------------------


class TestHistoryPropagation:
    def test_passes_history_to_mode_selector(self):
        """History with strong success bias should not crash or be ignored."""
        history = ModeHistory(
            successes={
                "http_simple": 100,
                "http_hardened": 50,
                "http_headless_browser": 5,
                "http_stealth": 0,
            },
            failures={
                "http_simple": 2,
                "http_hardened": 10,
                "http_headless_browser": 0,
                "http_stealth": 0,
            },
        )
        result = fetch_url(
            "https://example.com",
            history=history,
            executor=_immediate_success(),
        )
        assert result.ok is True


# ---------------------------------------------------------------------------
# Request forwarding
# ---------------------------------------------------------------------------


class TestRequestForwarding:
    def test_passes_headers_to_executor(self):
        captured: list[FetchRequest] = []

        def exec_fn(mode: str, req: FetchRequest) -> FetchResponse:
            captured.append(req)
            return _success()

        result = fetch_url(
            "https://example.com",
            headers={"authorization": "Bearer token1"},
            executor=exec_fn,
        )
        assert result.ok is True
        assert captured[0].headers.get("authorization") == "Bearer token1"

    def test_passes_timeout_to_request(self):
        captured: list[FetchRequest] = []

        def exec_fn(mode: str, req: FetchRequest) -> FetchResponse:
            captured.append(req)
            return _success()

        result = fetch_url(
            "https://example.com",
            timeout=30.0,
            executor=exec_fn,
        )
        assert result.ok is True
        assert captured[0].timeout == 30.0


# ---------------------------------------------------------------------------
# Forwarding cookie from response to next request
# ---------------------------------------------------------------------------


class TestCookiePersistAcrossEscalations:
    def test_cookies_from_failed_response_forwarded_to_next_request(self):
        seen_requests: list[FetchRequest] = []

        def exec_fn(mode: str, req: FetchRequest) -> FetchResponse:
            seen_requests.append(req)
            if mode == "http_simple":
                return _resp(ok=False, error_type="HTTPError", cookies={"session": "abc123", "csrf": "x"})
            return _success()

        result = fetch_url("https://example.com", executor=exec_fn)
        assert result.ok
        # Second request should carry cookies from first response
        assert len(seen_requests) >= 2
        assert seen_requests[1].cookies.get("session") == "abc123"
        assert seen_requests[1].cookies.get("csrf") == "x"


# ---------------------------------------------------------------------------
# Search mode handling
# ---------------------------------------------------------------------------


class TestSearchMode:
    def test_search_mode_dispatched_to_executor(self):
        """Fallback may go through 'search' → executor handles it.

        Uses text/plain content-type so blank_html is not flagged
        (otherwise Rule 3 jumps to headless and creates a loop).
        """
        modes_seen: list[str] = []

        def exec_fn(mode: str, req: FetchRequest) -> FetchResponse:
            modes_seen.append(mode)
            if mode == "search":
                return _success(body="search result")
            # text/plain prevents blank_html detection
            return _failure(
                error_type="HTTPError",
                body="403 Forbidden",
                headers={"content-type": "text/plain"},
            )

        result = fetch_url("https://example.com", executor=exec_fn)
        assert result.ok is True
        assert "search" in modes_seen


# ---------------------------------------------------------------------------
# Max iterations safety guard
# ---------------------------------------------------------------------------


class TestMaxIterationsGuard:
    def test_terminates_after_max_iterations(self):
        """When the fallback router keeps choosing modes (e.g., due to
        anti-bot signals looping), the orchestrator must eventually stop."""
        # Build an executor that always fails but never triggers give_up
        # (signals are empty, so signal_fallback just walks the chain)
        call_count = [0]
        max_allowed = 10  # matches _MAX_ITERATIONS

        def exec_fn(mode: str, req: FetchRequest) -> FetchResponse:
            call_count[0] += 1
            return _failure(error_type="HTTPError", body="just a plain failure")

        result = fetch_url("https://example.com", executor=exec_fn)
        assert result.ok is False
        # Should not exceed the max iteration cap
        assert call_count[0] <= max_allowed

    def test_result_indicates_exhaustion(self):
        def exec_fn(mode: str, req: FetchRequest) -> FetchResponse:
            return _failure(error_type="HTTPError")

        result = fetch_url("https://example.com", executor=exec_fn)
        assert result.ok is False
        # With only 4 modes + search + give_up, chain is < 10
        # The exact error type depends on whether give_up was reached
        assert result.error_type is not None


# ---------------------------------------------------------------------------
# No internal metadata leaks
# ---------------------------------------------------------------------------


class TestNoLeakage:
    def test_result_has_no_internal_fields(self):
        result = fetch_url("https://example.com", executor=_immediate_success())
        # Public schema only
        allowed_keys = {"ok", "status_code", "final_url", "headers", "cookies",
                        "body", "elapsed_ms", "error_type", "error_message"}
        actual_keys = set(vars(result).keys())
        assert actual_keys == allowed_keys, f"Unexpected fields: {actual_keys - allowed_keys}"

    def test_error_result_same_schema(self):
        result = fetch_url(
            "https://denied.example.com",
            domain_policy={"example.com": {"deny": True}},
            executor=_immediate_success(),
        )
        allowed_keys = {"ok", "status_code", "final_url", "headers", "cookies",
                        "body", "elapsed_ms", "error_type", "error_message"}
        actual_keys = set(vars(result).keys())
        assert actual_keys == allowed_keys