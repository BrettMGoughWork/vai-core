from __future__ import annotations

import json
import os
from urllib import request, error
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from ._base import ChatProvider

@factory.register("mistral", ChatProvider)
class MistralClient(ChatProvider):
    """
    Thin HTTP client for Mistral Chat Completions.

    Endpoint:
      POST https://api.mistral.ai/v1/chat/completions [1](https://docs.mistral.ai/api/endpoint/chat)[2](https://docs.mistral.ai/studio-api/conversations/chat-completion)

    Auth:
      Authorization: Bearer <MISTRAL_API_KEY> [3](https://docs.mistral.ai/admin/security-access/api-keys)

    Intentionally minimal (aligned with your providers):
    - no retry policy (Phase 3)
    - no circuit breaker (Phase 3)
    - no tracing (Phase 11)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.mistral.ai/v1",
        timeout: float = 30.0,
    ) -> None:
        load_dotenv(override=False)
        self.api_key = api_key or os.getenv("MISTRAL_API_KEY", "")
        if not self.api_key:
            raise ValueError("MistralClient requires an API key (env MISTRAL_API_KEY or api_key=...)")

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

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
        Call Mistral chat completions with optional tools.

        - messages: [{"role": "system"|"user"|"assistant"|"tool", "content": "..."}] [1](https://docs.mistral.ai/api/endpoint/chat)[2](https://docs.mistral.ai/studio-api/conversations/chat-completion)
        - tools: tool definitions (function calling / tool calling) [4](https://docs.mistral.ai/studio-api/conversations/function-calling)[1](https://docs.mistral.ai/api/endpoint/chat)
        """

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        if max_tokens is not None:
            payload["max_tokens"] = max_tokens  # supported by chat completions [1](https://docs.mistral.ai/api/endpoint/chat)

        if tools:
            payload["tools"] = tools  # supported by chat completions [1](https://docs.mistral.ai/api/endpoint/chat)[4](https://docs.mistral.ai/studio-api/conversations/function-calling)

        if tool_choice:
            # Mistral supports tool calling options; your protocol is str so pass-through.
            payload["tool_choice"] = tool_choice

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",  # [3](https://docs.mistral.ai/admin/security-access/api-keys)
            "Content-Type": "application/json",
        }

        req = request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))

        except error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8")
            except Exception:
                body = ""
            raise RuntimeError(
                f"Mistral chat completions failed: HTTP {getattr(e, 'code', '???')} {getattr(e, 'reason', '')} "
                f"body={body}"
            ) from e

        except error.URLError as e:
            raise RuntimeError(f"Mistral chat completions failed: {e}") from e
