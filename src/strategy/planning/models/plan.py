from dataclasses import dataclass
from typing import Any


@dataclass
class Plan:
    intent: str
    targetskillid: str
    arguments: dict[str, Any]
    reasoning_summary: str

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "targetskillid": self.targetskillid,
            "arguments": self.arguments,
            "reasoning_summary": self.reasoning_summary,
        }
