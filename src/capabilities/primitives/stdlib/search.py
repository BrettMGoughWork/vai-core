"""stdlib.search — Web search primitive (PHASE 3.13.2).

Performs a provider‑agnostic web search: accepts a query string, constructs a
provider request using runtime‑supplied configuration (SearchConfig
from ``context["search_config"]``), dispatches via the provider registry,
and normalises the raw provider response into the standard
``[{title, url, snippet}]`` schema.

This primitive NEVER exposes the provider name, API key, or endpoint to the
LLM.  The LLM receives only the normalised search results.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
import urllib.parse
from dataclasses import replace
from typing import Any

import httpx

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.capabilities.search.provider_registry import ProviderRegistry, RegistryError
from src.capabilities.search.providers._base import SearchResult
from src.strategy.state.config import SearchConfig, SearchProviderConfig
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class SearchPrimitive(PrimitiveBase):
    """Execute a web search and return provider‑agnostic normalised results."""

    name = "stdlib.search"
    description = "Execute a web search and return normalised results (title, url, snippet)"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query string",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (optional, defaults to provider config)",
            },
        },
        "required": ["query"],
    }

    def __init__(self) -> None:
        super().__init__(
            name=self.name,
            description=self.description,
            primitive_type=self.primitive_type,
        )
        self._cached_registry: tuple[SearchConfig, ProviderRegistry] | None = None

    @staticmethod
    def _run_async(coro):
        """Run an async coroutine safely from a sync context.

        Works both when there is no running event loop (uses
        ``asyncio.run``) and when already inside one (spawns a
        thread to avoid ``RuntimeError``).
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()

    def _get_registry(self, config: SearchConfig) -> ProviderRegistry:
        """Get or create a cached ProviderRegistry for *config*."""
        if self._cached_registry is not None and self._cached_registry[0] is config:
            return self._cached_registry[1]
        registry = ProviderRegistry(config)
        self._cached_registry = (config, registry)
        return registry

    # ── argument validation ──────────────────────────────────────────────

    def validate_args(self, args: dict) -> None:
        if not isinstance(args, dict):
            raise ValueError(f"args must be a dict, got {type(args).__name__}")
        if "query" not in args:
            raise ValueError("args must contain 'query' key")
        query = args["query"]
        if not isinstance(query, str):
            raise ValueError(f"'query' must be a string, got {type(query).__name__}")
        if not query.strip():
            raise ValueError("'query' must not be empty")

    # ── execution ────────────────────────────────────────────────────────

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)

        query: str = args["query"].strip()

        # Resolve search config from context (injected by runtime)
        config = context.get("search_config")
        if config is None or not config.enabled:
            return PrimitiveResult(
                status="error",
                data={"results": [], "error": "search is not configured or disabled"},
                error="search is not configured or disabled",
            )

        # Allow args to override provider max_results (per‑call override)
        max_results_override: int | None = None
        if "max_results" in args:
            try:
                override = int(args["max_results"])
                if override > 0:
                    max_results_override = override
            except (TypeError, ValueError):
                pass  # ignore invalid overrides

        start = time.perf_counter()

        try:
            results = self._execute_search(query, config, max_results_override)
            elapsed_ms = int((time.perf_counter() - start) * 1000)

            # Normalise to dicts — both SearchResult and legacy dict paths
            norm_results = []
            for r in results:
                if isinstance(r, SearchResult):
                    norm_results.append({"title": r.title, "url": r.url, "snippet": r.snippet})
                else:
                    norm_results.append(r)

            return PrimitiveResult(
                status="success",
                data={
                    "results": norm_results,
                    "query": query,
                    "elapsed_ms": elapsed_ms,
                },
            )

        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)

            return PrimitiveResult(
                status="error",
                data={
                    "results": [],
                    "query": query,
                    "elapsed_ms": elapsed_ms,
                    "error": str(exc),
                },
                error=str(exc),
            )

    # ── provider dispatch ────────────────────────────────────────────────

    def _execute_search(
        self,
        query: str,
        config: SearchConfig | SearchProviderConfig,
        max_results_override: int | None = None,
    ) -> list[SearchResult | dict]:
        """Dispatch to the appropriate provider and return results.

        Uses the provider registry for ``SearchConfig`` (new multi‑provider
        format).  Falls back to inline dispatch for legacy
        ``SearchProviderConfig``.
        """
        if isinstance(config, SearchConfig):
            return self._execute_via_registry(query, config, max_results_override)
        else:
            # Legacy SearchProviderConfig path — inline dispatch
            cfg: SearchProviderConfig = config
            if max_results_override:
                cfg = replace(cfg, max_results=max_results_override)
            provider = cfg.provider.lower()

            if provider == "tavily":
                raw = self._search_tavily(query, cfg)
            elif provider == "bing":
                raw = self._search_bing(query, cfg)
            elif provider == "serpapi":
                raw = self._search_serpapi(query, cfg)
            elif provider == "custom":
                raw = self._search_custom(query, cfg)
            else:
                raise ValueError(f"unknown search provider: {provider!r}")

            return self._normalise(provider, raw, cfg.max_results)

    def _execute_via_registry(
        self,
        query: str,
        config: SearchConfig,
        max_results_override: int | None,
    ) -> list[SearchResult]:
        """Execute search via the provider registry (cached)."""
        registry = self._get_registry(config)
        provider = registry.get_default_provider()

        # Determine max_results from override or default provider config
        provider_cfg = config.providers.get(config.default_provider)
        max_results = (
            max_results_override
            if max_results_override is not None
            else (provider_cfg.max_results if provider_cfg else 10)
        )

        return self._run_async(provider.search(query, max_results))

    # ── provider implementations ─────────────────────────────────────────

    def _search_tavily(self, query: str, config: SearchProviderConfig) -> list[dict]:
        """Search via Tavily API."""
        endpoint = config.endpoint or "https://api.tavily.com/search"
        payload: dict[str, Any] = {
            "api_key": config.api_key,
            "query": query,
            "max_results": config.max_results,
            **config.params,
        }

        with httpx.Client(timeout=config.timeout) as client:
            resp = client.post(endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", [])

    def _search_bing(self, query: str, config: SearchProviderConfig) -> list[dict]:
        """Search via Bing Web Search API."""
        endpoint = config.endpoint or "https://api.bing.microsoft.com/v7.0/search"
        headers = {
            "Ocp-Apim-Subscription-Key": config.api_key,
        }
        params: dict[str, Any] = {
            "q": query,
            "count": config.max_results,
            **config.params,
        }

        with httpx.Client(timeout=config.timeout) as client:
            resp = client.get(endpoint, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("webPages", {}).get("value", [])

    def _search_serpapi(self, query: str, config: SearchProviderConfig) -> list[dict]:
        """Search via SerpAPI."""
        endpoint = config.endpoint or "https://serpapi.com/search"
        params: dict[str, Any] = {
            "api_key": config.api_key,
            "q": query,
            "num": config.max_results,
            "engine": "google",
            **config.params,
        }

        with httpx.Client(timeout=config.timeout) as client:
            resp = client.get(endpoint, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("organic_results", [])

    def _search_custom(self, query: str, config: SearchProviderConfig) -> list[dict]:
        """Search via a custom HTTP endpoint.

        The custom endpoint MUST accept ``GET`` with query params ``q`` (the
        search query) and ``max_results``, and return a JSON array of result
        objects with at least ``title``, ``url``, and ``snippet`` fields.
        """
        if not config.endpoint:
            raise ValueError("custom search provider requires an endpoint")

        params: dict[str, Any] = {
            "q": query,
            "max_results": config.max_results,
            **config.params,
        }
        headers: dict[str, str] = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"

        with httpx.Client(timeout=config.timeout) as client:
            resp = client.get(config.endpoint, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()  # custom endpoint must return [{title, url, snippet}, ...]

    # ── normalisation ────────────────────────────────────────────────────

    def _normalise(
        self, provider: str, raw_results: list[dict], max_results: int
    ) -> list[dict]:
        """Normalise provider‑specific results into the standard schema.

        Standard schema::

            [
                {"title": str, "url": str, "snippet": str},
                ...
            ]
        """
        normalised: list[dict] = []

        if provider == "tavily":
            for r in raw_results:
                normalised.append(
                    {
                        "title": str(r.get("title", "")),
                        "url": str(r.get("url", "")),
                        "snippet": str(r.get("content", "")),
                    }
                )
        elif provider == "bing":
            for r in raw_results:
                normalised.append(
                    {
                        "title": str(r.get("name", "")),
                        "url": str(r.get("url", "")),
                        "snippet": str(r.get("snippet", "")),
                    }
                )
        elif provider == "serpapi":
            for r in raw_results:
                normalised.append(
                    {
                        "title": str(r.get("title", "")),
                        "url": str(r.get("link", "")),
                        "snippet": str(r.get("snippet", "")),
                    }
                )
        elif provider == "custom":
            # Custom endpoint already returns the standard schema
            for r in raw_results:
                normalised.append(
                    {
                        "title": str(r.get("title", "")),
                        "url": str(r.get("url", "")),
                        "snippet": str(r.get("snippet", "")),
                    }
                )

        # Truncate titles and snippets for conciseness
        for item in normalised:
            if len(item["title"]) > 200:
                item["title"] = item["title"][:197] + "..."
            if len(item["snippet"]) > 500:
                item["snippet"] = item["snippet"][:497] + "..."

        return normalised[:max_results]
