from __future__ import annotations

from typing import Any


class SkillRanker:
    def rank(self, skills: list[Any], user_message: str) -> list[Any]:
        message_lower = user_message.lower()

        def relevance(skill: Any) -> int:
            metadata = getattr(skill, "metadata", None)
            domains = getattr(metadata, "domains", []) or []
            return sum(1 for domain in domains if str(domain).lower() in message_lower)

        def cost(skill: Any) -> int:
            metadata = getattr(skill, "metadata", None)
            return int(getattr(metadata, "cost_hint", 0))

        def latency(skill: Any) -> int:
            metadata = getattr(skill, "metadata", None)
            return int(getattr(metadata, "latency_hint", 0))

        def stable_id(skill: Any) -> str:
            return str(getattr(skill, "id", getattr(skill, "name", "")))

        return sorted(
            skills,
            key=lambda skill: (-relevance(skill), cost(skill), latency(skill), stable_id(skill)),
        )
