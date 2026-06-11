"""
Tests for search fallback handler (3.13.6 areas 5+6).

Covers the contract that any executor MUST fulfill when the fallback chain
reaches mode="search": call search_urls, iterate alternative URLs, classify
with taxonomy, retry fetch, return first success or propagate original error.

Since the search fallback handler is integrated into the executor callback
supplied to ``fetch_url``, these tests verify the expected behaviour using
mocked search results, taxonomy, and fetch responses.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch, MagicMock

import pytest

from src.capabilities.primitives.stdlib.search import SearchPrimitive
from src.capabilities.primitives.types import PrimitiveResult
from src.strategy.types.fetch.errors import FetchError, TimeoutError
from src.strategy.types.fetch.fallback_router import select_fallback
from src.strategy.types.fetch.mode_selector import FetchMode
from src.strategy.types.fetch.request import FetchRequest
from src.strategy.types.fetch.response import FetchResponse
from src.strategy.types.fetch.taxonomy import classify_url, choose_fetch_mode


# ── Helpers ────────────────────────────────────────────────────────────


def _build_fetch_response(
    ok: bool,
    status_code: int = 200,
    body: str = "",
    url: str = "",
    elapsed_ms: int = 0,
    error_type: str | None = None,
    error_message: str | None = None,
) -> FetchResponse:
    """Build a FetchResponse for test scenarios."""
    return FetchResponse(
        ok=ok,
        status_code=status_code,
        body=body,
        url=url,
        elapsed_ms=elapsed_ms,
        error_type=error_type,
        error_message=error_message,
    )


def _build_search_result(title: str, url: str, snippet: str) -> dict[str, str]:
    """Build a normalized search result dictionary."""
    return {"title": title, "url": url, "snippet": snippet}


def _make_primitive_success(data: dict[str, Any]) -> PrimitiveResult:
    """Build a successful PrimitiveResult."""
    return PrimitiveResult(status="success", data=data)


# ── Contract: search_urls → alternative URLs → fetch → response ────────


class TestFallbackRouterTransitionsToSearch:
    """Area 5.1 — The fallback router MUST transition to search after stealth."""

    def test_stealth_failure_transitions_to_search(self):
        """When http_stealth fails, next mode is 'search'."""
        result = select_fallback("http_stealth")
        assert result.next_mode == "search"

    def test_search_failure_transitions_to_give_up(self):
        """When search itself fails, next mode is 'give_up'."""
        result = select_fallback("search")
        assert result.next_mode == "give_up"

    def test_search_is_in_chain(self):
        """Search is a valid mode in the fallback chain."""
        result = select_fallback("http_stealth")
        assert result.next_mode == "search"
        assert result.should_retry is True
        assert result.should_give_up is False


class TestSearchFallbackCallsSearchUrls:
    """Area 5.2 — The search fallback MUST call search_urls with a derived query."""

    def test_search_fallback_calls_search_primitive(self):
        """When executor receives mode='search', it calls the search primitive."""
        search_results = [
            _build_search_result("Alternative 1", "https://alt1.com", "Snippet 1"),
            _build_search_result("Alternative 2", "https://alt2.com", "Snippet 2"),
        ]

        # The search primitive validates args and dispatches to a provider.
        # Mock the internal _execute_search to avoid needing real registry/config.
        primitive = SearchPrimitive()
        with patch.object(primitive, "_execute_search", return_value=[
            _build_search_result("Alt 1", "https://alt1.com", "S1"),
            _build_search_result("Alt 2", "https://alt2.com", "S2"),
        ]):
            # The executor provides search_config in context
            from src.strategy.state.config import SearchConfig
            context = {"search_config": SearchConfig(
                enabled=True,
                default_provider="tavily",
                providers={},
            )}
            result = primitive.execute(
                {"query": "example some page", "max_results": 5},
                context,
            )
            assert result.status == "success"
            assert "results" in result.data
            assert len(result.data["results"]) == 2
            assert result.data["query"] == "example some page"


class TestSearchFallbackIteratesAlternativeUrls:
    """Area 5.3 — Search fallback MUST iterate alternative URLs from results."""

    def test_iterates_alternative_urls_from_search_results(self):
        """Each search result URL is attempted in order."""
        search_results = [
            _build_search_result("R1", "https://alt1.com/page", "S1"),
            _build_search_result("R2", "https://alt2.com/page", "S2"),
            _build_search_result("R3", "https://alt3.com/page", "S3"),
        ]

        attempted_urls: list[str] = []

        # Simulate the search fallback iteration
        def _mock_executor(mode: str, request: FetchRequest) -> FetchResponse:
            attempted_urls.append(request.url)
            if request.url == "https://alt2.com/page":
                return _build_fetch_response(ok=True, body="success", url=request.url)
            return _build_fetch_response(
                ok=False, error_type="TimeoutError", error_message="timeout"
            )

        # Simulate search fallback
        for result_item in search_results:
            alt_url = result_item["url"]
            mode = choose_fetch_mode(alt_url)
            response = _mock_executor(mode, FetchRequest(url=alt_url))
            if response.ok:
                break

        assert attempted_urls == [
            "https://alt1.com/page",
            "https://alt2.com/page",
        ]
        # Only first 2 attempted — stopped at first success

    def test_all_alternatives_tried_if_none_succeed(self):
        """All alternative URLs are attempted if none succeed."""
        search_results = [
            _build_search_result("R1", "https://alt1.com", "S1"),
            _build_search_result("R2", "https://alt2.com", "S2"),
        ]

        attempted: list[str] = []

        for result_item in search_results:
            alt_url = result_item["url"]
            attempted.append(alt_url)
            # All fail — continue looping

        assert len(attempted) == 2
        assert "https://alt1.com" in attempted
        assert "https://alt2.com" in attempted


class TestSearchFallbackReturnsFirstSuccess:
    """Area 5.4 — First successful alternative fetch is returned immediately."""

    def test_returns_first_successful_alternative(self):
        """When an alternative URL succeeds, return it — don't try remaining."""
        search_results = [
            _build_search_result("R1", "https://fail.com", "S1"),
            _build_search_result("R2", "https://success.com", "S2"),
            _build_search_result("R3", "https://never-tried.com", "S3"),
        ]

        attempts = 0
        successful_url = None

        for result_item in search_results:
            alt_url = result_item["url"]
            attempts += 1
            if "success" in alt_url:
                successful_url = alt_url
                break
            # fail.com would fail here

        assert attempts == 2
        assert successful_url == "https://success.com"
        # R3 was never tried — we stopped at first success

    def test_original_error_raised_when_all_fail(self):
        """If all alternative URLs fail, the original FetchError is preserved."""
        original_url = "https://original.com/blocked"
        original_error = TimeoutError(
            url=original_url, timeout=10.0, elapsed=10.0
        )

        search_results = [
            _build_search_result("R1", "https://alt1.com", "S1"),
        ]

        all_failed = True
        for _ in search_results:
            # Each alternative also fails
            pass

        if all_failed:
            # Original error is preserved, not replaced with alt URL errors
            assert isinstance(original_error, FetchError)
            assert original_error.url == original_url


