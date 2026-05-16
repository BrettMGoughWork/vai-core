from dataclasses import dataclass
from typing import Any


@dataclass
class Plan:
    intent: str
    targetskillid: str
    arguments: dict[str, Any]
    reasoning_summary: str
