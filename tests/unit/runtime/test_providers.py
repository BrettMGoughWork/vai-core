"""Tests for S4.6.6 — Provider-specific webhook adapters.

Covers:
    - WhatsApp adapter (normalize_webhook)
    - Slack adapter (normalize_webhook)
    - GitHub adapter (normalize_webhook)
    - Jira adapter (normalize_webhook)
    - Gateway PROVIDER_MAP and handle_provider_webhook
"""

from __future__ import annotations

from typing import Any

import pytest

from src.gateway.channels.registry import ChannelRegistry
from src.gateway.channels.webhook import WebhookEvent, register_webhook_channel
from src.gateway.entrypoint import (
    PROVIDER_MAP,
    handle_provider_webhook,
)
from src.platform.runtime.providers.whatsapp.adapter import (
    normalize_webhook as normalize_whatsapp,
)
from src.platform.runtime.providers.slack.adapter import (
    normalize_webhook as normalize_slack,
)
from src.platform.runtime.providers.github.adapter import (
    normalize_webhook as normalize_github,
)
from src.platform.runtime.providers.jira.adapter import (
    normalize_webhook as normalize_jira,
)


# ===================================================================
# WhatsApp
# ===================================================================


class TestWhatsAppAdapter:
    """WhatsApp Cloud API → WebhookEvent."""

    def test_normalise_full_payload(self) -> None:
        raw: dict[str, Any] = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [
                            {"from": "12345", "text": {"body": "Hello"}},
                        ],
                        "contacts": [
                            {"wa_id": "12345", "profile": {"name": "Alice"}},
                        ],
                    },
                }],
            }],
        }
        event = normalize_whatsapp(raw)
        assert event.source == "whatsapp"
        assert event.payload == {"from": "12345", "text": {"body": "Hello"}}
        assert event.sender == "12345"

    def test_normalise_empty_payload(self) -> None:
        event = normalize_whatsapp({})
        assert event.source == "whatsapp"
        assert event.payload == {}
        assert event.sender is None

    def test_normalise_no_messages(self) -> None:
        raw: dict[str, Any] = {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"value": {}}]}],
        }
        event = normalize_whatsapp(raw)
        assert event.payload == {}
        assert event.sender is None

    def test_normalise_no_contacts(self) -> None:
        raw: dict[str, Any] = {
            "entry": [{"changes": [{"value": {"messages": [{"from": "abc"}]}}]}],
        }
        event = normalize_whatsapp(raw)
        assert event.payload == {"from": "abc"}
        assert event.sender is None


# ===================================================================
# Slack
# ===================================================================


class TestSlackAdapter:
    """Slack Events API → WebhookEvent."""

    def test_normalise_full_payload(self) -> None:
        raw: dict[str, Any] = {
            "token": "xyz",
            "team_id": "T001",
            "event": {
                "type": "message",
                "user": "U123",
                "text": "Hello from Slack",
                "channel": "C456",
            },
        }
        event = normalize_slack(raw)
        assert event.source == "slack"
        assert event.payload["type"] == "message"
        assert event.payload["text"] == "Hello from Slack"
        assert event.sender == "U123"

    def test_normalise_empty_payload(self) -> None:
        event = normalize_slack({})
        assert event.source == "slack"
        assert event.payload == {}
        assert event.sender is None

    def test_normalise_no_event(self) -> None:
        raw: dict[str, Any] = {"token": "xyz"}
        event = normalize_slack(raw)
        assert event.payload == {}
        assert event.sender is None

    def test_normalise_no_user_in_event(self) -> None:
        raw: dict[str, Any] = {"event": {"type": "message", "text": "hi"}}
        event = normalize_slack(raw)
        assert event.payload["text"] == "hi"
        assert event.sender is None


# ===================================================================
# GitHub
# ===================================================================


class TestGitHubAdapter:
    """GitHub webhook → WebhookEvent."""

    def test_normalise_push_event(self) -> None:
        raw: dict[str, Any] = {
            "ref": "refs/heads/main",
            "commits": [{"id": "abc123", "message": "Fix bug"}],
            "sender": {"login": "octocat", "id": 1},
            "repository": {"full_name": "org/repo"},
        }
        event = normalize_github(raw)
        assert event.source == "github"
        assert event.payload["ref"] == "refs/heads/main"
        assert event.sender == "octocat"

    def test_normalise_empty_payload(self) -> None:
        event = normalize_github({})
        assert event.source == "github"
        assert event.payload == {}
        assert event.sender is None

    def test_normalise_no_sender(self) -> None:
        raw: dict[str, Any] = {"ref": "refs/heads/main"}
        event = normalize_github(raw)
        assert event.sender is None

    def test_normalise_pull_request_event(self) -> None:
        raw: dict[str, Any] = {
            "action": "opened",
            "pull_request": {"title": "New feature", "number": 42},
            "sender": {"login": "pr-author"},
        }
        event = normalize_github(raw)
        assert event.payload["action"] == "opened"
        assert event.sender == "pr-author"


