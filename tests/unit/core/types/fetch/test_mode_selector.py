"""Unit tests for initial mode selector (Phase 3.12.1)."""

from __future__ import annotations

import pytest

from src.core.types.fetch.mode_selector import (
    ALL_MODES,
    FetchMode,
    ModeHistory,
    ModeSelection,
    _domain_risk,
    _url_pattern_score,
    select_initial_mode,
)
from src.core.types.fetch.request import FetchRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _req(url: str, headers: dict[str, str] | None = None) -> FetchRequest:
    return FetchRequest(url=url, headers=headers or {})


# ---------------------------------------------------------------------------
# select_initial_mode — basic smoke tests
# ---------------------------------------------------------------------------


class TestSelectInitialModeSmoke:
    """Basic correctness: returns exactly one valid mode with reasoning."""

    def test_returns_mode_selection(self) -> None:
        result = select_initial_mode(_req("https://example.com"))
        assert isinstance(result, ModeSelection)
        assert result.mode in ALL_MODES
        assert isinstance(result.reasoning, str)
        assert len(result.reasoning) > 0

    def test_defaults_to_simple_for_trivial_url(self) -> None:
        result = select_initial_mode(_req("https://httpbin.org/get"))
        assert result.mode == "http_simple"

    def test_reasoning_includes_domain_risk(self) -> None:
        result = select_initial_mode(_req("https://example.com"))
        assert "domain risk" in result.reasoning.lower()

    def test_reasoning_includes_cost_rank(self) -> None:
        result = select_initial_mode(_req("https://example.com"))
        assert "cost rank" in result.reasoning.lower()


# ---------------------------------------------------------------------------
# URL pattern → mode mapping
# ---------------------------------------------------------------------------


class TestUrlPatternStaticAssets:
    """Static asset URLs → http_simple."""

    @pytest.mark.parametrize("url", [
        "https://cdn.example.com/app.js",
        "https://example.com/styles/main.css",
        "https://example.com/images/logo.png",
        "https://example.com/fonts/roboto.woff2",
        "https://example.com/downloads/report.pdf",
        "https://example.com/assets/bundle.mjs",
        "https://example.com/icon.svg",
        "https://example.com/video.mp4",
    ])
    def test_static_asset_maps_to_simple(self, url: str) -> None:
        result = select_initial_mode(_req(url))
        assert result.mode == "http_simple", f"{url} → {result.mode}"


class TestUrlPatternApi:
    """API endpoint URLs → http_simple."""

    @pytest.mark.parametrize("url", [
        "https://api.example.com/v1/users",
        "https://example.com/api/data",
        "https://example.com/graphql",
        "https://api.github.com/repos",
        "https://httpbin.org/get",
        "https://jsonplaceholder.typicode.com/posts/1",
        "https://example.com/data.json",
        "https://example.com/sitemap.xml",
    ])
    def test_api_maps_to_simple(self, url: str) -> None:
        result = select_initial_mode(_req(url))
        assert result.mode == "http_simple", f"{url} → {result.mode}"


class TestUrlPatternDocumentation:
    """Documentation URLs → http_simple."""

    @pytest.mark.parametrize("url", [
        "https://docs.python.org/3/library/urllib.html",
        "https://readthedocs.io/projects/flask/",
        "https://example.com/docs/getting-started",
        "https://wiki.archlinux.org/title/Pacman",
        "https://developer.mozilla.org/en-US/docs/Web/HTML",
    ])
    def test_docs_maps_to_simple(self, url: str) -> None:
        result = select_initial_mode(_req(url))
        assert result.mode == "http_simple", f"{url} → {result.mode}"


class TestUrlPatternBlog:
    """Blog / news / article URLs → http_hardened."""

    @pytest.mark.parametrize("url", [
        "https://blog.example.com/post-1",
        "https://example.com/blog/hello-world",
        "https://example.com/news/breaking",
        "https://example.com/article/123",
        "https://medium.com/@user/story",
        "https://user.substack.com/p/post",
    ])
    def test_blog_maps_to_hardened(self, url: str) -> None:
        result = select_initial_mode(_req(url))
        assert result.mode == "http_hardened", f"{url} → {result.mode}"


