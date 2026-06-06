from __future__ import annotations

import json
import os
from urllib import request, error
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from ._base import ChatProvider
from src.core.types.validation.deadcode_markers import deadcode_ignore

@deadcode_ignore(reason="Factory registration only, not directly used")
class QwenClient(ChatProvider):
    """
    Thin HTTP client for Alibaba Cloud Model Studio (DashScope) Qwen models,
    using the OpenAI-compatible Chat Completions endpoint.

    Base URL examples (region-specific): [1](https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope)[2](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)
      - International (Singapore): https://dashscope-intl.aliyuncs.com/compatible-mode/v1
      - US (Virginia):           https://dashscope-us.aliyuncs.com/compatible-mode/v1
      - China (Beijing):         https://dashscope.aliyuncs.com/compatible-mode/v1

    Endpoint:
      POST {BASE_URL}/chat/completions [1](https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope)[2](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)

    Auth:
      Authorization: Bearer <DASHSCOPE_API_KEY> [3](https://tokenmix.ai/blog/dashscope-alibaba-cloud-api-developer-setup-2026)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        load_dotenv(override=True)

        # Alibaba Cloud docs commonly use DASHSCOPE_API_KEY for Model Studio/DashScope keys. [5](https://www.alibabacloud.com/help/en/model-studio/first-api-call-to-qwen)
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        if not self.api_key:
            raise ValueError("QwenClient requires an API key (env DASHSCOPE_API_KEY or api_key=...)")

        # Allow override via env for region selection; default to international endpoint.
        # (International base URL is listed in Alibaba docs.) [1](https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope)[2](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)
        env_base = os.getenv("DASHSCOPE_API_BASE", "").strip()
        self.base_url = (base_url or env_base or "https://dashscope-intl.aliyuncs.com/compatible-mode/v1").rstrip("/")
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
        OpenAI-compatible Chat Completions call (works with Qwen models via DashScope). [1](https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope)[2](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)
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
            # Your protocol uses str. OpenAI-compatible APIs often accept "auto"/"none" or
            # a structured object; here we pass-through the string to match your interface.
            payload["tool_choice"] = tool_choice

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",  # [3](https://tokenmix.ai/blog/dashscope-alibaba-cloud-api-developer-setup-2026)
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
                f"Qwen (DashScope) chat completions failed: HTTP {getattr(e, 'code', '???')} "
                f"{getattr(e, 'reason', '')} body={body}"
            ) from e

        except error.URLError as e:
            raise RuntimeError(f"Qwen (DashScope) chat completions failed: {e}") from e