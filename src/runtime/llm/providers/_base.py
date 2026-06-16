from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol


class ChatProvider(Protocol):
    """Base protocol that all LLM chat providers must implement."""

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
        ...