class TestUrlPatternSpa:
    """SPA / JS-framework URLs → http_headless_browser."""

    @pytest.mark.parametrize("url", [
        "https://react.dev/learn",
        "https://vuejs.org/guide",
        "https://angular.io/docs",
        "https://nextjs.org/docs",
        "https://nuxt.com/docs",
        "https://svelte.dev/tutorial",
        "https://gatsbyjs.com/docs",
        "https://remix.run/docs",
        "https://my-react-app.vercel.app",
    ])
    def test_spa_maps_to_headless_browser(self, url: str) -> None:
        result = select_initial_mode(_req(url))
        assert result.mode == "http_headless_browser", f"{url} → {result.mode}"


class TestUrlPatternAntibot:
    """Anti-bot domain URLs → http_stealth."""

    @pytest.mark.parametrize("url", [
        "https://www.google.com/search?q=test",
        "https://example.com/cloudflare-protected",
        "https://datadome.co/protected",
        "https://www.akamai.com/login",
        "https://example.com/captcha-required",
        "https://www.imperva.com/blog",
        "https://www.perimeterx.com/why",
    ])
    def test_antibot_maps_to_stealth(self, url: str) -> None:
        result = select_initial_mode(_req(url))
        assert result.mode == "http_stealth", f"{url} → {result.mode}"


# ---------------------------------------------------------------------------
# Content-type header hints
# ---------------------------------------------------------------------------


class TestContentTypeHints:
    """Content-type headers influence mode selection."""

    def test_json_accept_boosts_simple(self) -> None:
        result = select_initial_mode(
            _req("https://example.com/data", headers={"Accept": "application/json"}),
        )
        assert result.mode == "http_simple"

    def test_text_plain_accept_boosts_simple(self) -> None:
        result = select_initial_mode(
            _req("https://example.com/doc", headers={"Accept": "text/plain"}),
        )
        assert result.mode == "http_simple"

    def test_xml_accept_boosts_simple(self) -> None:
        result = select_initial_mode(
            _req("https://example.com/feed", headers={"Accept": "application/xml"}),
        )
        assert result.mode == "http_simple"


# ---------------------------------------------------------------------------
# Domain risk tiers
# ---------------------------------------------------------------------------


class TestDomainRiskLow:
    """Low-risk domains always get http_simple (unless overridden by URL)."""

    @pytest.mark.parametrize("url", [
        "https://example.com",
        "https://httpbin.org/get",
        "https://jsonplaceholder.typicode.com/posts",
        "https://api.github.com",
    ])
    def test_low_risk_domain_uses_simple(self, url: str) -> None:
        result = select_initial_mode(_req(url))
        assert result.mode == "http_simple", f"{url} → {result.mode}"


class TestDomainRiskMedium:
    """Medium-risk domains cannot use http_simple without strong history."""

    @pytest.mark.parametrize("url", [
        "https://old.reddit.com/r/python",
        "https://medium.com/@user/post",
        "https://blog.cloudflare.com",
    ])
    def test_medium_risk_cannot_use_simple_without_history(self, url: str) -> None:
        result = select_initial_mode(_req(url))
        assert result.mode != "http_simple", f"{url} → {result.mode}"

    def test_medium_risk_with_strong_simple_history(self) -> None:
        history = ModeHistory(
            successes={"http_simple": 5},
            failures={"http_simple": 0},
        )
        result = select_initial_mode(
            _req("https://old.reddit.com/r/python"), history=history,
        )
        # With strong simple history it can still prefer simple
        assert result.mode == "http_simple"


class TestDomainRiskHigh:
    """High-risk domains never use http_simple."""

    @pytest.mark.parametrize("url", [
        "https://www.google.com/search",
        "https://datadome.co/login",
    ])
    def test_high_risk_never_uses_simple(self, url: str) -> None:
        result = select_initial_mode(_req(url))
        assert result.mode != "http_simple", f"{url} → {result.mode}"

    def test_high_risk_even_with_history(self) -> None:
        """Even with strong simple history, high-risk still blocks simple."""
        history = ModeHistory(
            successes={"http_simple": 100},
            failures={"http_simple": 0},
        )
        result = select_initial_mode(
            _req("https://www.google.com/search"), history=history,
        )
        assert result.mode != "http_simple"


# ---------------------------------------------------------------------------
# _url_pattern_score unit tests
# ---------------------------------------------------------------------------


class TestUrlPatternScoreStatic:
    def test_css_file(self) -> None:
        scores = _url_pattern_score("https://cdn.example.com/style.css")
        assert scores["http_simple"] == 1.0

    def test_png_image(self) -> None:
        scores = _url_pattern_score("https://example.com/img/photo.png")
        assert scores["http_simple"] == 1.0

    def test_woff2_font(self) -> None:
        scores = _url_pattern_score("https://fonts.example.com/roboto.woff2")
        assert scores["http_simple"] == 1.0


