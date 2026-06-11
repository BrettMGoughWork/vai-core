"""
Contract tests for LLM provider adapters and the LLM factory.

Covers:
- AnthropicClient._to_claude_messages: pure message schema transformation
- AnthropicClient.chat(): request shape, error handling (HTTP mocked)
- OpenAIClient.chat(): request shape, error handling (HTTP mocked)
- LLMFactory.create(): provider routing, unknown provider, kwarg filtering
"""
import json
import os
from io import BytesIO
from unittest.mock import patch, MagicMock
from urllib import error as urllib_error

import pytest

from src.strategy.llm.providers.anthropic import AnthropicClient, _to_claude_messages
from src.strategy.llm.providers.openai import OpenAIClient
from src.strategy.llm.llm_factory import create as factory_create


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fake_http_response(body: dict):
    """Returns a context-manager-compatible mock of urlopen's response."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(body).encode("utf-8")
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _openai_text_response(content="hello"):
    return {"choices": [{"message": {"tool_calls": None, "content": content}}]}


def _anthropic_text_response(content="hello"):
    return {
        "id": "msg_01",
        "type": "message",
        "content": [{"type": "text", "text": content}],
    }


# ── AnthropicClient._to_claude_messages ──────────────────────────────────────

class TestToClaudeMessages:
    """Pure function — no external dependencies, no mock needed."""

    def test_system_message_extracted_to_system_prompt(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]

        system, out = _to_claude_messages(messages)

        assert system == "You are helpful."
        assert out == [{"role": "user", "content": "Hello"}]

    def test_multiple_system_messages_joined_with_double_newline(self):
        messages = [
            {"role": "system", "content": "Part one."},
            {"role": "system", "content": "Part two."},
            {"role": "user", "content": "Go"},
        ]

        system, _ = _to_claude_messages(messages)

        assert system == "Part one.\n\nPart two."

    def test_user_message_preserved(self):
        messages = [{"role": "user", "content": "Do the thing"}]

        _, out = _to_claude_messages(messages)

        assert out == [{"role": "user", "content": "Do the thing"}]

    def test_assistant_message_preserved(self):
        messages = [
            {"role": "user", "content": "Prompt"},
            {"role": "assistant", "content": "Answer"},
        ]

        _, out = _to_claude_messages(messages)

        assert len(out) == 2
        assert out[1] == {"role": "assistant", "content": "Answer"}

    def test_unknown_role_ignored(self):
        messages = [
            {"role": "tool", "content": "tool result"},
            {"role": "user", "content": "ok"},
        ]

        _, out = _to_claude_messages(messages)

        assert len(out) == 1
        assert out[0]["role"] == "user"

    def test_empty_system_message_not_added_to_system_prompt(self):
        messages = [
            {"role": "system", "content": "   "},  # whitespace only
            {"role": "user", "content": "hi"},
        ]

        system, _ = _to_claude_messages(messages)

        assert system == ""

    def test_no_system_messages_returns_empty_system(self):
        messages = [{"role": "user", "content": "hello"}]

        system, _ = _to_claude_messages(messages)

        assert system == ""

    def test_non_string_content_passed_through(self):
        content_blocks = [{"type": "text", "text": "structured"}]
        messages = [{"role": "user", "content": content_blocks}]

        _, out = _to_claude_messages(messages)

        assert out[0]["content"] == content_blocks

    def test_message_order_preserved(self):
        messages = [
            {"role": "user", "content": "1"},
            {"role": "assistant", "content": "2"},
            {"role": "user", "content": "3"},
        ]

        _, out = _to_claude_messages(messages)

        assert [m["content"] for m in out] == ["1", "2", "3"]


# ── AnthropicClient.chat() — request shape ────────────────────────────────────

class TestAnthropicClientChat:
    @pytest.fixture
    def client(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            return AnthropicClient()

    def _call_with_mock(self, client, body, **kwargs):
        """Patch urlopen and call client.chat(), returning (result, captured_request)."""
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["req"] = req
            return _fake_http_response(body)

        model = kwargs.pop("model", "claude-3")
        messages = kwargs.pop("messages", [{"role": "user", "content": "hello"}])

        with patch("src.strategy.llm.providers.anthropic.request.urlopen", side_effect=fake_urlopen):
            result = client.chat(model=model, messages=messages, **kwargs)
        return result, captured.get("req")

    def test_posts_to_anthropic_messages_endpoint(self, client):
        _, req = self._call_with_mock(client, _anthropic_text_response())
        assert "api.anthropic.com" in req.full_url
        assert req.full_url.endswith("/messages")

    def test_uses_post_method(self, client):
        _, req = self._call_with_mock(client, _anthropic_text_response())
        assert req.method == "POST"

    def test_includes_api_key_header(self, client):
        _, req = self._call_with_mock(client, _anthropic_text_response())
        assert req.headers.get("X-api-key") == "test-key"

    def test_payload_contains_model(self, client):
        _, req = self._call_with_mock(client, _anthropic_text_response(), model="claude-opus")
        payload = json.loads(req.data.decode())
        assert payload["model"] == "claude-opus"

    def test_payload_always_includes_max_tokens(self, client):
        _, req = self._call_with_mock(client, _anthropic_text_response())
        payload = json.loads(req.data.decode())
        assert "max_tokens" in payload

    def test_system_prompt_extracted_from_messages(self, client):
        messages = [
            {"role": "system", "content": "You are precise."},
            {"role": "user", "content": "Go"},
        ]
        _, req = self._call_with_mock(client, _anthropic_text_response(), messages=messages)
        payload = json.loads(req.data.decode())
        assert payload.get("system") == "You are precise."
        # System message should not appear in messages list
        assert all(m["role"] != "system" for m in payload["messages"])

    def test_tools_included_when_provided(self, client):
        tools = [{"type": "function", "function": {"name": "echo"}}]
        _, req = self._call_with_mock(client, _anthropic_text_response(), tools=tools)
        payload = json.loads(req.data.decode())
        assert payload.get("tools") == tools

    def test_http_error_raises_runtime_error(self, client):
        http_err = urllib_error.HTTPError(url="", code=401, msg="Unauthorized", hdrs=None, fp=BytesIO(b""))
        with patch("src.strategy.llm.providers.anthropic.request.urlopen", side_effect=http_err):
            with pytest.raises(RuntimeError, match="401"):
                client.chat(model="m", messages=[{"role": "user", "content": "hi"}])

    def test_url_error_raises_runtime_error(self, client):
        url_err = urllib_error.URLError(reason="Name or service not known")
        with patch("src.strategy.llm.providers.anthropic.request.urlopen", side_effect=url_err):
            with pytest.raises(RuntimeError, match="Anthropic"):
                client.chat(model="m", messages=[{"role": "user", "content": "hi"}])

    def test_missing_api_key_raises_value_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("src.strategy.llm.providers.anthropic.load_dotenv"):
                with pytest.raises(ValueError, match="API key"):
                    AnthropicClient(api_key=None)


# ── OpenAIClient.chat() — request shape ──────────────────────────────────────

class TestOpenAIClientChat:
    @pytest.fixture
    def client(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
            return OpenAIClient()

    def _call_with_mock(self, client, body, **kwargs):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["req"] = req
            return _fake_http_response(body)

        model = kwargs.pop("model", "gpt-4")
        messages = kwargs.pop("messages", [{"role": "user", "content": "hello"}])

        with patch("src.strategy.llm.providers.openai.request.urlopen", side_effect=fake_urlopen):
            result = client.chat(model=model, messages=messages, **kwargs)
        return result, captured.get("req")

    def test_posts_to_chat_completions_endpoint(self, client):
        _, req = self._call_with_mock(client, _openai_text_response())
        assert "api.openai.com" in req.full_url
        assert req.full_url.endswith("/chat/completions")

    def test_uses_post_method(self, client):
        _, req = self._call_with_mock(client, _openai_text_response())
        assert req.method == "POST"

    def test_authorization_header_uses_bearer_token(self, client):
        _, req = self._call_with_mock(client, _openai_text_response())
        assert req.headers.get("Authorization") == "Bearer test-openai-key"

    def test_payload_contains_model_and_messages(self, client):
        messages = [{"role": "user", "content": "test"}]
        _, req = self._call_with_mock(client, _openai_text_response(), model="gpt-4", messages=messages)
        payload = json.loads(req.data.decode())
        assert payload["model"] == "gpt-4"
        assert payload["messages"] == messages

    def test_max_tokens_included_when_provided(self, client):
        _, req = self._call_with_mock(client, _openai_text_response(), max_tokens=512)
        payload = json.loads(req.data.decode())
        assert payload["max_tokens"] == 512

    def test_max_tokens_absent_when_not_provided(self, client):
        _, req = self._call_with_mock(client, _openai_text_response())
        payload = json.loads(req.data.decode())
        assert "max_tokens" not in payload

    def test_tools_included_when_provided(self, client):
        tools = [{"type": "function", "function": {"name": "echo"}}]
        _, req = self._call_with_mock(client, _openai_text_response(), tools=tools)
        payload = json.loads(req.data.decode())
        assert payload.get("tools") == tools

    def test_http_error_raises_runtime_error(self, client):
        http_err = urllib_error.HTTPError(url="", code=429, msg="Too Many Requests", hdrs=None, fp=BytesIO(b""))
        with patch("src.strategy.llm.providers.openai.request.urlopen", side_effect=http_err):
            with pytest.raises(RuntimeError, match="429"):
                client.chat(model="m", messages=[{"role": "user", "content": "hi"}])

    def test_missing_api_key_raises_value_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("src.strategy.llm.providers.openai.load_dotenv"):
                with pytest.raises(ValueError, match="API key"):
                    OpenAIClient(api_key=None)


# ── LLMFactory.create() ───────────────────────────────────────────────────────

class TestLLMFactory:
    def test_known_provider_returns_client_instance(self):
        class FakeClient:
            def __init__(self, model=None): self.model = model

        with patch("src.strategy.llm.llm_factory.PROVIDER_CLIENTS", {"fake": FakeClient}):
            client = factory_create("fake", "fake-model")

        assert isinstance(client, FakeClient)

    def test_provider_name_is_case_insensitive(self):
        class FakeClient:
            def __init__(self, model=None): pass

        with patch("src.strategy.llm.llm_factory.PROVIDER_CLIENTS", {"fakeprovider": FakeClient}):
            client = factory_create("FakeProvider", "m")

        assert isinstance(client, FakeClient)

    def test_unknown_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            factory_create("nonexistent", "some-model")

    def test_extra_kwargs_not_accepted_by_client_are_filtered(self):
        class StrictClient:
            def __init__(self, model=None): self.model = model
            # no 'unknown_kwarg' param

        with patch("src.strategy.llm.llm_factory.PROVIDER_CLIENTS", {"strict": StrictClient}):
            # Should NOT raise — unknown_kwarg is filtered out
            client = factory_create("strict", "m", unknown_kwarg="ignored")

        assert isinstance(client, StrictClient)

    def test_model_passed_when_accepted_by_client(self):
        class ModelAwareClient:
            def __init__(self, model=None): self.model = model

        with patch("src.strategy.llm.llm_factory.PROVIDER_CLIENTS", {"maware": ModelAwareClient}):
            client = factory_create("maware", "test-model-123")

        assert client.model == "test-model-123"

    def test_accepted_kwargs_forwarded_to_client(self):
        class ConfigurableClient:
            def __init__(self, model=None, timeout=30.0): self.timeout = timeout

        with patch("src.strategy.llm.llm_factory.PROVIDER_CLIENTS", {"conf": ConfigurableClient}):
            client = factory_create("conf", "m", timeout=60.0)

        assert client.timeout == 60.0