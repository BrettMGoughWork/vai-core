from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class CoreLLMResponse:
    """
    Normalised LLM output:
    - text: normal assistant message
    - tool_name: if the LLM wants to call a tool
    - tool_args: parsed arguments for the tool
    """
    text: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None