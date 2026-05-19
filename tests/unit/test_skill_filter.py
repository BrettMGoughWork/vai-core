from dataclasses import dataclass

from src.capabilities.skill_filter import SkillFilter


@dataclass
class FakeMetadata:
    domains: list[str]
    cost_hint: int = 0
    latency_hint: int = 0


@dataclass
class FakeSkill:
    id: str
    metadata: FakeMetadata


def test_filter_keeps_only_domain_matches():
    skills = [
        FakeSkill(id="math_add", metadata=FakeMetadata(domains=["math"])),
        FakeSkill(id="text_echo", metadata=FakeMetadata(domains=["text"])),
    ]

    filtered = SkillFilter().filter(skills, "please do some math")

    assert [skill.id for skill in filtered] == ["math_add"]


def test_filter_keeps_skill_with_no_domains():
    skills = [
        FakeSkill(id="generic", metadata=FakeMetadata(domains=[])),
        FakeSkill(id="text_echo", metadata=FakeMetadata(domains=["text"])),
    ]

    filtered = SkillFilter().filter(skills, "unrelated message")

    assert [skill.id for skill in filtered] == ["generic"]
