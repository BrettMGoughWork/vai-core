from __future__ import annotations

import json
import os
from urllib import request, error
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from ._base import ChatProvider
from ._factory import factory


@factory.register("gemini", ChatProvider)
class GeminiClient(ChatProvider):
    """
    Thin HTTP client for the Gemini API (Google AI for Developers).

    Gemini REST uses generateContent and returns "candidates", not OpenAI "choices".
    We normalise the response into an OpenAI-compatible shape so the rest of the
    runtime can treat it like other chat providers. [1](https://pip.pypa.io/en/stable/installation/)[2](https://packaging.python.org/tutorials/installing-packages/)
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
        system_text, contents = _to_gemini_contents(messages)

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens if max_tokens is not None else self.default_max_output_tokens,
            },
        }

        # Gemini/Vertex style system instruction is a Content object with parts. [4](https://pip.pypa.io/en/stable/getting-started/)[1](https://pip.pypa.io/en/stable/installation/)
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}

        if tools:
            payload["tools"] = _normalise_tools_for_gemini(tools)

        # tool_choice in Gemini is generally configured via toolConfig/functionCallingConfig.
        # Your interface only provides str, so we intentionally ignore anything beyond trivial cases.
        if tool_choice in ("auto", "none"):
            pass

        url = f"{self.base_url}/models/{model}:generateContent"
        headers: Dict[str, str] = {"Content-Type": "application/json"}

        # Gemini REST supports API key in query or header. [3](https://www.geeksforgeeks.org/installation-guide/how-to-install-pip-on-windows/)
        if self.use_query_key:
            url = f"{url}?key={self.api_key}"
        else:
            headers["x-goog-api-key"] = self.api_key  # matches documented REST header [3](https://www.geeksforgeeks.org/installation-guide/how-to-install-pip-on-windows/)

        req = request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
                return _gemini_to_openai(raw, model=model)

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


def _gemini_to_openai(raw: Dict[str, Any], *, model: str) -> Dict[str, Any]:
    """
    Convert Gemini generateContent JSON (candidates[]) into an OpenAI-style
    chat.completions response (choices[]). [1](https://pip.pypa.io/en/stable/installation/)[2](https://packaging.python.org/tutorials/installing-packages/)
    """
    # If Gemini blocked the prompt or produced no candidates, surface something useful.
    candidates = raw.get("candidates") or []
    if not candidates:
        prompt_feedback = raw.get("promptFeedback") or {}
        # Keep full raw payload for debugging upstream.
        return {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "",
                    },
                    "finish_reason": "blocked",
                }
            ],
            "model": model,
            "raw_provider_response": raw,
            "provider_prompt_feedback": prompt_feedback,
        }

    first = candidates[0]
    content = (first.get("content") or {})
    parts = content.get("parts") or []
    text_chunks: List[str] = []

    for p in parts:
        t = p.get("text")
        if isinstance(t, str) and t:
            text_chunks.append(t)

    text = "".join(text_chunks).strip()

    finish_reason = first.get("finishReason")  # Gemini uses finishReason on candidates [1](https://pip.pypa.io/en/stable/installation/)

    return {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": finish_reason,
            }
        ],
        "model": model,
        "raw_provider_response": raw,
    }


def _to_gemini_contents(openai_messages: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Convert OpenAI-style messages into Gemini 'contents' format:
      contents[] = [{ "role": "user"|"model", "parts": [{"text": "..."}] }, ...]

    Gemini responses are returned as candidates with content.parts[].text. [1](https://pip.pypa.io/en/stable/installation/)[2](https://packaging.python.org/tutorials/installing-packages/)
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

        # Keep it simple: text-only conversion.
        text = content if isinstance(content, str) else str(content or "")

        if role == "user":
            contents.append({"role": "user", "parts": [{"text": text}]})
        elif role == "assistant":
            # Gemini commonly uses "model" as the assistant role in contents.
            contents.append({"role": "model", "parts": [{"text": text}]})

    # If caller passed only system messages or empty list, provide a harmless fallback.
    if not contents:
        contents = [{"role": "user", "parts": [{"text": "Hello"}]}]

    return "\n\n".join(system_parts).strip(), contents


def _normalise_tools_for_gemini(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Accept either:
    - Gemini-style tools (already contain functionDeclarations), or
    - OpenAI-style tools and convert to Gemini functionDeclarations container.
    """
    if any(("functionDeclarations" in t) or ("function_declarations" in t) for t in tools):
        return tools

    decls: List[Dict[str, Any]] = []
