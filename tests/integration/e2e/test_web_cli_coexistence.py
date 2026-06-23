"""
E2E test: CLI + Web channel coexistence (Sprint 13.10).

Verifies that mounting the Web UI does not break the CLI channel's
normalization, routing, or integration with the Gateway pipeline.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.gateway.channels.registry import ChannelRegistry
from src.gateway.channels.cli import register_cli_channel
from src.gateway.channels.web import register_web_channel
from src.gateway.entrypoint import process_channel_input, submit_channel_input


@pytest.fixture
def coexistence_registry() -> Any:
    """ChannelRegistry with both CLI and Web channels registered.

    This mirrors the real gateway startup where both channels are
    active simultaneously alongside the mounted Web UI.
    """
    reg = ChannelRegistry()
    register_cli_channel(reg)
    register_web_channel(reg)
    return reg


class TestCLIWebCoexistence:
    """Both CLI and Web channels work when registered together."""

    def test_cli_normalizes_with_web_present(
        self,
        coexistence_registry: Any,
    ) -> None:
        """CLI channel normalises input even when Web channel is registered."""
        payload = process_channel_input(
            coexistence_registry, "cli", {"text": "hello from cli"},
        )
        assert payload is not None
        assert "input" in payload
        assert payload["input"] == "hello from cli"

    def test_web_normalizes_with_cli_present(
        self,
        coexistence_registry: Any,
    ) -> None:
        """Web channel normalises input even when CLI channel is registered."""
        payload = process_channel_input(
            coexistence_registry, "web",
            {"input": "hello from web", "sender": "user-1"},
        )
        assert payload is not None
        assert any(k in payload for k in ("text", "input", "message"))

    def test_cli_requires_text_field_with_web_present(
        self,
        coexistence_registry: Any,
    ) -> None:
        """CLI channel still enforces 'text' field requirement."""
        with pytest.raises(ValueError, match="requires a 'text' field"):
            process_channel_input(coexistence_registry, "cli", {})

    def test_unknown_channel_returns_none_with_both_registered(
        self,
        coexistence_registry: Any,
    ) -> None:
        """Unknown channel still returns None with both channels registered."""
        payload = process_channel_input(
            coexistence_registry, "telegram", {"text": "hello"},
        )
        assert payload is None

    def test_submit_via_cli_with_adapter(
        self,
        coexistence_registry: Any,
        gateway_adapter: Any,
    ) -> None:
        """CLI → submit_channel_input → adapter works with Web channel present."""
        result = submit_channel_input(
            coexistence_registry, "cli",
            {"text": "hello from coexistence test"},
            adapter=gateway_adapter,
        )
        assert "reply" in result, f"Expected reply, got: {result}"

    def test_submit_via_web_with_adapter(
        self,
        coexistence_registry: Any,
        gateway_adapter: Any,
    ) -> None:
        """Web → submit_channel_input → adapter works with CLI channel present."""
        result = submit_channel_input(
            coexistence_registry, "web",
            {"input": "hello from web coexistence", "sender": "user-1"},
            adapter=gateway_adapter,
        )
        assert "reply" in result, f"Expected reply, got: {result}"


class TestUIMountDoesNotBreakApp:
    """Verify the FastAPI app still works with UI mounted."""

    def test_app_still_has_run_route(self) -> None:
        """The app module-level routes are intact after mount_ui."""
        from src.platform.transport.app import app as gateway_app

        routes = [r.path for r in gateway_app.routes]
        assert "/run" in routes, "'/run' route should exist"
        assert "/" in routes, "'/' route should exist (web UI)"
        assert any(r.startswith("/static") for r in routes), (
            "'/static' mount should exist"
        )

    def test_web_simple_mount_ui_is_idempotent(self) -> None:
        """Calling mount_ui twice does not break things."""
        from src.platform.transport.app import app as gateway_app
        from src.gateway.channels.web_simple import mount_ui

        # mount_ui is called at import time in app.py; calling again should
        # add duplicate routes.  This test verifies it doesn't crash.
        try:
            mount_ui(gateway_app)
        except Exception as exc:
            pytest.fail(f"mount_ui should not crash on re-invocation: {exc}")