class TestUrlPatternScoreApi:
    def test_api_v1_path(self) -> None:
        scores = _url_pattern_score("https://api.example.com/v1/users")
        assert scores["http_simple"] > 0.8

    def test_graphql_path(self) -> None:
        scores = _url_pattern_score("https://example.com/graphql")
        assert scores["http_simple"] > 0.8

    def test_json_extension(self) -> None:
        scores = _url_pattern_score("https://example.com/data.json")
        assert scores["http_simple"] > 0.8


class TestUrlPatternScoreDefault:
    def test_random_html_page(self) -> None:
        scores = _url_pattern_score("https://some-random-site.com/page")
        # Simple should be preferred by default
        assert scores["http_simple"] >= scores["http_hardened"]


# ---------------------------------------------------------------------------
# _domain_risk unit tests
# ---------------------------------------------------------------------------


class TestDomainRiskUnit:
    def test_known_low_risk(self) -> None:
        label, score = _domain_risk("https://example.com/page")
        assert label == "low"
        assert score == 0

    def test_known_medium_risk(self) -> None:
        label, score = _domain_risk("https://old.reddit.com/r/python")
        assert label == "medium"

    def test_known_high_risk(self) -> None:
        label, score = _domain_risk("https://www.google.com/search")
        assert label == "high"

    def test_subdomain_match_medium(self) -> None:
        label, score = _domain_risk("https://api.reddit.com/data")
        assert label == "medium"

    def test_unknown_domain_is_low(self) -> None:
        label, score = _domain_risk("https://my-personal-blog.example.org/post")
        assert label == "low"

    def test_antibot_signal_in_url(self) -> None:
        label, score = _domain_risk("https://some-site.com/cloudflare-protected")
        assert label == "high"


# ---------------------------------------------------------------------------
# History influence
# ---------------------------------------------------------------------------


class TestHistoryInfluence:
    """History data meaningfully changes the selected mode."""

    def test_no_history_defaults_to_neutral(self) -> None:
        result = select_initial_mode(_req("https://example.com"))
        assert result.mode == "http_simple"

    def test_strong_simple_history_keeps_simple(self) -> None:
        history = ModeHistory(
            successes={"http_simple": 10},
            failures={"http_simple": 0},
        )
        result = select_initial_mode(_req("https://example.com/page"), history=history)
        assert result.mode == "http_simple"

    def test_repeated_simple_failures_promotes_hardened(self) -> None:
        """After 5 simple failures and 0 successes, pick hardened."""
        history = ModeHistory(
            successes={"http_simple": 0},
            failures={"http_simple": 5},
        )
        result = select_initial_mode(_req("https://example.com/page"), history=history)
        assert result.mode != "http_simple"

    def test_hardened_success_promotes_hardened(self) -> None:
        history = ModeHistory(
            successes={"http_hardened": 10},
            failures={"http_hardened": 0},
        )
        result = select_initial_mode(_req("https://example.com/page"), history=history)
        assert result.mode == "http_hardened"

    def test_mixed_history_selects_best(self) -> None:
        history = ModeHistory(
            successes={"http_simple": 5, "http_hardened": 10},
            failures={"http_simple": 5, "http_hardened": 0},
        )
        result = select_initial_mode(_req("https://example.com/page"), history=history)
        assert result.mode == "http_hardened"

    def test_history_included_in_reasoning(self) -> None:
        history = ModeHistory(
            successes={"http_simple": 5, "http_hardened": 10},
            failures={"http_simple": 2, "http_hardened": 0},
        )
        result = select_initial_mode(_req("https://example.com/page"), history=history)
        assert "history" in result.reasoning.lower()


# ---------------------------------------------------------------------------
# ModeHistory
# ---------------------------------------------------------------------------


