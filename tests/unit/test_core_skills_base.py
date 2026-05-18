import pytest

from src.skills.base import BaseSkill
from src.skills.registry import SkillRegistry


@pytest.fixture(autouse=True)
def _isolate_registry():
    previous = SkillRegistry._skills.copy()
    SkillRegistry._skills = {}
    try:
        yield
    finally:
        SkillRegistry._skills = previous


def test_base_skill_runs_canonicalise_validate_and_execute():
    def add(a: int, b: int) -> int:
        return a + b

    skill = BaseSkill(
        name="add_int",
        description="Add two integers",
        handler=add,
        schema={
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        },
    )

    # Strings are canonicalised to integers before validation/execution.
    out = skill.run(a=" 2 ", b="3")
    assert out == 5


def test_base_skill_registers_itself_and_exposes_llm_spec():
    def echo(text: str) -> str:
        return text

    skill = BaseSkill(name="echo_text", description="Echo text", handler=echo)

    assert SkillRegistry.get("echo_text").name == "echo_text"
    assert skill.to_llm_spec()["name"] == "echo_text"
    assert "parameters" in skill.to_llm_spec()
