from dataclasses import dataclass

from src.primitives.runtime.skill_ranker import SkillRanker


@dataclass
class FakeMetadata:
    domains: list[str]
    cost_hint: int
    latency_hint: int


@dataclass
class FakeSkill:
    id: str
    metadata: FakeMetadata


def test_rank_orders_by_relevance_then_cost_then_latency_then_id():
    skills = [
        FakeSkill(id="b_skill", metadata=FakeMetadata(domains=["math"], cost_hint=2, latency_hint=2)),
        FakeSkill(id="a_skill", metadata=FakeMetadata(domains=["math"], cost_hint=2, latency_hint=2)),
        FakeSkill(id="fast_skill", metadata=FakeMetadata(domains=["math"], cost_hint=2, latency_hint=1)),
        FakeSkill(id="cheap_skill", metadata=FakeMetadata(domains=["math"], cost_hint=1, latency_hint=9)),
        FakeSkill(id="other_skill", metadata=FakeMetadata(domains=["text"], cost_hint=0, latency_hint=0)),
    ]

    ranked = SkillRanker().rank(skills, "need math help")

    assert [skill.id for skill in ranked] == [
        "cheap_skill",
        "fast_skill",
        "a_skill",
        "b_skill",
        "other_skill",
    ]


def test_rank_is_deterministic_for_identical_inputs():
    skills = [
        FakeSkill(id="zeta", metadata=FakeMetadata(domains=["x"], cost_hint=1, latency_hint=1)),
        FakeSkill(id="alpha", metadata=FakeMetadata(domains=["x"], cost_hint=1, latency_hint=1)),
    ]

    ranker = SkillRanker()
    first = [skill.id for skill in ranker.rank(skills, "x")]
    second = [skill.id for skill in ranker.rank(skills, "x")]

    assert first == ["alpha", "zeta"]
    assert second == first
