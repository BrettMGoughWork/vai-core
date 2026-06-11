"""Tests for URL taxonomy classifier (PHASE 3.13.5)."""

from __future__ import annotations

import pytest

from src.strategy.types.fetch.taxonomy import classify_url, choose_fetch_mode


# ── classify_url: article URLs ──────────────────────────────────────────


class TestClassifyArticle:
    """URLs that should be classified as 'article'."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/news/breaking-story",
            "https://example.com/news/2025/election-results",
            "https://example.com/article/12345",
            "https://example.com/articles/some-title",
            "https://example.com/stories/a-great-story",
            "https://example.com/story/once-upon-a-time",
            "https://example.com/press/release-2025",
            "https://example.com/releases/v2.0",
            "https://example.com/page.html",
            "https://example.com/index.htm",
            "https://example.com/deep/nested/path/page.html",
            "https://sub.example.com/news/local",
        ],
    )
    def test_article_urls(self, url: str) -> None:
        assert classify_url(url) == "article"

    def test_html_extension_trumps_unknown(self) -> None:
        """A URL with .html that has no other signal still classifies as article."""
        assert classify_url("https://example.com/random/page.html") == "article"


# ── classify_url: documentation URLs ────────────────────────────────────


class TestClassifyDocumentation:
    """URLs that should be classified as 'documentation'."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/docs/getting-started",
            "https://example.com/documentation/overview",
            "https://example.com/api/v1/users",
            "https://example.com/api/auth/login",
            "https://example.com/reference/cli",
            "https://example.com/reference/python-sdk",
            "https://example.com/guide/quickstart",
            "https://example.com/guides/advanced",
            "https://example.com/tutorial/hello-world",
            "https://example.com/tutorials/part-2",
            "https://example.com/manual/installation",
            "https://example.com/wiki/Main_Page",
            "https://docs.example.com/",
            "https://api.example.com/v2/",
            "https://example.com/docs/api/endpoints",
        ],
    )
    def test_documentation_urls(self, url: str) -> None:
        assert classify_url(url) == "documentation"

    def test_documentation_takes_priority_over_blog(self) -> None:
        """When /docs/ overlaps with /blog/, /docs/ wins (ordered first)."""
        # This URL contains both /docs/ and /blog/ but /docs/ is checked first
        assert classify_url("https://example.com/docs/blog-migration") == "documentation"


# ── classify_url: blog URLs ─────────────────────────────────────────────


class TestClassifyBlog:
    """URLs that should be classified as 'blog'."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/blog/my-post",
            "https://example.com/blogs/tech",
            "https://example.com/posts/2025/something",
            "https://example.com/post/hello-world",
            "https://example.com/writing/essay",
            "https://example.com/writings/poetry",
            "https://example.com/essays/on-code",
            "https://example.com/essay/why-testing",
            "https://example.com/journal/day-1",
            "https://example.com/diary/2025-06-09",
            "https://example.com/notes/meeting",
            "https://example.com/thoughts/ai",
            "https://example.com/musings/philosophy",
            "https://blog.example.com/",
            "https://example.com/blog/",
            "https://example.com/blog",
        ],
    )
    def test_blog_urls(self, url: str) -> None:
        assert classify_url(url) == "blog"


# ── classify_url: unknown URLs ──────────────────────────────────────────


class TestClassifyUnknown:
    """URLs that should be classified as 'unknown'."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/",
            "https://example.com",
            "https://example.com/about",
            "https://example.com/contact",
            "https://example.com/products/item",
            "https://example.com/search?q=test",
            "https://example.com/login",
            "https://example.com/sitemap.xml",
            "https://example.com/robots.txt",
            "https://cdn.example.com/assets/script.js",
            "https://cdn.example.com/style.css",
            "https://example.com/image.png",
            "https://example.com/download/file.pdf",
            "https://example.com/video.mp4",
        ],
    )
    def test_unknown_urls(self, url: str) -> None:
        assert classify_url(url) == "unknown"

    def test_empty_url_is_unknown(self) -> None:
        assert classify_url("") == "unknown"


# ── classify_url: edge cases ────────────────────────────────────────────


