"""Unit tests for signal extraction engine (Phase 3.12.4)."""

from __future__ import annotations

import pytest

from src.core.types.fetch.domain_policy import DomainPolicy
from src.core.types.fetch.mode_selector import FetchMode
from src.core.types.fetch.request import FetchRequest
from src.core.types.fetch.response import FetchResponse
from src.core.types.fetch.signal_extraction import (
    FetchSignals,
    _detect_akamai,
    _detect_blank_html,
    _detect_captcha,
    _detect_cloudflare,
    _detect_connection_reset,
    _detect_datadome,
    _detect_empty_body,
    _detect_hydration_error,
    _detect_json,
    _detect_js_required,
    _detect_malformed_html,
    _detect_meta_refresh,
    _detect_perimeterx,
    _detect_redirect_loop,
    _detect_script_timeout,
    _detect_ssl_error,
    _detect_static_asset,
    _detect_xml,
    _get_content_type,
    _sniff_content_type,
    extract_signals,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _req(url: str = "https://example.com", headers: dict[str, str] | None = None) -> FetchRequest:
    return FetchRequest(url=url, headers=headers or {})


def _resp(
    ok: bool = True,
    status_code: int | None = 200,
    body: str | None = None,
    headers: dict[str, str] | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    url: str = "https://example.com",
) -> FetchResponse:
    return FetchResponse(
        ok=ok,
        status_code=status_code,
        body=body or "",
        headers=headers or {},
        cookies={},
        elapsed_ms=100,
        url=url,
        error_type=error_type,
        error_message=error_message,
    )


# ---------------------------------------------------------------------------
# FetchSignals dataclass smoke tests
# ---------------------------------------------------------------------------


class TestFetchSignalsSmoke:
    """Basic correctness: all fields are boolean with False default."""

    def test_all_fields_default_false(self) -> None:
        signals = FetchSignals()
        assert signals.js_required is False
        assert signals.blank_html is False
        assert signals.hydration_error is False
        assert signals.script_timeout is False
        assert signals.cloudflare_challenge is False
        assert signals.datadome_block is False
        assert signals.perimeterx_block is False
        assert signals.akamai_bot_detected is False
        assert signals.captcha_present is False
        assert signals.json_endpoint_detected is False
        assert signals.xml_feed is False
        assert signals.static_asset is False
        assert signals.redirect_loop is False
        assert signals.ssl_error is False
        assert signals.connection_reset is False
        assert signals.malformed_html is False
        assert signals.empty_body is False
        assert signals.suspicious_meta_refresh is False
        assert signals.reasoning == ""

    def test_is_frozen(self) -> None:
        signals = FetchSignals()
        with pytest.raises(Exception):
            signals.js_required = True  # type: ignore[misc]

    def test_hashable(self) -> None:
        signals = FetchSignals(js_required=True)
        assert hash(signals) is not None

    def test_repr(self) -> None:
        signals = FetchSignals(js_required=True, reasoning="test")
        r = repr(signals)
        assert "js_required=True" in r
        assert "reasoning='test'" in r

    def test_eq(self) -> None:
        a = FetchSignals(js_required=True)
        b = FetchSignals(js_required=True)
        c = FetchSignals(js_required=False)
        assert a == b
        assert a != c


# ---------------------------------------------------------------------------
# Convenience properties
# ---------------------------------------------------------------------------


class TestFetchSignalsProperties:
    def test_has_any_signal_false(self) -> None:
        assert FetchSignals().has_any_signal is False

    def test_has_any_signal_true(self) -> None:
        assert FetchSignals(js_required=True).has_any_signal is True

    def test_has_anti_bot_signal_false(self) -> None:
        assert FetchSignals().has_anti_bot_signal is False

    def test_has_anti_bot_signal_true(self) -> None:
        assert FetchSignals(cloudflare_challenge=True).has_anti_bot_signal is True

    def test_has_js_signal_false(self) -> None:
        assert FetchSignals().has_js_signal is False

    def test_has_js_signal_true(self) -> None:
        assert FetchSignals(js_required=True).has_js_signal is True

    def test_raised_signals_empty(self) -> None:
        assert FetchSignals().raised_signals == ()

    def test_raised_signals_multiple(self) -> None:
        s = FetchSignals(js_required=True, empty_body=True, ssl_error=True)
        assert set(s.raised_signals) == {"js_required", "empty_body", "ssl_error"}


# ---------------------------------------------------------------------------
# extract_signals — smoke tests
# ---------------------------------------------------------------------------


class TestExtractSignalsSmoke:
    """Basic integration: returns FetchSignals for a normal response."""

    def test_returns_fetch_signals(self) -> None:
        result = extract_signals(
            _req(),
            _resp(body="<html><head></head><body>" + ("<p>Hello World! This is a normal web page with plenty of content to avoid blank detection.</p>" * 4) + "</body></html>"),
            "http_simple",
        )
        assert isinstance(result, FetchSignals)
        assert result.reasoning == "no unusual signals detected"

    def test_all_signals_false_for_normal_html(self) -> None:
        result = extract_signals(
            _req(),
            _resp(
                body="<html><head><title>Test</title></head><body>" + ("<p>Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.</p>" * 5) + "</body></html>",
                headers={"content-type": "text/html"},
            ),
            "http_simple",
        )
        assert result.has_any_signal is False

    def test_accepts_domain_policy(self) -> None:
        policy = DomainPolicy(domain="example.com")
        result = extract_signals(_req(), _resp(), "http_simple", domain_policy=policy)
        assert isinstance(result, FetchSignals)


# ---------------------------------------------------------------------------
# Content-type helper tests
# ---------------------------------------------------------------------------


class TestGetContentType:
    def test_from_header(self) -> None:
        assert _get_content_type({"Content-Type": "text/html"}, "") == "text/html"

    def test_case_insensitive(self) -> None:
        assert _get_content_type({"content-type": "Application/Json"}, "") == "application/json"

    def test_strips_charset(self) -> None:
        assert _get_content_type({"Content-Type": "text/html; charset=utf-8"}, "") == "text/html"

    def test_falls_back_to_sniff_json(self) -> None:
        assert _get_content_type({}, '{"key": "value"}') == "application/json"

    def test_falls_back_to_sniff_html(self) -> None:
        assert _get_content_type({}, "<html></html>") == "text/html"

    def test_falls_back_to_sniff_xml(self) -> None:
        assert _get_content_type({}, '<?xml version="1.0"?>') == "application/xml"

    def test_empty(self) -> None:
        assert _get_content_type({}, "") == ""


class TestSniffContentType:
    def test_json_object(self) -> None:
        assert _sniff_content_type('{"a": 1}') == "application/json"

    def test_json_array(self) -> None:
        assert _sniff_content_type('[1, 2, 3]') == "application/json"

    def test_xml_declaration(self) -> None:
        assert _sniff_content_type('<?xml version="1.0"?><root/>') == "application/xml"

    def test_html_tag(self) -> None:
        assert _sniff_content_type("<html><body></body></html>") == "text/html"

    def test_doctype(self) -> None:
        assert _sniff_content_type("<!DOCTYPE html><html>") == "text/html"

    def test_plain_text(self) -> None:
        assert _sniff_content_type("Hello world") == ""


# ---------------------------------------------------------------------------
# 1. JavaScript / rendering signals
# ---------------------------------------------------------------------------


class TestJsRequired:
    def test_react_root_div(self) -> None:
        assert _detect_js_required('<div id="root"></div>', "text/html") is True

    def test_react_app_div(self) -> None:
        assert _detect_js_required('<div id="app"></div>', "text/html") is True

    def test_nextjs_div(self) -> None:
        assert _detect_js_required('<div id="__next"></div>', "text/html") is True

    def test_react_script_src(self) -> None:
        assert _detect_js_required('<script src="/static/react.js"></script>', "text/html") is True

    def test_vue_script_src(self) -> None:
        assert _detect_js_required('<script src="vue.min.js"></script>', "text/html") is True

    def test___next_data__(self) -> None:
        assert _detect_js_required('__NEXT_DATA__ = {}', "text/html") is True

    def test___nuxt__(self) -> None:
        assert _detect_js_required('window.__NUXT__={}', "text/html") is True

    def test_angular_ng_version(self) -> None:
        assert _detect_js_required('<app ng-version="15"></app>', "text/html") is True

    def test_data_reactroot(self) -> None:
        assert _detect_js_required('<div data-reactroot="">', "text/html") is True

    def test_vue_scoped_style(self) -> None:
        assert _detect_js_required('<div data-v-abc123="">', "text/html") is True

    def test_blank_with_script_tags(self) -> None:
        body = "<script>console.log('hi')</script>"
        assert _detect_js_required(body, "text/html") is True

    def test_normal_html(self) -> None:
        assert _detect_js_required("<html><body><p>Hi</p></body></html>", "text/html") is False

    def test_empty_body(self) -> None:
        assert _detect_js_required("", "text/html") is False

    def test_non_html_content_type(self) -> None:
        assert _detect_js_required('<div id="root"></div>', "application/json") is False


class TestBlankHtml:
    def test_short_body(self) -> None:
        assert _detect_blank_html("<html></html>", "text/html") is True

    def test_skeleton_only(self) -> None:
        skeleton = '<!DOCTYPE html><html><head></head><body></body></html>'
        assert _detect_blank_html(skeleton, "text/html") is True

    def test_normal_body(self) -> None:
        body = "<!DOCTYPE html><html><head></head><body><p>" + "x" * 200 + "</p></body></html>"
        assert _detect_blank_html(body, "text/html") is False

    def test_non_html(self) -> None:
        assert _detect_blank_html("{}", "application/json") is False

    def test_empty(self) -> None:
        assert _detect_blank_html("", "text/html") is True


class TestHydrationError:
    def test_hydration_failed(self) -> None:
        assert _detect_hydration_error("Hydration failed because") is True

    def test_expected_server_html(self) -> None:
        assert _detect_hydration_error("Expected server HTML to contain") is True

    def test_minified_react_418(self) -> None:
        assert _detect_hydration_error("Minified React error #418") is True

    def test_minified_react_419(self) -> None:
        assert _detect_hydration_error("Minified React error #419") is True

    def test_minified_react_422(self) -> None:
        assert _detect_hydration_error("Minified React error #422") is True

    def test_case_insensitive(self) -> None:
        assert _detect_hydration_error("HYDRATION FAILED because") is True

    def test_no_hydration_error(self) -> None:
        assert _detect_hydration_error("<html><body>ok</body></html>") is False

    def test_empty_body(self) -> None:
        assert _detect_hydration_error("") is False


class TestScriptTimeout:
    def test_error_type_scripttimeouterror(self) -> None:
        assert _detect_script_timeout("ScriptTimeoutError", "", {}, "http_headless_browser") is True

    def test_error_message_script_timeout(self) -> None:
        assert _detect_script_timeout("TimeoutError", "script timeout in 30s", {}, "http_headless_browser") is True

    def test_metadata_js_timeout(self) -> None:
        assert _detect_script_timeout("", "", {"js_timeout": True}, "http_headless_browser") is True

    def test_metadata_script_timeout(self) -> None:
        assert _detect_script_timeout("", "", {"script_timeout": True}, "http_stealth") is True

    def test_browser_mode_timeout_with_script(self) -> None:
        assert _detect_script_timeout("TimeoutError", "Script execution timed out", {}, "http_headless_browser") is True

    def test_simple_mode_timeout_not_script(self) -> None:
        assert _detect_script_timeout("TimeoutError", "connection timed out", {}, "http_simple") is False

    def test_no_timeout(self) -> None:
        assert _detect_script_timeout("", "", {}, "http_headless_browser") is False


# ---------------------------------------------------------------------------
# 2. Anti-bot / security signals
# ---------------------------------------------------------------------------


class TestCloudflare:
    def test_cf_chl_bypass_header(self) -> None:
        assert _detect_cloudflare("", {"cf-chl-bypass": "1"}) is True

    def test_cf_browser_verification(self) -> None:
        assert _detect_cloudflare("cf-browser-verification", {}) is True

    def test_challenge_platform(self) -> None:
        assert _detect_cloudflare("/cdn-cgi/challenge-platform", {}) is True

    def test_checking_your_browser(self) -> None:
        assert _detect_cloudflare("Checking your browser before accessing", {}) is True

    def test_jschl_answer(self) -> None:
        assert _detect_cloudflare('name="jschl-answer"', {}) is True

    def test_no_cloudflare(self) -> None:
        assert _detect_cloudflare("<html>Hello</html>", {}) is False


class TestDatadome:
    def test_datadome_marker(self) -> None:
        assert _detect_datadome("datadome") is True

    def test_dd_browser_check(self) -> None:
        assert _detect_datadome("dd-browser-check") is True

    def test_no_datadome(self) -> None:
        assert _detect_datadome("<html>Hello</html>") is False


class TestPerimeterx:
    def test_perimeterx_marker(self) -> None:
        assert _detect_perimeterx("perimeterx") is True

    def test_px_appid(self) -> None:
        assert _detect_perimeterx("window._pxAppId") is True

    def test_px_captcha(self) -> None:
        assert _detect_perimeterx("px-captcha") is True

    def test_human_security(self) -> None:
        assert _detect_perimeterx("human security") is True

    def test_no_perimeterx(self) -> None:
        assert _detect_perimeterx("<html>Hello</html>") is False


class TestAkamai:
    def test_akamai_marker(self) -> None:
        assert _detect_akamai("akamai") is True

    def test_ak_bmsc(self) -> None:
        assert _detect_akamai("ak_bmsc") is True

    def test_reference_number(self) -> None:
        assert _detect_akamai("reference number") is True

    def test_no_akamai(self) -> None:
        assert _detect_akamai("<html>Hello</html>") is False


class TestCaptcha:
    def test_recaptcha(self) -> None:
        assert _detect_captcha("g-recaptcha") is True

    def test_hcaptcha(self) -> None:
        assert _detect_captcha("h-captcha") is True

    def test_cf_turnstile(self) -> None:
        assert _detect_captcha("cf-turnstile") is True

    def test_arkose(self) -> None:
        assert _detect_captcha('data-funcaptcha="arkose"') is True

    def test_are_you_a_robot(self) -> None:
        assert _detect_captcha("Are you a robot?") is True

    def test_verify_you_are_human(self) -> None:
        assert _detect_captcha("Please verify you are human") is True

    def test_no_captcha(self) -> None:
        assert _detect_captcha("<html>Hello</html>") is False


# ---------------------------------------------------------------------------
# 3. Content-type signals
# ---------------------------------------------------------------------------


class TestJsonEndpoint:
    def test_content_type_json(self) -> None:
        assert _detect_json("application/json", "") is True

    def test_content_type_plus_json(self) -> None:
        assert _detect_json("application/ld+json", "") is True

    def test_parses_as_json_object(self) -> None:
        assert _detect_json("", '{"key": "value"}') is True

    def test_parses_as_json_array(self) -> None:
        assert _detect_json("", "[1, 2]") is True

    def test_not_json(self) -> None:
        assert _detect_json("text/html", "<html></html>") is False

    def test_empty_body(self) -> None:
        assert _detect_json("", "") is False


class TestXmlFeed:
    def test_content_type_xml(self) -> None:
        assert _detect_xml("application/xml", "") is True

    def test_content_type_text_xml(self) -> None:
        assert _detect_xml("text/xml", "") is True

    def test_content_type_plus_xml(self) -> None:
        assert _detect_xml("application/rss+xml", "") is True

    def test_body_starts_with_xml_declaration(self) -> None:
        assert _detect_xml("", '<?xml version="1.0"?>') is True

    def test_not_xml(self) -> None:
        assert _detect_xml("text/html", "<html></html>") is False


class TestStaticAsset:
    def test_image_png(self) -> None:
        assert _detect_static_asset("image/png", "https://example.com") is True

    def test_image_jpeg(self) -> None:
        assert _detect_static_asset("image/jpeg", "https://example.com") is True

    def test_video_mp4(self) -> None:
        assert _detect_static_asset("video/mp4", "https://example.com") is True

    def test_font_woff2(self) -> None:
        assert _detect_static_asset("font/woff2", "https://example.com") is True

    def test_css(self) -> None:
        assert _detect_static_asset("text/css", "https://example.com") is True

    def test_javascript(self) -> None:
        assert _detect_static_asset("application/javascript", "https://example.com") is True

    def test_url_extension_css(self) -> None:
        assert _detect_static_asset("", "https://example.com/style.css") is True

    def test_url_extension_js(self) -> None:
        assert _detect_static_asset("", "https://example.com/app.js") is True

    def test_url_extension_png(self) -> None:
        assert _detect_static_asset("", "https://example.com/img/logo.png") is True

    def test_url_extension_with_query(self) -> None:
        assert _detect_static_asset("", "https://example.com/style.css?v=2") is True

    def test_url_extension_with_hash(self) -> None:
        assert _detect_static_asset("", "https://example.com/app.js#L10") is True

    def test_url_extension_pdf(self) -> None:
        assert _detect_static_asset("", "https://example.com/doc.pdf") is True

    def test_not_static_asset(self) -> None:
        assert _detect_static_asset("text/html", "https://example.com") is False

    def test_not_static_url(self) -> None:
        assert _detect_static_asset("", "https://example.com/page") is False


# ---------------------------------------------------------------------------
# 4. Network / protocol signals
# ---------------------------------------------------------------------------


class TestRedirectLoop:
    def test_error_type_redirectloop(self) -> None:
        assert _detect_redirect_loop("RedirectLoopError", {}) is True

    def test_error_type_too_many_redirects(self) -> None:
        assert _detect_redirect_loop("TooManyRedirects", {}) is True

    def test_metadata_redirect_count_over_5(self) -> None:
        assert _detect_redirect_loop("", {"redirect_count": 6}) is True

    def test_metadata_redirect_count_5(self) -> None:
        assert _detect_redirect_loop("", {"redirect_count": 5}) is False

    def test_metadata_redirect_count_string(self) -> None:
        assert _detect_redirect_loop("", {"redirect_count": "10"}) is False

    def test_no_redirect_loop(self) -> None:
        assert _detect_redirect_loop("", {}) is False


class TestSslError:
    def test_ssl_error(self) -> None:
        assert _detect_ssl_error("SSLError") is True

    def test_tls_error(self) -> None:
        assert _detect_ssl_error("TLSError") is True

    def test_certificate_error(self) -> None:
        assert _detect_ssl_error("CertificateError") is True

    def test_case_insensitive(self) -> None:
        assert _detect_ssl_error("sslerror") is True

    def test_no_ssl_error(self) -> None:
        assert _detect_ssl_error("TimeoutError") is False


class TestConnectionReset:
    def test_error_type_connection_reset(self) -> None:
        assert _detect_connection_reset("ConnectionResetError", "") is True

    def test_error_message_connection_reset(self) -> None:
        assert _detect_connection_reset("OSError", "connection reset by peer") is True

    def test_error_message_connection_refused(self) -> None:
        assert _detect_connection_reset("OSError", "connection refused") is True

    def test_econnreset(self) -> None:
        assert _detect_connection_reset("", "ECONNRESET") is True

    def test_no_connection_reset(self) -> None:
        assert _detect_connection_reset("TimeoutError", "timed out") is False


# ---------------------------------------------------------------------------
# 5. Quality / structure signals
# ---------------------------------------------------------------------------


class TestMalformedHtml:
    def test_metadata_html_parse_errors(self) -> None:
        assert _detect_malformed_html({"html_parse_errors": True}) is True

    def test_metadata_parse_errors(self) -> None:
        assert _detect_malformed_html({"parse_errors": 3}) is True

    def test_no_metadata(self) -> None:
        assert _detect_malformed_html({}) is False

    def test_metadata_without_error_keys(self) -> None:
        assert _detect_malformed_html({"redirect_count": 0}) is False


class TestEmptyBody:
    def test_empty_string(self) -> None:
        assert _detect_empty_body("") is True

    def test_none_like_body(self) -> None:
        assert _detect_empty_body("") is True

    def test_non_empty_body(self) -> None:
        assert _detect_empty_body("hello") is False


class TestMetaRefresh:
    def test_meta_http_equiv_refresh(self) -> None:
        assert _detect_meta_refresh('<meta http-equiv="refresh" content="0;url=/">') is True

    def test_meta_refresh_single_quotes(self) -> None:
        assert _detect_meta_refresh("<meta http-equiv='refresh' content='5'>") is True

    def test_case_insensitive(self) -> None:
        assert _detect_meta_refresh('<META HTTP-EQUIV="REFRESH">') is True

    def test_no_meta_refresh(self) -> None:
        assert _detect_meta_refresh('<meta name="description" content="refresh page">') is False

    def test_empty_body(self) -> None:
        assert _detect_meta_refresh("") is False


# ---------------------------------------------------------------------------
# Integration: extract_signals detects signals correctly
# ---------------------------------------------------------------------------


class TestExtractSignalsIntegration:
    def test_detects_js_required(self) -> None:
        result = extract_signals(
            _req("https://example.com"),
            _resp(
                body='<div id="root"></div><script src="react.js"></script>',
                headers={"content-type": "text/html"},
            ),
            "http_simple",
        )
        assert result.js_required is True
        assert "js_required" in result.raised_signals

    def test_detects_cloudflare(self) -> None:
        result = extract_signals(
            _req("https://example.com"),
            _resp(
                body="Checking your browser before accessing the site",
                headers={"content-type": "text/html", "cf-chl-bypass": "1"},
            ),
            "http_simple",
        )
        assert result.cloudflare_challenge is True

    def test_detects_captcha(self) -> None:
        result = extract_signals(
            _req("https://example.com"),
            _resp(
                body='<div class="g-recaptcha"></div>',
                headers={"content-type": "text/html"},
            ),
            "http_simple",
        )
        assert result.captcha_present is True

    def test_detects_ssl_error(self) -> None:
        result = extract_signals(
            _req("https://badssl.com"),
            _resp(ok=False, error_type="SSLError", error_message="certificate verify failed"),
            "http_simple",
        )
        assert result.ssl_error is True

    def test_detects_empty_body(self) -> None:
        result = extract_signals(
            _req("https://example.com"),
            _resp(),
            "http_simple",
        )
        assert result.empty_body is True

    def test_detects_json_endpoint(self) -> None:
        result = extract_signals(
            _req("https://api.example.com/data"),
            _resp(body='{"result": "ok"}', headers={"content-type": "application/json"}),
            "http_simple",
        )
        assert result.json_endpoint_detected is True

    def test_multiple_signals(self) -> None:
        result = extract_signals(
            _req("https://protected.example.com"),
            _resp(
                ok=False,
                error_type="SSLError",
                error_message="certificate verify failed",
                body='<div id="root"></div><div class="g-recaptcha"></div>',
                headers={"cf-chl-bypass": "1"},
            ),
            "http_simple",
        )
        assert result.ssl_error is True
        assert result.cloudflare_challenge is True
        assert result.captcha_present is True
        assert result.js_required is True

    def test_reasoning_includes_detected_signals(self) -> None:
        result = extract_signals(
            _req("https://example.com"),
            _resp(error_type="SSLError"),
            "http_simple",
        )
        assert "ssl_error" in result.reasoning

    def test_no_signals_gives_clean_reasoning(self) -> None:
        result = extract_signals(
            _req("https://example.com"),
            _resp(
                body="<html><head><title>Normal</title></head><body>" + ("<p>This is a perfectly normal web page with enough content to pass all signal detection checks without triggering any false positives.</p>" * 3) + "</body></html>",
                headers={"content-type": "text/html"},
            ),
            "http_simple",
        )
        assert result.reasoning == "no unusual signals detected"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_none_like_body_handled(self) -> None:
        result = extract_signals(_req(), _resp(body=None), "http_simple")
        assert result.empty_body is True

    def test_none_like_headers_handled(self) -> None:
        result = extract_signals(
            _req(),
            _resp(headers=None, body='{"ok":true}'),
            "http_simple",
        )
        assert result.json_endpoint_detected is True

    def test_long_normal_page(self) -> None:
        body = "<!DOCTYPE html><html><head></head><body><p>" + ("Hello world. " * 50) + "</p></body></html>"
        result = extract_signals(
            _req(),
            _resp(body=body, headers={"content-type": "text/html"}),
            "http_simple",
        )
        assert result.has_any_signal is False

    def test_xml_rss_feed(self) -> None:
        body = '<?xml version="1.0"?><rss><channel><title>Feed</title></channel></rss>'
        result = extract_signals(
            _req("https://example.com/feed.xml"),
            _resp(body=body, headers={"content-type": "application/rss+xml"}),
            "http_simple",
        )
        assert result.xml_feed is True

    def test_static_css_asset(self) -> None:
        result = extract_signals(
            _req("https://cdn.example.com/bundle.css"),
            _resp(body=".btn { color: red }", headers={"content-type": "text/css"}),
            "http_simple",
        )
        assert result.static_asset is True

    def test_script_timeout_in_headless_mode(self) -> None:
        result = extract_signals(
            _req("https://spa.example.com"),
            _resp(ok=False, error_type="ScriptTimeoutError", error_message="Page script timed out"),
            "http_headless_browser",
        )
        assert result.script_timeout is True

    def test_hydration_error_in_body(self) -> None:
        body = '<html><body>Hydration failed because the server HTML was different</body></html>'
        result = extract_signals(
            _req(),
            _resp(body=body, headers={"content-type": "text/html"}),
            "http_hardened",
        )
        assert result.hydration_error is True

    def test_suspicious_meta_refresh(self) -> None:
        body = "<html><head><meta http-equiv='refresh' content='0; url=/login'></head><body></body></html>"
        result = extract_signals(
            _req(),
            _resp(body=body, headers={"content-type": "text/html"}),
            "http_simple",
        )
        assert result.suspicious_meta_refresh is True

    def test_meta_refresh_short_body_also_blank(self) -> None:
        body = '<meta http-equiv="refresh" content="0">'
        result = extract_signals(
            _req(),
            _resp(body=body, headers={"content-type": "text/html"}),
            "http_simple",
        )
        assert result.suspicious_meta_refresh is True
        assert result.blank_html is True  # < 200 chars
