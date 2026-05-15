from dataclasses import dataclass
from typing import List

from src.core.skills.categories import SkillCategory
from src.core.skills.side_effects import SideEffect


@dataclass
class AgentConfig:
    model: str
    allowed_tools: List[str]
    allowed_categories: List[SkillCategory]
    allowed_side_effects: List[SideEffect]
    max_steps: int = 4