class TestClassifyEdgeCases:
    """Edge cases that must still classify correctly."""

    def test_query_params_do_not_affect_classification(self) -> None:
        url = "https://example.com/docs/api?version=2&lang=en"
        assert classify_url(url) == "documentation"

    def test_fragment_does_not_affect_classification(self) -> None:
        url = "https://example.com/blog/post#section-1"
        assert classify_url(url) == "blog"

    def test_uppercase_path_segments_normalised(self) -> None:
        url = "https://example.com/DOCS/API/Reference"
        assert classify_url(url) == "documentation"

    def test_mixed_case_path_segments(self) -> None:
        url = "https://example.com/Blog/My-Post"
        assert classify_url(url) == "blog"

    def test_trailing_slash_does_not_break_matching(self) -> None:
        url = "https://example.com/docs/"
        assert classify_url(url) == "documentation"

    def test_no_trailing_slash_still_matches(self) -> None:
        url = "https://example.com/docs"
        assert classify_url(url) == "documentation"

    def test_url_encoded_path_decoded(self) -> None:
        """Percent-encoded paths are decoded before matching."""
        url = "https://example.com/%64%6F%63%73/api"  # /docs/api
        assert classify_url(url) == "documentation"

    def test_blog_segment_in_the_middle_of_path(self) -> None:
        url = "https://example.com/site/blog/posts/something"
        assert classify_url(url) == "blog"

    def test_docs_as_subdirectory_not_root(self) -> None:
        url = "https://example.com/project/docs/setup"
        assert classify_url(url) == "documentation"

    def test_article_path_substring_not_matched(self) -> None:
        """Only whole path segments match — 'newsletter' is not 'news'."""
        url = "https://example.com/newsletter/subscribe"
        assert classify_url(url) == "unknown"

    def test_docs_substring_not_matched(self) -> None:
        """'docsify/index' is not 'docs' — path segments must be exact."""
        url = "https://example.com/docsify/index"
        assert classify_url(url) == "unknown"

    def test_trailing_segment_boundary(self) -> None:
        """Path ending exactly on a segment name still matches."""
        assert classify_url("https://example.com/api") == "documentation"


# ── choose_fetch_mode: taxonomy label → FetchMode ───────────────────────


class TestChooseFetchModeFromLabel:
    """Mapping taxonomy labels directly to fetch modes."""

    def test_article_maps_to_http_simple(self) -> None:
        assert choose_fetch_mode("article") == "http_simple"

    def test_documentation_maps_to_http_hardened(self) -> None:
        assert choose_fetch_mode("documentation") == "http_hardened"

    def test_blog_maps_to_http_headless_browser(self) -> None:
        assert choose_fetch_mode("blog") == "http_headless_browser"

    def test_unknown_maps_to_http_stealth(self) -> None:
        assert choose_fetch_mode("unknown") == "http_stealth"


# ── choose_fetch_mode: URL → classify → FetchMode ───────────────────────


class TestChooseFetchModeFromUrl:
    """Classify a URL first, then map to fetch mode."""

    def test_article_url_maps_to_http_simple(self) -> None:
        assert choose_fetch_mode("https://example.com/news/breaking") == "http_simple"

    def test_documentation_url_maps_to_http_hardened(self) -> None:
        assert choose_fetch_mode("https://example.com/docs/api") == "http_hardened"

    def test_blog_url_maps_to_http_headless_browser(self) -> None:
        assert choose_fetch_mode("https://example.com/blog/post") == "http_headless_browser"

    def test_unknown_url_maps_to_http_stealth(self) -> None:
        assert choose_fetch_mode("https://example.com/about") == "http_stealth"

    def test_html_article_url_maps_to_http_simple(self) -> None:
        assert choose_fetch_mode("https://example.com/page.html") == "http_simple"


# ── Determinism check ───────────────────────────────────────────────────


class TestDeterminism:
    """The classifier must be deterministic — same URL always gives same label."""

    def test_repeated_calls_same_result(self) -> None:
        urls = [
            "https://example.com/news/item",
            "https://example.com/docs/start",
            "https://example.com/blog/post",
            "https://example.com/about",
        ]
        for url in urls:
            first = classify_url(url)
            for _ in range(10):
                assert classify_url(url) == first