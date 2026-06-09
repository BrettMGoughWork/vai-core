"""Tests for stdlib.search primitive (PHASE 3.13.2)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.capabilities.primitives.stdlib.search import SearchPrimitive
from src.capabilities.primitives.types import PrimitiveResult
from src.core.state.config import SearchProviderConfig


@pytest.fixture
def search() -> SearchPrimitive:
    return SearchPrimitive()


@pytest.fixture
def tavily_config() -> SearchProviderConfig:
    return SearchProviderConfig(
        provider="tavily",
        api_key="test-key",
        max_results=5,
        timeout=5.0,
        enabled=True,
    )


@pytest.fixture
def bing_config() -> SearchProviderConfig:
    return SearchProviderConfig(
        provider="bing",
        api_key="test-key",
        max_results=5,
        timeout=5.0,
        enabled=True,
    )


@pytest.fixture
def serpapi_config() -> SearchProviderConfig:
    return SearchProviderConfig(
        provider="serpapi",
        api_key="test-key",
        max_results=5,
        timeout=5.0,
        enabled=True,
    )


class TestSearchPrimitiveValidation:
    """Tests for SearchPrimitive.validate_args."""

    def test_valid_query_passes(self, search: SearchPrimitive) -> None:
        search.validate_args({"query": "weather in London"})

    def test_missing_query_raises(self, search: SearchPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'query' key"):
            search.validate_args({})

    def test_query_not_string_raises(self, search: SearchPrimitive) -> None:
        with pytest.raises(ValueError, match="'query' must be a string"):
            search.validate_args({"query": 42})

    def test_empty_query_raises(self, search: SearchPrimitive) -> None:
        with pytest.raises(ValueError, match="'query' must not be empty"):
            search.validate_args({"query": "   "})

    def test_args_not_dict_raises(self, search: SearchPrimitive) -> None:
        with pytest.raises(ValueError, match="args must be a dict"):
            search.validate_args("not a dict")


class TestSearchPrimitiveConfigResolution:
    """Tests for how the primitive resolves and validates context config."""

    def test_missing_config_returns_error(self, search: SearchPrimitive) -> None:
        result = search.execute({"query": "test"}, {})
        assert result.status == "error"
        assert "not configured or disabled" in result.error

    def test_disabled_config_returns_error(
        self, search: SearchPrimitive, tavily_config: SearchProviderConfig
    ) -> None:
        tavily_config.enabled = False
        result = search.execute({"query": "test"}, {"search_config": tavily_config})
        assert result.status == "error"
        assert "disabled" in result.error

    def test_none_config_returns_error(self, search: SearchPrimitive) -> None:
        result = search.execute({"query": "test"}, {"search_config": None})
        assert result.status == "error"


class TestSearchPrimitiveNormalisation:
    """Tests for the provider-agnostic normalisation logic."""

    def test_tavily_normalisation(
        self, search: SearchPrimitive, tavily_config: SearchProviderConfig
    ) -> None:
        raw_results = [
            {"title": "T1", "url": "https://a.com", "content": "Snippet A"},
            {"title": "T2", "url": "https://b.com", "content": "Snippet B"},
        ]
        normalised = search._normalise("tavily", raw_results, 10)
        assert len(normalised) == 2
        assert normalised[0] == {"title": "T1", "url": "https://a.com", "snippet": "Snippet A"}
        assert normalised[1] == {"title": "T2", "url": "https://b.com", "snippet": "Snippet B"}

    def test_bing_normalisation(
        self, search: SearchPrimitive, bing_config: SearchProviderConfig
    ) -> None:
        raw_results = [
            {"name": "Bing Title", "url": "https://c.com", "snippet": "Bing snippet"},
        ]
        normalised = search._normalise("bing", raw_results, 10)
        assert len(normalised) == 1
        assert normalised[0] == {
            "title": "Bing Title",
            "url": "https://c.com",
            "snippet": "Bing snippet",
        }

    def test_serpapi_normalisation(
        self, search: SearchPrimitive, serpapi_config: SearchProviderConfig
    ) -> None:
        raw_results = [
            {"title": "Serp Title", "link": "https://d.com", "snippet": "Serp snippet"},
        ]
        normalised = search._normalise("serpapi", raw_results, 10)
        assert len(normalised) == 1
        assert normalised[0] == {
            "title": "Serp Title",
            "url": "https://d.com",
            "snippet": "Serp snippet",
        }

    def test_custom_normalisation(self, search: SearchPrimitive) -> None:
        raw_results = [
            {"title": "Custom T", "url": "https://e.com", "snippet": "Custom snippet"},
        ]
        normalised = search._normalise("custom", raw_results, 10)
        assert len(normalised) == 1
        assert normalised[0] == {
            "title": "Custom T",
            "url": "https://e.com",
            "snippet": "Custom snippet",
        }

    def test_max_results_truncation(self, search: SearchPrimitive) -> None:
        raw_results = [{"title": f"T{i}", "url": f"https://{i}.com", "content": f"S{i}"} for i in range(10)]
        normalised = search._normalise("tavily", raw_results, 3)
        assert len(normalised) == 3

    def test_title_truncation(self, search: SearchPrimitive) -> None:
        long_title = "A" * 300
        raw_results = [{"title": long_title, "url": "https://x.com", "content": "S"}]
        normalised = search._normalise("tavily", raw_results, 10)
        assert len(normalised[0]["title"]) == 200  # 197 + "..."
        assert normalised[0]["title"].endswith("...")

    def test_snippet_truncation(self, search: SearchPrimitive) -> None:
        long_snippet = "B" * 600
        raw_results = [{"title": "T", "url": "https://y.com", "content": long_snippet}]
        normalised = search._normalise("tavily", raw_results, 10)
        assert len(normalised[0]["snippet"]) == 500  # 497 + "..."
        assert normalised[0]["snippet"].endswith("...")

    def test_empty_results(self, search: SearchPrimitive) -> None:
        normalised = search._normalise("tavily", [], 10)
        assert normalised == []

    def test_missing_fields_default_to_empty_strings(
        self, search: SearchPrimitive
    ) -> None:
        raw_results = [{}]
        normalised = search._normalise("tavily", raw_results, 10)
        assert normalised == [{"title": "", "url": "", "snippet": ""}]


class TestSearchPrimitiveExecution:
    """Integration-style tests that mock httpx."""

    def test_successful_tavily_search(
        self, search: SearchPrimitive, tavily_config: SearchProviderConfig
    ) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "results": [
                {"title": "Weather", "url": "https://weather.com", "content": "Cloudy"},
            ]
        }

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )
            result = search.execute(
                {"query": "weather"}, {"search_config": tavily_config}
            )

        assert result.status == "success"
        assert len(result.data["results"]) == 1
        assert result.data["results"][0]["title"] == "Weather"
        assert result.data["results"][0]["url"] == "https://weather.com"
        assert result.data["results"][0]["snippet"] == "Cloudy"
        assert "elapsed_ms" in result.data

    def test_successful_bing_search(
        self, search: SearchPrimitive, bing_config: SearchProviderConfig
    ) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "webPages": {
                "value": [
                    {"name": "Bing R", "url": "https://b.com", "snippet": "Result"},
                ]
            }
        }

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = (
                mock_response
            )
            result = search.execute(
                {"query": "test"}, {"search_config": bing_config}
            )

        assert result.status == "success"
        assert result.data["results"][0]["title"] == "Bing R"

    def test_http_error_is_caught(
        self, search: SearchPrimitive, tavily_config: SearchProviderConfig
    ) -> None:
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.side_effect = (
                Exception("Connection refused")
            )
            result = search.execute(
                {"query": "test"}, {"search_config": tavily_config}
            )

        assert result.status == "error"
        assert "Connection refused" in result.error
        assert result.data["results"] == []

    def test_unknown_provider_returns_error(
        self, search: SearchPrimitive
    ) -> None:
        config = SearchProviderConfig(
            provider="unknown_provider",
            api_key="k",
            max_results=5,
            timeout=5.0,
            enabled=True,
        )
        result = search.execute(
            {"query": "test"}, {"search_config": config}
        )
        assert result.status == "error"
        assert "unknown search provider" in result.error

    def test_custom_endpoint_requires_endpoint(
        self, search: SearchPrimitive
    ) -> None:
        config = SearchProviderConfig(
            provider="custom",
            api_key="k",
            max_results=5,
            timeout=5.0,
            enabled=True,
        )
        # No endpoint set — should raise ValueError
        result = search.execute(
            {"query": "test"}, {"search_config": config}
        )
        assert result.status == "error"
        assert "requires an endpoint" in result.error

    def test_max_results_override_from_args(
        self, search: SearchPrimitive, tavily_config: SearchProviderConfig
    ) -> None:
        """max_results in args overrides config.max_results."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "results": [
                {"title": f"R{i}", "url": f"https://{i}.com", "content": f"S{i}"}
                for i in range(10)
            ]
        }

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )
            result = search.execute(
                {"query": "test", "max_results": 3},
                {"search_config": tavily_config},
            )

        assert result.status == "success"
        # Should be truncated to 3, not the config's default of 5
        assert len(result.data["results"]) == 3

    def test_invalid_max_results_override_is_ignored(
        self, search: SearchPrimitive, tavily_config: SearchProviderConfig
    ) -> None:
        """Invalid max_results values are silently ignored."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "results": [
                {"title": "R1", "url": "https://a.com", "content": "S1"},
                {"title": "R2", "url": "https://b.com", "content": "S2"},
            ]
        }

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )
            # Negative value should be ignored, falls back to config default
            result = search.execute(
                {"query": "test", "max_results": -5},
                {"search_config": tavily_config},
            )

        assert result.status == "success"
        assert len(result.data["results"]) == 2  # not truncated (config default=5)
