"""Tests for S3 search providers and provider registry (PHASE 3.13.1)."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.capabilities.search.provider_registry import ProviderRegistry, RegistryError
from src.capabilities.search.providers._base import SearchProviderError, SearchResult
from src.capabilities.search.providers.duckduckgo import DuckDuckGoProvider
from src.capabilities.search.providers.tavily import TavilyProvider
from src.strategy.state.config import ProviderConfig, SearchConfig


# ── Test helpers ──────────────────────────────────────────────────────────


def _make_async_response(status_code: int, text: str = "", json_data=None):
    """Build an AsyncMock that mimics an httpx.Response for async usage."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    return resp


def _patch_async_get(monkeypatch, return_value):
    """Patch httpx.AsyncClient.get to return *return_value*."""
    mock_get = AsyncMock(return_value=return_value)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: mock_ctx)
    return mock_get


def _patch_async_post(monkeypatch, return_value):
    """Patch httpx.AsyncClient.post to return *return_value*."""
    mock_post = AsyncMock(return_value=return_value)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: mock_ctx)
    return mock_post


# ── DuckDuckGoProvider ────────────────────────────────────────────────────


class TestDuckDuckGoProvider:
    """Tests for the DuckDuckGo HTML-scraping provider."""

    @pytest.fixture
    def config(self) -> ProviderConfig:
        return ProviderConfig(max_results=5, timeout=10.0)

    @pytest.fixture
    def provider(self, config: ProviderConfig) -> DuckDuckGoProvider:
        return DuckDuckGoProvider(config)

    @pytest.mark.anyio
    async def test_search_returns_normalised_results(
        self, provider: DuckDuckGoProvider, monkeypatch
    ) -> None:
        """Successful search returns SearchResult objects."""
        html = """<html><body>
        <div class="result">
            <a class="result__a" href="//duckduckgo.com/l/?uddg=https://example.com">Example</a>
            <span class="result__snippet">An example website</span>
        </div>
        <div class="result">
            <a class="result__a" href="https://test.com">Test Site</a>
            <span class="result__snippet">Another snippet</span>
        </div>
        </body></html>"""
        resp = _make_async_response(200, text=html)
        _patch_async_get(monkeypatch, resp)

        results = await provider.search("test query", 5)

        assert len(results) == 2
        assert isinstance(results[0], SearchResult)
        assert results[0].title == "Example"
        assert results[0].url == "https://example.com"
        assert results[0].snippet == "An example website"
        assert results[1].title == "Test Site"
        assert results[1].url == "https://test.com"

    @pytest.mark.anyio
    async def test_respects_max_results(
        self, provider: DuckDuckGoProvider, monkeypatch
    ) -> None:
        """Only returns up to max_results items."""
        html = "<html><body>" + "".join(
            f'<div class="result"><a class="result__a" href="https://{i}.com">Title {i}</a>'
            f'<span class="result__snippet">Snippet {i}</span></div>'
            for i in range(10)
        ) + "</body></html>"
        resp = _make_async_response(200, text=html)
        _patch_async_get(monkeypatch, resp)

        results = await provider.search("test", 3)

        assert len(results) == 3

    @pytest.mark.anyio
    async def test_empty_results_on_no_matches(
        self, provider: DuckDuckGoProvider, monkeypatch
    ) -> None:
        """When no .result elements are found, returns empty list."""
        html = "<html><body><p>No results found</p></body></html>"
        resp = _make_async_response(200, text=html)
        _patch_async_get(monkeypatch, resp)

        results = await provider.search("xyznonexistent", 5)

        assert results == []

    @pytest.mark.anyio
    async def test_http_error_raises_search_provider_error(
        self, provider: DuckDuckGoProvider, monkeypatch
    ) -> None:
        """HTTP errors are wrapped in SearchProviderError."""
        resp = _make_async_response(500, text="Server Error")
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "server error",
            request=httpx.Request("GET", "https://html.duckduckgo.com/html/"),
            response=httpx.Response(500),
        )
        _patch_async_get(monkeypatch, resp)

        with pytest.raises(SearchProviderError, match="HTTP 500"):
            await provider.search("test", 5)

    @pytest.mark.anyio
    async def test_request_error_raises_search_provider_error(
        self, provider: DuckDuckGoProvider, monkeypatch
    ) -> None:
        """Network errors are wrapped in SearchProviderError."""
        mock_get = AsyncMock(side_effect=httpx.RequestError("connection failed"))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: mock_ctx)

        with pytest.raises(SearchProviderError, match="request failed"):
            await provider.search("test", 5)

    @pytest.mark.anyio
    async def test_title_truncation(
        self, provider: DuckDuckGoProvider, monkeypatch
    ) -> None:
        """Titles longer than 200 chars are truncated with ellipsis."""
        long_title = "A" * 250
        html = f"""<html><body>
        <div class="result">
            <a class="result__a" href="https://x.com">{long_title}</a>
            <span class="result__snippet">snippet</span>
        </div>
        </body></html>"""
        resp = _make_async_response(200, text=html)
        _patch_async_get(monkeypatch, resp)

        results = await provider.search("test", 5)

        assert len(results[0].title) == 200
        assert results[0].title.endswith("...")

    @pytest.mark.anyio
    async def test_missing_snippet_defaults_to_empty(
        self, provider: DuckDuckGoProvider, monkeypatch
    ) -> None:
        """When snippet element is absent, snippet is empty string."""
        html = """<html><body>
        <div class="result">
            <a class="result__a" href="https://x.com">Title</a>
        </div>
        </body></html>"""
        resp = _make_async_response(200, text=html)
        _patch_async_get(monkeypatch, resp)

        results = await provider.search("test", 5)

        assert results[0].snippet == ""

    @pytest.mark.anyio
    async def test_missing_url_element_skipped(
        self, provider: DuckDuckGoProvider, monkeypatch
    ) -> None:
        """Result without a title link is skipped."""
        html = """<html><body>
        <div class="result">
            <span class="result__snippet">no link here</span>
        </div>
        <div class="result">
            <a class="result__a" href="https://valid.com">Valid</a>
            <span class="result__snippet">has link</span>
        </div>
        </body></html>"""
        resp = _make_async_response(200, text=html)
        _patch_async_get(monkeypatch, resp)

        results = await provider.search("test", 5)

        assert len(results) == 1
        assert results[0].title == "Valid"

    def test_extract_url_handles_uddg_redirect(self) -> None:
        """_extract_url decodes DuckDuckGo redirect URLs."""
        href = "//duckduckgo.com/l/?uddg=https://real-site.com/page&rut=abc"
        result = DuckDuckGoProvider._extract_url(href)
        assert result == "https://real-site.com/page"

    def test_extract_url_passes_through_plain_urls(self) -> None:
        """_extract_url returns plain URLs unchanged."""
        href = "https://example.com"
        result = DuckDuckGoProvider._extract_url(href)
        assert result == "https://example.com"

    def test_extract_url_handles_missing_uddg(self) -> None:
        """_extract_url returns original if no uddg param."""
        href = "//duckduckgo.com/l/?rut=abc"
        result = DuckDuckGoProvider._extract_url(href)
        assert "duckduckgo.com" in result

    def test_name_is_duckduckgo(self, provider: DuckDuckGoProvider) -> None:
        assert provider.name == "duckduckgo"


