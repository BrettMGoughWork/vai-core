"""
Shared Skill and SkillMetadata contracts.

These dataclasses define the skill contract shared across strata.
They live in the runtime (S1) so that all strata can depend on them
without violating stratum import rules.
"""

from dataclasses import dataclass


@dataclass
class SkillMetadata:
    domains: list[str]
    input_types: list[str]
    output_types: list[str]
    safety_tags: list[str]
    cost_hint: int
    latency_hint: int


@dataclass
class Skill:
    id: str
    name: str
    metadata: SkillMetadata
