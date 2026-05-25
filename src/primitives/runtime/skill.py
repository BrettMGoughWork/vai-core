from dataclasses import dataclass

from src.primitives.runtime.skillmetadata import SkillMetadata


@dataclass
class Skill:
    id: str
    name: str
    metadata: SkillMetadata
