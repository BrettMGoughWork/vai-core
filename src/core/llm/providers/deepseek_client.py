from __future__ import annotations

import json
import os
from urllib import request
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency fallback
    def load_dotenv(*args, **kwargs):
        return False

from .base import ChatProvider


class DeepSeekClient(ChatProvider):
    """
    Thin HTTP client for DeepSeek chat completions.

    This is intentionally minimal:
    - no retry policy (Phase 3)
    - no circuit breaker (Phase 3)
    - no tracing (Phase 11)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com/v1",
        timeout: float = 30.0,
    ) -> None:
        # Load local .env values for dev/runtime environments where env vars
        # are not pre-exported by the shell/session.
        load_dotenv(override=False)
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise ValueError("DeepSeekClient requires an API key (env DEEPSEEK_API_KEY or api_key=...)")

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ---------------------------------------------------------
    # Public API
    # ---------------------------------------------------------
    def chat(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Call DeepSeek chat completions with optional tools.

        - messages: OpenAI-style [{"role": "user"|"assistant"|"system", "content": "..."}]
        - tools: OpenAI-style tool definitions (JSON schema)
        """

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        if tools:
            payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        req = request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))