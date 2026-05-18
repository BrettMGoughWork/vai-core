from dataclasses import dataclass


@dataclass
class SkillMetadata:
    domains: list[str]
    input_types: list[str]
    output_types: list[str]
    safety_tags: list[str]
    cost_hint: int
    latency_hint: int