# ===================================================================
# Jira
# ===================================================================


class TestJiraAdapter:
    """Jira webhook → WebhookEvent."""

    def test_normalise_issue_created(self) -> None:
        raw: dict[str, Any] = {
            "timestamp": 1234567890,
            "webhookEvent": "jira:issue_created",
            "issue": {
                "id": "10000",
                "key": "PROJ-123",
                "fields": {"summary": "Something broke"},
            },
            "user": {"name": "admin", "displayName": "Admin User"},
        }
        event = normalize_jira(raw)
        assert event.source == "jira"
        assert event.payload["key"] == "PROJ-123"
        assert event.sender == "admin"

    def test_normalise_empty_payload(self) -> None:
        event = normalize_jira({})
        assert event.source == "jira"
        assert event.payload == {}
        assert event.sender is None

    def test_normalise_no_issue(self) -> None:
        raw: dict[str, Any] = {"webhookEvent": "jira:issue_updated"}
        event = normalize_jira(raw)
        assert event.payload == {}
        assert event.sender is None

    def test_normalise_no_user(self) -> None:
        raw: dict[str, Any] = {
            "issue": {"key": "PROJ-456"},
        }
        event = normalize_jira(raw)
        assert event.payload["key"] == "PROJ-456"
        assert event.sender is None


# ===================================================================
# Gateway integration — PROVIDER_MAP + handle_provider_webhook
# ===================================================================


class TestProviderMap:
    """PROVIDER_MAP contains all four adapters."""

    def test_contains_all_providers(self) -> None:
        assert set(PROVIDER_MAP) == {"whatsapp", "slack", "github", "jira"}

    def test_whatsapp_adapter_mapped(self) -> None:
        assert callable(PROVIDER_MAP["whatsapp"])

    def test_slack_adapter_mapped(self) -> None:
        assert callable(PROVIDER_MAP["slack"])

    def test_github_adapter_mapped(self) -> None:
        assert callable(PROVIDER_MAP["github"])

    def test_jira_adapter_mapped(self) -> None:
        assert callable(PROVIDER_MAP["jira"])


class TestHandleProviderWebhook:
    """handle_provider_webhook integration."""

    def setup_method(self) -> None:
        self.registry = ChannelRegistry()
        register_webhook_channel(self.registry)

    def test_whatsapp_webhook(self) -> None:
        result = handle_provider_webhook(self.registry, "whatsapp", {
            "entry": [{"changes": [{"value": {
                "messages": [{"from": "wa-1", "text": {"body": "Hi"}}],
                "contacts": [{"wa_id": "wa-1"}],
            }}]}],
        })
        assert result is not None
        assert result["input"]["from"] == "wa-1"
        assert result["metadata"]["source"] == "whatsapp"
        assert result["metadata"]["sender"] == "wa-1"
        assert result["metadata"]["channel"] == "webhook"

    def test_slack_webhook(self) -> None:
        result = handle_provider_webhook(self.registry, "slack", {
            "event": {"type": "message", "user": "U001", "text": "Hello"},
        })
        assert result is not None
        assert result["input"]["text"] == "Hello"
        assert result["metadata"]["source"] == "slack"
        assert result["metadata"]["sender"] == "U001"

    def test_github_webhook(self) -> None:
        result = handle_provider_webhook(self.registry, "github", {
            "ref": "refs/heads/main",
            "sender": {"login": "octocat"},
        })
        assert result is not None
        assert result["input"]["ref"] == "refs/heads/main"
        assert result["metadata"]["source"] == "github"
        assert result["metadata"]["sender"] == "octocat"

    def test_jira_webhook(self) -> None:
        result = handle_provider_webhook(self.registry, "jira", {
            "issue": {"key": "PROJ-789"},
            "user": {"name": "admin"},
        })
        assert result is not None
        assert result["input"]["key"] == "PROJ-789"
        assert result["metadata"]["source"] == "jira"
        assert result["metadata"]["sender"] == "admin"

    def test_unknown_provider_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="unknown"):
            handle_provider_webhook(self.registry, "unknown_provider", {})

    def test_unregistered_webhook_channel_returns_none(self) -> None:
        empty = ChannelRegistry()
        result = handle_provider_webhook(empty, "github", {})
        assert result is None

    def test_provider_map_not_mutated(self) -> None:
        original_keys = set(PROVIDER_MAP)
        assert original_keys == {"whatsapp", "slack", "github", "jira"}