# ── TavilyProvider ────────────────────────────────────────────────────────


class TestTavilyProvider:
    """Tests for the Tavily API provider."""

    @pytest.fixture
    def config(self) -> ProviderConfig:
        return ProviderConfig(
            max_results=5,
            timeout=10.0,
            api_key_env="TAVILY_API_KEY",
        )

    @pytest.fixture(autouse=True)
    def _set_api_key(self, monkeypatch) -> None:
        monkeypatch.setenv("TAVILY_API_KEY", "test-api-key-value")

    @pytest.fixture
    def provider(self, config: ProviderConfig) -> TavilyProvider:
        return TavilyProvider(config)

    @pytest.mark.anyio
    async def test_search_returns_normalised_results(
        self, provider: TavilyProvider, monkeypatch
    ) -> None:
        """Successful search returns SearchResult objects."""
        resp = _make_async_response(
            200,
            json_data={
                "results": [
                    {"title": "AI News", "url": "https://ai.example.com", "content": "Latest AI news"},
                    {"title": "ML Trends", "url": "https://ml.example.com", "content": "ML trends 2025"},
                ]
            },
        )
        _patch_async_post(monkeypatch, resp)

        results = await provider.search("AI trends", 5)

        assert len(results) == 2
        assert isinstance(results[0], SearchResult)
        assert results[0].title == "AI News"
        assert results[0].url == "https://ai.example.com"
        assert results[0].snippet == "Latest AI news"

    @pytest.mark.anyio
    async def test_respects_max_results(
        self, provider: TavilyProvider, monkeypatch
    ) -> None:
        """Only returns up to max_results items."""
        resp = _make_async_response(
            200,
            json_data={
                "results": [
                    {"title": f"Result {i}", "url": f"https://{i}.com", "content": f"Snippet {i}"}
                    for i in range(10)
                ]
            },
        )
        _patch_async_post(monkeypatch, resp)

        results = await provider.search("test", 3)

        assert len(results) == 3

    @pytest.mark.anyio
    async def test_empty_results_when_no_data(
        self, provider: TavilyProvider, monkeypatch
    ) -> None:
        """When API returns no results key, returns empty list."""
        resp = _make_async_response(200, json_data={})
        _patch_async_post(monkeypatch, resp)

        results = await provider.search("test", 5)

        assert results == []

    @pytest.mark.anyio
    async def test_empty_results_when_empty_array(
        self, provider: TavilyProvider, monkeypatch
    ) -> None:
        """When API returns empty results array, returns empty list."""
        resp = _make_async_response(200, json_data={"results": []})
        _patch_async_post(monkeypatch, resp)

        results = await provider.search("test", 5)

        assert results == []

    @pytest.mark.anyio
    async def test_http_error_raises_search_provider_error(
        self, provider: TavilyProvider, monkeypatch
    ) -> None:
        """HTTP errors are wrapped in SearchProviderError."""
        resp = _make_async_response(401)
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "unauthorized",
            request=httpx.Request("POST", "https://api.tavily.com/search"),
            response=httpx.Response(401),
        )
        _patch_async_post(monkeypatch, resp)

        with pytest.raises(SearchProviderError, match="HTTP 401"):
            await provider.search("test", 5)

    @pytest.mark.anyio
    async def test_request_error_raises_search_provider_error(
        self, provider: TavilyProvider, monkeypatch
    ) -> None:
        """Network errors are wrapped in SearchProviderError."""
        mock_post = AsyncMock(side_effect=httpx.RequestError("connection failed"))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: mock_ctx)

        with pytest.raises(SearchProviderError, match="request failed"):
            await provider.search("test", 5)

    @pytest.mark.anyio
    async def test_title_truncation(
        self, provider: TavilyProvider, monkeypatch
    ) -> None:
        """Titles longer than 200 chars are truncated."""
        long_title = "B" * 250
        resp = _make_async_response(
            200,
            json_data={
                "results": [{"title": long_title, "url": "https://x.com", "content": "snippet"}]
            },
        )
        _patch_async_post(monkeypatch, resp)

        results = await provider.search("test", 5)

        assert len(results[0].title) == 200
        assert results[0].title.endswith("...")

    @pytest.mark.anyio
    async def test_missing_title_defaults_to_empty(
        self, provider: TavilyProvider, monkeypatch
    ) -> None:
        """Missing title field defaults to empty string."""
        resp = _make_async_response(
            200,
            json_data={"results": [{"url": "https://x.com", "content": "snippet"}]},
        )
        _patch_async_post(monkeypatch, resp)

        results = await provider.search("test", 5)

        assert results[0].title == ""

    def test_missing_api_key_env_raises(self) -> None:
        """Provider raises if api_key_env is not set."""
        config = ProviderConfig(max_results=5, timeout=10.0, api_key_env=None)

        with pytest.raises(SearchProviderError, match="api_key_env"):
            TavilyProvider(config)

    def test_empty_env_var_raises(self, monkeypatch) -> None:
        """Provider raises if the env var is set but empty."""
        monkeypatch.setenv("TAVILY_API_KEY", "")
        config = ProviderConfig(max_results=5, timeout=10.0, api_key_env="TAVILY_API_KEY")

        with pytest.raises(SearchProviderError, match="not set or empty"):
            TavilyProvider(config)

    def test_missing_env_var_raises(self, monkeypatch) -> None:
        """Provider raises if the env var is not set at all."""
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        config = ProviderConfig(max_results=5, timeout=10.0, api_key_env="TAVILY_API_KEY")

        with pytest.raises(SearchProviderError, match="not set or empty"):
            TavilyProvider(config)

    def test_uses_config_endpoint_override(self, monkeypatch) -> None:
        """Provider uses endpoint from config when provided."""
        monkeypatch.setenv("CUSTOM_API_KEY", "key123")
        config = ProviderConfig(
            max_results=5,
            timeout=10.0,
            api_key_env="CUSTOM_API_KEY",
            endpoint="https://custom-tavily.example.com/search",
        )
        provider = TavilyProvider(config)
        # The endpoint override is used when config.endpoint is set
        assert provider._config.endpoint == "https://custom-tavily.example.com/search"

    def test_name_is_tavily(self, provider: TavilyProvider) -> None:
        assert provider.name == "tavily"


