from __future__ import annotations

from typing import Any


class SkillFilter:
    def filter(self, skills: list[Any], user_message: str) -> list[Any]:
        message_lower = user_message.lower()
        candidates: list[Any] = []

        for skill in skills:
            metadata = getattr(skill, "metadata", None)
            domains = getattr(metadata, "domains", []) or []
            if domains:
                if not any(str(domain).lower() in message_lower for domain in domains):
                    continue
            candidates.append(skill)

        return candidates
