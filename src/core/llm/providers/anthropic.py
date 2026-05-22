from __future__ import annotations

import json
import os
from urllib import request, error
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from ._base import ChatProvider
from src.core.types.validation.deadcode_markers import deadcode_ignore

@deadcode_ignore(reason="Factory registration only, not directly used")
class AnthropicClient(ChatProvider):
    """
    Thin HTTP client for Anthropic Claude Messages API.

    Notes vs OpenAI-style:
    - Endpoint is POST /v1/messages
    - Requires `max_tokens` on every request (we apply a default if None)
    - Uses x-api-key + anthropic-version headers
    - System prompt is top-level `system`, not a message role
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.anthropic.com/v1",
        timeout: float = 30.0,
        anthropic_version: str = "2023-06-01",
        default_max_tokens: int = 1024,
    ) -> None:
        load_dotenv(override=False)

        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise ValueError("AnthropicClient requires an API key (env ANTHROPIC_API_KEY or api_key=...)")

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.anthropic_version = anthropic_version
        self.default_max_tokens = default_max_tokens

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
        Accepts OpenAI-style messages and converts to Claude Messages API format.

        Input messages:
          [{"role":"system"|"user"|"assistant","content":...}, ...]

        Claude expects:
          - optional top-level "system": str | blocks
          - messages with role in {"user","assistant"}
          - max_tokens is required
        """
        system_prompt, claude_messages = _to_claude_messages(messages)

        payload: Dict[str, Any] = {
            "model": model,
            "messages": claude_messages,
            # Claude requires max_tokens on every request
            "max_tokens": max_tokens if max_tokens is not None else self.default_max_tokens,
        }

        if system_prompt:
            payload["system"] = system_prompt

        # Temperature is supported by Messages API.
        payload["temperature"] = temperature

        # Tools: pass through if provided (Claude supports tool use on Messages API)
        if tools:
            payload["tools"] = tools

        # tool_choice: Claude supports tool configuration, but it is not always a simple string.
        # Because your interface is Optional[str], we only pass through obvious cases.
        # If you later widen to dict, you can support richer selection.
        if tool_choice in ("auto", "none"):
            payload["tool_choice"] = tool_choice

        url = f"{self.base_url}/messages"
        headers: Dict[str, str] = {
            "x-api-key": self.api_key,
            "anthropic-version": self.anthropic_version,
            "content-type": "application/json",
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
                f"Anthropic messages failed: HTTP {getattr(e, 'code', '???')} {getattr(e, 'reason', '')} "
                f"body={body}"
            ) from e

        except error.URLError as e:
            raise RuntimeError(f"Anthropic messages failed: {e}") from e


def _to_claude_messages(openai_messages: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Convert OpenAI-style messages into Claude Messages API format.

    - Collect all system messages and join them into a single system prompt string.
    - Convert remaining messages to Claude's role set: {"user","assistant"}.
    - Claude content can be string or list of blocks; we pass string through, and for
      non-string content we attempt a basic normalisation.
    """
    system_parts: List[str] = []
    out: List[Dict[str, Any]] = []

    for m in openai_messages:
        role = (m.get("role") or "").lower()
        content = m.get("content")

        if role == "system":
            if isinstance(content, str) and content.strip():
                system_parts.append(content.strip())
            continue

        if role not in ("user", "assistant"):
            # Ignore unknown roles rather than failing hard
            continue

        # Claude accepts string or structured blocks; keep strings as-is.
        if isinstance(content, str):
            out.append({"role": role, "content": content})
        else:
            # Best-effort: if caller is already using content blocks, pass through.
            # Otherwise coerce to string.
            out.append({"role": role, "content": content if content is not None else ""})

    system_prompt = "\n\n".join(system_parts).strip()
    return system_prompt, out