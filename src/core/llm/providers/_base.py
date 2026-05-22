from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol
from src.core.types.validation.deadcode_markers import deadcode_ignore

"""Base protocol that all LLM chat providers must implement."""
@deadcode_ignore
class ChatProvider(Protocol):
    @deadcode_ignore
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
