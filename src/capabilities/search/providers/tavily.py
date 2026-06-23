"""Tavily search provider (PHASE 3.13.1).

Searches via the Tavily Search API.  The API key is resolved from the
environment variable named in ``ProviderConfig.api_key_env`` at
construction time — it is NEVER hard-coded or exposed to the LLM.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from src.capabilities.search.providers._base import SearchProviderError, SearchResult
from src.domain.types.config import ProviderConfig


class TavilyProvider:
    """Search provider for Tavily Search API."""

    name = "tavily"
    _ENDPOINT = "https://api.tavily.com/search"

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        self._api_key = self._resolve_api_key(config)

    @staticmethod
    def _resolve_api_key(config: ProviderConfig) -> str:
        """Resolve the API key from the environment variable named in config."""
        env_var = config.api_key_env
        if not env_var:
            raise SearchProviderError(
                "Tavily requires api_key_env in provider config "
                "(e.g. api_key_env: TAVILY_API_KEY)"
            )
        key = os.getenv(env_var, "")
        if not key:
            raise SearchProviderError(
                f"Tavily API key not found: environment variable "
                f"'{env_var}' is not set or empty"
            )
        return key

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Execute a Tavily search and return normalised results."""
        payload: dict[str, Any] = {
            "api_key": self._api_key,
            "query": query,
            "max_results": max_results,
            **self._config.params,
        }

        endpoint = self._config.endpoint or self._ENDPOINT

        try:
            async with httpx.AsyncClient(timeout=self._config.timeout) as client:
                resp = await client.post(endpoint, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return self._normalise(data.get("results", []), max_results)
        except httpx.HTTPStatusError as exc:
            raise SearchProviderError(
                f"Tavily returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise SearchProviderError(
                f"Tavily request failed: {exc}"
            ) from exc

    def _normalise(
        self, raw_results: list[dict], max_results: int
    ) -> list[SearchResult]:
        """Normalise Tavily's raw response into SearchResult objects."""
        results: list[SearchResult] = []

        for r in raw_results:
            if len(results) >= max_results:
                break
            results.append(
                SearchResult(
                    title=self._truncate(str(r.get("title", "")), 200),
                    url=str(r.get("url", "")),
                    snippet=self._truncate(str(r.get("content", "")), 500),
                )
            )

        return results

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        """Truncate text to max_len, adding ellipsis if truncated."""
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."
