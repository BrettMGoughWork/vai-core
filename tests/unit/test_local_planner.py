from dataclasses import dataclass

import pytest

from src.core.planning.generator.local_planner import LocalPlanner


@dataclass
class FakeSkill:
    id: str


def test_plan_selects_top_ranked_skill():
    planner = LocalPlanner()
    ranked = [FakeSkill(id="skill_a"), FakeSkill(id="skill_b")]

    plan = planner.plan("do something", ranked)

    assert plan.intent == "do something"
    assert plan.targetskillid == "skill_a"
    assert plan.arguments == {}
    assert "skill_a" in plan.reasoning_summary


def test_plan_raises_when_no_ranked_skills():
    planner = LocalPlanner()

    with pytest.raises(ValueError, match="No ranked skills available"):
        planner.plan("do something", [])
