from __future__ import annotations

from typing import Any

from src.core.planning.models.plan import Plan


class LocalPlanner:
    def plan(self, user_message: str, ranked_skills: list[Any]) -> Plan:
        if not ranked_skills:
            raise ValueError("No ranked skills available")

        top_skill = ranked_skills[0]
        skill_id = str(getattr(top_skill, "id", getattr(top_skill, "name", "")))
        if not skill_id:
            raise ValueError("Top-ranked skill is missing an identifier")

        return Plan(
            intent=user_message,
            targetskillid=skill_id,
            arguments={},
            reasoning_summary=f"Selected top-ranked skill: {skill_id}",
        )
