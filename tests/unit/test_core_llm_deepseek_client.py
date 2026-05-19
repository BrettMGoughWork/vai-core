import json
from unittest.mock import patch

import pytest

from src.core.llm.providers.deepseek import DeepSeekClient


def test_deepseek_client_requires_api_key():
    with patch("src.core.llm.providers.deepseek_client.load_dotenv", return_value=False), patch.dict(
        "os.environ",
        {},
        clear=True,
    ):
        with pytest.raises(ValueError):
            DeepSeekClient()


def test_deepseek_client_loads_dotenv_on_init():
    with patch("src.core.llm.providers.deepseek_client.load_dotenv") as mock_load_dotenv, patch.dict(
        "os.environ",
        {"DEEPSEEK_API_KEY": "env-key"},
        clear=True,
    ):
        DeepSeekClient()

    mock_load_dotenv.assert_called_once_with(override=False)


def test_deepseek_client_posts_chat_completion_payload():
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        @staticmethod
        def read():
            return b'{"choices":[{"message":{"content":"ok"}}]}'

    with patch("src.core.llm.providers.deepseek_client.request.urlopen", return_value=FakeResponse()) as mock_urlopen:
        client = DeepSeekClient(api_key="test-key", base_url="https://api.deepseek.com/v1")
        raw = client.chat(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "echo", "parameters": {"type": "object"}}}],
            temperature=0.1,
            max_tokens=128,
        )

    assert raw["choices"][0]["message"]["content"] == "ok"
    mock_urlopen.assert_called_once()
    req = mock_urlopen.call_args.args[0]
    assert req.full_url == "https://api.deepseek.com/v1/chat/completions"
    payload = json.loads(req.data.decode("utf-8"))
    assert payload["model"] == "deepseek-chat"
    assert payload["messages"] == [{"role": "user", "content": "hello"}]
    assert payload["temperature"] == 0.1
    assert payload["max_tokens"] == 128
