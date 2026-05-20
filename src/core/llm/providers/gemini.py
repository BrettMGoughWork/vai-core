from __future__ import annotations

import json
import os
from urllib import request, error
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from ._base import ChatProvider

@factory.register("gemini", ChatProvider)
class GeminiClient(ChatProvider):
    """
    Thin HTTP client for the Gemini API (Google AI for Developers).

    - Endpoint: POST /v1beta/models/{model}:generateContent
      Base URL: https://generativelanguage.googleapis.com/v1beta
    - Auth: API key via query param (?key=...) or header (X-Goog-Api-Key)
    - Request body uses "contents": [{"parts": [{"text": "..."}]}]

    Intentionally minimal:
    - no retries (Phase 3)
    - no circuit breaker (Phase 3)
    - no tracing (Phase 11)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout: float = 30.0,
        use_query_key: bool = True,
        default_max_output_tokens: int = 1024,
    ) -> None:
        load_dotenv(override=False)

        # Docs commonly reference GEMINI_API_KEY as env var for SDK usage. [2](https://ai.google.dev/gemini-api/docs/quickstart)
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
        if not self.api_key:
            raise ValueError("GeminiClient requires an API key (env GEMINI_API_KEY/GOOGLE_API_KEY or api_key=...)")

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.use_query_key = use_query_key
        self.default_max_output_tokens = default_max_output_tokens

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
        Accepts OpenAI-style messages and converts them to Gemini 'contents' format.

        Input messages:
          [{"role":"system"|"user"|"assistant","content":...}, ...]

        Gemini generateContent expects:
          {
            "contents": [{"parts":[{"text":"..."}], "role": "..."}],
            "generationConfig": {"temperature": ..., "maxOutputTokens": ...},
            "tools": [...]
          }
        [1](https://deepwiki.com/google-gemini/cookbook/9.3-rest-api-usage)[3](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/reference/rest/v1/projects.locations.endpoints/generateContent)
        """
        system_text, contents = _to_gemini_contents(messages)

        payload: Dict[str, Any] = {
            "contents": contents,  # contents[] with parts[] [1](https://deepwiki.com/google-gemini/cookbook/9.3-rest-api-usage)
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens if max_tokens is not None else self.default_max_output_tokens,
            },
        }

        # Vertex AI docs describe systemInstruction as a Content object. [3](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/reference/rest/v1/projects.locations.endpoints/generateContent)
        # For Gemini API, system instructions are supported; we encode as Content with a text part.
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}

        # Tools: Gemini/Vertex uses "tools" and may include function declarations. [3](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/reference/rest/v1/projects.locations.endpoints/generateContent)[4](https://ai.google.dev/gemini-api/docs/function-calling)
        if tools:
            payload["tools"] = _normalise_tools_for_gemini(tools)

        # tool_choice: Gemini uses toolConfig/functionCallingConfig patterns (not a simple string in general).
        # We keep minimal compatibility: recognise "auto"/"none" but otherwise ignore.
        if tool_choice in ("auto", "none"):
            # no-op: default behaviour is effectively "auto" when tools are present
            pass

        url = f"{self.base_url}/models/{model}:generateContent"
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
        }

        # Auth supports API key in header or query parameter. [1](https://deepwiki.com/google-gemini/cookbook/9.3-rest-api-usage)
        if self.use_query_key:
            url = f"{url}?key={self.api_key}"
        else:
            headers["X-Goog-Api-Key"] = self.api_key

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
                f"Gemini generateContent failed: HTTP {getattr(e, 'code', '???')} {getattr(e, 'reason', '')} "
                f"body={body}"
            ) from e

        except error.URLError as e:
            raise RuntimeError(f"Gemini generateContent failed: {e}") from e


def _to_gemini_contents(openai_messages: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Convert OpenAI-style messages to Gemini 'contents'.

    Gemini REST requires contents[].parts[].text. [1](https://deepwiki.com/google-gemini/cookbook/9.3-rest-api-usage)
    The 'role' field is optional in REST examples; we include it for better multi-turn fidelity. [1](https://deepwiki.com/google-gemini/cookbook/9.3-rest-api-usage)

    Implementation choice:
      - system messages are merged into one systemInstruction text
      - user -> role "user"
      - assistant -> role "model" (common Gemini convention); if this causes issues,
        you can omit role for assistant turns and keep parts only.
    """
    system_parts: List[str] = []
    contents: List[Dict[str, Any]] = []

    for m in openai_messages:
        role = (m.get("role") or "").lower()
        content = m.get("content")

        if role == "system":
            if isinstance(content, str) and content.strip():
                system_parts.append(content.strip())
            continue

        if content is None:
            text = ""
        elif isinstance(content, str):
            text = content
        else:
            # Best-effort: coerce non-string to JSON string.
            text = json.dumps(content, ensure_ascii=False)

        if role == "user":
            contents.append({"role": "user", "parts": [{"text": text}]})
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": text}]})
        else:
            # Ignore unknown roles
            continue

    return "\n\n".join(system_parts).strip(), contents


def _normalise_tools_for_gemini(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Accept either:
    - Gemini/Vertex-style tools already (pass-through), or
    - OpenAI-style tool definitions:
        {"type":"function","function":{"name":..., "description":..., "parameters":...}}

    Vertex/Gemini docs show tools[] as a first-class request field. [3](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/reference/rest/v1/projects.locations.endpoints/generateContent)[4](https://ai.google.dev/gemini-api/docs/function-calling)
    A common REST shape uses functionDeclarations. [5](https://blevinscm.github.io/genai-docs/model-reference/gemini/)
    """
    # If it already looks like Gemini (contains functionDeclarations or function_declarations), pass through.
    if any(("functionDeclarations" in t) or ("function_declarations" in t) for t in tools):
        return tools

    # Otherwise try to map OpenAI-style tools -> Gemini functionDeclarations
    decls: List[Dict[str, Any]] = []
    for t in tools:
        if t.get("type") != "function":
            continue
        fn = t.get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        decl: Dict[str, Any] = {"name": name}
        if fn.get("description"):
            decl["description"] = fn["description"]
        if fn.get("parameters"):
            # Gemini expects OpenAPI-ish schema for parameters too.
            decl["parameters"] = fn["parameters"]
        decls.append(decl)

    if not decls:
        return tools  # fallback, better than dropping

    return [{"functionDeclarations": decls}]