class TestModeHistory:
    def test_default_construction(self) -> None:
        h = ModeHistory()
        assert h.successes == {}
        assert h.failures == {}

    def test_success_rate_no_data(self) -> None:
        h = ModeHistory()
        assert h.success_rate("http_simple") == 0.5
        assert h.success_rate("http_stealth") == 0.5

    def test_success_rate_perfect(self) -> None:
        h = ModeHistory(successes={"http_simple": 10}, failures={"http_simple": 0})
        assert h.success_rate("http_simple") == 1.0

    def test_success_rate_zero(self) -> None:
        h = ModeHistory(successes={"http_simple": 0}, failures={"http_simple": 5})
        assert h.success_rate("http_simple") == 0.0

    def test_success_rate_mixed(self) -> None:
        h = ModeHistory(successes={"http_simple": 7}, failures={"http_simple": 3})
        assert h.success_rate("http_simple") == 0.7

    def test_total_attempts(self) -> None:
        h = ModeHistory(successes={"http_simple": 3}, failures={"http_simple": 2})
        assert h.total_attempts("http_simple") == 5

    def test_total_attempts_unknown(self) -> None:
        h = ModeHistory()
        assert h.total_attempts("http_stealth") == 0

    def test_from_dict(self) -> None:
        d = {
            "successes": {"http_simple": 5, "http_hardened": 2},
            "failures": {"http_simple": 1},
        }
        h = ModeHistory.from_dict(d)
        assert h.successes["http_simple"] == 5
        assert h.successes["http_hardened"] == 2
        assert h.failures["http_simple"] == 1
        # Unknown modes default to 0
        assert h.successes["http_stealth"] == 0

    def test_from_dict_handles_non_int_values(self) -> None:
        d = {"successes": {"http_simple": "5"}, "failures": {"http_simple": "abc"}}
        h = ModeHistory.from_dict(d)
        assert h.successes["http_simple"] == 5
        assert h.failures["http_simple"] == 0


# ---------------------------------------------------------------------------
# Cost awareness — cheaper mode preferred when confidence is equal
# ---------------------------------------------------------------------------


class TestCostAwareness:
    """Cheaper modes are preferred when scores are otherwise similar."""

    def test_identical_url_prefers_cheapest(self) -> None:
        """A simple HTML page with no distinguishing features — pick simple."""
        result = select_initial_mode(_req("https://example.com"))
        assert result.mode == "http_simple"

    def test_only_escalates_when_necessary(self) -> None:
        """Static assets use simple even with hardened history."""
        history = ModeHistory(
            successes={"http_hardened": 100},
            failures={"http_hardened": 0},
        )
        result = select_initial_mode(
            _req("https://cdn.example.com/app.js"), history=history,
        )
        # Static assets are a strong URL signal that overrides history
        assert result.mode == "http_simple"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_url(self) -> None:
        result = select_initial_mode(_req(""))
        assert result.mode in ALL_MODES

    def test_url_with_no_path(self) -> None:
        result = select_initial_mode(_req("https://example.com"))
        assert result.mode in ALL_MODES

    def test_url_with_query_params(self) -> None:
        result = select_initial_mode(_req("https://example.com/page?utm_source=test"))
        assert result.mode in ALL_MODES

    def test_url_with_fragment(self) -> None:
        result = select_initial_mode(_req("https://example.com/page#section"))
        assert result.mode in ALL_MODES

    def test_localhost(self) -> None:
        result = select_initial_mode(_req("http://localhost:8080/api/data"))
        assert result.mode == "http_simple"

    def test_ip_address(self) -> None:
        result = select_initial_mode(_req("http://192.168.1.1/status"))
        assert result.mode == "http_simple"

    def test_long_url(self) -> None:
        result = select_initial_mode(
            _req("https://example.com/" + "a" * 200 + "/page")
        )
        assert result.mode in ALL_MODES

    def test_uppercase_url(self) -> None:
        result = select_initial_mode(_req("HTTPS://EXAMPLE.COM/PAGE"))
        assert result.mode in ALL_MODES

    def test_none_history(self) -> None:
        result = select_initial_mode(_req("https://example.com"), history=None)
        assert result.mode == "http_simple"

    def test_non_ascii_url(self) -> None:
        result = select_initial_mode(_req("https://münchen.de/seite"))
        assert result.mode in ALL_MODES


# ---------------------------------------------------------------------------
# Integration: all four modes reachable
# ---------------------------------------------------------------------------


class TestAllModesReachable:
    """Every mode can be selected under the right conditions."""

    def test_simple_reachable(self) -> None:
        result = select_initial_mode(_req("https://example.com"))
        assert result.mode == "http_simple"

    def test_hardened_reachable(self) -> None:
        result = select_initial_mode(_req("https://blog.example.com/post"))
        assert result.mode == "http_hardened"

    def test_headless_browser_reachable(self) -> None:
        result = select_initial_mode(_req("https://react.dev/learn"))
        assert result.mode == "http_headless_browser"

    def test_stealth_reachable(self) -> None:
        result = select_initial_mode(_req("https://www.google.com/search?q=test"))
        assert result.mode == "http_stealth"
