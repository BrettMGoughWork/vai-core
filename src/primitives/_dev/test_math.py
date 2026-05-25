from src.primitives.base import BaseSkill
from src.primitives.runtime.categories import SkillCategory
from src.primitives.runtime.side_effects import SideEffect

def add(a: int, b: int) -> int:
    return a + b

test_math_add = BaseSkill(
    name="test_math_add",
    description="Temporary test skill for agent loop.",
    handler=add,
    category=SkillCategory.MATH,
    side_effects=SideEffect.NONE,
)