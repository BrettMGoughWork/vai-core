from __future__ import annotations

import json
import os
from urllib import request, error
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from ._base import ChatProvider


class OpenAIClient(ChatProvider):
    """
    Thin HTTP client for OpenAI chat completions.

    Intentionally minimal (aligned with DeepSeekClient):
    - no retries (Phase 3)
    - no circuit breaker (Phase 3)
    - no tracing (Phase 11)

    Uses Chat Completions endpoint:
      POST https://api.openai.com/v1/chat/completions
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 30.0,
        organisation: Optional[str] = None,
        project: Optional[str] = None,
    ) -> None:
        # Load local .env values for dev/runtime environments where env vars
        # are not pre-exported by the shell/session.
        load_dotenv(override=False)

        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        if not self.api_key:
            raise ValueError("OpenAIClient requires an API key (env OPENAI_API_KEY or api_key=...)")

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        # Optional headers supported by OpenAI for org/project scoping.
        # If you don't use these, leave them unset.
        self.organisation = organisation or os.getenv("OPENAI_ORG_ID") or None
        self.project = project or os.getenv("OPENAI_PROJECT_ID") or None

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
        Call OpenAI Chat Completions with optional tools.

        - messages: [{"role": "user"|"assistant"|"system", "content": "..."}]
        - tools: OpenAI-style tool definitions (JSON schema)
        """
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        # Chat Completions accepts max_tokens (depending on model).
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        if tools:
            payload["tools"] = tools

        # tool_choice can be "auto", "none", or a specific tool selection object in newer APIs,
        # but you're modelling it as Optional[str], so we pass-through string if provided.
        if tool_choice:
            payload["tool_choice"] = tool_choice

        url = f"{self.base_url}/chat/completions"
        headers: Dict[str, str] = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Optional scoping headers
        if self.organisation:
            headers["OpenAI-Organization"] = self.organisation
        if self.project:
            headers["OpenAI-Project"] = self.project

        req = request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)

        except error.HTTPError as e:
            # Preserve response body for diagnostics.
            body = ""
            try:
                body = e.read().decode("utf-8")
            except Exception:
                body = ""

            raise RuntimeError(
                f"OpenAI chat completions failed: HTTP {getattr(e, 'code', '???')} {getattr(e, 'reason', '')} "
                f"body={body}"
            ) from e

        except error.URLError as e:
            raise RuntimeError(f"OpenAI chat completions failed: {e}") from e