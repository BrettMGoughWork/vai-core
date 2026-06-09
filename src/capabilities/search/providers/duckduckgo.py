"""DuckDuckGo search provider (PHASE 3.13.1).

Searches via the DuckDuckGo HTML endpoint (no API key required).
Parses the HTML response with BeautifulSoup and returns normalised
``SearchResult`` objects.
"""

from __future__ import annotations

import urllib.parse

import httpx
from bs4 import BeautifulSoup

from src.capabilities.search.providers._base import SearchProviderError, SearchResult
from src.core.state.config import ProviderConfig


class DuckDuckGoProvider:
    """Search provider for DuckDuckGo (HTML scraping, no API key)."""

    name = "duckduckgo"
    _ENDPOINT = "https://html.duckduckgo.com/html/"

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Execute a DuckDuckGo search and return normalised results."""
        try:
            async with httpx.AsyncClient(timeout=self._config.timeout) as client:
                resp = await client.get(
                    self._ENDPOINT,
                    params={"q": query},
                    headers={"User-Agent": "vai-core/1.0"},
                )
                resp.raise_for_status()
                return self._parse_html(resp.text, max_results)
        except httpx.HTTPStatusError as exc:
            raise SearchProviderError(
                f"DuckDuckGo returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise SearchProviderError(
                f"DuckDuckGo request failed: {exc}"
            ) from exc

    def _parse_html(self, html: str, max_results: int) -> list[SearchResult]:
        """Parse DuckDuckGo HTML results page."""
        soup = BeautifulSoup(html, "html.parser")
        results: list[SearchResult] = []

        for result_elem in soup.select(".result"):
            if len(results) >= max_results:
                break

            # Extract title and URL from the link
            title_elem = result_elem.select_one(".result__title a, .result__a")
            if title_elem is None:
                continue

            title = title_elem.get_text(strip=True)
            url = self._extract_url(title_elem.get("href", ""))

            # Extract snippet
            snippet_elem = result_elem.select_one(".result__snippet")
            snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

            if not url:
                continue

            results.append(
                SearchResult(
                    title=self._truncate(title, 200),
                    url=url,
                    snippet=self._truncate(snippet, 500),
                )
            )

        return results

    @staticmethod
    def _extract_url(href: str) -> str:
        """Extract the actual URL from a DuckDuckGo redirect URL.

        DuckDuckGo HTML results use a redirect wrapper like
        ``//duckduckgo.com/l/?uddg=https://example.com&rut=...``.
        """
        if "uddg=" in href:
            parsed = urllib.parse.urlparse(f"https:{href}" if href.startswith("//") else href)
            params = urllib.parse.parse_qs(parsed.query)
            uddg = params.get("uddg", [""])[0]
            if uddg:
                return uddg
        return href

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        """Truncate text to max_len, adding ellipsis if truncated."""
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."