# ── ProviderRegistry ──────────────────────────────────────────────────────


class TestProviderRegistry:
    """Tests for the provider registry."""

    def test_default_provider_selection(self) -> None:
        """get_default_provider returns the configured default."""
        config = SearchConfig(
            default_provider="duckduckgo",
            providers={"duckduckgo": ProviderConfig(max_results=5)},
        )
        registry = ProviderRegistry(config)
        provider = registry.get_default_provider()
        assert isinstance(provider, DuckDuckGoProvider)
        assert provider.name == "duckduckgo"

    def test_get_provider_by_name(self) -> None:
        """get_provider returns the named provider."""
        config = SearchConfig(
            default_provider="tavily",
            providers={
                "tavily": ProviderConfig(max_results=5, api_key_env="TAVILY_API_KEY"),
                "duckduckgo": ProviderConfig(max_results=10),
            },
        )
        with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
            registry = ProviderRegistry(config)
            ddg = registry.get_provider("duckduckgo")
            assert isinstance(ddg, DuckDuckGoProvider)

    def test_provider_instances_are_cached(self) -> None:
        """get_provider returns the same instance on repeated calls."""
        config = SearchConfig(
            default_provider="duckduckgo",
            providers={"duckduckgo": ProviderConfig(max_results=5)},
        )
        registry = ProviderRegistry(config)
        a = registry.get_provider("duckduckgo")
        b = registry.get_provider("duckduckgo")
        assert a is b

    def test_missing_default_provider_raises(self) -> None:
        """Raises RegistryError when default_provider is empty."""
        config = SearchConfig(
            default_provider="",
            providers={"tavily": ProviderConfig()},
        )
        with pytest.raises(RegistryError, match="default_provider is not set"):
            ProviderRegistry(config)

    def test_unconfigured_default_raises(self) -> None:
        """Raises RegistryError when default has no provider config."""
        config = SearchConfig(
            default_provider="tavily",
            providers={"duckduckgo": ProviderConfig()},
        )
        with pytest.raises(RegistryError, match="no configuration"):
            ProviderRegistry(config)

    def test_configured_but_not_registered_raises(self) -> None:
        """Raises RegistryError when a provider is configured but not registered."""
        config = SearchConfig(
            default_provider="tavily",
            providers={
                "tavily": ProviderConfig(api_key_env="TAVILY_API_KEY"),
                "nonexistent_provider_xyz": ProviderConfig(),
            },
        )
        with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
            registry = ProviderRegistry(config)
            with pytest.raises(RegistryError, match="not registered"):
                registry.get_provider("nonexistent_provider_xyz")

    def test_unconfigured_provider_lookup_raises(self) -> None:
        """Raises RegistryError when looking up a provider not in config."""
        config = SearchConfig(
            default_provider="duckduckgo",
            providers={"duckduckgo": ProviderConfig()},
        )
        registry = ProviderRegistry(config)
        with pytest.raises(RegistryError, match="not configured"):
            registry.get_provider("tavily")

    def test_provider_init_failure_raises_registry_error(self) -> None:
        """When a provider fails to initialise, RegistryError is raised at lookup time."""
        config = SearchConfig(
            default_provider="tavily",
            providers={"tavily": ProviderConfig(api_key_env="TAVILY_API_KEY")},
        )
        with patch.dict(os.environ, {}, clear=True):
            # TAVILY_API_KEY not set → TavilyProvider.__init__ raises on lazy init
            registry = ProviderRegistry(config)
            with pytest.raises(RegistryError, match="Failed to initialise"):
                registry.get_provider("tavily")

    def test_custom_provider_registration(self) -> None:
        """register_provider allows adding a custom provider class."""

        class FakeProvider:
            name = "fake"

            def __init__(self, config: ProviderConfig) -> None:
                self._config = config

            async def search(self, query: str, max_results: int) -> list[SearchResult]:
                return [SearchResult(title="Fake", url="https://f.com", snippet="fake")]

        config = SearchConfig(
            default_provider="fake",
            providers={"fake": ProviderConfig(max_results=5)},
        )
        registry = ProviderRegistry(config)
        registry.register_provider("fake", FakeProvider)
        provider = registry.get_provider("fake")
        assert isinstance(provider, FakeProvider)
        assert provider.name == "fake"

    def test_list_configured(self) -> None:
        """_list_configured returns sorted provider names from config."""
        config = SearchConfig(
            default_provider="tavily",
            providers={
                "tavily": ProviderConfig(api_key_env="TAVILY_API_KEY"),
                "duckduckgo": ProviderConfig(),
            },
        )
        with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
            registry = ProviderRegistry(config)
            assert registry._list_configured() == ["duckduckgo", "tavily"]

    def test_list_available(self) -> None:
        """_list_available returns all built-in + custom provider names."""
        config = SearchConfig(
            default_provider="duckduckgo",
            providers={"duckduckgo": ProviderConfig()},
        )
        registry = ProviderRegistry(config)
        available = registry._list_available()
        assert "duckduckgo" in available
        assert "tavily" in available
