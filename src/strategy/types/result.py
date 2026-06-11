# Stratum 1 AND Stratum 3 
# CoreResult: unified output type for the agent runtime.

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class CoreResult:
    """
    Unified output type for the agent runtime.
    - text: normal LLM output
    - tool_name: which tool was executed (if any)
    - tool_output: result of the tool handler
    - error: any error raised during execution
    """

    text: Optional[str] = None
    tool_name: Optional[str] = None
    tool_output: Optional[Any] = None
    error: Optional[str] = None

    @property
    def is_error(self) -> bool:
        return self.error is not None

    @property
    def is_tool(self) -> bool:
        return self.tool_name is not None

    @property
    def is_text(self) -> bool:
        return self.text is not None
    
    @staticmethod
    def from_text(text: str) -> "CoreResult":
        return CoreResult(text=text)

    @staticmethod
    def from_tool(name: str, output: Any) -> "CoreResult":
        return CoreResult(tool_name=name, tool_output=output)

    @staticmethod
    def from_error(err: Exception) -> "CoreResult":
        return CoreResult(error=str(err))