from dataclasses import dataclass

from src.capabilities.skillmetadata import SkillMetadata


@dataclass
class Skill:
    id: str
    name: str
    metadata: SkillMetadata
