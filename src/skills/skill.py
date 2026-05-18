from dataclasses import dataclass

from src.skills.skillmetadata import SkillMetadata


@dataclass
class Skill:
    id: str
    name: str
    metadata: SkillMetadata
