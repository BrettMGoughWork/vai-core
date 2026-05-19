from src.skills.base import BaseSkill
from src.capabilities.categories import SkillCategory
from src.capabilities.side_effects import SideEffect

def add(a: int, b: int) -> int:
    return a + b

test_math_add = BaseSkill(
    name="test_math_add",
    description="Temporary test skill for agent loop.",
    handler=add,
    category=SkillCategory.MATH,
    side_effects=SideEffect.NONE,
)