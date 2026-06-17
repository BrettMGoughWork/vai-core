"""
N.3 — Integration tests: Channel → Gateway → S5 normalization pipeline

Scenarios covered
-----------------
1. Channel normalization: raw CLI/Web input → canonical payload
2. submit_channel_input: normalised payload → adapter → S5 response
3. Missing channel handling
4. Provider webhook: provider adapter → webhook channel → payload
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from src.gateway.entrypoint import (
    process_channel_input,
    submit_channel_input,
    handle_provider_webhook,
    handle_web_request,
    handle_ws_message,
    handle_slack_event,
    handle_mail_message,
    handle_webhook_post,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Channel normalization
# ═══════════════════════════════════════════════════════════════════════════════


class TestChannelNormalization:
    """Channels normalise raw input into canonical S4 payloads."""

    def test_cli_channel_normalizes(
        self,
        full_gateway_registry: Any,
    ) -> None:
        """CLI channel: raw text input → canonical payload with 'text' key."""
        payload = process_channel_input(
            full_gateway_registry, "cli", {"text": "hello world"},
        )
        assert payload is not None
        assert "input" in payload
        assert payload["input"] == "hello world"

    def test_web_channel_normalizes(
        self,
        full_gateway_registry: Any,
    ) -> None:
        """Web channel: JSON body with 'input' → canonical payload."""
        payload = process_channel_input(
            full_gateway_registry, "web",
            {"input": "hello from web", "sender": "user-1"},
        )
        assert payload is not None
        # Web channel may use 'text' or 'input' key depending on normalization
        assert any(k in payload for k in ("text", "input", "message"))

    def test_unknown_channel_returns_none(
        self,
        full_gateway_registry: Any,
    ) -> None:
        """An unregistered channel should return None."""
        payload = process_channel_input(
            full_gateway_registry, "nonexistent", {"text": "hello"},
        )
        assert payload is None

    def test_missing_text_in_cli(
        self,
        full_gateway_registry: Any,
    ) -> None:
        """CLI channel raises ValueError when 'text' field is missing."""
        import pytest
        with pytest.raises(ValueError, match="requires a 'text' field"):
            process_channel_input(
                full_gateway_registry, "cli", {},
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. submit_channel_input: normalise → adapter → S5
# ═══════════════════════════════════════════════════════════════════════════════


class TestSubmitChannelInput:
    """Full wired path: channel → normalize → adapter → S5 response."""

    def test_cli_with_adapter_returns_reply(
        self,
        full_gateway_registry: Any,
        gateway_adapter: Any,
    ) -> None:
        """CLI input → submit_channel_input → GatewayAdapter → S5 → reply."""
        result = submit_channel_input(
            full_gateway_registry, "cli",
            {"text": "hello world"},
            adapter=gateway_adapter,
        )
        assert "reply" in result, f"Expected reply, got: {result}"
        assert "Mock response" in result["reply"]

    def test_web_with_adapter_returns_reply(
        self,
        full_gateway_registry: Any,
        gateway_adapter: Any,
    ) -> None:
        """Web input → submit_channel_input → GatewayAdapter → S5 → reply."""
        result = submit_channel_input(
            full_gateway_registry, "web",
            {"input": "hello from web", "sender": "user-1"},
            adapter=gateway_adapter,
        )
        assert "reply" in result, f"Expected reply, got: {result}"

    def test_without_adapter_returns_payload(
        self,
        full_gateway_registry: Any,
    ) -> None:
        """Without an adapter, submit_channel_input returns the payload dict."""
        result = submit_channel_input(
            full_gateway_registry, "cli",
            {"text": "hello"},
            adapter=None,
        )
        assert "payload" in result
        assert "channel" in result

    def test_unknown_channel_returns_error(
        self,
        full_gateway_registry: Any,
        gateway_adapter: Any,
    ) -> None:
        """Unknown channel → error dict."""
        result = submit_channel_input(
            full_gateway_registry, "void",
            {"text": "hello"},
            adapter=gateway_adapter,
        )
        assert "error" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Convenience handlers
# ═══════════════════════════════════════════════════════════════════════════════


class TestConvenienceHandlers:
    """Each convenience wrapper routes to the correct channel."""

    def test_handle_web_request(
        self,
        full_gateway_registry: Any,
    ) -> None:
        """handle_web_request processes JSON body via Web channel."""
        result = handle_web_request(
            full_gateway_registry,
            {"input": "hello web", "sender": "tester"},
        )
        assert result is not None

    def test_handle_ws_message(
        self,
        full_gateway_registry: Any,
    ) -> None:
        """handle_ws_message processes frame body via WS channel."""
        result = handle_ws_message(
            full_gateway_registry,
            {"text": "hello ws", "sender": "tester"},
        )
        assert result is not None

    def test_handle_slack_event(
        self,
        full_gateway_registry: Any,
    ) -> None:
        """handle_slack_event processes Slack event body."""
        result = handle_slack_event(
            full_gateway_registry,
            {"text": "hello slack", "sender": "U12345",
             "channel": "C67890", "team": "T11111"},
        )
        assert result is not None

    def test_handle_mail_message(
        self,
        full_gateway_registry: Any,
    ) -> None:
        """handle_mail_message processes email body."""
        result = handle_mail_message(
            full_gateway_registry,
            {"from": "alice@example.com", "subject": "Hello",
             "body": "This is a test email", "to": "bot@example.com"},
        )
        assert result is not None

    def test_handle_webhook_post(
        self,
        full_gateway_registry: Any,
    ) -> None:
        """handle_webhook_post processes webhook POST body."""
        result = handle_webhook_post(
            full_gateway_registry,
            {"source": "github", "payload": {"action": "push"},
             "sender": "webhook-bot"},
        )
        assert result is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Provider webhooks
# ═══════════════════════════════════════════════════════════════════════════════


class TestProviderWebhooks:
    """Provider-specific webhook normalization."""

    def test_unknown_provider_raises_key_error(
        self,
        full_gateway_registry: Any,
    ) -> None:
        """An unregistered provider should raise KeyError."""
        with pytest.raises(KeyError, match="unknown-provider"):
            handle_provider_webhook(
                full_gateway_registry, "unknown-provider",
                {"payload": {}},
            )

    def test_provider_webhook_requires_webhook_channel(
        self,
    ) -> None:
        """Without a webhook channel registered, returns None."""
        from src.gateway.channels.registry import ChannelRegistry

        empty_reg = ChannelRegistry()
        result = handle_provider_webhook(
            empty_reg, "slack", {"payload": {}},
        )
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Channel → Gateway → WAITING → resume (Gap 3)
# ═══════════════════════════════════════════════════════════════════════════════


class TestChannelGatewayResumeFlow:
    """Gap 3: ingest → WAITING → set_tool_result → resume → reply.

    Exercises the full flow where a tool-workflow request enters via
    the gateway adapter, enters WAITING state, gets a simulated S4B
    result injected, and resumes to completion.
    """

    def test_tool_workflow_ingest_resume_flow(
        self,
        tool_gateway_adapter: Any,
    ) -> None:
        """ingest → WAITING → set_tool_result → resume → reply."""
        from src.gateway.adapters.agent_adapter import AgentRequest

        result = tool_gateway_adapter.ingest(AgentRequest(
            channel="cli",
            message_text="run workflow",
            user_id="test-user",
            metadata={"agent_id": "tools-workflow"},
        ))

        assert "error" not in result, f"ingest failed: {result}"
        assert result.get("state") == "waiting"
        agent_id = result["agent_id"]

        # Simulate S4B job completion
        tool_gateway_adapter._supervisor.set_tool_result(agent_id, '"hello from channel"')

        # Resume via the same adapter
        result = tool_gateway_adapter.resume(agent_id, "continue")
        assert "error" not in result, f"resume failed: {result}"
        assert "reply" in result
        assert result["agent_id"] == agent_id


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Error paths through submit_channel_input (Gap 4)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAdapterErrorHandling:
    """Gap 4: Error paths through submit_channel_input.

    Tests that adapter-level errors are correctly surfaced when
    submitted through the channel pipeline.
    """

    def test_submit_with_failing_adapter_ingest(
        self,
        full_gateway_registry: Any,
    ) -> None:
        """submit_channel_input should surface ingest errors."""
        from unittest.mock import MagicMock

        failing = MagicMock()
        failing.ingest.return_value = {"error": "adapter exploded"}

        result = submit_channel_input(
            full_gateway_registry, "cli",
            {"text": "hello"},
            adapter=failing,
        )
        assert "error" in result
        assert "adapter exploded" in result["error"]

    def test_resume_with_bad_agent_id(
        self,
        tool_gateway_adapter: Any,
    ) -> None:
        """Resume via adapter with nonexistent agent_id should error."""
        from src.gateway.adapters.agent_adapter import AgentRequest

        # Start a workflow that waits
        result = tool_gateway_adapter.ingest(AgentRequest(
            channel="cli",
            message_text="run workflow",
            user_id="test-user",
            metadata={"agent_id": "tools-workflow"},
        ))
        assert result.get("state") == "waiting"

        # Try resume with a tampered agent_id
        result = tool_gateway_adapter.resume("nonexistent-agent", "continue")
        assert "error" in result

    def test_submit_resume_on_completed_agent(
        self,
        full_gateway_registry: Any,
        gateway_adapter: Any,
    ) -> None:
        """Resume on a completed agent should error.

        Uses the mock ``gateway_adapter`` (hello_world workflow, no
        tool_execute) so ingestion completes immediately.
        """
        result = submit_channel_input(
            full_gateway_registry, "cli",
            {"text": "hello world"},
            adapter=gateway_adapter,
        )
        assert "reply" in result, f"expected reply, got: {result}"

        # The mock adapter doesn't actually store state, so we test
        # that the adapter-level resume returns an error for a
        # completed agent
        from src.gateway.adapters.agent_adapter import AgentRequest

        agent_id = result.get("agent_id", "default-agent")
        result = gateway_adapter.resume(agent_id, "continue")
        assert "error" in result