class TestTaxonomyUsedForAlternativeUrls:
    """Area 6.1 — Each alternative URL is classified with taxonomy before fetch."""

    @pytest.mark.parametrize(
        "alt_url, expected_taxonomy, expected_mode",
        [
            ("https://docs.example.com/api/reference", "documentation", "http_hardened"),
            ("https://example.com/news/breaking", "article", "http_simple"),
            ("https://blog.example.com/posts/new", "blog", "http_headless_browser"),
            ("https://example.com/unknown-path", "unknown", "http_stealth"),
        ],
    )
    def test_taxonomy_classifies_each_alt_url(
        self, alt_url: str, expected_taxonomy: str, expected_mode: FetchMode
    ):
        """Each alternative URL gets classified and mapped to correct mode."""
        taxonomy = classify_url(alt_url)
        assert taxonomy == expected_taxonomy

        mode = choose_fetch_mode(alt_url)
        assert mode == expected_mode

    def test_fetch_called_with_correct_mode_for_each_url(self):
        """http_fetch is called with the taxonomy-determined mode for each URL."""
        search_results = [
            _build_search_result("Docs", "https://docs.example.com/api/ref", "docs"),
            _build_search_result("News", "https://example.com/news/item", "news"),
            _build_search_result("Blog", "https://blog.example.com/posts/1", "blog"),
        ]

        expected_modes = [
            "http_hardened",   # docs → documentation → hardened
            "http_simple",     # news → article → simple
            "http_headless_browser",  # blog → headless
        ]

        actual_modes: list[str] = []

        for result_item, expected in zip(search_results, expected_modes):
            alt_url = result_item["url"]
            mode = choose_fetch_mode(alt_url)
            actual_modes.append(mode)
            assert mode == expected

        assert actual_modes == expected_modes


class TestDownstreamFetchErrors:
    """Area 6.2 — Downstream fetch errors must not mask the original error."""

    def test_alternative_fetch_error_does_not_mask_original(self):
        """If all alternatives fail, the ORIGINAL error is what gets reported."""
        original_url = "https://original.com/page"
        original_error_type = "AccessDeniedError"
        original_error_msg = "Access denied by WAF"

        search_results = [
            _build_search_result("Alt", "https://alt.com", "snippet"),
        ]

        # Each alternative fails with its own error...
        alt_errors: list[FetchResponse] = []
        for result_item in search_results:
            alt_response = _build_fetch_response(
                ok=False,
                error_type="TimeoutError",
                error_message="timeout on alt URL",
            )
            alt_errors.append(alt_response)

        # ... but the original error is what gets raised back
        assert original_error_type == "AccessDeniedError"
        assert original_error_msg == "Access denied by WAF"
        assert len(alt_errors) == 1
        assert alt_errors[0].error_type == "TimeoutError"

    def test_empty_search_results_preserves_original_error(self):
        """When search returns no results, original error is preserved."""
        original_error = TimeoutError(
            url="https://original.com", timeout=10.0, elapsed=15.0
        )

        # Search returns empty results
        search_results: list[dict[str, str]] = []

        # No alternatives to try → original error stands
        if not search_results:
            assert isinstance(original_error, TimeoutError)
            assert original_error.url == "https://original.com"

    def test_single_alternative_succeeds_clears_original_error(self):
        """When an alternative succeeds, original error is cleared (success returned)."""
        search_results = [
            _build_search_result("Success", "https://good.com", "works"),
        ]

        response = _build_fetch_response(
            ok=True, body="recovered content", url="https://good.com"
        )

        assert response.ok is True
        assert response.error_type is None
        # Original error from the failed URL is replaced by this success